"""Cargar un resumen desde el navegador: en segundo plano y con progreso por SSE.

Contra Postgres, en un esquema temporal. El cargador corre en un hilo con su
propia conexión a ese esquema, y el modelo es un clasificador falso. Fijan los
eventos de cada salida, que el archivo no queda en disco, que el modelo ve sólo
el resumen cargado y que no hay dos cargas a la vez.
"""

import json
import tempfile
import threading
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.cargas import Cargador, nombre_seguro
from app.clasificar import Clasificacion
from app.llm import ClienteLLM
from app.memoria import clasificar_pendientes
from app.pipeline import procesar
from app.store import DATABASE_URL, guardar

RESUMEN_MP = Path(__file__).parent / "fixtures" / "resumen_mp.pdf"
PDF = RESUMEN_MP.read_bytes()
SINTETICO = {"sin_procesar": 23, "evidencia": 9}


class FlotaFalsa:
    """Manda todo a revisión, anota qué ve y, si se le pide, espera una señal."""

    def __init__(self):
        self.vistas: list[str] = []
        self.cliente = ClienteLLM(modelo="falso")
        self.senal: threading.Event | None = None

    def clasificar(self, descripcion, monto, titular=None):
        if self.senal is not None:
            self.senal.wait(10)
        self.vistas.append(descripcion)
        self.cliente.uso.llamadas += 2
        return Clasificacion(categoria="Otros", confianza=0.5, via="desacuerdo",
                             estado="needs_review")


@pytest.fixture
def entorno(db, monkeypatch, tmp_path):
    from app.main import app, get_cargador, get_conn

    with db.cursor() as cur:
        cur.execute("SELECT current_schema()")
        esquema = cur.fetchone()[0]
    flota = FlotaFalsa()
    cargador = Cargador(
        conectar=lambda: psycopg.connect(DATABASE_URL, options=f"-c search_path={esquema},public"),
        crear_clasificador=lambda conn: flota,
    )
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    def conexion_de_prueba():
        yield db

    app.dependency_overrides[get_conn] = conexion_de_prueba
    app.dependency_overrides[get_cargador] = lambda: cargador
    try:
        yield TestClient(app), cargador, flota, tmp_path
    finally:
        if flota.senal is not None:
            flota.senal.set()
        for carga in list(cargador._cargas.values()):
            if carga.hilo is not None:
                carga.hilo.join(30)
        app.dependency_overrides.clear()


def _cargar(cliente, contenido=PDF, nombre="resumen_mp.pdf", tipo="application/pdf", **params):
    return cliente.post("/api/cargas", params={"nombre": nombre, **params}, content=contenido,
                        headers={"Content-Type": tipo})


def _eventos(cliente, cargador, carga_id) -> list[tuple[str, dict]]:
    """Espera a que la carga termine y lee todo su flujo SSE."""
    cargador.obtener(carga_id).hilo.join(30)
    r = cliente.get(f"/api/cargas/{carga_id}/eventos")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    salida = []
    for bloque in r.text.split("\n\n"):
        campos = dict(linea.split(": ", 1) for linea in bloque.splitlines()
                      if linea and not linea.startswith(":"))
        if "event" in campos:
            salida.append((campos["event"], json.loads(campos["data"])))
    return salida


