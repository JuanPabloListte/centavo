"""Recurrentes fijos y proyección del mes.

Primero el detector solo, con series sintéticas: mensual estable, con aumentos,
irregular, de una sola vez, con un salto, con el día corrido, con dos por mes y
un ingreso. Después contra Postgres, con cuatro meses armados a partir del
resumen sintético, y la proyección del quinto.
"""

import calendar
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.patrones import clave_memoria
from app.balance import verificar_cuadratura
from app.memoria import aplicar_decision, clasificar_pendientes
from app.models import CierrePorSaldos
from app.pipeline import procesar
from app.recurrentes import Aparicion, detectar, evaluar, mes_siguiente, proyeccion
from app.store import guardar

RESUMEN_MP = Path(__file__).parent / "fixtures" / "resumen_mp.pdf"
CERO = Decimal("0.00")
ULTIMO = date(2026, 11, 1)


def _serie(montos, dias=None, meses=None):
    """Una aparición por mes, en los últimos meses hasta noviembre inclusive."""
    dias = dias or [10] * len(montos)
    meses = meses or [date(2026, 12 - len(montos) + i, 1) for i in range(len(montos))]
    return [
        Aparicion(mes, mes.replace(day=dia), Decimal(m))
        for mes, dia, m in zip(meses, dias, montos)
    ]


def test_mensual_estable():
    r = evaluar("X", _serie(["-1000", "-1000", "-1000", "-1000"]), ULTIMO)
    assert r is not None
    assert (r.monto_esperado, r.dia_esperado, len(r.meses), r.tendencia) == \
           (Decimal("-1000"), 10, 4, Decimal("0"))


def test_con_aumentos_mensuales_del_diez_por_ciento():
    r = evaluar("X", _serie(["-1000", "-1100", "-1210", "-1331"]), ULTIMO)
    assert r is not None
    assert r.monto_esperado == Decimal("-1331"), "el último monto es la mejor estimación"
    assert r.tendencia == Decimal("0.331")


def test_un_salto_grande_no_es_recurrente():
    """Un aumento del 30% se tolera; un salto al doble es otra cosa."""
    assert evaluar("X", _serie(["-1000", "-1250", "-1600"]), ULTIMO) is not None
    assert evaluar("X", _serie(["-1000", "-1000", "-2000"]), ULTIMO) is None


def test_irregular_con_un_hueco_no_llega_a_tres_seguidos():
    meses = [date(2026, 8, 1), date(2026, 9, 1), date(2026, 11, 1)]
    assert evaluar("X", _serie(["-1000"] * 3, meses=meses), ULTIMO) is None


def test_de_una_sola_vez():
    assert evaluar("X", _serie(["-50000"], meses=[ULTIMO]), ULTIMO) is None


def test_si_no_aparece_en_el_ultimo_mes_no_se_proyecta():
    """Tres meses seguidos, pero se cortó: un servicio dado de baja."""
    meses = [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]
    assert evaluar("X", _serie(["-1000"] * 3, meses=meses), ULTIMO) is None


def test_el_dia_corrido_mas_de_cinco_no_es_fijo():
    assert evaluar("X", _serie(["-1000"] * 3, dias=[5, 8, 10]), ULTIMO) is not None
    assert evaluar("X", _serie(["-1000"] * 3, dias=[5, 12, 20]), ULTIMO) is None


def test_dos_por_mes_es_variable_no_fijo():
    serie = _serie(["-1000"] * 3) + _serie(["-1000"] * 3, dias=[20] * 3)
    assert evaluar("X", serie, ULTIMO) is None


def test_un_cambio_de_signo_no_es_recurrente():
    assert evaluar("X", _serie(["-1000", "-1000", "1000"]), ULTIMO) is None


def test_un_ingreso_mensual_tambien_es_recurrente():
    r = evaluar("X", _serie(["30000", "30000", "31000"]), ULTIMO)
    assert r is not None and r.monto_esperado == Decimal("31000")


def test_detectar_ordena_los_gastos_grandes_primero():
    por_clave = {
        "A": _serie(["-100"] * 3), "B": _serie(["-5000"] * 3), "C": _serie(["2000"] * 3),
    }
    assert [r.clave for r in detectar(por_clave, ULTIMO)] == ["B", "A", "C"]


def test_mes_siguiente_cruza_el_anio():
    assert mes_siguiente(date(2026, 12, 1)) == date(2027, 1, 1)


# ---------------------------------------------------------------------------
# Contra Postgres: cuatro meses armados con el resumen sintético
# ---------------------------------------------------------------------------

STREAMING = "Pago de suscripción Streaming Ejemplo Plus"
MUSICA = "Pago de suscripción Música Ejemplo"
INTERNET = "Pago Servicio de Internet Ejemplo Sociedad Anónima"
LUZ = "Pago Luz Distribuidora Ejemplo"
CLUB = "Transferencia enviada Club Atlético Barrio Norte Cuota Social Mensual"
EXPENSAS = "Transferencia enviada Consorcio Edificio Las Acacias Administración Expensas"
LOPEZ = "Transferencia recibida Lopez Martin Ezequiel"
SUBE = "Pago SUBE Viajes"


