"""Una devolución unida a su pago.

En los resúmenes reales, la devolución de un pago trae el mismo ID de operación
que el pago. Estos tests fijan qué pasa con ese vínculo: la devolución toma la
clave del pago, se decide con él, hereda su categoría sin pasar por el modelo,
resta del gasto en el reporte y, si el pago no está cargado, queda suelta y se
revisa aparte.

Contra Postgres, en un esquema temporal. El resumen es el sintético más una
devolución agregada en memoria: el PDF no la trae, y agregarla ahí movería los
números esperados de todos los tests que lo leen.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.patrones import clave_memoria, es_devolucion
from app.balance import verificar_cuadratura
from app.clasificar import Clasificacion
from app.devoluciones import devoluciones_sueltas, vincular_devoluciones
from app.memoria import aplicar_decision, clasificar_pendientes, grupos_pendientes
from app.models import CierrePorSaldos
from app.pipeline import procesar
from app.reporte import reporte_de_resumen
from app.store import guardar
from tools.resumen_mp_sintetico import con_devolucion

RESUMEN_MP = Path(__file__).parent / "fixtures" / "resumen_mp.pdf"
MIGRACION = (
    Path(__file__).resolve().parents[2] / "db" / "migraciones" / "002_devoluciones.sql"
)
FARMACIA = "Pago con QR Farmacia del Centro"
PAGO = Decimal("-11076.00")
PARTE = Decimal("5000.00")


@pytest.mark.parametrize("descripcion, esperado", [
    ("Devolución de Pago con QR Farmacia del Centro", True),
    ("devolucion de pago x", True),
    ("DEVOLUCIÓN DE PAGO X", True),
    ("Pago con QR Farmacia del Centro", False),
    ("Transferencia recibida Devolución Gomez", False),
])
def test_es_devolucion(descripcion, esperado):
    assert es_devolucion(descripcion) is esperado


# ---------------------------------------------------------------------------
# Contra Postgres, en un esquema temporal (fixture `db`, en conftest.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sintetico():
    return procesar(RESUMEN_MP)


def _pago(resumen, descripcion=FARMACIA):
    return next(m for m in resumen.movimientos if m.descripcion_cruda == descripcion)


def _fila(db, sql: str, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def _id_de(db, sid: int, descripcion: str) -> int:
    return _fila(
        db, "SELECT id FROM transactions WHERE statement_id = %s AND descripcion_cruda = %s",
        sid, descripcion,
    )[0]


def _devolucion(db, sid: int):
    """(devuelve_a, clave, estado, categoría) de la devolución del resumen."""
    return _fila(db, """
        SELECT t.devuelve_a, t.clave, t.estado_clasificacion, c.nombre
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.categoria_id
        WHERE t.statement_id = %s AND t.descripcion_cruda ILIKE 'devoluci%%'
    """, sid)


@pytest.fixture
def con_parcial(db, sintetico):
    """El sintético más una devolución parcial del pago a la farmacia, guardado."""
    resumen, _ = sintetico
    resumen, resultado = con_devolucion(resumen, _pago(resumen), monto=PARTE)
    return guardar(resumen, resultado, conn=db)


def _mes_siguiente(resumen, pago, sha: str, **cambios):
    """Un resumen del mes siguiente con una sola fila: la devolución de `pago`."""
    desde = resumen.periodo_hasta + timedelta(days=1)
    inicial = resumen.cierre.saldo_final
    devolucion = pago.model_copy(update={
        "fecha": desde + timedelta(days=2),
        "monto": PARTE,
        "descripcion_cruda": f"Devolución de {pago.descripcion_cruda}",
        "linea_origen": 1001,
        "saldo": inicial + PARTE,
    } | cambios)
    siguiente = resumen.model_copy(update={
        "sha256": sha * 64,
        "archivo": "siguiente.pdf",
        "periodo_desde": desde,
        "periodo_hasta": desde + timedelta(days=29),
        "cierre": CierrePorSaldos(saldo_inicial=inicial, saldo_final=inicial + PARTE),
        "movimientos": [devolucion],
    })
    return siguiente, verificar_cuadratura(siguiente)


def test_la_devolucion_se_une_a_su_pago_y_toma_su_clave(db, con_parcial):
    devuelve_a, clave, _, _ = _devolucion(db, con_parcial)

    assert devuelve_a == _id_de(db, con_parcial, FARMACIA)
    assert clave == clave_memoria(FARMACIA)
    assert clave != clave_memoria(f"Devolución de {FARMACIA}"), "ya no es una contraparte aparte"
    assert devoluciones_sueltas(db) == 0


def test_una_devolucion_del_mes_siguiente_encuentra_el_pago_del_mes_anterior(db, sintetico):
    resumen, resultado = sintetico
    primero = guardar(resumen, resultado, conn=db)
    segundo = guardar(*_mes_siguiente(resumen, _pago(resumen), "b"), conn=db)

    assert _devolucion(db, segundo)[0] == _id_de(db, primero, FARMACIA)


def test_una_devolucion_cargada_antes_que_su_pago_se_une_cuando_el_pago_aparece(db, sintetico):
    """Cargar mayo antes que abril: el vínculo se calcula sobre todo lo que
    todavía no lo tiene, no sólo sobre el resumen nuevo."""
    resumen, resultado = sintetico
    segundo = guardar(*_mes_siguiente(resumen, _pago(resumen), "b"), conn=db)
    assert _devolucion(db, segundo)[0] is None
    assert devoluciones_sueltas(db) == 1

    primero = guardar(resumen, resultado, conn=db)

    assert _devolucion(db, segundo)[0] == _id_de(db, primero, FARMACIA)
    assert devoluciones_sueltas(db) == 0


def test_sin_pago_cargado_queda_suelta_y_se_revisa_aparte(db, sintetico):
    resumen, resultado = sintetico
    guardar(resumen, resultado, conn=db)
    sid = guardar(
        *_mes_siguiente(resumen, _pago(resumen), "b", id_operacion="999999999999"), conn=db
    )
    clasificar_pendientes(db)

    devuelve_a, clave, estado, _ = _devolucion(db, sid)
    assert devuelve_a is None
    assert clave == clave_memoria(f"Devolución de {FARMACIA}")
    assert estado == "sin_procesar"
    assert devoluciones_sueltas(db) == 1
    grupo = next(g for g in grupos_pendientes(db) if g["clave"] == clave)
    assert (grupo["cantidad"], grupo["devoluciones"]) == (1, 0)


def test_una_devolucion_mayor_que_el_pago_no_se_une(db, sintetico):
    """No es una devolución de ese pago. Ante la duda, a revisión."""
    resumen, _ = sintetico
    pago = _pago(resumen)
    resumen, resultado = con_devolucion(resumen, pago, monto=-pago.monto + Decimal("0.01"))
    sid = guardar(resumen, resultado, conn=db)

    assert _devolucion(db, sid)[0] is None
    assert devoluciones_sueltas(db) == 1


def test_una_decision_sobre_el_pago_resuelve_la_devolucion(db, con_parcial):
    clasificar_pendientes(db)
    clave = clave_memoria(FARMACIA)
    grupo = next(g for g in grupos_pendientes(db) if g["clave"] == clave)
    assert (grupo["cantidad"], grupo["devoluciones"], grupo["total"]) == (2, 1, PAGO + PARTE)
    assert grupo["ejemplos"][0] == FARMACIA, "el grupo se nombra por el pago"

    assert aplicar_decision(db, clave, "Salud y Farmacia") == 2

    _, _, estado, categoria = _devolucion(db, con_parcial)
    assert (estado, categoria) == ("resuelto", "Salud y Farmacia")
    assert clave not in {g["clave"] for g in grupos_pendientes(db)}


class ClasificadorTestigo:
    """Anota qué descripciones le llegan. Nunca resuelve nada."""

    def __init__(self):
        self.vistas: list[str] = []

    def clasificar(self, descripcion, monto, titular=None):
        self.vistas.append(descripcion)
        return Clasificacion(
            categoria="Otros", confianza=0.5, via="modelo", estado="needs_review"
        )


def test_la_devolucion_hereda_la_categoria_del_pago_resuelto_sin_pasar_por_el_modelo(
    db, con_parcial
):
    # El pago lo resolvió el modelo por consenso: su clave no está en memoria.
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE transactions
               SET categoria_id = (SELECT id FROM categories WHERE nombre = 'Salud y Farmacia'),
                   confianza = 0.90, via = 'consenso', estado_clasificacion = 'resuelto'
             WHERE id = %s
            """,
            (_id_de(db, con_parcial, FARMACIA),),
        )
    db.commit()
    testigo = ClasificadorTestigo()

    conteo = clasificar_pendientes(db, testigo)

    _, _, estado, categoria = _devolucion(db, con_parcial)
    assert (estado, categoria) == ("resuelto", "Salud y Farmacia")
    assert conteo["evidencia"] == 9 + 1, "los 9 del sintético, más la devolución"
    assert not any(es_devolucion(d) for d in testigo.vistas), "el modelo nunca ve una devolución"


