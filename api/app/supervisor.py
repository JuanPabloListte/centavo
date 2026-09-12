"""El supervisor: arbitra entre los agentes.

No promedia opiniones ni elige la de más confianza — la fase 1 midió que la
confianza autodeclarada no tiene señal, así que decidir por ella sería decidir
al azar con cara de rigor.

Aplica reglas, en orden, y la de más arriba que corresponda gana:

  1.  Una decisión tuya sobre esa contraparte es absoluta (memoria, fase 3).
  1b. La evidencia concluyente resuelve sin consultar a ningún agente: textos
      fijos de la fuente ("Dinero reservado", "Rendimientos") o una
      transferencia a nombre del propio titular.
  2.  La evidencia determinista le gana a la opinión del modelo.
  3.  Los dos agentes coinciden -> se resuelve.
  4.  Discrepan -> `needs_review`. No se elige un ganador.

La regla 4 es el corazón de la fase 2 y viene de una medición: si un modelo
chico no sabe cuándo no sabe, el desacuerdo entre dos rutas independientes es
una señal de incertidumbre mejor que su propia confianza. Si esa hipótesis es
falsa, el harness lo va a mostrar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .agents.categorizador import Categorizador
from .agents.comercio import AgenteComercio
from .agents.patrones import Patrones, analizar, clave_memoria


@dataclass
class Veredicto:
    categoria: str
    confianza: float
    via: str            # 'regla' | 'consenso' | 'evidencia' | 'desacuerdo'
    estado: str         # 'resuelto' | 'needs_review'
    comercio: str = ""
    motivo: str = ""
    acuerdo: bool | None = None      # None cuando no hubo dos opiniones
    opiniones: dict[str, str] = field(default_factory=dict)
    evidencia: list[str] = field(default_factory=list)


class Supervisor:
    def __init__(
        self,
        categorizador: Categorizador,
        agente_comercio: AgenteComercio,
        reglas: dict[str, str] | None = None,
        umbral: float = 0.75,
    ):
        self.categorizador = categorizador
        self.comercio = agente_comercio
        self.reglas = reglas or {}
        self.umbral = umbral

    def resolver(
        self, descripcion: str, monto: Decimal, titular: str | None = None
    ) -> Veredicto:
        # --- Regla 1: una decisión tuya no se discute -----------------------
        if (categoria := self.reglas.get(clave_memoria(descripcion))) is not None:
            return Veredicto(
                categoria=categoria,
                confianza=1.0,
                via="regla",
                estado="resuelto",
                motivo="ya decidiste antes qué es esta contraparte",
            )

        patrones: Patrones = analizar(descripcion, monto, titular)

        # --- Regla 1b: evidencia concluyente, sin llamar a ningún agente ----
        if patrones.categoria_determinada is not None:
            return Veredicto(
                categoria=patrones.categoria_determinada,
                confianza=1.0,
                via="evidencia",
                estado="resuelto",
                comercio=patrones.comercio_limpio,
                motivo="; ".join(patrones.evidencia),
                evidencia=patrones.evidencia,
            )

        # Las dos rutas independientes.
        d = self.categorizador.clasificar(descripcion, monto)
        c = self.comercio.opinar(descripcion, monto)

        opiniones = {"categorizador": d.categoria, "comercio": c.categoria}

        # --- Regla 2: la evidencia dura manda -------------------------------
        # Una opinión que contradice un hecho verificable del texto se descarta,
        # por más confianza que declare.
        vetadas = patrones.categorias_prohibidas
        vetos = [f"{a}={cat}" for a, cat in opiniones.items() if cat in vetadas]
        candidatas = {a: cat for a, cat in opiniones.items() if cat not in vetadas}

        if vetos and candidatas:
            motivo = (
                f"evidencia determinista descarta {', '.join(vetos)} "
                f"({'; '.join(patrones.evidencia)})"
            )
            elegida = next(iter(candidatas.values()))
            return Veredicto(
                categoria=elegida,
                confianza=0.9,
                via="evidencia",
                estado="resuelto",
                comercio=patrones.comercio_limpio,
                motivo=motivo,
                acuerdo=False,
                opiniones=opiniones,
                evidencia=patrones.evidencia,
            )

        if vetos and not candidatas:
            return Veredicto(
                categoria="Otros",
                confianza=0.0,
                via="evidencia",
                estado="needs_review",
                comercio=patrones.comercio_limpio,
                motivo=f"todas las opiniones contradicen la evidencia: {', '.join(vetos)}",
                acuerdo=True,
                opiniones=opiniones,
                evidencia=patrones.evidencia,
            )

        # --- Regla 3: consenso ---------------------------------------------
        if d.categoria == c.categoria:
            return Veredicto(
                categoria=d.categoria,
                confianza=max(d.confianza, c.confianza),
                via="consenso",
                estado="resuelto",
                comercio=c.comercio or patrones.comercio_limpio,
                motivo="los dos agentes llegaron a lo mismo por caminos distintos",
                acuerdo=True,
                opiniones=opiniones,
                evidencia=patrones.evidencia,
            )

        # --- Regla 4: desacuerdo -> preguntar -------------------------------
        # No se elige el de más confianza: la fase 1 midió que esa señal no
        # discrimina entre acierto y error.
        return Veredicto(
            categoria=d.categoria,          # se guarda como sugerencia
            confianza=min(d.confianza, c.confianza),
            via="desacuerdo",
            estado="needs_review",
            comercio=c.comercio or patrones.comercio_limpio,
            motivo=(
                f"desacuerdo: el categorizador dice {d.categoria!r} y "
                f"el de comercios dice {c.categoria!r}"
            ),
            acuerdo=False,
            opiniones=opiniones,
            evidencia=patrones.evidencia,
        )
