"""El reporte del mes.

Lo que un contador personal tiene que contestar: cuánto entró, cuánto salió y en
qué, y cuánto falta clasificar. Con dos reglas que no se negocian:

1. **Los movimientos internos no son gastos ni ingresos.** Apartar plata en una
   reserva o mandártela a otra cuenta tuya no cambia cuánto gastaste. Se
   muestran aparte, y no se mezclan con el resto.
2. **El reporte cuadra con el resumen.** Ingresos + gastos + internos + sin
   clasificar tiene que dar exactamente lo que el resumen declara: el total, o
   saldo final menos saldo inicial. Es la compuerta de la fase 0 aplicada a la
   salida. Si no cuadra, algún movimiento se contó dos veces o ninguna, y el
   reporte lo dice en vez de mostrar números que parecen buenos.
3. **Una devolución unida a su pago resta del gasto.** Es plata que vuelve de
   una compra, no un ingreso: cuenta en la categoría y en el tipo de su pago.
   Una devolución sin pago cargado es un movimiento como cualquier otro.

La plata se suma con Decimal y sale como texto: la conversión a número, si hace
falta para dibujar una barra, es cosa de la interfaz y nunca vuelve al cálculo.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import psycopg

CATEGORIAS_INTERNAS = frozenset({"Ahorro y reservas", "Movimientos entre cuentas propias"})
CERO = Decimal("0.00")


class ResumenNoEncontrado(LookupError):
    pass


class ResumenDescuadrado(Exception):
    """Un resumen que no pasó la compuerta no tiene reporte: sus movimientos no
    son de fiar, y un reporte sobre ellos lo parecería."""


def _texto(valor: Decimal | None) -> str | None:
    return None if valor is None else str(valor.quantize(CERO))


def reporte_de_resumen(conn: psycopg.Connection, statement_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, banco, archivo, periodo_desde, periodo_hasta, estado,
                   cierre_tipo, esperado, saldo_inicial, saldo_final
            FROM statements
            WHERE id = %s
            """,
            (statement_id,),
        )
        fila = cur.fetchone()
        if fila is None:
            raise ResumenNoEncontrado(statement_id)
        (sid, banco, archivo, desde, hasta, estado,
         cierre_tipo, esperado, saldo_inicial, saldo_final) = fila

        if estado != "cuadrado":
            raise ResumenDescuadrado(
                f"el resumen {sid} no cuadró al ingerirse: no se reporta sobre "
                f"movimientos que no son de fiar"
            )

        cur.execute(
            """
            SELECT c.nombre, t.estado_clasificacion, t.monto, t.devuelve_a IS NOT NULL
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.categoria_id
            WHERE t.statement_id = %s
            """,
            (sid,),
        )
        movimientos = cur.fetchall()

    grupos: dict[str, dict[str, list]] = {
        "ingreso": defaultdict(lambda: [CERO, 0]),
        "gasto": defaultdict(lambda: [CERO, 0]),
        "interno": defaultdict(lambda: [CERO, 0]),
    }
    sin_clasificar, pendientes = CERO, 0
    devoluciones = sum(1 for *_, devuelve in movimientos if devuelve)

    for categoria, estado_clasificacion, monto, devuelve in movimientos:
        if estado_clasificacion != "resuelto" or categoria is None:
            sin_clasificar += monto
            pendientes += 1
            continue
        if categoria in CATEGORIAS_INTERNAS:
            tipo = "interno"
        elif devuelve:
            tipo = "gasto"      # vuelve de un pago: resta del gasto, no es ingreso
        else:
            tipo = "ingreso" if monto > 0 else "gasto"
        grupos[tipo][categoria][0] += monto
        grupos[tipo][categoria][1] += 1

    total = {tipo: sum((v[0] for v in d.values()), CERO) for tipo, d in grupos.items()}
    suma = total["ingreso"] + total["gasto"] + total["interno"] + sin_clasificar
    diferencia = esperado - suma

    por_categoria = sorted(
        (
            {
                "categoria": categoria,
                "tipo": tipo,
                "monto": _texto(monto),
                "movimientos": cantidad,
            }
            for tipo, d in grupos.items()
            for categoria, (monto, cantidad) in d.items()
        ),
        key=lambda l: -abs(Decimal(l["monto"])),
    )

    return {
        "resumen": {
            "id": sid,
            "banco": banco,
            "archivo": archivo,
            "periodo_desde": desde.isoformat(),
            "periodo_hasta": hasta.isoformat(),
            "cierre_tipo": cierre_tipo,
            "esperado": _texto(esperado),
            "saldo_inicial": _texto(saldo_inicial),
            "saldo_final": _texto(saldo_final),
        },
        "totales": {
            "ingresos": _texto(total["ingreso"]),
            "gastos": _texto(total["gasto"]),
            "internos": _texto(total["interno"]),
            "sin_clasificar": _texto(sin_clasificar),
            "neto": _texto(total["ingreso"] + total["gasto"]),
        },
        "cuadra": diferencia == CERO,
        "diferencia": _texto(diferencia),
        "cobertura": {
            "movimientos": len(movimientos),
            "resueltos": len(movimientos) - pendientes,
            "pendientes": pendientes,
        },
        "devoluciones": devoluciones,
        "por_categoria": por_categoria,
    }
