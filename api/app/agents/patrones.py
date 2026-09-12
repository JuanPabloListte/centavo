"""Analizador de patrones. **No usa el modelo.**

Es el tercer participante del abanico y el más importante, aunque no tenga una
sola llamada a un LLM. No compite con una opinión: aporta **evidencia dura y
restricciones**, que es lo que le permite al supervisor arbitrar con algo más
que dos corazonadas.

Y en algunos casos aporta la respuesta entera. Hay movimientos cuya categoría
está escrita en el texto de la fuente —"Dinero reservado", "Rendimientos"— o
se deduce con certeza comparando con el titular del resumen. Para esos, llamar
al modelo sería pagar tokens por una respuesta que el código ya tiene.

También calcula la **clave de memoria** de la fase 3: la identidad exacta de
una contraparte, para que una decisión tuya se aplique a todos sus movimientos.

Regla de diseño: acá sólo entra lo que se puede afirmar con certeza a partir
del texto. Si hay que interpretar, es trabajo de otro agente.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

# "3/12", "CUOTA 7/12", "12 CUOTAS", "CUOTA 3 DE 6"
RE_CUOTA_BARRA = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b")
RE_CUOTA_DE = re.compile(r"\bCUOTA\s+(\d{1,2})\s+DE\s+(\d{1,2})\b", re.I)
RE_N_CUOTAS = re.compile(r"\b(\d{1,2})\s+CUOTAS?\b", re.I)

# Prefijos de medio de pago. No son el comercio.
PREFIJOS = re.compile(
    r"^(MERPAGO|MP|DLO|PAYU|PAGOFACIL|RAPIPAGO|DEBIN|POSNET|MOBBEX)\s*[\*\s\-]+",
    re.I,
)

# Sufijos de sucursal o terminal: "0231", "CBA CENTRO", "ARG"
RE_COLA_NUMERICA = re.compile(r"\s+\d{3,6}$")

RE_TRANSFERENCIA = re.compile(
    r"^Transferencia\s+(?P<sentido>recibida|enviada)\s+(?P<contraparte>.+)$", re.I
)

# Textos fijos del resumen de Mercado Pago que determinan la categoría sin
# interpretar nada. El signo está verificado sobre un resumen real: reservar
# resta del saldo disponible y retirar de la reserva suma. Si un movimiento
# viene con el signo contrario, contradice lo verificado y no se adivina.
#   (prefijo, signo esperado, categoría, qué es)
TEXTOS_DETERMINISTAS = (
    ("Dinero reservado", -1, "Ahorro y reservas", "plata apartada en una reserva propia"),
    ("Dinero retirado", +1, "Ahorro y reservas", "plata que vuelve de una reserva propia"),
    ("Rendimientos", +1, "Rendimientos e intereses", "rendimiento del saldo invertido"),
)

# Clave de memoria: tipo de movimiento + contraparte. El orden importa: "Pago
# con QR" y "Pago de suscripción" tienen que probarse antes que "Pago".
#   (patrón, tipo, ¿la contraparte es un nombre de persona?)
PATRONES_CLAVE = (
    (re.compile(r"^Transferencia\s+enviada\s+(.+)$", re.I), "TRANSF_ENVIADA", True),
    (re.compile(r"^Transferencia\s+recibida\s+(.+)$", re.I), "TRANSF_RECIBIDA", True),
    (re.compile(r"^Pago\s+con\s+QR\s+(.+)$", re.I), "QR", True),
    (re.compile(r"^Pedido\s+de\s+\d+\s+productos?\s+(.+)$", re.I), "PEDIDO", False),
    (re.compile(r"^Pedido\s+(.+)$", re.I), "PEDIDO", False),
    (re.compile(r"^Pago\s+de\s+suscripci[oó]n\s+(.+)$", re.I), "SUSCRIPCION", False),
    (re.compile(r"^Pago\s+(.+)$", re.I), "PAGO", False),
)


@dataclass
class Patrones:
    """Lo que se puede afirmar del texto sin interpretar nada."""

    comercio_limpio: str
    medio_de_pago: str | None = None
    es_cuota: bool = False
    cuota_n: int | None = None
    cuota_total: int | None = None
    es_credito: bool = False
    categorias_prohibidas: set[str] = field(default_factory=set)
    categoria_determinada: str | None = None
    evidencia: list[str] = field(default_factory=list)


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def _palabras(texto: str) -> set[str]:
    return {t for t in re.findall(r"[A-Z]+", _sin_tildes(texto).upper()) if len(t) > 1}


def es_el_titular(contraparte: str, titular: str) -> bool:
    """¿La contraparte de una transferencia es el propio titular del resumen?

    Mercado Pago imprime el nombre reordenado y en mayúsculas ("PEREZ MARIA
    LAURA" para "María Laura Pérez Gómez"), así que comparar strings no
    sirve. La regla: TODAS las palabras de la contraparte tienen que estar en
    el nombre del titular, y tienen que ser al menos dos.

    Compartir el apellido no alcanza, y ese es justamente el caso peligroso:
    una transferencia a un familiar con el mismo apellido NO es un movimiento
    entre cuentas propias. Un nombre truncado tampoco pasa — ante la duda, se
    pregunta.
    """
    c, t = _palabras(contraparte), _palabras(titular)
    return len(c) >= 2 and c <= t


# Movimientos que traen el tipo pero no la contraparte. En un resumen real
# aparecieron transferencias sin nombre: si compartieran una clave, una sola
# decisión etiquetaría a todas las transferencias anónimas —las de este mes y
# las de los que vienen— como la misma cosa.
RE_SIN_CONTRAPARTE = re.compile(
    r"^(Transferencia\s+(enviada|recibida)"
    r"|Pago(\s+con\s+QR|\s+de\s+suscripci[oó]n)?"
    r"|Pedido(\s+de\s+\d+\s+productos?)?)$",
    re.I,
)
MARCA_SIN_CONTRAPARTE = "SIN CONTRAPARTE"


def es_memorizable(clave: str) -> bool:
    """Una clave sin contraparte identifica a un movimiento, no a alguien: se
    puede decidir, pero no se aprende."""
    return MARCA_SIN_CONTRAPARTE not in clave


# Una devolución, como la imprime Mercado Pago: "Devolución de Pago X". Es sólo
# el texto: con qué pago se une lo decide el ID de operación
# (app/devoluciones.py), porque en los resúmenes reales el texto de la
# devolución no siempre repite el del pago.
RE_DEVOLUCION = re.compile(r"^Devoluci[oó]n\s+de\b", re.I)


def es_devolucion(descripcion: str) -> bool:
    return RE_DEVOLUCION.match(descripcion.strip()) is not None


def clave_memoria(descripcion: str, id_operacion: str | None = None) -> str:
    """Identidad EXACTA de la contraparte de un movimiento: 'TIPO|CONTRAPARTE'.

    Es la llave de la memoria de la fase 3: una decisión tuya sobre una clave se
    aplica a todos los movimientos que la comparten, ahora y en resúmenes
    futuros.

    - Normaliza mayúsculas, tildes y espacios, y descarta el código de sucursal:
      "SUPERMERCADO DIA 4821" y "SUPERMERCADO DIA 0911" son la misma cadena.
    - Descarta lo que varía y no identifica: "Pedido de 3 productos X" y
      "Pedido de 2 productos X" dan la misma clave.
    - La dirección de una transferencia es parte de la clave: mandarle plata a
      alguien y recibirla de esa persona pueden ser cosas distintas.
    - Para nombres de persona, las palabras se ordenan, así "PEREZ MARIA LAURA"
      y "MARIA LAURA PEREZ" son la misma persona. Sigue siendo exacta: con el
      mismo apellido y otro nombre, el conjunto de palabras es otro y la clave
      también.
    - Un movimiento sin contraparte ("Transferencia enviada", a secas) recibe
      una clave propia con su ID de operación, y `es_memorizable` la rechaza.
      Sin ID —al consultar la memoria— la clave nunca coincide con nada
      guardado, así que tampoco se resuelve sola.

    Lo que no es: una búsqueda por parecido. Dos contrapartes que se parecen
    tienen claves distintas, y eso es a propósito.
    """
    texto = descripcion.strip()

    if RE_SIN_CONTRAPARTE.match(texto):
        # El tipo canónico sale de los mismos patrones, completando un nombre.
        tipo = next(t for patron, t, _ in PATRONES_CLAVE if patron.match(f"{texto} X"))
        sufijo = f" {id_operacion}" if id_operacion else ""
        return f"{tipo}|{MARCA_SIN_CONTRAPARTE}{sufijo}"

    for patron, tipo, es_persona in PATRONES_CLAVE:
        if (m := patron.match(texto)) is not None:
            contraparte = _normalizar(m.group(1))
            if es_persona:
                contraparte = " ".join(sorted(contraparte.split()))
            return f"{tipo}|{contraparte}"
    return f"COMERCIO|{_normalizar(PREFIJOS.sub('', texto))}"


def _normalizar(texto: str) -> str:
    plano = " ".join(_sin_tildes(texto).upper().split())
    return RE_COLA_NUMERICA.sub("", plano).strip()


def nombre_legible(descripcion: str) -> str:
    """La contraparte tal como la imprime la fuente, para mostrársela a una persona.

    La clave de memoria ordena las palabras de los nombres y los pasa a
    mayúsculas: sirve para comparar, no para leer. "CARNICERIA HERMANOS LOS"
    identifica bien a la contraparte, pero en pantalla tiene que decir
    "Carnicería Los Hermanos".
    """
    texto = descripcion.strip()
    if RE_SIN_CONTRAPARTE.match(texto):
        return "Sin contraparte"
    for patron, _tipo, _es_persona in PATRONES_CLAVE:
        if (m := patron.match(texto)) is not None:
            return m.group(1).strip()
    return PREFIJOS.sub("", texto).strip() or texto


def analizar(descripcion: str, monto: Decimal, titular: str | None = None) -> Patrones:
    texto = descripcion.strip()
    p = Patrones(comercio_limpio=texto)

    if (m := PREFIJOS.match(texto)) is not None:
        p.medio_de_pago = m.group(1).upper()
        p.comercio_limpio = PREFIJOS.sub("", texto).strip()
        p.evidencia.append(
            f"prefijo de medio de pago {p.medio_de_pago!r}: el comercio es "
            f"{p.comercio_limpio!r}"
        )

    p.comercio_limpio = RE_COLA_NUMERICA.sub("", p.comercio_limpio).strip()

    if (m := RE_CUOTA_DE.search(texto)) or (m := RE_CUOTA_BARRA.search(texto)):
        n, total = int(m.group(1)), int(m.group(2))
        if 1 <= n <= total <= 60:
            p.es_cuota, p.cuota_n, p.cuota_total = True, n, total
            p.evidencia.append(f"plan de cuotas {n}/{total}")
    elif (m := RE_N_CUOTAS.search(texto)) is not None:
        p.es_cuota, p.cuota_total = True, int(m.group(1))
        p.evidencia.append(f"compra en {m.group(1)} cuotas")

    if p.es_cuota:
        # Una compra financiada NO es una suscripción, por más que se repita
        # todos los meses. Esta restricción sola corrige el error que el
        # categorizador cometió en la fase 1 con "MUSIMUNDO CUOTA 7/12".
        p.categorias_prohibidas.add("Suscripciones")

    if monto > 0:
        p.es_credito = True
        p.evidencia.append("monto positivo: entra plata, no es un gasto")

    # --- Categoría escrita en el propio texto ---------------------------
    for prefijo, signo, categoria, que_es in TEXTOS_DETERMINISTAS:
        if texto.lower().startswith(prefijo.lower()) and monto * signo > 0:
            p.categoria_determinada = categoria
            p.evidencia.append(f"{prefijo!r}: {que_es}")
            break

    # --- Transferencia a nombre del propio titular ----------------------
    if p.categoria_determinada is None and titular:
        if (m := RE_TRANSFERENCIA.match(texto)) and es_el_titular(m["contraparte"], titular):
            p.categoria_determinada = "Movimientos entre cuentas propias"
            p.evidencia.append(
                f"transferencia {m['sentido'].lower()} a nombre del propio titular"
            )

    return p