def _uno(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def test_una_carga_recorre_los_pasos_y_termina_como_tools_ingerir(entorno, db):
    cliente, cargador, _, carpeta = entorno
    r = _cargar(cliente)
    assert r.status_code == 202, r.text
    eventos = _eventos(cliente, cargador, r.json()["id"])

    assert [(d["paso"], d["estado"]) for t, d in eventos if t == "paso"] == [
        ("lectura", "en_curso"), ("lectura", "hecho"), ("compuerta", "hecho"),
        ("guardado", "en_curso"), ("guardado", "hecho"),
        ("clasificacion", "en_curso"), ("clasificacion", "hecho"),
    ]
    tipo, fin = eventos[-1]
    assert (tipo, fin["cuadra"], fin["clasificacion"]) == ("fin", True, SINTETICO)
    assert list(carpeta.iterdir()) == [], "el archivo no queda en disco"
    assert _uno(db, "SELECT archivo FROM statements WHERE id = %s", fin["statement_id"]) == \
           ("resumen_mp.pdf",)
    assert _uno(db, "SELECT origen, resultado FROM corridas WHERE id = %s", fin["corrida"]) == \
           ("api", "cuadrado")


def test_el_mismo_archivo_otra_vez_termina_en_falla_ya_ingerido(entorno):
    cliente, cargador, _, _ = entorno
    primero = _eventos(cliente, cargador, _cargar(cliente).json()["id"])[-1][1]
    tipo, falla = _eventos(cliente, cargador, _cargar(cliente).json()["id"])[-1]
    assert (tipo, falla["motivo"], falla["statement_id"]) == \
           ("falla", "ya_ingerido", primero["statement_id"])


def test_un_archivo_que_no_es_un_resumen_termina_en_falla_de_lectura(entorno):
    cliente, cargador, _, carpeta = entorno
    r = _cargar(cliente, contenido=b"fecha;descripcion;importe\n01/08/2026;algo;10\n",
                nombre="otra.csv", tipo="text/csv")
    tipo, falla = _eventos(cliente, cargador, r.json()["id"])[-1]
    assert (tipo, falla["motivo"]) == ("falla", "lectura")
    assert list(carpeta.iterdir()) == []


def test_con_modelo_la_flota_ve_solo_el_resumen_cargado_y_avisa_el_progreso(entorno, db):
    cliente, cargador, flota, _ = entorno
    resumen, resultado = procesar(RESUMEN_MP)
    previo = resumen.model_copy(deep=True)
    previo.sha256, previo.archivo = "b" * 64, "previo.pdf"
    for m in previo.movimientos:
        m.id_operacion = "8" + m.id_operacion
    guardar(previo, resultado, conn=db)
    clasificar_pendientes(db)

    eventos = _eventos(cliente, cargador, _cargar(cliente, con_modelo="true").json()["id"])

    progreso = [d for t, d in eventos if t == "progreso"]
    assert [p["hechos"] for p in progreso] == list(range(24))
    assert (progreso[0]["segundos_restantes"], progreso[-1]["segundos_restantes"]) == (None, 0)
    assert len(flota.vistas) == 23, "sólo los pendientes del resumen cargado"
    tipo, fin = eventos[-1]
    assert (tipo, fin["clasificacion"]) == ("fin", {"needs_review": 23, "evidencia": 9})
    assert _uno(db, """
        SELECT count(*) FROM transactions t JOIN statements s ON s.id = t.statement_id
        WHERE s.archivo = 'previo.pdf' AND t.estado_clasificacion = 'sin_procesar'
    """) == (23,), "lo pendiente de otro mes no pasa por el modelo"
    assert _uno(db, "SELECT llamadas_modelo, desacuerdos FROM corridas WHERE id = %s",
                fin["corrida"]) == (46, 23)


def test_no_hay_dos_cargas_a_la_vez(entorno):
    cliente, cargador, flota, _ = entorno
    flota.senal = threading.Event()
    primera = _cargar(cliente, con_modelo="true")
    assert primera.status_code == 202
    assert cliente.get("/api/cargas/activa").json()["id"] == primera.json()["id"]

    assert _cargar(cliente, contenido=b"%PDF-otro", nombre="otro.pdf").status_code == 409

    flota.senal.set()
    assert _eventos(cliente, cargador, primera.json()["id"])[-1][0] == "fin"
    assert cliente.get("/api/cargas/activa").json() is None


def test_el_pedido_se_valida_antes_de_lanzar(entorno, monkeypatch):
    import app.main as principal

    cliente, cargador, _, _ = entorno
    assert _cargar(cliente, tipo="text/plain").status_code == 415, "un tipo que no pide permiso"
    assert _cargar(cliente, contenido=b"").status_code == 422
    assert _cargar(cliente, nombre="..").status_code == 422
    monkeypatch.setattr(principal, "TAMANIO_MAXIMO", 1024)
    assert _cargar(cliente).status_code == 413
    assert cargador.activa() is None and not cargador._cargas


def test_una_carga_terminada_no_reabre_el_flujo(entorno):
    """Con Last-Event-ID del último evento, 204: EventSource deja de reconectar."""
    cliente, cargador, _, _ = entorno
    carga_id = _cargar(cliente).json()["id"]
    eventos = _eventos(cliente, cargador, carga_id)
    r = cliente.get(f"/api/cargas/{carga_id}/eventos",
                    headers={"Last-Event-ID": str(len(eventos) - 1)})
    assert r.status_code == 204
    assert cliente.get("/api/cargas/no-existe/eventos").status_code == 404


def test_nombre_seguro_saca_las_carpetas():
    assert nombre_seguro(r"C:\Users\alguien\Descargas\resumen.pdf") == "resumen.pdf"
    assert nombre_seguro("../../etc/resumen.pdf") == "resumen.pdf"
    with pytest.raises(ValueError):
        nombre_seguro("   ")


def test_clasificar_pendientes_se_limita_a_un_resumen_y_avisa_el_avance(db):
    resumen, resultado = procesar(RESUMEN_MP)
    sid = guardar(resumen, resultado, conn=db)
    otro = resumen.model_copy(deep=True)
    otro.sha256 = "c" * 64
    for m in otro.movimientos:
        m.id_operacion = "7" + m.id_operacion
    guardar(otro, resultado, conn=db)
    avances = []

    conteo = clasificar_pendientes(db, statement_id=sid, al_avanzar=lambda h, t: avances.append((h, t)))

    assert conteo == SINTETICO
    assert (avances[0], avances[-1], len(avances)) == ((0, 32), (32, 32), 33)
    assert _uno(db, "SELECT count(*) FROM transactions WHERE statement_id <> %s "
                    "AND estado_clasificacion = 'sin_procesar'", sid) == (32,)
