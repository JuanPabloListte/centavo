"""API local de Centavo.

Escucha sólo en 127.0.0.1, y eso es parte de la premisa del producto: ningún
movimiento sale de la máquina, lo que incluye no exponer la API a la red local.

    uvicorn app.main:app --host 127.0.0.1 --port 8000

La plata viaja como texto en el JSON, nunca como número. Un float en JavaScript
pierde centavos, y el reporte tiene que cuadrar al centavo.

La conexión a la base se inyecta (`get_conn`), así los tests corren la API
contra un esquema temporal y nunca contra tus datos.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .agents.patrones import es_memorizable, nombre_legible
from .cargas import TAMANIO_MAXIMO, TIPOS_ACEPTADOS, Cargador, CargaEnCurso, flujo_sse
from .clasificar import cargar_categorias, construir
from .corridas import Corrida, conteo_del_resumen, ultimas
from .memoria import (
    aplicar_decision,
    cargar_memoria,
    clasificar_pendientes,
    grupos_pendientes,
    grupos_resueltos,
)
from .pipeline import procesar
from .recurrentes import proyeccion
from .reporte import (
    CATEGORIAS_INTERNAS,
    ResumenDescuadrado,
    ResumenNoEncontrado,
    reporte_de_resumen,
)
from .store import SuperposicionParcial, YaIngerido, conectar, guardar

app = FastAPI(title="Centavo", version="0.4.0")


def get_conn() -> Iterator[psycopg.Connection]:
    try:
        conn = conectar()
    except psycopg.OperationalError as exc:
        raise HTTPException(
            503, "La base de datos no responde. ¿Está corriendo Docker?"
        ) from exc
    try:
        yield conn
    finally:
        conn.close()


def _crear_flota(conn: psycopg.Connection):
    return construir("flota", categorias=cargar_categorias(conn), reglas=cargar_memoria(conn))


_cargador = Cargador(conectar=conectar, crear_clasificador=_crear_flota)


def get_cargador() -> Cargador:
    """Las cargas en segundo plano. Se inyecta, como la conexión, para los tests."""
    return _cargador


def _pendientes(conn: psycopg.Connection) -> dict:
    grupos = grupos_pendientes(conn)
    return {"grupos": len(grupos), "movimientos": sum(g["cantidad"] for g in grupos)}


@app.get("/api/salud")
def salud(conn: psycopg.Connection = Depends(get_conn)) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return {"ok": True}


@app.get("/api/resumenes")
def resumenes(conn: psycopg.Connection = Depends(get_conn)) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.banco, s.archivo, s.periodo_desde, s.periodo_hasta, s.estado,
                   count(t.id),
                   count(t.id) FILTER (WHERE t.estado_clasificacion = 'resuelto')
            FROM statements s
            LEFT JOIN transactions t ON t.statement_id = s.id
            GROUP BY s.id
            ORDER BY s.periodo_desde DESC, s.id DESC
            """
        )
        return [
            {
                "id": sid,
                "banco": banco,
                "archivo": archivo,
                "periodo_desde": desde.isoformat(),
                "periodo_hasta": hasta.isoformat(),
                "estado": estado,
                "movimientos": movimientos,
                "resueltos": resueltos,
            }
            for sid, banco, archivo, desde, hasta, estado, movimientos, resueltos in cur.fetchall()
        ]


@app.get("/api/categorias")
def categorias(conn: psycopg.Connection = Depends(get_conn)) -> list[dict]:
    todas = cargar_categorias(conn, para_modelo=False)
    with conn.cursor() as cur:
        cur.execute("SELECT nombre, solo_determinista FROM categories")
        deterministas = dict(cur.fetchall())
    return [
        {
            "nombre": nombre,
            "descripcion": descripcion,
            "solo_determinista": deterministas[nombre],
            "interna": nombre in CATEGORIAS_INTERNAS,
        }
        for nombre, descripcion in todas.items()
    ]


