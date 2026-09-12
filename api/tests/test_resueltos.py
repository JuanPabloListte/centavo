"""Corregir una decisión ya tomada, y medir cuánto acierta la memoria.

Contra Postgres, en un esquema temporal. Lo que fijan:

- Cambiar la categoría de una contraparte reinicia sus confirmaciones: no suma.
- Cada corrección guarda cómo estaba resuelto el movimiento antes, vía y estado.
- Lo resuelto se lista por contraparte y categoría, con su vía, y se puede
  cambiar con la misma decisión que la bandeja, también si lo decidió la
  evidencia: una decisión tuya es absoluta.
- La precisión de la memoria cuenta sólo lo que la memoria resolvió sola.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.patrones import clave_memoria
from app.memoria import (
    aplicar_decision,
    clasificar_pendientes,
    grupos_pendientes,
    grupos_resueltos,
    precision_de_la_memoria,
)
from app.pipeline import procesar
from app.store import guardar

RESUMEN_MP = Path(__file__).parent / "fixtures" / "resumen_mp.pdf"
MIGRACION = (
    Path(__file__).resolve().parents[2] / "db" / "migraciones" / "003_correcciones_con_via.sql"
)
SUBE = clave_memoria("Pago SUBE Viajes")
RENDIMIENTOS = clave_memoria("Rendimientos")


@pytest.fixture
def cargado(db):
    """El sintético guardado y clasificado sin modelo: 9 por evidencia, 23 pendientes."""
    resumen, resultado = procesar(RESUMEN_MP)
    guardar(resumen, resultado, conn=db)
    clasificar_pendientes(db)
    return resumen, resultado


def _uno(db, sql: str, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def _mes_siguiente(db, resumen, resultado) -> int:
    """El mismo resumen como si fuera otro mes: otros IDs de operación."""
    siguiente = resumen.model_copy(deep=True)
    siguiente.sha256, siguiente.archivo = "a" * 64, "siguiente.pdf"
    for m in siguiente.movimientos:
        m.id_operacion = "9" + m.id_operacion
    return guardar(siguiente, resultado, conn=db)


def test_cambiar_la_categoria_reinicia_las_confirmaciones(cargado, db):
    aplicar_decision(db, SUBE, "Transporte")
    aplicar_decision(db, SUBE, "Transporte")
    assert _uno(db, "SELECT confirmaciones FROM memoria WHERE clave = %s", SUBE) == 2

    assert aplicar_decision(db, SUBE, "Otros") == 4

    assert _uno(db, "SELECT confirmaciones FROM memoria WHERE clave = %s", SUBE) == 1
    assert _uno(db, """
        SELECT c.nombre FROM memoria m JOIN categories c ON c.id = m.categoria_id
        WHERE m.clave = %s
    """, SUBE) == "Otros"


def test_cada_correccion_guarda_como_estaba_resuelto_antes(cargado, db):
    aplicar_decision(db, SUBE, "Transporte")
    aplicar_decision(db, SUBE, "Otros")

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT via_anterior, estado_anterior, count(*)
            FROM correcciones WHERE clave = %s
            GROUP BY 1, 2 ORDER BY 2
            """,
            (SUBE,),
        )
        assert cur.fetchall() == [("regla", "resuelto", 4), (None, "sin_procesar", 4)]


def test_lo_resuelto_se_lista_por_contraparte_con_categoria_y_via(cargado, db):
    antes = {g["clave"]: g for g in grupos_resueltos(db)}
    rend = antes[RENDIMIENTOS]
    assert (rend["categoria"], rend["via"], rend["cantidad"]) == \
           ("Rendimientos e intereses", "evidencia", 6)
    assert SUBE not in antes

    aplicar_decision(db, SUBE, "Transporte")

    despues = {g["clave"]: g for g in grupos_resueltos(db)}
    assert (despues[SUBE]["categoria"], despues[SUBE]["via"], despues[SUBE]["cantidad"]) == \
           ("Transporte", "regla", 4)
    assert SUBE not in {g["clave"] for g in grupos_pendientes(db)}
    assert sum(g["cantidad"] for g in despues.values()) == 9 + 4


def test_pisar_lo_que_decidio_la_evidencia_esta_permitido_y_queda_registrado(cargado, db):
    """Una decisión tuya es absoluta, también sobre la evidencia. Queda la traza."""
    assert aplicar_decision(db, RENDIMIENTOS, "Otros") == 6
    assert _uno(db, """
        SELECT count(*) FROM correcciones WHERE clave = %s AND via_anterior = 'evidencia'
    """, RENDIMIENTOS) == 6
    assert {g["clave"]: g["via"] for g in grupos_resueltos(db)}[RENDIMIENTOS] == "regla"


def test_la_precision_de_la_memoria_cuenta_solo_lo_que_resolvio_sola(cargado, db):
    resumen, resultado = cargado
    aplicar_decision(db, SUBE, "Transporte")      # decisión directa: no es la memoria
    assert precision_de_la_memoria(db) == \
           {"resueltos_por_memoria": 0, "corregidos": 0, "acierto": None}

    _mes_siguiente(db, resumen, resultado)
    clasificar_pendientes(db)                     # 4 SUBE nuevos, resueltos por la memoria
    assert precision_de_la_memoria(db) == \
           {"resueltos_por_memoria": 4, "corregidos": 0, "acierto": 1.0}

    assert aplicar_decision(db, SUBE, "Otros") == 8    # los 4 viejos y los 4 nuevos
    p = precision_de_la_memoria(db)
    assert (p["resueltos_por_memoria"], p["corregidos"], p["acierto"]) == (0, 4, 0.0)


def test_la_migracion_agrega_las_columnas_y_se_puede_repetir(db):
    with db.cursor() as cur:
        cur.execute("SELECT current_schema()")
        esquema = cur.fetchone()[0]
        # Sólo el esquema temporal en el search_path: en public están tus datos.
        cur.execute(f"SET search_path TO {esquema}")
        cur.execute("ALTER TABLE correcciones DROP COLUMN via_anterior, DROP COLUMN estado_anterior")

        migracion = MIGRACION.read_text(encoding="utf-8")
        cur.execute(migracion)
        cur.execute(migracion)

        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'correcciones'",
            (esquema,),
        )
        columnas = {fila[0] for fila in cur.fetchall()}
    assert {"via_anterior", "estado_anterior"} <= columnas


def test_la_api_lista_lo_resuelto_y_deja_cambiarlo(cargado, db):
    from app.main import app, get_conn

    def conexion_de_prueba():
        yield db

    app.dependency_overrides[get_conn] = conexion_de_prueba
    try:
        cliente = TestClient(app)
        datos = cliente.get("/api/revision/resueltos").json()
        assert datos["total_movimientos"] == 9
        rend = next(g for g in datos["grupos"] if g["clave"] == RENDIMIENTOS)
        assert (rend["categoria"], rend["via"], rend["nombre"], rend["cantidad"]) == \
               ("Rendimientos e intereses", "evidencia", "Rendimientos", 6)

        r = cliente.post("/api/revision/decisiones", json={"clave": RENDIMIENTOS, "categoria": "Otros"})
        assert r.status_code == 200 and r.json()["cambiados"] == 6

        grupos = cliente.get("/api/revision/resueltos").json()["grupos"]
        rend = next(g for g in grupos if g["clave"] == RENDIMIENTOS)
        assert (rend["categoria"], rend["via"]) == ("Otros", "regla")
    finally:
        app.dependency_overrides.clear()
