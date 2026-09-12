"""Tests de la lógica de clasificación, sin tocar el modelo.

El harness (`python -m tools.evaluar`) mide qué tan bien clasifica. Esto es
otra cosa: verifica que el andamiaje alrededor del modelo haga lo que dice —
el loop de reparación, el umbral, el atajo determinista y la defensa contra
categorías inventadas.

Son las cuatro piezas que hacen que un modelo chico sea usable, así que tienen
que estar cubiertas por tests rápidos y deterministas, no por una corrida de
Ollama de tres minutos.
"""

from decimal import Decimal

import pytest

from app.agents.categorizador import Decision
from app.clasificar import Clasificador
from app.llm import ClienteLLM, ErrorModelo

CATEGORIAS = {
    "Supermercado y Almacén": "supermercados, kioscos",
    "Gastronomía": "restaurantes y delivery",
    "Otros": "no encaja en ninguna",
}


class ClienteFalso(ClienteLLM):
    """Devuelve respuestas guionadas en vez de llamar a Ollama."""

    def __init__(self, respuestas: list[str]):
        super().__init__(modelo="falso")
        self.respuestas = list(respuestas)
        self.mensajes_vistos: list[list[dict]] = []

    def _post(self, mensajes, esquema):
        self.mensajes_vistos.append(mensajes)
        self.uso.llamadas += 1
        if not self.respuestas:
            raise AssertionError("el cliente falso se quedó sin respuestas")
        return self.respuestas.pop(0), {}


# ---------------------------------------------------------------------------
# Loop de reparación
# ---------------------------------------------------------------------------

def test_repara_json_invalido_y_lo_cuenta():
    cliente = ClienteFalso([
        "no soy JSON, soy prosa",
        '{"categoria":"Gastronomía","confianza":0.9,"comercio":"Pedidos","motivo":"delivery"}',
    ])
    clas = Clasificador(CATEGORIAS, cliente=cliente)

    r = clas.clasificar("PEDIDOSYA", Decimal("-5000"))

    assert r.categoria == "Gastronomía"
    assert cliente.uso.llamadas == 2
    assert cliente.uso.reparaciones == 1


def test_el_reintento_le_pasa_el_error_de_validacion():
    """Reintentar con 'devolvé JSON válido' no sirve; con el error, sí."""
    cliente = ClienteFalso([
        '{"categoria":"Gastronomía","confianza":7,"comercio":"x","motivo":"y"}',  # confianza fuera de rango
        '{"categoria":"Gastronomía","confianza":0.8,"comercio":"x","motivo":"y"}',
    ])
    clas = Clasificador(CATEGORIAS, cliente=cliente)
    clas.clasificar("PEDIDOSYA", Decimal("-5000"))

    ultimo = cliente.mensajes_vistos[-1][-1]["content"]
    assert "no valida contra el esquema" in ultimo
    assert "confianza" in ultimo


def test_se_rinde_despues_del_maximo_de_reparaciones():
    cliente = ClienteFalso(["basura"] * 5)
    clas = Clasificador(CATEGORIAS, cliente=cliente)

    with pytest.raises(ErrorModelo):
        clas.clasificar("LO QUE SEA", Decimal("-1"))


def test_rescata_json_envuelto_en_markdown():
    cliente = ClienteFalso([
        '```json\n{"categoria":"Gastronomía","confianza":0.9,'
        '"comercio":"x","motivo":"y"}\n```'
    ])
    clas = Clasificador(CATEGORIAS, cliente=cliente)

    r = clas.clasificar("RAPPI", Decimal("-3000"))

    assert r.categoria == "Gastronomía"
    assert cliente.uso.reparaciones == 0, "rescatarlo es más barato que reintentar"


# ---------------------------------------------------------------------------
# Umbral de confianza — el guardrail que define el producto
# ---------------------------------------------------------------------------

def _cliente_con_confianza(valor: float) -> ClienteFalso:
    return ClienteFalso([
        f'{{"categoria":"Gastronomía","confianza":{valor},'
        f'"comercio":"x","motivo":"y"}}'
    ])


def test_confianza_alta_resuelve():
    clas = Clasificador(CATEGORIAS, cliente=_cliente_con_confianza(0.9), umbral=0.75)
    assert clas.clasificar("RAPPI", Decimal("-1")).estado == "resuelto"


def test_confianza_baja_va_a_revision():
    clas = Clasificador(CATEGORIAS, cliente=_cliente_con_confianza(0.4), umbral=0.75)
    r = clas.clasificar("ALGO RARO", Decimal("-1"))

    assert r.estado == "needs_review"
    # Guarda la sugerencia: a revisión no significa sin opinión.
    assert r.categoria == "Gastronomía"


def test_el_umbral_es_inclusivo():
    clas = Clasificador(CATEGORIAS, cliente=_cliente_con_confianza(0.75), umbral=0.75)
    assert clas.clasificar("BORDE", Decimal("-1")).estado == "resuelto"


# ---------------------------------------------------------------------------
# Atajo determinista: si ya lo corregiste, el modelo ni se entera
# ---------------------------------------------------------------------------

def test_una_regla_evita_llamar_al_modelo():
    from app.agents.patrones import clave_memoria

    cliente = ClienteFalso([])  # si lo llama, revienta
    clas = Clasificador(
        CATEGORIAS,
        # La memoria se indexa por clave de contraparte (fase 3): el código de
        # sucursal no cuenta, así que lo aprendido en otra sucursal aplica acá.
        reglas={clave_memoria("SUPERMERCADO DIA 0911"): "Supermercado y Almacén"},
        cliente=cliente,
    )

    r = clas.clasificar("supermercado dia 4821", Decimal("-9000"))

    assert r.via == "regla"
    assert r.estado == "resuelto"
    assert r.confianza == 1.0
    assert cliente.uso.llamadas == 0, "una regla tiene que costar cero tokens"


# ---------------------------------------------------------------------------
# Defensa contra categorías inventadas
# ---------------------------------------------------------------------------

def test_categoria_fuera_del_catalogo_cae_a_otros():
    cliente = ClienteFalso([
        '{"categoria":"Criptomonedas","confianza":0.95,"comercio":"x","motivo":"y"}'
    ])
    clas = Clasificador(CATEGORIAS, cliente=cliente)

    r = clas.clasificar("BINANCE", Decimal("-1"))

    assert r.categoria == "Otros"
    assert r.confianza == 0.0
    assert r.estado == "needs_review", "una categoría inventada no se resuelve sola"
    assert "Criptomonedas" in r.motivo


def test_el_esquema_rechaza_confianza_fuera_de_rango():
    with pytest.raises(Exception):
        Decision(categoria="Otros", confianza=1.5, comercio="x", motivo="y")