def _mes(resumen, k: int, montos: dict | None = None, dias: dict | None = None):
    """El resumen sintético como si fuera k meses después de agosto de 2026:
    fechas, período, IDs y saldos corridos. `montos` cambia o saltea (None)
    movimientos por descripción; `dias`, el día del mes."""
    montos, dias = montos or {}, dias or {}
    desde = date(2026, 8 + k, 1)
    hasta = date(desde.year, desde.month, calendar.monthrange(desde.year, desde.month)[1])
    saldo, movimientos = resumen.cierre.saldo_inicial, []
    for m in resumen.movimientos:
        monto = montos.get(m.descripcion_cruda, m.monto)
        if monto is None:
            continue
        monto = Decimal(monto).quantize(CERO)
        saldo += monto
        movimientos.append(m.model_copy(update={
            "fecha": date(desde.year, desde.month, dias.get(m.descripcion_cruda, m.fecha.day)),
            "monto": monto,
            "saldo": saldo,
            "id_operacion": f"{k}{m.id_operacion}",
        }))
    nuevo = resumen.model_copy(update={
        "sha256": format(k, "x") * 64, "archivo": f"mes{k}.pdf",
        "periodo_desde": desde, "periodo_hasta": hasta, "movimientos": movimientos,
        "cierre": CierrePorSaldos(saldo_inicial=resumen.cierre.saldo_inicial, saldo_final=saldo),
    })
    return nuevo, verificar_cuadratura(nuevo)


@pytest.fixture
def cuatro_meses(db):
    """Agosto a noviembre. Streaming sube 5% por mes; Música no cambia; Internet
    falta en octubre; Luz salta 50% en noviembre; el club se corre de día;
    las expensas aparecen sólo en noviembre; SUBE va cuatro veces por mes."""
    resumen, _ = procesar(RESUMEN_MP)
    for k in range(4):
        montos = {
            STREAMING: Decimal("-8122.73") * Decimal("1.05") ** k,
            INTERNET: None if k == 2 else Decimal("-21980.00"),
            LUZ: Decimal("-17450.00") * (Decimal("1.5") if k == 3 else 1),
            EXPENSAS: None if k < 3 else Decimal("-63400.00"),
        }
        nuevo, resultado = _mes(resumen, k, montos, dias={CLUB: 16 + 4 * k})
        assert resultado.cuadra, resultado.explicar()
        guardar(nuevo, resultado, conn=db)
    clasificar_pendientes(db)
    return resumen


def test_detecta_los_fijos_y_deja_afuera_lo_demas(cuatro_meses, db):
    p = proyeccion(db)
    detectados = {r["clave"]: r for r in p["recurrentes"]}

    assert clave_memoria(STREAMING) in detectados
    assert clave_memoria(MUSICA) in detectados
    assert clave_memoria(LOPEZ) in detectados, "un ingreso mensual también"
    for descripcion in (INTERNET, LUZ, CLUB, EXPENSAS, SUBE):
        assert clave_memoria(descripcion) not in detectados, descripcion

    streaming = detectados[clave_memoria(STREAMING)]
    esperado = (Decimal("-8122.73") * Decimal("1.05") ** 3).quantize(CERO)
    assert (streaming["monto_esperado"], streaming["meses"], streaming["dia_esperado"],
            streaming["tendencia"], streaming["categoria"], streaming["nombre"]) == \
           (str(esperado), 4, 4, "+16%", None, "Streaming Ejemplo Plus")


def test_la_proyeccion_es_del_mes_siguiente_y_se_reconstruye_sumando(cuatro_meses, db):
    aplicar_decision(db, clave_memoria(SUBE), "Transporte")

    p = proyeccion(db)

    assert (p["ultimo_mes"], p["mes_objetivo"]) == ("2026-11", "2026-12")
    assert p["meses_base"] == ["2026-09", "2026-10", "2026-11"]
    transporte = next(v for v in p["variable_por_categoria"] if v["categoria"] == "Transporte")
    assert (transporte["promedio"], transporte["meses_con_datos"]) == ("-8600.00", 3)
    assert Decimal(p["sin_clasificar"]["promedio"]) < 0
    assert p["sin_clasificar"]["movimientos_por_mes"] > 0

    t = p["totales"]
    assert Decimal(t["gastos_proyectados"]) == \
           Decimal(t["recurrentes_gastos"]) + Decimal(t["variable_gastos"]) + \
           Decimal(t["sin_clasificar_gastos"])
    assert Decimal(t["recurrentes_ingresos"]) == Decimal("30000.00")
    assert all(isinstance(v, str) for v in t.values()), "la plata viaja como texto"


def test_la_categoria_del_recurrente_sale_de_tu_decision(cuatro_meses, db):
    aplicar_decision(db, clave_memoria(STREAMING), "Suscripciones")
    p = proyeccion(db)
    assert {r["clave"]: r["categoria"] for r in p["recurrentes"]}[clave_memoria(STREAMING)] == \
           "Suscripciones"


def test_sin_resumenes_no_hay_proyeccion(db):
    p = proyeccion(db)
    assert p["mes_objetivo"] is None and p["recurrentes"] == [] and p["totales"] is None


def test_la_api_devuelve_la_proyeccion(cuatro_meses, db):
    from app.main import app, get_conn

    def conexion_de_prueba():
        yield db

    app.dependency_overrides[get_conn] = conexion_de_prueba
    try:
        r = TestClient(app).get("/api/proyeccion")
        assert r.status_code == 200, r.text
        assert r.json()["mes_objetivo"] == "2026-12"
        assert r.json()["criterios"]["meses_minimos"] == 3
    finally:
        app.dependency_overrides.clear()
