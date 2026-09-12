"""Una devolución unida a su pago.

En los resúmenes reales de Mercado Pago, la devolución de un pago trae el
mismo ID de operación que el pago: a veces el mismo día y por el mismo monto,
a veces otro día y por una parte. Sin el vínculo, la devolución es un
movimiento suelto: cae en una clave propia ("COMERCIO|DEVOLUCION DE PAGO ..."),
se revisa aparte y, una vez clasificada, figura como ingreso de su categoría.

Con el vínculo:

- **Toma la clave del pago.** La memoria, la bandeja y las decisiones la
  tratan con su pago sin código extra: una decisión sobre el comercio resuelve
  las dos.
- **Hereda la categoría del pago** si el pago ya está resuelto; si no, espera
  a que se decida con él. El modelo no la ve nunca (`memoria.py`).
- **En el reporte resta del gasto** de su categoría, en vez de sumarse como
  ingreso (`reporte.py`).

El vínculo es determinista y exacto. Un movimiento positivo cuyo texto arranca
con "Devolución de" se une a un movimiento negativo con el mismo (fuente, ID
de operación), de fecha igual o anterior y por un monto igual o mayor: una
"devolución" más grande que el pago no es una devolución de ese pago. Si hay
más de un candidato, gana el del mismo resumen y, entre esos, el más reciente.
Si no hay ninguno —un pago anterior al primer resumen cargado— la devolución
queda suelta, como antes, y se revisa aparte. Ante la duda, a revisión.

Se calcula al guardar cada resumen, sobre todo lo que todavía no tiene vínculo,
no sólo sobre el resumen nuevo: así una devolución cargada antes que su pago
(mayo cargado antes que abril) se une cuando el pago aparece.
"""

from __future__ import annotations

import psycopg

from .agents.patrones import es_devolucion

# Filtro barato en SQL; la regla exacta es `es_devolucion`, en Python.
_CANDIDATAS = """
    SELECT id, descripcion_cruda
    FROM transactions
    WHERE devuelve_a IS NULL
      AND monto > 0
      AND id_operacion IS NOT NULL
      AND descripcion_cruda ILIKE 'devoluci%'
    ORDER BY id
"""


def _sin_vinculo(cur) -> list[int]:
    cur.execute(_CANDIDATAS)
    return [tid for tid, descripcion in cur.fetchall() if es_devolucion(descripcion)]


def vincular_devoluciones(conn: psycopg.Connection) -> int:
    """Une cada devolución sin vínculo con su pago, si está cargado, y le pasa
    la clave del pago. Devuelve cuántas unió.

    No hace commit: corre dentro de la transacción de quien llama.
    """
    unidas = 0
    with conn.cursor() as cur:
        for tid in _sin_vinculo(cur):
            cur.execute(
                """
                UPDATE transactions AS dev
                   SET devuelve_a = pago.id,
                       clave      = pago.clave
                  FROM (
                      SELECT p.id, p.clave
                      FROM transactions p
                      JOIN transactions d ON d.id = %(id)s
                      WHERE p.id <> d.id
                        AND p.fuente = d.fuente
                        AND p.id_operacion = d.id_operacion
                        AND p.monto < 0
                        AND p.fecha <= d.fecha
                        AND -p.monto >= d.monto
                      ORDER BY (p.statement_id = d.statement_id) DESC,
                               p.fecha DESC, p.id DESC
                      LIMIT 1
                  ) AS pago
                 WHERE dev.id = %(id)s
                """,
                {"id": tid},
            )
            unidas += cur.rowcount
    return unidas


def devoluciones_sueltas(conn: psycopg.Connection) -> int:
    """Devoluciones sin pago cargado. Se revisan aparte, como cualquier otro
    movimiento."""
    with conn.cursor() as cur:
        return len(_sin_vinculo(cur))
