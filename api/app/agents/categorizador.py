"""El agente categorizador.

Único agente de la fase 1. Recibe la descripción cruda de un movimiento y
devuelve una categoría del catálogo con un nivel de confianza.

Dos cosas deliberadas:

**El prompt le prohíbe inventar categorías.** El esquema Pydantic sólo acepta
nombres del catálogo, así que una alucinación no pasa la validación y dispara
el loop de reparación. La restricción está en el tipo, no en la buena voluntad
del modelo.

**Puede decir que no sabe.** Confianza baja no es un fracaso: es la señal que
manda el movimiento a `needs_review`. Un sistema que categoriza el 100% con
80% de acierto es peor que uno que categoriza el 70% con 99% y pregunta el
resto.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from ..llm import ClienteLLM

SISTEMA = """Sos un asistente que clasifica movimientos bancarios argentinos.

Recibís la descripción tal como la imprime el banco o la tarjeta —abreviada,
en mayúsculas, a veces con prefijos del medio de pago como MERPAGO*, MP*,
PAYU* o DEBIN— y el monto.

Reglas:
- Elegí exactamente una categoría de la lista que te dan. No inventes ninguna.
- El prefijo del medio de pago no es el comercio. En "MERPAGO*KIOSCO LA ESQ"
  el comercio es el kiosco, no Mercado Pago.
- Un monto positivo es plata que entra (un pago, una acreditación, un sueldo);
  uno negativo es un gasto.
- La confianza es honesta: 0.9 o más sólo si el comercio es inequívoco. Si la
  descripción es ambigua o no reconocés el comercio, poné confianza baja y
  usá "Otros". Preferimos preguntar antes que inventar.
- Respondé sólo con el objeto JSON pedido, sin texto alrededor."""


class Decision(BaseModel):
    categoria: str = Field(description="Nombre exacto de una categoría del catálogo.")
    confianza: float = Field(ge=0.0, le=1.0)
    comercio: str = Field(
        description="El comercio, limpio, sin el prefijo del medio de pago.",
        max_length=80,
    )
    motivo: str = Field(
        description="Una frase corta explicando por qué esa categoría.",
        max_length=200,
    )


class Categorizador:
    def __init__(self, cliente: ClienteLLM, categorias: dict[str, str]):
        """`categorias` es nombre -> descripción, tal como está en la base."""
        self.cliente = cliente
        self.categorias = categorias

    def _catalogo(self) -> str:
        return "\n".join(f"- {n}: {d}" for n, d in self.categorias.items())

    def clasificar(self, descripcion: str, monto: Decimal) -> Decision:
        usuario = (
            f"Categorías disponibles:\n{self._catalogo()}\n\n"
            f"Movimiento:\n"
            f"  descripcion: {descripcion}\n"
            f"  monto: {monto}\n\n"
            f"Devolvé el JSON con la categoría, la confianza, el comercio limpio "
            f"y el motivo."
        )

        decision = self.cliente.estructurado(SISTEMA, usuario, Decision)

        # Última defensa: si igual devolvió algo fuera del catálogo, no se
        # propaga una categoría inventada al resto del sistema.
        if decision.categoria not in self.categorias:
            decision = decision.model_copy(
                update={
                    "categoria": "Otros",
                    "confianza": 0.0,
                    "motivo": f"categoría fuera del catálogo: {decision.categoria!r}",
                }
            )
        return decision
