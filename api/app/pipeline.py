"""El pipeline de la fase 0, de punta a punta.

Una sola función para que el test, la CLI y (más adelante) el endpoint corran
exactamente el mismo camino. Si el test pasa por acá y la API por otro lado,
el test deja de significar algo.
"""

from __future__ import annotations

from pathlib import Path

from .balance import verificar_cuadratura
from .models import Resumen, ResultadoCuadratura
from .normalize import normalizar
from .parsers import parsear


def procesar(path: Path) -> tuple[Resumen, ResultadoCuadratura]:
    crudo = parsear(Path(path))
    resumen = normalizar(crudo)
    return resumen, verificar_cuadratura(resumen)
