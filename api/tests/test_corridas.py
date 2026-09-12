"""Observabilidad: una fila por ingesta, con conteos y sin datos.

Contra Postgres, en un esquema temporal. Fijan que la corrida cuenta sólo el
resumen que se ingirió, que toma el costo del modelo del cliente, que de un
error guarda la clase y no el texto, y que la API la registra en cada salida.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.corridas import Corrida, ultimas
from app.llm import ClienteLLM, Uso
from app.memoria import clasificar_pendientes
from app.pipeline import procesar
from app.store import guardar

RESUMEN_MP = Path(__file__).parent / "fixtures" / "resumen_mp.pdf"
MIGRACION = Path(__file__).resolve().parents[2] / "db" / "migraciones" / "004_corridas.sql"
SINTETICO = {"sin_procesar": 23, "evidencia": 9}


@pytest.fixture
def sid(db):
    resumen, resultado = procesar(RESUMEN_MP)
    statement_id = guardar(resumen, resultado, conn=db)
    clasificar_pendientes(db)
    return statement_id


def _esquema(db) -> str:
    with db.cursor() as cur:
        cur.execute("SELECT current_schema()")
        return cur.fetchone()[0]


def test_la_corrida_cuenta_el_resumen_que_se_ingirio(db, sid):
    numero = Corrida("terminal").guardar(db, "cuadrado", statement_id=sid)

    [c] = ultimas(db)
    assert c["id"] == numero
    assert (c["origen"], c["resultado"], c["statement_id"]) == ("terminal", "cuadrado", sid)
    assert (c["por_via"], c["movimientos"]) == (SINTETICO, 32)
    assert (c["modelo"], c["llamadas_modelo"], c["tokens_entrada"], c["error_tipo"]) == \
           (None, 0, 0, None)
    assert c["milisegundos"] >= 0


def test_toma_el_costo_del_modelo_y_cuenta_los_desacuerdos(db, sid):
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE transactions SET via = 'desacuerdo', estado_clasificacion = 'needs_review'
            WHERE id IN (SELECT id FROM transactions
                          WHERE statement_id = %s AND estado_clasificacion = 'sin_procesar'
                          ORDER BY id LIMIT 2)
            """,
            (sid,),
        )
    db.commit()
    cliente = ClienteLLM(modelo="qwen2.5:7b", uso=Uso(
        llamadas=46, reparaciones=3, tokens_entrada=30000, tokens_salida=4000, segundos=321.456,
    ))

    Corrida("terminal").guardar(db, "cuadrado", statement_id=sid, cliente=cliente)

    [c] = ultimas(db)
    assert (c["modelo"], c["llamadas_modelo"], c["reparaciones"]) == ("qwen2.5:7b", 46, 3)
    assert (c["tokens_entrada"], c["tokens_salida"], str(c["segundos_modelo"])) == \
           (30000, 4000, "321.46")
    assert c["desacuerdos"] == 2
    assert c["por_via"] == {"sin_procesar": 21, "evidencia": 9, "needs_review": 2}


def test_de_un_error_guarda_la_clase_y_no_el_texto(db):
    error = ValueError("resumen.pdf línea 3007: no se pudo leer '$ 12.345,67' de Fulano Ejemplo")
    Corrida("api").guardar(db, "error", error=error)

    [c] = ultimas(db)
    assert (c["resultado"], c["error_tipo"], c["statement_id"], c["por_via"]) == \
           ("error", "ValueError", None, {})
    assert "Fulano" not in json.dumps(c, default=str)


def test_la_tabla_no_tiene_donde_guardar_un_movimiento(db):
    """Contrato: las únicas columnas de texto son cortas y de valores fijos."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'corridas'
              AND data_type IN ('text', 'character varying')
            """,
            (_esquema(db),),
        )
        assert {f[0] for f in cur.fetchall()} == {"origen", "resultado", "modelo", "error_tipo"}


def test_un_resultado_desconocido_no_se_guarda(db):
    with pytest.raises(ValueError):
        Corrida("api").guardar(db, "a medias")


def test_la_migracion_crea_la_tabla_y_se_puede_repetir(db):
    esquema = _esquema(db)
    with db.cursor() as cur:
        # Sólo el esquema temporal en el search_path: en public están tus datos.
        cur.execute(f"SET search_path TO {esquema}")
        cur.execute("DROP TABLE corridas")
        migracion = MIGRACION.read_text(encoding="utf-8")
        cur.execute(migracion)
        cur.execute(migracion)
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = 'corridas'",
            (esquema,),
        )
        assert cur.fetchone()[0] == 1


# ---------------------------------------------------------------------------
# La API
# ---------------------------------------------------------------------------

@pytest.fixture
def cliente(db):
    from app.main import app, get_conn

    def conexion_de_prueba():
        yield db

    app.dependency_overrides[get_conn] = conexion_de_prueba
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_la_api_registra_cada_salida_de_una_ingesta(cliente, tmp_path):
    ok = cliente.post("/api/ingest", json={"path": str(RESUMEN_MP)})
    assert ok.status_code == 200, ok.text

    assert cliente.post("/api/ingest", json={"path": str(RESUMEN_MP)}).status_code == 409

    roto = tmp_path / "no-es-un-resumen.csv"
    roto.write_text("fecha;descripcion;importe\n01/08/2026;algo;10\n", encoding="utf-8")
    assert cliente.post("/api/ingest", json={"path": str(roto)}).status_code == 422

    corridas = cliente.get("/api/corridas").json()
    assert [c["resultado"] for c in corridas] == ["error", "ya_ingerido", "cuadrado"]
    assert corridas[-1]["id"] == ok.json()["corrida"]
    assert corridas[1]["statement_id"] == ok.json()["statement_id"]
    assert all(isinstance(c["segundos_modelo"], str) for c in corridas)
    assert [c["id"] for c in cliente.get("/api/corridas?limite=1").json()] == [corridas[0]["id"]]


def test_la_clasificacion_de_la_api_cuenta_solo_el_resumen_nuevo(cliente, db):
    """Antes sumaba lo pendiente de todos los meses cargados."""
    resumen, resultado = procesar(RESUMEN_MP)
    previo = resumen.model_copy(deep=True)
    previo.sha256, previo.archivo = "b" * 64, "previo.pdf"
    for m in previo.movimientos:
        m.id_operacion = "8" + m.id_operacion
    guardar(previo, resultado, conn=db)
    clasificar_pendientes(db)

    r = cliente.post("/api/ingest", json={"path": str(RESUMEN_MP)})

    assert r.status_code == 200, r.text
    assert r.json()["clasificacion"] == SINTETICO
    assert r.json()["pendientes"]["movimientos"] == 46
