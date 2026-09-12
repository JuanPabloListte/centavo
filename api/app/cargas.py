"""Cargar un resumen desde el navegador, en segundo plano y con progreso.

Una carga corre en un hilo propio, con su propia conexión, y hace lo mismo que
`tools.ingerir`: leer el archivo, verificar la compuerta, guardar, clasificar
con memoria y evidencia y, si se pide, pasarle a la flota local lo que quede
pendiente de ESE resumen. Cada paso deja un evento, y el navegador los recibe
por SSE (`GET /api/cargas/{id}/eventos`).

**Por qué un hilo y no Celery con Redis.** Es una persona y una carga por vez,
en la misma máquina: un hilo del proceso de la API alcanza y no suma dos
servicios. Lo que se pierde: si la API se reinicia en medio de una carga, la
carga se corta. Lo guardado queda guardado, porque guardar es una transacción y,
con el modelo, cada movimiento se guarda apenas se clasifica. Lo que falte queda
pendiente, como cualquier otro movimiento.

**El archivo no queda en disco.** Vive en un directorio temporal mientras el
parser lo lee y se borra ni bien termina, salga bien o mal. En la base queda lo
mismo que deja `tools.ingerir`: el resumen, con su sha256 y el nombre del
archivo, sin carpetas.

**Una carga por vez.** Dos cargas simultáneas se pisarían al clasificar y, con
el modelo, en la GPU. Mientras hay una en curso, otra se rechaza.

Los eventos quedan en memoria mientras la API corre: una pestaña que se cierra y
se vuelve a abrir retoma el progreso desde el principio.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

import psycopg

from .corridas import Corrida, conteo_del_resumen
from .memoria import clasificar_pendientes, grupos_pendientes
from .pipeline import procesar
from .store import SuperposicionParcial, YaIngerido, guardar

TAMANIO_MAXIMO = 20 * 1024 * 1024
TIPOS_ACEPTADOS = frozenset({"application/pdf", "text/csv", "application/octet-stream"})
CARGAS_RECORDADAS = 20
TERMINALES = frozenset({"fin", "falla"})


class CargaEnCurso(Exception):
    def __init__(self, carga_id: str):
        self.carga_id = carga_id
        super().__init__("Ya hay una carga en curso: esperá a que termine.")


def nombre_seguro(nombre: str) -> str:
    """El nombre del archivo, sin carpetas de ningún sistema. Es lo que queda en
    `statements.archivo` y el nombre con el que se escribe el temporal."""
    limpio = PurePosixPath(PureWindowsPath(nombre.strip()).name).name
    if limpio in ("", ".", ".."):
        raise ValueError("El nombre del archivo no es válido.")
    return limpio[:200]


@dataclass
class Evento:
    numero: int
    tipo: str            # 'paso' | 'progreso' | 'fin' | 'falla'
    datos: dict


@dataclass
class Carga:
    id: str
    archivo: str
    con_modelo: bool
    eventos: list[Evento] = field(default_factory=list)
    terminada: bool = False
    hilo: threading.Thread | None = None
    cambio: threading.Condition = field(default_factory=threading.Condition, repr=False)

    def emitir(self, tipo: str, **datos) -> None:
        with self.cambio:
            self.eventos.append(Evento(len(self.eventos), tipo, datos))
            self.terminada = self.terminada or tipo in TERMINALES
            self.cambio.notify_all()

    def paso(self, paso: str, estado: str, detalle: str) -> None:
        self.emitir("paso", paso=paso, estado=estado, detalle=detalle)

    def falla(self, motivo: str, mensaje: str, **datos) -> None:
        self.emitir("falla", motivo=motivo, mensaje=mensaje, **datos)

    def esperar(self, desde: int, segundos: float) -> list[Evento]:
        """Los eventos a partir de `desde`. Si todavía no hay, espera hasta
        `segundos` a que llegue alguno."""
        with self.cambio:
            if len(self.eventos) <= desde and not self.terminada:
                self.cambio.wait(segundos)
            return self.eventos[desde:]

    def resumen(self) -> dict:
        return {"id": self.id, "archivo": self.archivo, "con_modelo": self.con_modelo,
                "terminada": self.terminada}


def flujo_sse(carga: Carga, desde: int = 0, espera: float = 15.0) -> Iterator[str]:
    """Los eventos de una carga en formato SSE, a partir de `desde`. Termina
    cuando la carga terminó y ya se mandó todo. Sin novedades, cada `espera`
    segundos manda un comentario, para que ningún proxy corte la conexión."""
    while True:
        nuevos = carga.esperar(desde, espera)
        if not nuevos:
            if carga.terminada:
                return
            yield ": sigue\n\n"
            continue
        for e in nuevos:
            datos = json.dumps(e.datos, ensure_ascii=False)
            yield f"id: {e.numero}\nevent: {e.tipo}\ndata: {datos}\n\n"
        desde = nuevos[-1].numero + 1


class Cargador:
    """Lanza cargas en segundo plano y las recuerda mientras la API corre.
    `conectar` y `crear_clasificador` se inyectan: la API usa la base y la flota
    reales; los tests, un esquema temporal y un clasificador falso."""

    def __init__(
        self,
        conectar: Callable[[], psycopg.Connection],
        crear_clasificador: Callable[[psycopg.Connection], object],
    ):
        self._conectar = conectar
        self._crear_clasificador = crear_clasificador
        self._cargas: dict[str, Carga] = {}
        self._candado = threading.Lock()

    def activa(self) -> Carga | None:
        return next((c for c in self._cargas.values() if not c.terminada), None)

    def obtener(self, carga_id: str) -> Carga | None:
        return self._cargas.get(carga_id)

    def lanzar(self, nombre: str, contenido: bytes, con_modelo: bool) -> Carga:
        archivo = nombre_seguro(nombre)
        with self._candado:
            if (activa := self.activa()) is not None:
                raise CargaEnCurso(activa.id)
            carga = Carga(id=uuid.uuid4().hex, archivo=archivo, con_modelo=con_modelo)
            self._cargas[carga.id] = carga
            for vieja in list(self._cargas)[:-CARGAS_RECORDADAS]:
                del self._cargas[vieja]
        carga.hilo = threading.Thread(target=self._ejecutar, args=(carga, contenido),
                                      name=f"carga-{carga.id[:8]}", daemon=True)
        carga.hilo.start()
        return carga

    def _ejecutar(self, carga: Carga, contenido: bytes) -> None:
        try:
            conn = self._conectar()
        except psycopg.OperationalError:
            carga.falla("base", "La base de datos no responde. ¿Está corriendo Docker?")
            return
        corrida = Corrida("api")
        statement_id = cliente = None
        try:
            carga.paso("lectura", "en_curso", "Leyendo el archivo")
            try:
                with tempfile.TemporaryDirectory(prefix="centavo-") as carpeta:
                    ruta = Path(carpeta) / carga.archivo
                    ruta.write_bytes(contenido)
                    resumen, resultado = procesar(ruta)
            except Exception as exc:
                corrida.guardar(conn, "error", error=exc)
                carga.falla("lectura", str(exc) or type(exc).__name__)
                return
            n = len(resumen.movimientos)
            carga.paso("lectura", "hecho", f"{n} movimientos de {resumen.banco}, del "
                       f"{resumen.periodo_desde:%d/%m/%Y} al {resumen.periodo_hasta:%d/%m/%Y}")
            carga.paso("compuerta", "hecho" if resultado.cuadra else "fallo", resultado.explicar())

            carga.paso("guardado", "en_curso", "Guardando en la base")
            try:
                statement_id = guardar(resumen, resultado, conn=conn)
            except YaIngerido as exc:
                corrida.guardar(conn, "ya_ingerido", statement_id=exc.statement_id)
                carga.falla("ya_ingerido", str(exc), statement_id=exc.statement_id)
                return
            except SuperposicionParcial as exc:
                corrida.guardar(conn, "superposicion")
                carga.falla("superposicion", str(exc))
                return
            carga.paso("guardado", "hecho", f"Guardado como resumen {statement_id}")

            if resultado.cuadra:
                carga.paso("clasificacion", "en_curso", "Memoria y evidencia")
                clasificar_pendientes(conn)
                pendientes = conteo_del_resumen(conn, statement_id).get("sin_procesar", 0)
                carga.paso("clasificacion", "hecho", f"{n - pendientes} de {n} resueltos sin modelo")

                if carga.con_modelo and pendientes:
                    clasificador = self._crear_clasificador(conn)
                    cliente = getattr(clasificador, "cliente", None)
                    carga.paso("modelo", "en_curso", f"{pendientes} movimientos con la flota local")
                    inicio = time.perf_counter()

                    def avanzar(hechos: int, total: int) -> None:
                        pasaron = time.perf_counter() - inicio
                        falta = None if hechos == 0 else round(pasaron / hechos * (total - hechos))
                        carga.emitir("progreso", hechos=hechos, total=total, segundos_restantes=falta)

                    clasificar_pendientes(conn, clasificador, statement_id=statement_id,
                                          al_avanzar=avanzar)
                    despues = conteo_del_resumen(conn, statement_id)
                    revision = despues.get("needs_review", 0)
                    resueltos = pendientes - revision - despues.get("sin_procesar", 0)
                    carga.paso("modelo", "hecho",
                               f"{resueltos} resueltos por la flota, {revision} a revisión")

            numero = corrida.guardar(conn, "cuadrado" if resultado.cuadra else "descuadrado",
                                     statement_id=statement_id, cliente=cliente)
            grupos = grupos_pendientes(conn)
            carga.emitir(
                "fin",
                statement_id=statement_id,
                cuadra=resultado.cuadra,
                detalle=resultado.explicar(),
                clasificacion=conteo_del_resumen(conn, statement_id) if resultado.cuadra else {},
                pendientes={"grupos": len(grupos),
                            "movimientos": sum(g["cantidad"] for g in grupos)},
                corrida=numero,
            )
        except Exception as exc:
            conn.rollback()
            try:
                corrida.guardar(conn, "error", statement_id=statement_id, cliente=cliente,
                                error=exc)
            except Exception:
                pass
            motivo = "modelo" if cliente is not None else "inesperado"
            carga.falla(motivo, f"{type(exc).__name__}: {exc}")
        finally:
            conn.close()
            if not carga.terminada:
                carga.falla("inesperado", "La carga se cortó sin avisar.")
