"""Agente normalizador de comercios.

Hace el mismo trabajo final que el categorizador —decidir un rubro— pero por
**otro camino**: primero descifra qué comercio es, y recién después clasifica
ese comercio limpio.

Que llegue por otra ruta es el punto. Dos agentes que comparten prompt y
entrada son un solo agente corriendo dos veces: coinciden siempre y su acuerdo
no informa nada. Acá uno mira la cadena cruda y el otro razona sobre la
entidad comercial, así que cuando coinciden es una señal de verdad — y cuando
no, también.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from ..llm import ClienteLLM

SISTEMA = """Sos un asistente que identifica comercios a partir de como los
imprime un resumen bancario argentino.

Trabajás en dos pasos y en este orden:

1. Descifrá QUÉ COMERCIO ES. La cadena viene abreviada, truncada y con
   prefijos del medio de pago (MERPAGO*, MP*, DLO*, PAYU*, DEBIN, PAGOFACIL).
   Esos prefijos NO son el comercio: son por dónde pasó la plata. En
   "DLO*SPOTIFY" el comercio es Spotify; en "PAGOFACIL EDECOR" el comercio es
   EDECOR, la distribuidora de energía.
2. Recién con el comercio identificado, elegí el rubro.

Reglas:
- Elegí exactamente una categoría de la lista. No inventes ninguna.
- Si no reconocés el comercio, decilo: rubro "Otros" y confianza baja. Es
  mejor que adivinar.
- Respondé sólo con el objeto JSON pedido."""


class LecturaComercio(BaseModel):
    comercio: str = Field(
        description="Nombre real del comercio, sin prefijo de medio de pago.",
        max_length=80,
    )
    reconocido: bool = Field(
        description="True sólo si identificaste el comercio; False si estás adivinando."
    )
    categoria: str = Field(description="Nombre exacto de una categoría del catálogo.")
    confianza: float = Field(ge=0.0, le=1.0)


class AgenteComercio:
    nombre = "comercio"

    def __init__(self, cliente: ClienteLLM, categorias: dict[str, str]):
        self.cliente = cliente
        self.categorias = categorias

    def opinar(self, descripcion: str, monto: Decimal) -> LecturaComercio:
        catalogo = "\n".join(f"- {n}: {d}" for n, d in self.categorias.items())
        usuario = (
            f"Categorías disponibles:\n{catalogo}\n\n"
            f"Cadena del resumen: {descripcion}\n"
            f"Monto: {monto}\n\n"
            f"Identificá el comercio y después elegí su rubro."
        )
        lectura = self.cliente.estructurado(SISTEMA, usuario, LecturaComercio)

        if lectura.categoria not in self.categorias:
            lectura = lectura.model_copy(
                update={"categoria": "Otros", "confianza": 0.0, "reconocido": False}
            )
        return lectura