def test_si_el_pago_no_esta_resuelto_la_devolucion_espera_y_no_va_al_modelo(db, con_parcial):
    testigo = ClasificadorTestigo()

    clasificar_pendientes(db, testigo)

    assert _devolucion(db, con_parcial)[2] == "sin_procesar"
    assert FARMACIA in testigo.vistas, "el pago sí pasa por el modelo"
    assert not any(es_devolucion(d) for d in testigo.vistas)


def test_en_el_reporte_la_devolucion_resta_del_gasto_y_no_es_ingreso(db, con_parcial):
    clasificar_pendientes(db)
    aplicar_decision(db, clave_memoria(FARMACIA), "Salud y Farmacia")

    rep = reporte_de_resumen(db, con_parcial)

    farmacia = next(l for l in rep["por_categoria"] if l["categoria"] == "Salud y Farmacia")
    assert (farmacia["tipo"], Decimal(farmacia["monto"]), farmacia["movimientos"]) == \
           ("gasto", PAGO + PARTE, 2)
    assert Decimal(rep["totales"]["gastos"]) == PAGO + PARTE
    assert Decimal(rep["totales"]["ingresos"]) == Decimal("658.43"), "sólo los rendimientos"
    assert rep["devoluciones"] == 1
    assert rep["cuadra"], rep["diferencia"]