def _grupo_json(g: dict) -> dict:
    tipo, contraparte = g["clave"].split("|", 1)
    return {
        "clave": g["clave"],
        "tipo": tipo,
        # La clave, normalizada para comparar; `nombre`, como lo imprime el
        # resumen, para mostrar.
        "contraparte": contraparte,
        "nombre": nombre_legible(g["ejemplos"][0]) if g["ejemplos"] else contraparte,
        "cantidad": g["cantidad"],
        "devoluciones": g["devoluciones"],
        "total": str(g["total"]),
        "desde": g["desde"].isoformat(),
        "hasta": g["hasta"].isoformat(),
        "ejemplos": g["ejemplos"],
        "memorizable": es_memorizable(g["clave"]),
    }


def _lista(grupos: list[dict]) -> dict:
    return {
        "total_grupos": len(grupos),
        "total_movimientos": sum(g["cantidad"] for g in grupos),
        "grupos": grupos,
    }


@app.get("/api/revision/grupos")
def revision_grupos(conn: psycopg.Connection = Depends(get_conn)) -> dict:
    return _lista([_grupo_json(g) for g in grupos_pendientes(conn)])


@app.get("/api/revision/resueltos")
def revision_resueltos(conn: psycopg.Connection = Depends(get_conn)) -> dict:
    """Lo ya resuelto, por contraparte y categoría, para corregirlo con la misma
    decisión que la bandeja. Una decisión tuya pisa lo que haya: memoria,
    evidencia o modelo."""
    return _lista([
        _grupo_json(g) | {"categoria": g["categoria"], "via": g["via"]}
        for g in grupos_resueltos(conn)
    ])


class DecisionPedido(BaseModel):
    clave: str = Field(min_length=3)
    categoria: str = Field(min_length=1)


