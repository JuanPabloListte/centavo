"""Piezas compartidas por todos los parsers.

Nada de esto es específico de un banco: son las conversiones que en este
dominio se hacen mal una y otra vez —formato de monto argentino, fechas
día/mes, y el signo— aisladas acá para que se prueben una sola vez.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Protocol

from ..models import Moneda, ResumenCrudo

# ---------------------------------------------------------------------------
# Conversiones
# ---------------------------------------------------------------------------

_LIMPIEZA_MONTO = re.compile(r"[^\d,.\-()]")


def parse_monto_ar(texto: str) -> Decimal:
    """Convierte un monto en formato argentino a Decimal.

    Acepta lo que aparece en la calle: '1.234,56', '$ -3.450,00',
    '(1.234,56)' para negativo, y también el formato inglés '1234.56'
    cuando no hay coma decimal.

    Devuelve Decimal, nunca float. Levanta ValueError si no es un monto.
    """
    if texto is None:
        raise ValueError("monto vacío")

    s = _LIMPIEZA_MONTO.sub("", str(texto).strip())
    if not s:
        raise ValueError(f"monto vacío tras limpiar: {texto!r}")

    negativo = False
    if s.startswith("(") and s.endswith(")"):
        negativo, s = True, s[1:-1]
    if s.startswith("-"):
        negativo, s = True, s[1:]
    s = s.replace("(", "").replace(")", "")

    if "," in s:
        # Formato argentino: el punto separa miles, la coma decimales.
        s = s.replace(".", "").replace(",", ".")
    # Si no hay coma, el punto ya es decimal (o no hay parte decimal).

    try:
        valor = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"no es un monto: {texto!r}") from exc

    valor = valor.quantize(Decimal("0.01"))
    return -valor if negativo else valor


def parse_fecha(texto: str, formatos: tuple[str, ...]) -> date:
    """Primer formato que matchee gana. Día primero, que es lo local."""
    s = str(texto).strip()
    for fmt in formatos:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"no es una fecha reconocible: {texto!r} (probé {formatos})")


def sha256_archivo(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for bloque in iter(lambda: fh.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Perfil de banco
#
# Agregar un banco nuevo es agregar un Perfil, no escribir un parser.
# Ese es el mismo principio que en la fase 3 se convierte en "layouts
# aprendidos": la maquetación es dato, no código.
# ---------------------------------------------------------------------------

TipoImporte = Literal["columna_unica", "debito_credito"]


@dataclass(frozen=True)
class Perfil:
    banco: str
    formato: Literal["csv", "pdf"]

    # Cadena que tiene que aparecer al principio del archivo para que este
    # perfil se considere aplicable. Es el mecanismo de detección.
    marcador: str

    # Cómo se llaman las columnas en la fila de encabezado.
    col_fecha: str
    col_descripcion: str
    tipo_importe: TipoImporte
    col_importe: str | None = None          # si tipo_importe == 'columna_unica'
    col_debito: str | None = None           # si tipo_importe == 'debito_credito'
    col_credito: str | None = None

    moneda: Moneda = "ARS"
    formatos_fecha: tuple[str, ...] = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d")

    # Cómo encontrar el cierre. Cada regexp captura un grupo con el monto.
    re_total: str | None = None             # cierre por total (tarjeta)
    re_saldo_inicial: str | None = None     # cierre por saldos (cuenta)
    re_saldo_final: str | None = None
    re_periodo: str | None = None           # captura dos grupos: desde, hasta

    # Separador del CSV.
    delimitador: str = ";"
    encoding: str = "utf-8"

    # --- Resúmenes con ID y saldo por renglón (p. ej. Mercado Pago) --------
    # "tabla": filas con columnas nombradas (CSV, o PDF con tabla detectable).
    # "coordenadas": PDF sin tabla, con descripciones partidas en renglones;
    #   cada movimiento se reconstruye por la posición de las palabras.
    estrategia: Literal["tabla", "coordenadas"] = "tabla"
    col_id_operacion: str | None = None
    col_saldo: str | None = None
    re_titular: str | None = None           # captura el nombre del titular
    # Si el encabezado de una tabla trae alguno de estos rótulos, es de un tipo
    # que el parser todavía no sabe leer: vacía se ignora, con filas es error.
    rotulos_no_soportados: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        """Identidad estable del perfil: viaja en el ResumenCrudo para que
        la normalización sepa con qué columnas fue parseado."""
        return f"{self.banco}::{self.formato}"

    def importe_de(self, celdas: dict[str, str]) -> Decimal:
        """Aplica la convención de signo única del proyecto:
        negativo = débito (sale), positivo = crédito (entra)."""
        if self.tipo_importe == "columna_unica":
            assert self.col_importe
            return parse_monto_ar(celdas[self.col_importe])

        assert self.col_debito and self.col_credito
        crudo_debito = (celdas.get(self.col_debito) or "").strip()
        crudo_credito = (celdas.get(self.col_credito) or "").strip()

        if crudo_debito and crudo_credito:
            raise ValueError("la fila trae débito y crédito a la vez")
        if crudo_debito:
            # El banco lo escribe en positivo en la columna de débitos;
            # acá se vuelve negativo.
            return -abs(parse_monto_ar(crudo_debito))
        if crudo_credito:
            return abs(parse_monto_ar(crudo_credito))
        raise ValueError("la fila no trae ni débito ni crédito")


class Parser(Protocol):
    """Todo parser hace lo mismo: de un archivo a un ResumenCrudo."""

    def acepta(self, path: Path) -> bool: ...

    def parse(self, path: Path) -> ResumenCrudo: ...
