"""Tests de la API local y del reporte del mes.

Corren contra un esquema temporal (fixture `db`), con la conexión de la API
reemplazada por la de prueba. El resumen es el sintético con maquetación de
Mercado Pago, clasificado sin modelo: 9 movimientos por evidencia y 23
pendientes.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.patrones import clave_memoria
from app.memoria import clasificar_pendientes
from app.pipeline import procesar
from app.store import guardar

RESUMEN_MP = Path(__file__).parent / "fixtures" / "resumen_mp.pdf"
INTERNAS = {"Ahorro y reservas", "Movimientos entre cuentas propias"}


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


@pytest.fixture
def statement_id(db):
    resumen, resultado = procesar(RESUMEN_MP)
    sid = guardar(resumen, resultado, conn=db)
    clasificar_pendientes(db)
    return sid


def _reporte(cliente, sid) -> dict:
    r = cliente.get(f"/api/resumenes/{sid}/reporte")
    assert r.status_code == 200, r.text
    return r.json()


def _suma_sin_resolver(db, sid) -> Decimal:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT coalesce(sum(monto), 0) FROM transactions
            WHERE statement_id = %s AND estado_clasificacion <> 'resuelto'
            """,
            (sid,),
        )
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# El reporte
# ---------------------------------------------------------------------------

def test_el_reporte_cuadra_con_el_resumen_antes_de_revisar(cliente, db, statement_id):
    rep = _reporte(cliente, statement_id)
    t = rep["totales"]

    assert rep["cuadra"], f"diferencia {rep['diferencia']}"
    assert Decimal(t["ingresos"]) == Decimal("658.43"), "los 6 rendimientos"
    # reserva -120.000, retiro de la reserva +40.000, transferencia propia +250.000
    assert Decimal(t["internos"]) == Decimal("170000.00")
    assert Decimal(t["gastos"]) == Decimal("0.00"), "todavía no se decidió ningún gasto"
    # Calculado por otro camino: lo que no está resuelto, sumado directo en SQL.
    assert Decimal(t["sin_clasificar"]) == _suma_sin_resolver(db, statement_id)
    assert rep["cobertura"] == {"movimientos": 32, "resueltos": 9, "pendientes": 23}


def test_los_movimientos_internos_no_cuentan_como_gasto_ni_ingreso(cliente, statement_id):
    rep = _reporte(cliente, statement_id)

    for linea in rep["por_categoria"]:
        if linea["categoria"] in INTERNAS:
            assert linea["tipo"] == "interno", linea
    tipos = {l["tipo"] for l in rep["por_categoria"] if l["categoria"] in INTERNAS}
    assert tipos == {"interno"}
    assert Decimal(rep["totales"]["neto"]) == Decimal("658.43"), "el neto no incluye internos"


def test_decidir_mueve_la_plata_a_su_categoria_y_el_reporte_sigue_cuadrando(cliente, statement_id):
    r = cliente.post(
        "/api/revision/decisiones",
        json={"clave": clave_memoria("Pago SUBE Viajes"), "categoria": "Transporte"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cambiados"] == 4
    assert r.json()["pendientes"] == {"grupos": r.json()["pendientes"]["grupos"], "movimientos": 19}

    rep = _reporte(cliente, statement_id)
    transporte = next(l for l in rep["por_categoria"] if l["categoria"] == "Transporte")
    assert (transporte["tipo"], Decimal(transporte["monto"]), transporte["movimientos"]) == \
           ("gasto", Decimal("-8600.00"), 4)
    assert Decimal(rep["totales"]["gastos"]) == Decimal("-8600.00")
    assert rep["cuadra"]


def test_un_resumen_descuadrado_no_tiene_reporte(cliente, db):
    resumen, resultado = procesar(RESUMEN_MP)
    sid = guardar(resumen, resultado.model_copy(update={"cuadra": False}), conn=db)

    assert cliente.get(f"/api/resumenes/{sid}/reporte").status_code == 409


def test_un_resumen_inexistente_da_404(cliente, statement_id):
    assert cliente.get("/api/resumenes/999999/reporte").status_code == 404


# ---------------------------------------------------------------------------
# Revisión
# ---------------------------------------------------------------------------

def test_los_grupos_dicen_tipo_contraparte_y_si_se_aprenden(cliente, statement_id):
    datos = cliente.get("/api/revision/grupos").json()

    assert datos["total_movimientos"] == 23
    sube = next(g for g in datos["grupos"] if g["clave"] == clave_memoria("Pago SUBE Viajes"))
    assert (sube["tipo"], sube["contraparte"], sube["cantidad"], sube["memorizable"]) == \
           ("PAGO", "SUBE VIAJES", 4, True)


def test_categoria_inexistente_da_422(cliente, statement_id):
    r = cliente.post(
        "/api/revision/decisiones",
        json={"clave": clave_memoria("Pago SUBE Viajes"), "categoria": "Criptomonedas"},
    )
    assert r.status_code == 422


def test_clave_sin_movimientos_da_404_y_no_se_guarda_en_memoria(cliente, db, statement_id):
    r = cliente.post(
        "/api/revision/decisiones",
        json={"clave": "PAGO|NO EXISTE", "categoria": "Transporte"},
    )
    assert r.status_code == 404
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM memoria")
        assert cur.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Contrato
# ---------------------------------------------------------------------------

def test_la_plata_viaja_como_texto_nunca_como_numero(cliente, statement_id):
    """Un float en JavaScript pierde centavos; el reporte tiene que cuadrar al centavo."""
    rep = _reporte(cliente, statement_id)
    assert all(isinstance(v, str) for v in rep["totales"].values())
    assert all(isinstance(l["monto"], str) for l in rep["por_categoria"])
    grupos = cliente.get("/api/revision/grupos").json()["grupos"]
    assert all(isinstance(g["total"], str) for g in grupos)


def test_las_categorias_marcan_las_internas(cliente, statement_id):
    cats = {c["nombre"]: c for c in cliente.get("/api/categorias").json()}

    assert len(cats) == 18
    assert cats["Ahorro y reservas"]["interna"] and cats["Ahorro y reservas"]["solo_determinista"]
    assert not cats["Rendimientos e intereses"]["interna"], "los rendimientos son ingreso"
    assert not cats["Transporte"]["interna"]


def test_los_grupos_muestran_el_nombre_como_lo_imprime_el_resumen(cliente, statement_id):
    """La clave ordena y pasa a mayúsculas los nombres: sirve para comparar, no
    para leer. En pantalla va el nombre tal como está en el resumen."""
    grupos = cliente.get("/api/revision/grupos").json()["grupos"]
    carniceria = next(
        g for g in grupos if g["clave"] == clave_memoria("Pago con QR Carnicería Los Hermanos")
    )

    assert carniceria["contraparte"] == "CARNICERIA HERMANOS LOS"
    assert carniceria["nombre"] == "Carnicería Los Hermanos"


def test_nombre_legible_de_cada_tipo():
    from app.agents.patrones import nombre_legible

    assert nombre_legible("Transferencia enviada Perez Carlos Alberto") == "Perez Carlos Alberto"
    assert nombre_legible("Pago SUBE Viajes") == "SUBE Viajes"
    assert nombre_legible("Pedido de 2 productos Pizzería La Esquina") == "Pizzería La Esquina"
    assert nombre_legible("MERPAGO*KIOSCO LA ESQ") == "KIOSCO LA ESQ"
    assert nombre_legible("Transferencia enviada") == "Sin contraparte"
