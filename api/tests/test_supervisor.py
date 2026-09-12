"""Tests del arbitraje y del analizador de patrones.

El harness mide si la flota clasifica mejor. Esto verifica que el supervisor
aplique las reglas en el orden correcto — que es una propiedad lógica, no
estadística, y por lo tanto se testea acá y no con una corrida de Ollama.
"""

from decimal import Decimal

from app.agents.categorizador import Categorizador
from app.agents.comercio import AgenteComercio
from app.agents.patrones import analizar
from app.supervisor import Supervisor
from tests.test_clasificacion import CATEGORIAS, ClienteFalso

CATS = {**CATEGORIAS, "Hogar y Electro": "electro", "Suscripciones": "streaming"}


def _supervisor(cat_dice: str, com_dice: str, reglas=None, conf=0.9) -> Supervisor:
    """Arma un supervisor con las dos opiniones guionadas."""
    cliente = ClienteFalso([
        f'{{"categoria":"{cat_dice}","confianza":{conf},"comercio":"x","motivo":"y"}}',
        f'{{"comercio":"x","reconocido":true,"categoria":"{com_dice}","confianza":{conf}}}',
    ])
    return Supervisor(
        categorizador=Categorizador(cliente, CATS),
        agente_comercio=AgenteComercio(cliente, CATS),
        reglas=reglas or {},
    )


# ---------------------------------------------------------------------------
# Analizador de patrones — determinista, sin modelo
# ---------------------------------------------------------------------------

def test_saca_el_prefijo_del_medio_de_pago():
    p = analizar("MERPAGO*KIOSCO LA ESQ", Decimal("-100"))
    assert p.medio_de_pago == "MERPAGO"
    assert p.comercio_limpio == "KIOSCO LA ESQ"


def test_detecta_cuota_con_barra():
    p = analizar("MUSIMUNDO CUOTA 7/12", Decimal("-30000"))
    assert (p.es_cuota, p.cuota_n, p.cuota_total) == (True, 7, 12)


def test_detecta_n_cuotas():
    p = analizar("GARBARINO 12 CUOTAS", Decimal("-30000"))
    assert p.es_cuota and p.cuota_total == 12


def test_una_cuota_no_puede_ser_suscripcion():
    """La restricción que corrige el error medido en la fase 1."""
    p = analizar("MUSIMUNDO CUOTA 7/12", Decimal("-30000"))
    assert "Suscripciones" in p.categorias_prohibidas


def test_no_confunde_una_fecha_con_una_cuota():
    p = analizar("PAGO SERVICIOS 2026", Decimal("-100"))
    assert not p.es_cuota


def test_monto_positivo_es_credito():
    assert analizar("SU PAGO - GRACIAS", Decimal("50000")).es_credito


# ---------------------------------------------------------------------------
# Reglas de arbitraje, en orden
# ---------------------------------------------------------------------------

def test_regla_1_una_correccion_tuya_gana_y_no_llama_al_modelo():
    from app.agents.patrones import clave_memoria

    cliente = ClienteFalso([])          # si llama al modelo, revienta
    sup = Supervisor(
        categorizador=Categorizador(cliente, CATS),
        agente_comercio=AgenteComercio(cliente, CATS),
        reglas={clave_memoria("COTO CICSA"): "Supermercado y Almacén"},
    )

    v = sup.resolver("coto cicsa", Decimal("-1"))

    assert v.via == "regla" and v.estado == "resuelto"
    assert cliente.uso.llamadas == 0


def test_regla_2_la_evidencia_dura_descarta_una_opinion():
    """Aunque el categorizador esté 'seguro', una cuota no es una suscripción."""
    sup = _supervisor(cat_dice="Suscripciones", com_dice="Hogar y Electro")

    v = sup.resolver("MUSIMUNDO CUOTA 7/12", Decimal("-30000"))

    assert v.categoria == "Hogar y Electro"
    assert v.via == "evidencia"
    assert v.estado == "resuelto"
    assert "Suscripciones" in v.motivo


def test_regla_2_si_la_evidencia_descarta_todo_va_a_revision():
    sup = _supervisor(cat_dice="Suscripciones", com_dice="Suscripciones")

    v = sup.resolver("GARBARINO 12 CUOTAS", Decimal("-30000"))

    assert v.estado == "needs_review"
    assert v.via == "evidencia"


def test_regla_3_consenso_resuelve():
    sup = _supervisor(cat_dice="Gastronomía", com_dice="Gastronomía")

    v = sup.resolver("PEDIDOSYA", Decimal("-5000"))

    assert v.estado == "resuelto"
    assert v.via == "consenso"
    assert v.acuerdo is True


def test_regla_4_desacuerdo_va_a_revision_sin_elegir_ganador():
    sup = _supervisor(cat_dice="Gastronomía", com_dice="Supermercado y Almacén")

    v = sup.resolver("MERPAGO*LA ESQUINA", Decimal("-2000"))

    assert v.estado == "needs_review"
    assert v.via == "desacuerdo"
    assert v.acuerdo is False
    assert v.opiniones == {
        "categorizador": "Gastronomía",
        "comercio": "Supermercado y Almacén",
    }


def test_el_desacuerdo_no_se_resuelve_por_confianza():
    """La fase 1 midió que la confianza autodeclarada no discrimina entre
    acierto y error. Elegir por ella sería decidir al azar con cara de rigor."""
    cliente = ClienteFalso([
        '{"categoria":"Gastronomía","confianza":0.99,"comercio":"x","motivo":"y"}',
        '{"comercio":"x","reconocido":true,"categoria":"Supermercado y Almacén","confianza":0.30}',
    ])
    sup = Supervisor(
        categorizador=Categorizador(cliente, CATS),
        agente_comercio=AgenteComercio(cliente, CATS),
    )

    v = sup.resolver("AMBIGUO", Decimal("-1"))

    assert v.estado == "needs_review", (
        "aunque un agente declare 0.99 contra 0.30, sigue siendo un desacuerdo"
    )
