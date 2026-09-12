"""Resumen sintético con la maquetación del resumen de cuenta de Mercado Pago.

Existe para tener un test versionable del parser por coordenadas sin usar un
solo dato real. Reproduce lo que hace difícil al resumen verdadero:

- descripciones partidas en dos y tres renglones, centradas respecto de la
  fecha, sin tabla detectable
- fechas con guiones, ID de operación, valor y saldo en cada renglón
- el encabezado de la tabla repetido en cada página, y pie "n/m"
- un bloque de texto al pie, a la izquierda de la columna de descripción: el
  que en el resumen real se pegaba al último movimiento
- una página anexa con otra tabla (con cotización del dólar) y sin filas

Y trae los movimientos que el analizador resuelve sin modelo: una reserva, un
retiro de la reserva, rendimientos, una transferencia a la propia titular con
el nombre reordenado, y una transferencia a un familiar con el mismo apellido,
que NO es a la propia titular.

Todos los nombres, comercios, CVU y CUIT son inventados.
"""

from __future__ import annotations

import html
from datetime import date
from decimal import Decimal
from pathlib import Path

TITULAR = "María Laura Pérez Gómez"
SALDO_INICIAL = Decimal("85000.00")
PERIODO = (date(2026, 8, 1), date(2026, 8, 31))

# (día, descripción, monto)
MOVIMIENTOS: list[tuple[int, str, Decimal]] = [
    (1, "Pago con QR Verdulería Doña Rosa", Decimal("-4350.00")),
    (1, "Rendimientos", Decimal("21.37")),
    (2, "Transferencia recibida PEREZ MARIA LAURA", Decimal("250000.00")),
    (2, "Dinero reservado Vacaciones de invierno", Decimal("-120000.00")),
    (3, "Pago SUBE Viajes", Decimal("-2150.00")),
    (3, "Transferencia enviada Perez Carlos Alberto", Decimal("-15000.00")),
    (4, "Pago de suscripción Streaming Ejemplo Plus", Decimal("-8122.73")),
    (4, "Rendimientos", Decimal("168.40")),
    (5, "Transferencia enviada Consorcio Edificio Las Acacias Administración Expensas",
     Decimal("-63400.00")),
    (6, "Pedido de 2 productos Pizzería La Esquina Nueva", Decimal("-18900.00")),
    (6, "Pago con QR Farmacia del Centro", Decimal("-11076.00")),
    (7, "Rendimientos", Decimal("152.88")),
    (8, "Pago Servicio de Internet Ejemplo Sociedad Anónima", Decimal("-21980.00")),
    (9, "Transferencia enviada Gomez Ana", Decimal("-5500.00")),
    (10, "Pago SUBE Viajes", Decimal("-2150.00")),
    (11, "Transferencia recibida Lopez Martin Ezequiel", Decimal("30000.00")),
    (12, "Pago con QR Kiosco El Paso", Decimal("-2500.00")),
    (13, "Rendimientos", Decimal("140.05")),
    (14, "Dinero retirado Vacaciones de invierno", Decimal("40000.00")),
    (15, "Pago de suscripción Música Ejemplo", Decimal("-3899.00")),
    (16, "Transferencia enviada Club Atlético Barrio Norte Cuota Social Mensual",
     Decimal("-12000.00")),
    (17, "Pago SUBE Viajes", Decimal("-2150.00")),
    (18, "Pago con QR Carnicería Los Hermanos", Decimal("-26700.00")),
    (19, "Rendimientos", Decimal("98.12")),
    (20, "Pago Luz Distribuidora Ejemplo", Decimal("-17450.00")),
    (21, "Transferencia enviada Fernandez Julia", Decimal("-7000.00")),
    (22, "Pago con QR Panadería San Martín", Decimal("-3200.00")),
    (23, "Pedido Sushi Ejemplo Centro", Decimal("-21400.00")),
    (24, "Rendimientos", Decimal("77.61")),
    (25, "Pago SUBE Viajes", Decimal("-2150.00")),
    (26, "Transferencia enviada Perez Carlos Alberto", Decimal("-9000.00")),
    (28, "Pago con QR Estación de Servicio Ruta 9", Decimal("-20000.00")),
]


def ids() -> list[str]:
    return [str(170_000_000_000 + i * 7919) for i in range(len(MOVIMIENTOS))]


def filas() -> list[tuple[date, str, str, Decimal, Decimal]]:
    saldo, salida = SALDO_INICIAL, []
    for (dia, desc, monto), idop in zip(MOVIMIENTOS, ids()):
        saldo += monto
        salida.append((date(2026, 8, dia), desc, idop, monto, saldo))
    return salida


