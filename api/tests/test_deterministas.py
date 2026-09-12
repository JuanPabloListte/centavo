"""Tests de las categorías que resuelve el código sin consultar al modelo.

Son movimientos que no son gastos ni ingresos —reservas, rendimientos,
transferencias entre cuentas propias— y que en un resumen real distorsionan
todo si se cuentan mal: una reserva contada como gasto infla el mes, y una
transferencia a uno mismo contada como ingreso infla lo que entró.
"""

from decimal import Decimal

import pytest

from app.agents.categorizador import Categorizador
from app.agents.comercio import AgenteComercio
from app.agents.patrones import analizar, es_el_titular
from app.clasificar import Clasificador
from app.supervisor import Supervisor
from tests.test_clasificacion import CATEGORIAS, ClienteFalso

TITULAR = "María Laura Pérez Gómez"


# ---------------------------------------------------------------------------
# Textos fijos de la fuente
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("descripcion, monto, categoria", [
    ("Dinero reservado Vacaciones", Decimal("-120000"), "Ahorro y reservas"),
    ("Dinero retirado Vacaciones", Decimal("40000"), "Ahorro y reservas"),
    ("Rendimientos", Decimal("21.37"), "Rendimientos e intereses"),
])
def test_un_texto_fijo_determina_la_categoria(descripcion, monto, categoria):
    assert analizar(descripcion, monto).categoria_determinada == categoria


@pytest.mark.parametrize("descripcion, monto", [
    ("Dinero reservado Vacaciones", Decimal("5000")),     # reservar resta, no suma
    ("Dinero retirado Vacaciones", Decimal("-5000")),     # retirar suma, no resta
    ("Rendimientos", Decimal("-10")),
])
def test_con_el_signo_contrario_no_se_adivina(descripcion, monto):
    """El signo está verificado sobre un resumen real. Un movimiento que lo
    contradice es otra cosa, y no se resuelve por el texto."""
    assert analizar(descripcion, monto).categoria_determinada is None


# ---------------------------------------------------------------------------
# Transferencias entre cuentas propias
# ---------------------------------------------------------------------------

def test_transferencia_a_uno_mismo_con_el_nombre_reordenado():
    p = analizar("Transferencia recibida PEREZ MARIA LAURA", Decimal("250000"), TITULAR)
    assert p.categoria_determinada == "Movimientos entre cuentas propias"


def test_el_mismo_apellido_no_es_uno_mismo():
    """El caso peligroso: un familiar con el mismo apellido."""
    p = analizar("Transferencia enviada Perez Carlos Alberto", Decimal("-15000"), TITULAR)
    assert p.categoria_determinada is None


@pytest.mark.parametrize("contraparte, esperado", [
    ("PEREZ MARIA LAURA", True),
    ("Maria Laura Perez Gomez", True),
    ("Perez Carlos Alberto", False),
    ("PEREZ", False),              # una sola palabra no alcanza
    ("PEREZ MARIA LAU", False),    # nombre truncado: ante la duda, se pregunta
])
def test_es_el_titular(contraparte, esperado):
    assert es_el_titular(contraparte, TITULAR) is esperado


def test_sin_titular_no_hay_transferencia_propia():
    p = analizar("Transferencia recibida PEREZ MARIA LAURA", Decimal("1000"), None)
    assert p.categoria_determinada is None


# ---------------------------------------------------------------------------
# Lo determinado no pasa por el modelo, en ninguno de los dos modos
# ---------------------------------------------------------------------------

def test_el_supervisor_resuelve_lo_determinado_sin_llamar_a_los_agentes():
    cliente = ClienteFalso([])          # si se llama al modelo, revienta
    sup = Supervisor(
        categorizador=Categorizador(cliente, CATEGORIAS),
        agente_comercio=AgenteComercio(cliente, CATEGORIAS),
    )

    v = sup.resolver("Rendimientos", Decimal("30.67"))

    assert (v.categoria, v.via, v.estado) == ("Rendimientos e intereses", "evidencia", "resuelto")
    assert cliente.uso.llamadas == 0


def test_el_modo_solo_tambien_resuelve_lo_determinado_sin_modelo():
    cliente = ClienteFalso([])
    clas = Clasificador(CATEGORIAS, cliente=cliente)

    r = clas.clasificar(
        "Transferencia recibida PEREZ MARIA LAURA", Decimal("1000"), titular=TITULAR
    )

    assert (r.categoria, r.via) == ("Movimientos entre cuentas propias", "evidencia")
    assert cliente.uso.llamadas == 0