@app.post("/api/revision/decisiones")
def decidir(pedido: DecisionPedido, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM transactions t
            JOIN statements s ON s.id = t.statement_id
            WHERE t.clave = %s AND s.estado = 'cuadrado'
            """,
            (pedido.clave,),
        )
        if cur.fetchone()[0] == 0:
            raise HTTPException(404, f"No hay movimientos con la clave {pedido.clave!r}.")

    try:
        cambiados = aplicar_decision(conn, pedido.clave, pedido.categoria)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    return {
        "cambiados": cambiados,
        "se_aprende": es_memorizable(pedido.clave),
        "pendientes": _pendientes(conn),
    }


@app.get("/api/resumenes/{statement_id}/reporte")
def reporte(statement_id: int, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    try:
        return reporte_de_resumen(conn, statement_id)
    except ResumenNoEncontrado as exc:
        raise HTTPException(404, f"No existe el resumen {statement_id}.") from exc
    except ResumenDescuadrado as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/proyeccion")
def proyeccion_del_mes(conn: psycopg.Connection = Depends(get_conn)) -> dict:
    """Recurrentes fijos y proyección del mes siguiente al último cargado. Es
    aritmética sobre lo cargado, en piezas que se pueden sumar."""
    return proyeccion(conn)


class IngestPedido(BaseModel):
    path: str


@app.post("/api/ingest")
def ingest(pedido: IngestPedido, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    """Lo mismo que tools.ingerir, sin modelo. Cada salida deja una fila en
    `corridas`, y `clasificacion` cuenta sólo este resumen, no lo pendiente de
    los otros meses."""
    path = Path(pedido.path)
    if not path.exists():
        raise HTTPException(404, f"No existe: {path}")

    corrida = Corrida("api")
    try:
        resumen, resultado = procesar(path)
    except ValueError as exc:
        # Un archivo que no se puede parsear es un 422, no un 500: el problema
        # está en el archivo o en el perfil, no en el servidor.
        corrida.guardar(conn, "error", error=exc)
        raise HTTPException(422, str(exc)) from exc

    try:
        statement_id = guardar(resumen, resultado, conn=conn)
    except YaIngerido as exc:
        corrida.guardar(conn, "ya_ingerido", statement_id=exc.statement_id)
        raise HTTPException(409, str(exc)) from exc
    except SuperposicionParcial as exc:
        corrida.guardar(conn, "superposicion")
        raise HTTPException(409, str(exc)) from exc

    if resultado.cuadra:
        clasificar_pendientes(conn)
    numero = corrida.guardar(
        conn, "cuadrado" if resultado.cuadra else "descuadrado", statement_id=statement_id
    )
    return {
        "statement_id": statement_id,
        "cuadra": resultado.cuadra,
        "detalle": resultado.explicar(),
        "clasificacion": conteo_del_resumen(conn, statement_id) if resultado.cuadra else {},
        "pendientes": _pendientes(conn),
        "corrida": numero,
    }


@app.get("/api/corridas")
def corridas(
    limite: int = Query(20, ge=1, le=200),
    conn: psycopg.Connection = Depends(get_conn),
) -> list[dict]:
    """Las últimas ingestas: cuánto tardaron, cómo terminaron y cuánto costó el
    modelo. Sólo conteos: la tabla no tiene dónde guardar un movimiento."""
    return [
        c | {"empezo_en": c["empezo_en"].isoformat(), "segundos_modelo": str(c["segundos_modelo"])}
        for c in ultimas(conn, limite)
    ]


# ---------------------------------------------------------------------------
# Cargar un resumen desde el navegador
# ---------------------------------------------------------------------------

@app.post("/api/cargas", status_code=202)
async def nueva_carga(
    request: Request,
    nombre: str = Query(min_length=1, max_length=255),
    con_modelo: bool = False,
    cargador: Cargador = Depends(get_cargador),
) -> dict:
    """El archivo viaja como cuerpo crudo con su tipo: application/pdf, text/csv
    o application/octet-stream. No hace falta multipart, y ninguno de esos tipos
    es de los que el navegador manda a otro origen sin preguntar antes: un sitio
    ajeno abierto en el navegador no puede subir nada, porque la API no autoriza
    otros orígenes."""
    tipo = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if tipo not in TIPOS_ACEPTADOS:
        raise HTTPException(
            415, "Mandá el archivo como application/pdf, text/csv o application/octet-stream."
        )
    grande = HTTPException(413, f"El archivo supera los {TAMANIO_MAXIMO // 2**20} MB.")
    declarado = request.headers.get("content-length", "")
    if declarado.isdigit() and int(declarado) > TAMANIO_MAXIMO:
        raise grande
    partes, leido = [], 0
    async for trozo in request.stream():
        leido += len(trozo)
        if leido > TAMANIO_MAXIMO:
            raise grande
        partes.append(trozo)
    contenido = b"".join(partes)
    if not contenido:
        raise HTTPException(422, "El archivo está vacío.")
    try:
        carga = cargador.lanzar(nombre, contenido, con_modelo)
    except CargaEnCurso as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return carga.resumen()


@app.get("/api/cargas/activa")
def carga_activa(cargador: Cargador = Depends(get_cargador)) -> dict | None:
    """La carga en curso, si hay una: la interfaz la retoma al volver."""
    activa = cargador.activa()
    return None if activa is None else activa.resumen()


@app.get("/api/cargas/{carga_id}/eventos")
def eventos_de_carga(
    carga_id: str, request: Request, cargador: Cargador = Depends(get_cargador)
):
    """El progreso de una carga, por SSE. Con Last-Event-ID retoma desde ahí; si
    la carga terminó y ya no queda nada por mandar, 204, que le indica al
    navegador que deje de reconectar."""
    carga = cargador.obtener(carga_id)
    if carga is None:
        raise HTTPException(404, "No existe esa carga: se olvidan al reiniciar la API.")
    ultimo = request.headers.get("last-event-id", "")
    desde = int(ultimo) + 1 if ultimo.isdigit() else 0
    if carga.terminada and desde >= len(carga.eventos):
        return Response(status_code=204)
    return StreamingResponse(
        flujo_sse(carga, desde),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