def test_el_grupo_se_nombra_por_el_pago_aunque_la_devolucion_venga_antes(db, sintetico):
    """Si el resumen imprime la devolución antes que el pago, el mismo día, el
    primer ejemplo del grupo sigue siendo el pago: es lo que se muestra."""
    resumen, _ = sintetico
    pago = _pago(resumen)
    i = resumen.movimientos.index(pago)
    devolucion = pago.model_copy(update={
        "monto": PARTE,
        "descripcion_cruda": f"Devolución de {pago.descripcion_cruda}",
        "linea_origen": pago.linea_origen - 1,
    })
    saldo, movimientos = resumen.cierre.saldo_inicial, []
    for m in [*resumen.movimientos[:i], devolucion, *resumen.movimientos[i:]]:
        saldo += m.monto
        movimientos.append(m.model_copy(update={"saldo": saldo}))
    nuevo = resumen.model_copy(update={
        "movimientos": movimientos,
        "cierre": resumen.cierre.model_copy(update={"saldo_final": saldo}),
    })
    sid = guardar(nuevo, verificar_cuadratura(nuevo), conn=db)
    clasificar_pendientes(db)

    assert _devolucion(db, sid)[0] == _id_de(db, sid, FARMACIA)
    grupo = next(g for g in grupos_pendientes(db) if g["clave"] == clave_memoria(FARMACIA))
    assert grupo["ejemplos"][0] == FARMACIA


def test_la_migracion_agrega_la_columna_se_puede_repetir_y_une_lo_ya_cargado(db, con_parcial):
    clave_suelta = clave_memoria(f"Devolución de {FARMACIA}")
    with db.cursor() as cur:
        cur.execute("SELECT current_schema()")
        esquema = cur.fetchone()[0]
        # Sólo el esquema temporal en el search_path: en public están tus datos.
        cur.execute(f"SET search_path TO {esquema}")

        # La base como estaba antes del cambio: sin la columna, y la devolución
        # con la clave de un movimiento suelto.
        cur.execute("ALTER TABLE transactions DROP COLUMN devuelve_a")
        cur.execute(
            "UPDATE transactions SET clave = %s WHERE descripcion_cruda ILIKE 'devoluci%%'",
            (clave_suelta,),
        )

        migracion = MIGRACION.read_text(encoding="utf-8")
        cur.execute(migracion)
        cur.execute(migracion)

        cur.execute(
            """
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'transactions' AND column_name = 'devuelve_a'
            """,
            (esquema,),
        )
        assert cur.fetchone()[0] == 1

    assert vincular_devoluciones(db) == 1, "lo que tools.migrar hace después de los .sql"
    db.commit()
    assert _devolucion(db, con_parcial)[:2] == (
        _id_de(db, con_parcial, FARMACIA), clave_memoria(FARMACIA)
    )


def test_la_api_dice_cuantas_devoluciones_incluye_cada_grupo_y_el_reporte(db, con_parcial):
    from app.main import app, get_conn

    clasificar_pendientes(db)

    def conexion_de_prueba():
        yield db

    app.dependency_overrides[get_conn] = conexion_de_prueba
    try:
        cliente = TestClient(app)
        grupos = cliente.get("/api/revision/grupos").json()["grupos"]
        farmacia = next(g for g in grupos if g["clave"] == clave_memoria(FARMACIA))
        assert (farmacia["cantidad"], farmacia["devoluciones"], farmacia["nombre"]) == \
               (2, 1, "Farmacia del Centro")
        assert cliente.get(f"/api/resumenes/{con_parcial}/reporte").json()["devoluciones"] == 1
    finally:
        app.dependency_overrides.clear()
