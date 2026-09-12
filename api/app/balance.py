"""La compuerta aritmética.

Dos controles, y cuadrar exige los dos cuando se puede hacer el segundo:

1. **Del período.** La suma de los movimientos tiene que dar lo que el resumen
   declara: el total, o saldo final menos saldo inicial.
2. **Renglón por renglón.** Si la fuente imprime el saldo después de cada
   movimiento, cada fila tiene que cumplir saldo_anterior + monto == saldo.

El segundo es mucho más fuerte que el primero. Un parser que lee mal una fila
puede, por casualidad, compensarse con otra y dejar el total intacto; la cadena
de saldos no perdona eso. Y cuando falla no dice "el mes no cierra": dice en
qué línea.

La comparación es exacta: sin tolerancia, sin redondeo, sin epsilon. Si no
cuadra, el parser está mal — y el trabajo es corregir el parser, nunca aflojar
esta función.
"""

from decimal import Decimal

from .models import Resumen, ResultadoCuadratura


def _verificar_cadena(resumen: Resumen) -> tuple[bool, int | None]:
    """Devuelve (se_pudo_verificar, linea_del_primer_eslabon_roto).

    Sólo aplica si todos los movimientos traen saldo y el cierre es por saldos,
    porque hace falta un saldo inicial desde donde arrancar la cadena.
    """
    movs = resumen.movimientos
    if not movs or any(m.saldo is None for m in movs):
        return False, None
    if resumen.cierre.tipo != "saldos":
        return False, None

    previo = resumen.cierre.saldo_inicial
    for m in movs:
        if previo + m.monto != m.saldo:
            return True, m.linea_origen
        previo = m.saldo
    return True, None


def verificar_cuadratura(resumen: Resumen) -> ResultadoCuadratura:
    calculado = sum(
        (m.monto for m in resumen.movimientos),
        start=Decimal("0.00"),
    )
    esperado = resumen.cierre.esperado()
    diferencia = esperado - calculado
    cadena_verificada, eslabon_roto = _verificar_cadena(resumen)

    return ResultadoCuadratura(
        cuadra=diferencia == Decimal("0.00") and eslabon_roto is None,
        tipo_cierre=resumen.cierre.tipo,
        esperado=esperado,
        calculado=calculado,
        diferencia=diferencia,
        cantidad_movimientos=len(resumen.movimientos),
        cadena_verificada=cadena_verificada,
        eslabon_roto=eslabon_roto,
    )
