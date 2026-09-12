"""Orquestación de la clasificación.

El orden importa y es el principio rector del proyecto aplicado acá:

1.  **Memoria primero.** Si esa contraparte ya la decidiste vos, se usa esa
    decisión. Gratis, instantáneo, exacto, y no toca el modelo. La memoria se
    indexa por clave de contraparte (`clave_memoria`), no por descripción
    exacta. El porcentaje resuelto por esta vía es la métrica que tiene que
    subir con el tiempo.
1b. **Evidencia concluyente.** Si la categoría está escrita en el texto de la
    fuente o se deduce con certeza del titular, tampoco se consulta al modelo.
2.  **Recién si no hay memoria ni evidencia, el modelo.**
3.  **Umbral de confianza.** Por debajo, va a `needs_review` en vez de
    resolverse mal en silencio.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal

import psycopg

from .agents.categorizador import Categorizador, Decision
from .agents.patrones import analizar, clave_memoria
from .llm import ClienteLLM

UMBRAL = float(os.getenv("CENTAVO_UMBRAL_CONFIANZA", "0.75"))


@dataclass
class Clasificacion:
    categoria: str
    confianza: float
    via: str                 # 'regla' | 'modelo' | 'consenso' | 'evidencia' | 'desacuerdo'
    estado: str              # 'resuelto' | 'needs_review'
    comercio: str = ""
    motivo: str = ""
    acuerdo: bool | None = None                       # None en modo solo
    opiniones: dict[str, str] = field(default_factory=dict)


def cargar_categorias(conn: psycopg.Connection, para_modelo: bool = True) -> dict[str, str]:
    """Nombre -> descripción.

    Con `para_modelo=True`, el default, excluye las categorías que asigna sólo
    el código. Ofrecérselas al modelo nada más le suma opciones para
    equivocarse, y cambiaría el catálogo sobre el que se midió la fase 2.
    """
    sql = "SELECT nombre, descripcion FROM categories"
    if para_modelo:
        sql += " WHERE NOT solo_determinista"
    with conn.cursor() as cur:
        cur.execute(sql + " ORDER BY id")
        return dict(cur.fetchall())


def cargar_reglas(conn: psycopg.Connection) -> dict[str, str]:
    """La memoria de la fase 3: clave de contraparte -> categoría."""
    from .memoria import cargar_memoria

    return cargar_memoria(conn)


class Clasificador:
    def __init__(
        self,
        categorias: dict[str, str],
        reglas: dict[str, str] | None = None,
        cliente: ClienteLLM | None = None,
        umbral: float = UMBRAL,
    ):
        self.categorias = categorias
        self.reglas = reglas or {}
        self.cliente = cliente or ClienteLLM()
        self.agente = Categorizador(self.cliente, categorias)
        self.umbral = umbral

    def clasificar(
        self, descripcion: str, monto: Decimal, titular: str | None = None
    ) -> Clasificacion:
        if (categoria := self.reglas.get(clave_memoria(descripcion))) is not None:
            return Clasificacion(
                categoria=categoria,
                confianza=1.0,
                via="regla",
                estado="resuelto",
                motivo="ya decidiste antes qué es esta contraparte",
            )

        p = analizar(descripcion, monto, titular)
        if p.categoria_determinada is not None:
            return Clasificacion(
                categoria=p.categoria_determinada,
                confianza=1.0,
                via="evidencia",
                estado="resuelto",
                comercio=p.comercio_limpio,
                motivo="; ".join(p.evidencia),
            )

        d: Decision = self.agente.clasificar(descripcion, monto)
        return Clasificacion(
            categoria=d.categoria,
            confianza=d.confianza,
            via="modelo",
            estado="resuelto" if d.confianza >= self.umbral else "needs_review",
            comercio=d.comercio,
            motivo=d.motivo,
        )


# ---------------------------------------------------------------------------
# Modo flota: dos agentes + supervisor.
#
# Vive detrás de la misma interfaz que el modo solo para que el harness pueda
# comparar los dos sobre exactamente el mismo conjunto. Si el test corre por un
# camino y el sistema por otro, el número deja de significar algo.
# ---------------------------------------------------------------------------

class ClasificadorFlota:
    def __init__(
        self,
        categorias: dict[str, str],
        reglas: dict[str, str] | None = None,
        cliente: ClienteLLM | None = None,
        umbral: float = UMBRAL,
    ):
        from .agents.comercio import AgenteComercio
        from .supervisor import Supervisor

        self.cliente = cliente or ClienteLLM()
        self.umbral = umbral
        self.supervisor = Supervisor(
            categorizador=Categorizador(self.cliente, categorias),
            agente_comercio=AgenteComercio(self.cliente, categorias),
            reglas=reglas or {},
            umbral=umbral,
        )

    def clasificar(
        self, descripcion: str, monto: Decimal, titular: str | None = None
    ) -> Clasificacion:
        v = self.supervisor.resolver(descripcion, monto, titular)
        return Clasificacion(
            categoria=v.categoria,
            confianza=v.confianza,
            via=v.via,
            estado=v.estado,
            comercio=v.comercio,
            motivo=v.motivo,
            acuerdo=v.acuerdo,
            opiniones=v.opiniones,
        )


def construir(modo: str, **kw):
    """'solo' -> un agente; 'flota' -> dos agentes + supervisor."""
    if modo == "solo":
        return Clasificador(**kw)
    if modo == "flota":
        return ClasificadorFlota(**kw)
    raise ValueError(f"modo desconocido: {modo!r} (usá 'solo' o 'flota')")
