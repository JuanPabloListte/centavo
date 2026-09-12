"""Dispatcher: elige el parser que corresponde al archivo.

La detección es por contenido, no por nombre de archivo. Cada perfil declara
un marcador que tiene que aparecer en el documento; el primero que acepta,
gana. Si ninguno acepta, es un error explícito y no un parseo silencioso a
medias.
"""

from __future__ import annotations

from pathlib import Path

from ..models import ResumenCrudo
from .base import Parser
from .csv_parser import CsvParser
from .pdf_coordenadas import PdfCoordenadasParser
from .pdf_parser import PdfParser
from .perfiles import PERFILES


def parsers_disponibles() -> list[Parser]:
    salida: list[Parser] = []
    for perfil in PERFILES:
        if perfil.formato == "csv":
            salida.append(CsvParser(perfil))
        elif perfil.formato == "pdf" and perfil.estrategia == "coordenadas":
            salida.append(PdfCoordenadasParser(perfil))
        elif perfil.formato == "pdf":
            salida.append(PdfParser(perfil))
    return salida


def parsear(path: Path) -> ResumenCrudo:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    for parser in parsers_disponibles():
        if parser.acepta(path):
            return parser.parse(path)

    conocidos = ", ".join(p.banco for p in PERFILES)
    raise ValueError(
        f"{path.name}: ningún perfil reconoce este archivo. "
        f"Perfiles cargados: {conocidos}. "
        f"Para un banco nuevo, agregá un Perfil en app/parsers/perfiles.py."
    )


__all__ = ["parsear", "parsers_disponibles"]
