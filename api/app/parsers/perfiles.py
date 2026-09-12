"""Registro de perfiles de banco.

Cada entrada describe cómo lee un banco. Agregar un banco real es agregar un
Perfil acá y un fixture en tests/fixtures/ — no hace falta tocar los parsers.

Los tres primeros son de bancos sintéticos, generados por
`tools/generar_fixtures.py`. Existen para que el pipeline se pueda construir y
probar de punta a punta sin tener un resumen real a mano, y están armados a
propósito con las dos formas de cierre y las dos formas de expresar el importe
que hay en la calle.
"""

from .base import Perfil

# ---------------------------------------------------------------------------
# Tarjeta de crédito: cierra por TOTAL, importe en una sola columna con signo.
# ---------------------------------------------------------------------------
TARJETA_SINTETICA = Perfil(
    banco="Banco Ejemplo — Tarjeta VISA",
    formato="csv",
    marcador="Resumen de Tarjeta de Credito",
    col_fecha="Fecha",
    col_descripcion="Descripcion",
    tipo_importe="columna_unica",
    col_importe="Importe",
    re_total=r"Total a pagar;([\-\d\.,]+)",
    re_periodo=r"Periodo;([\d/]+);([\d/]+)",
)

# ---------------------------------------------------------------------------
# Cuenta corriente: cierra por SALDOS, importe en columnas débito/crédito.
# ---------------------------------------------------------------------------
CUENTA_SINTETICA = Perfil(
    banco="Banco Ejemplo — Cuenta Corriente",
    formato="csv",
    marcador="Cuenta Corriente en Pesos",
    col_fecha="Fecha",
    col_descripcion="Descripcion",
    tipo_importe="debito_credito",
    col_debito="Debito",
    col_credito="Credito",
    re_saldo_inicial=r"Saldo inicial;([\-\d\.,]+)",
    re_saldo_final=r"Saldo final;([\-\d\.,]+)",
    re_periodo=r"Periodo;([\d/]+);([\d/]+)",
)

# ---------------------------------------------------------------------------
# El mismo resumen de tarjeta, pero en PDF. Mismas columnas; lo que cambia son
# las expresiones para encontrar el cierre, porque en el PDF no hay ';'.
# ---------------------------------------------------------------------------
TARJETA_SINTETICA_PDF = Perfil(
    banco="Banco Ejemplo — Tarjeta VISA",
    formato="pdf",
    marcador="Resumen de Tarjeta de Credito",
    col_fecha="Fecha",
    col_descripcion="Descripcion",
    tipo_importe="columna_unica",
    col_importe="Importe",
    re_total=r"Total a pagar\s+([\-\$\s\d\.,]+)",
    re_periodo=r"Periodo\s+([\d/]+)\s+a\s+([\d/]+)",
)

# ---------------------------------------------------------------------------
# Mercado Pago — "Resumen de cuenta en pesos", el PDF que se genera desde la web.
#
# Primer perfil real del proyecto, armado sobre un resumen de agosto de 2026:
# 131 movimientos en 10 páginas, 70 con la descripción partida en varios
# renglones y sin tabla detectable. Por eso va por coordenadas.
#
# Cierra por saldos, imprime el saldo después de cada movimiento —lo que
# habilita el control renglón por renglón— y trae un ID único por operación.
# La página final es una tabla de operaciones en dólares con otras columnas:
# se ignora mientras venga vacía.
# ---------------------------------------------------------------------------
MERCADO_PAGO_RESUMEN = Perfil(
    banco="Mercado Pago — Resumen de cuenta",
    formato="pdf",
    estrategia="coordenadas",
    marcador="RESUMEN DE CUENTA EN PESOS",
    col_fecha="Fecha",
    col_descripcion="Descripción",
    tipo_importe="columna_unica",
    col_importe="Valor",
    col_id_operacion="ID",
    col_saldo="Saldo",
    formatos_fecha=("%d-%m-%Y", "%d/%m/%Y"),
    re_saldo_inicial=r"Saldo inicial:\s*\$\s*(-?[\d\.]+,\d{2})",
    re_saldo_final=r"Saldo final:\s*\$\s*(-?[\d\.]+,\d{2})",
    re_titular=r"RESUMEN DE CUENTA EN PESOS\s*\n\s*([^\n]+?)\s*\n",
    rotulos_no_soportados=("Cotización",),
)


PERFILES: list[Perfil] = [
    TARJETA_SINTETICA,
    CUENTA_SINTETICA,
    TARJETA_SINTETICA_PDF,
    MERCADO_PAGO_RESUMEN,
]