def _ar(valor: Decimal) -> str:
    """Decimal -> formato argentino: 1.234,56"""
    signo = "-" if valor < 0 else ""
    entero, _, dec = f"{abs(valor):.2f}".partition(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return f"{signo}{'.'.join(grupos)},{dec}"


def construir_html(*, anexo_con_filas: bool = False) -> str:
    montos = [m for _, _, m in MOVIMIENTOS]
    entradas = sum((m for m in montos if m > 0), Decimal("0"))
    salidas = sum((m for m in montos if m < 0), Decimal("0"))
    saldo_final = SALDO_INICIAL + entradas + salidas

    renglones = "\n".join(
        f"<tr><td>{f:%d-%m-%Y}</td><td>{html.escape(d)}</td><td>{i}</td>"
        f"<td class='n'>$ {_ar(m)}</td><td class='n'>$ {_ar(s)}</td></tr>"
        for f, d, i, m, s in filas()
    )

    fila_anexo = (
        "<tr><td>10-08-2026</td><td>Compra de dólares</td><td>179999999999</td>"
        "<td class='n'>100,00</td><td class='n'>$ -120.000,00</td>"
        "<td class='n'>1.200,00</td><td class='n'>100,00</td></tr>"
        if anexo_con_filas else ""
    )

    return f"""<!doctype html>
<html lang="es"><meta charset="utf-8">
<style>
  @page {{
    size: 446.25pt 632.25pt;
    margin: 30pt 30pt 34pt 30pt;
    @bottom-right {{ content: counter(page) "/" counter(pages); font: 7pt Arial; }}
  }}
  body {{ font-family: Arial, Helvetica, sans-serif; font-size: 7pt; color: #111; margin: 0; }}
  h1 {{ font-size: 10pt; margin: 0 0 4pt; }}
  .cab p {{ margin: 2pt 0; }}
  .titulo-detalle {{ font-weight: 700; margin-top: 10pt; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 6pt; table-layout: fixed; }}
  thead {{ display: table-header-group; }}
  th {{ font-weight: 700; text-align: left; padding: 3pt 4pt; vertical-align: bottom; }}
  td {{ padding: 9pt 4pt; vertical-align: middle; line-height: 1.5; }}
  tr {{ break-inside: avoid; page-break-inside: avoid; }}
  td.n {{ text-align: right; white-space: nowrap; }}
  th.n {{ text-align: right; }}  /* los rótulos sí se parten: si no, se pisan entre columnas */
  .pie {{ margin-top: 20pt; font-size: 6pt; }}
  .pie p {{ margin: 2pt 0; }}
  .anexo {{ break-before: page; }}
</style>

<div class="cab">
  <h1>RESUMEN DE CUENTA EN PESOS</h1>
  <p>{html.escape(TITULAR)}</p>
  <p>CVU: 0000000000000000000000 CUIT/ CUIL: 27000000000</p>
  <p>Periodo: Del 1 al 31 de agosto de 2026</p>
  <p>Entradas: $ {_ar(entradas)}</p>
  <p>Saldo inicial: $ {_ar(SALDO_INICIAL)} Saldo final: $ {_ar(saldo_final)}</p>
  <p>Salidas: $ {_ar(salidas)}</p>
</div>
<p class="titulo-detalle">DETALLE DE MOVIMIENTOS</p>

<table>
  <colgroup><col style="width:48pt"><col style="width:104pt"><col style="width:70pt"><col style="width:66pt"><col style="width:70pt"></colgroup>
  <thead><tr><th>Fecha</th><th>Descripción</th><th>ID de la operación</th><th class="n">Valor</th><th class="n">Saldo</th></tr></thead>
  <tbody>
{renglones}
  </tbody>
</table>

<div class="pie">
  <p>Fecha de emisión: 01/09/2026. Resumen sintético generado para pruebas.</p>
  <p>Entidad Ejemplo S.A. — todos los datos de este documento son ficticios.</p>
</div>

<div class="anexo">
  <h1>OPERACIONES EN DÓLARES</h1>
  <table>
    <thead><tr><th>Fecha</th><th>Descripción</th><th>ID de la operación</th><th class="n">Valor</th><th class="n">Pesos recibidos/ usados</th><th class="n">Cotización del dólar</th><th class="n">Saldo</th></tr></thead>
    <tbody>{fila_anexo}</tbody>
  </table>
  <div class="pie"><p>Tipo de cambio informado al cierre del período.</p></div>
</div>
</html>"""


def generar(destino: Path, html_a_pdf, *, anexo_con_filas: bool = False) -> bool:
    return html_a_pdf(construir_html(anexo_con_filas=anexo_con_filas), destino)


def con_devolucion(resumen, pago, *, monto: Decimal | None = None, fecha: date | None = None):
    """El resumen más una devolución de `pago`, agregada al final, con la cadena
    de saldos y el cierre ajustados para que siga cuadrando. Devuelve
    (resumen, resultado).

    El PDF sintético no trae devoluciones, y agregarle una movería los números
    esperados de todos los tests que lo leen. Esto sirve a los tests de
    devoluciones y al esquema demo. Como en el resumen real, la devolución
    lleva el ID de operación del pago; sin `monto`, devuelve el pago entero.
    """
    from app.balance import verificar_cuadratura
    from app.models import CierrePorSaldos

    ultimo = resumen.movimientos[-1]
    monto = -pago.monto if monto is None else monto
    devolucion = pago.model_copy(update={
        "fecha": fecha or ultimo.fecha,
        "monto": monto,
        "descripcion_cruda": f"Devolución de {pago.descripcion_cruda}",
        "linea_origen": ultimo.linea_origen + 1,
        "saldo": None if ultimo.saldo is None else ultimo.saldo + monto,
    })
    cierre = resumen.cierre
    if isinstance(cierre, CierrePorSaldos):
        cierre = cierre.model_copy(update={"saldo_final": cierre.saldo_final + monto})
    else:
        cierre = cierre.model_copy(update={"total_declarado": cierre.total_declarado + monto})
    nuevo = resumen.model_copy(
        update={"movimientos": [*resumen.movimientos, devolucion], "cierre": cierre}
    )
    return nuevo, verificar_cuadratura(nuevo)
