"""Contratos entre etapas del pipeline.

Regla que atraviesa todo el módulo: la plata se representa con `Decimal`.
Nunca `float`. Un float en un total bancario produce diferencias de centavos
fantasma y la compuerta de cuadratura deja de significar algo.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

Moneda = Literal["ARS", "USD"]


# ---------------------------------------------------------------------------
# Cómo cierra un resumen.
#
# Hay dos formas en la calle y el parser tiene que declarar cuál usa:
#
#   - Tarjeta de crédito: declara un TOTAL, que es la suma de los consumos.
#   - Cuenta bancaria: declara SALDO INICIAL y SALDO FINAL, y lo que tiene que
#     cerrar es la diferencia entre los dos.
#
# Modelarlo como unión discriminada evita el bug clásico de meter un saldo
# final en un campo llamado "total" y que la compuerta compare cualquier cosa.
# ---------------------------------------------------------------------------

class CierrePorTotal(BaseModel):
    tipo: Literal["total"] = "total"
    total_declarado: Decimal

    def esperado(self) -> Decimal:
        return self.total_declarado


class CierrePorSaldos(BaseModel):
    tipo: Literal["saldos"] = "saldos"
    saldo_inicial: Decimal
    saldo_final: Decimal

    def esperado(self) -> Decimal:
        return self.saldo_final - self.saldo_inicial


Cierre = Annotated[
    Union[CierrePorTotal, CierrePorSaldos],
    Field(discriminator="tipo"),
]


class FilaCruda(BaseModel):
    """Una fila tal como salió del archivo, sin interpretar."""

    origen: str
    numero_linea: int
    celdas: list[str]


class Movimiento(BaseModel):
    """Un movimiento normalizado.

    Convención de signo, obligatoria y única para todos los parsers:
    negativo = débito (sale plata), positivo = crédito (entra plata).
    El parser traduce a esto sin importar cómo lo exprese el banco —
    columnas separadas, paréntesis, signo menos o una columna de tipo.
    """

    fecha: date
    monto: Decimal
    moneda: Moneda
    descripcion_cruda: str = Field(
        description="Texto del banco, intacto. No limpiar: los agentes de la fase 2 lo necesitan crudo."
    )
    linea_origen: int
    id_operacion: str | None = Field(
        default=None,
        description=(
            "ID único de la operación en la fuente, si lo trae. Permite no duplicar "
            "a nivel movimiento aunque el mismo período se descargue dos veces."
        ),
    )
    saldo: Decimal | None = Field(
        default=None,
        description=(
            "Saldo después del movimiento, si la fuente lo imprime. Habilita el "
            "control renglón por renglón."
        ),
    )


class ResumenCrudo(BaseModel):
    """Salida del parser, antes de normalizar."""

    banco: str
    perfil_id: str = Field(
        description="Con qué perfil se parseó. La normalización lo usa para mapear columnas."
    )
    archivo: str
    sha256: str
    filas: list[FilaCruda]
    cierre: Cierre | None = Field(
        default=None,
        description="None si el parser no logró encontrar el total ni los saldos.",
    )
    periodo_desde: date | None = None
    periodo_hasta: date | None = None
    titular: str | None = Field(
        default=None,
        description="Nombre del titular impreso en el resumen, si lo trae.",
    )


class Resumen(BaseModel):
    """Salida de la normalización. Todo resuelto, listo para verificar."""

    banco: str
    archivo: str
    sha256: str
    periodo_desde: date
    periodo_hasta: date
    cierre: Cierre
    movimientos: list[Movimiento]
    titular: str | None = None


class ResultadoCuadratura(BaseModel):
    """La compuerta. Si `cuadra` es False, los movimientos no son de fiar."""

    cuadra: bool
    tipo_cierre: Literal["total", "saldos"]
    esperado: Decimal = Field(
        description="El total declarado, o saldo_final - saldo_inicial según el tipo de cierre."
    )
    calculado: Decimal = Field(description="Suma de los montos de los movimientos.")
    diferencia: Decimal = Field(
        description="esperado - calculado. Exactamente 0 cuando cuadra."
    )
    cantidad_movimientos: int
    cadena_verificada: bool = Field(
        default=False,
        description=(
            "True si se pudo controlar el saldo renglón por renglón: todos los "
            "movimientos traen saldo y el cierre es por saldos."
        ),
    )
    eslabon_roto: int | None = Field(
        default=None,
        description=(
            "linea_origen del primer movimiento donde saldo_anterior + monto != saldo. "
            "Señala la fila exacta que el parser leyó mal."
        ),
    )

    def explicar(self) -> str:
        """Mensaje para el fallo del test. Un `assert False` pelado no sirve
        para depurar un parser: hace falta el número, y si se puede, la fila."""
        if self.cuadra:
            cadena = " y el saldo encadena renglón por renglón" if self.cadena_verificada else ""
            return (
                f"cuadra por {self.tipo_cierre}: "
                f"{self.cantidad_movimientos} movimientos suman {self.calculado}{cadena}"
            )

        partes = []
        if self.diferencia != 0:
            falta = "de menos" if self.diferencia > 0 else "de más"
            partes.append(
                f"NO cuadra por {abs(self.diferencia)} {falta} "
                f"(cierre por {self.tipo_cierre}: esperado {self.esperado}, "
                f"calculado {self.calculado}, {self.cantidad_movimientos} movimientos)"
            )
        if self.eslabon_roto is not None:
            partes.append(
                f"el saldo se rompe en la línea {self.eslabon_roto}: "
                f"saldo anterior + monto no da el saldo impreso"
            )
        return "; ".join(partes)
