"""Memoria de la fase 3: tus decisiones, aplicadas a todo lo que comparte clave.

Tres operaciones:

- `aplicar_decision`: guardás qué es una contraparte y se aplica YA a todos sus
  movimientos cargados, dejando una corrección por cada uno.
- `clasificar_pendientes`: resuelve los movimientos sin procesar en el orden del
  proyecto — memoria, evidencia y, sólo si se pide, modelo.
- `grupos_pendientes`: lo que falta, agrupado por clave. Una decisión por grupo.

Una devolución unida a su pago (`devoluciones.py`) tiene la clave del pago, así
que cae en su grupo y una decisión resuelve las dos. Si el pago ya está
resuelto, hereda su categoría; si no, espera. El modelo no la ve nunca.

Todo trabaja sólo sobre resúmenes con estado 'cuadrado'. Un resumen que no pasó
la compuerta no se clasifica ni se corrige: sus movimientos no son de fiar.
"""

from __future__ import annotations

from collections import Counter

import psycopg

from .agents.patrones import analizar, es_memorizable


def cargar_memoria(conn: psycopg.Connection) -> dict[str, str]:
    """clave -> nombre de categoría."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.clave, c.nombre
            FROM memoria m
            JOIN categories c ON c.id = m.categoria_id
            """
        )
        return dict(cur.fetchall())


def _categoria_resuelta(conn: psycopg.Connection, transaction_id: int) -> str | None:
    """La categoría de un movimiento, sólo si está resuelto."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.nombre
            FROM transactions t
            JOIN categories c ON c.id = t.categoria_id
            WHERE t.id = %s AND t.estado_clasificacion = 'resuelto'
            """,
            (transaction_id,),
        )
        fila = cur.fetchone()
    return None if fila is None else fila[0]


def _categoria_id(cur, nombre: str) -> int:
    cur.execute("SELECT id FROM categories WHERE nombre = %s", (nombre,))
    if (fila := cur.fetchone()) is None:
        raise ValueError(f"categoría inexistente: {nombre!r}")
    return fila[0]


# Movimientos a los que alcanza una decisión sobre una clave: de resúmenes
# cuadrados, con esa clave, y que todavía no tienen esa categoría resuelta.
_ALCANCE = """
    FROM statements s
    WHERE s.id = t.statement_id
      AND s.estado = 'cuadrado'
      AND t.clave = %(clave)s
      AND (t.categoria_id IS DISTINCT FROM %(categoria)s
           OR t.estado_clasificacion <> 'resuelto')
"""


def aplicar_decision(conn: psycopg.Connection, clave: str, categoria: str) -> int:
    """Aplica la decisión a todos los movimientos con esa clave y la guarda en
    memoria. Devuelve cuántos movimientos cambió.

    Una decisión tuya es absoluta: pisa lo que haya decidido la evidencia o el
    modelo. Decidir de nuevo lo mismo no cambia movimientos, pero cuenta como
    una confirmación más. Una clave sin contraparte se decide pero no se
    guarda en memoria: no identifica a nadie.
    """
    try:
        with conn.cursor() as cur:
            params = {"clave": clave, "categoria": _categoria_id(cur, categoria)}

            if es_memorizable(clave):
                cur.execute(
                    """
                    INSERT INTO memoria (clave, categoria_id)
                    VALUES (%(clave)s, %(categoria)s)
                    ON CONFLICT (clave) DO UPDATE
                       SET categoria_id   = EXCLUDED.categoria_id,
                           confirmaciones = memoria.confirmaciones + 1,
                           actualizada_en = now()
                    """,
                    params,
                )

            cur.execute(
                f"""
                INSERT INTO correcciones
                    (transaction_id, clave, categoria_anterior_id, categoria_nueva_id)
                SELECT t.id, t.clave, t.categoria_id, %(categoria)s
                FROM transactions t
                WHERE EXISTS (SELECT 1 {_ALCANCE})
                """,
                params,
            )
            cur.execute(
                f"""
                UPDATE transactions t
                   SET categoria_id = %(categoria)s,
                       confianza = 1.00,
                       via = 'regla',
                       estado_clasificacion = 'resuelto'
                {_ALCANCE}
                """,
                params,
            )
            cambiados = cur.rowcount
        conn.commit()
        return cambiados
    except Exception:
        conn.rollback()
        raise


def clasificar_pendientes(conn: psycopg.Connection, clasificador=None) -> dict[str, int]:
    """Clasifica los movimientos 'sin_procesar' de resúmenes cuadrados.

    Orden: memoria -> el pago que devuelve -> evidencia -> modelo. Sin
    `clasificador`, lo que no resuelven la memoria ni la evidencia queda
    'sin_procesar', listo para la revisión. Devuelve cuántos se resolvieron
    por cada vía.

    Las devoluciones van al final: así su pago, si está en el mismo lote, ya
    quedó resuelto cuando les toca.
    """
    memoria = cargar_memoria(conn)
    conteo: Counter[str] = Counter()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.descripcion_cruda, t.monto, t.clave, s.titular, t.devuelve_a
            FROM transactions t
            JOIN statements s ON s.id = t.statement_id
            WHERE s.estado = 'cuadrado'
              AND t.estado_clasificacion = 'sin_procesar'
            ORDER BY (t.devuelve_a IS NOT NULL), t.id
            """
        )
        filas = cur.fetchall()

    try:
        for tid, descripcion, monto, clave, titular, devuelve_a in filas:
            if clave in memoria:
                categoria, via, estado, confianza = memoria[clave], "regla", "resuelto", 1.0
            elif devuelve_a is not None:
                # Una devolución hereda la categoría de su pago si ya está
                # resuelto; si no, se decide con él. El modelo no la ve.
                categoria = _categoria_resuelta(conn, devuelve_a)
                if categoria is None:
                    conteo["sin_procesar"] += 1
                    continue
                via, estado, confianza = "evidencia", "resuelto", 1.0
            else:
                p = analizar(descripcion, monto, titular)
                if p.categoria_determinada is not None:
                    categoria, via, estado, confianza = (
                        p.categoria_determinada, "evidencia", "resuelto", 1.0
                    )
                elif clasificador is not None:
                    r = clasificador.clasificar(descripcion, monto, titular=titular)
                    categoria, via, estado, confianza = r.categoria, r.via, r.estado, r.confianza
                else:
                    conteo["sin_procesar"] += 1
                    continue

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE transactions
                       SET categoria_id = (SELECT id FROM categories WHERE nombre = %s),
                           confianza = %s,
                           via = %s,
                           estado_clasificacion = %s
                     WHERE id = %s
                    """,
                    (categoria, round(confianza, 2), via, estado, tid),
                )
            conteo[via if estado == "resuelto" else "needs_review"] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return dict(conteo)


def grupos_pendientes(conn: psycopg.Connection) -> list[dict]:
    """Movimientos sin resolver, agrupados por clave, de mayor a menor cantidad."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.clave,
                   count(*),
                   sum(t.monto),
                   min(t.fecha),
                   max(t.fecha),
                   array_agg(t.descripcion_cruda
                             ORDER BY (t.devuelve_a IS NOT NULL), t.fecha, t.id),
                   count(*) FILTER (WHERE t.devuelve_a IS NOT NULL)
            FROM transactions t
            JOIN statements s ON s.id = t.statement_id
            WHERE s.estado = 'cuadrado'
              AND t.estado_clasificacion <> 'resuelto'
            GROUP BY t.clave
            ORDER BY count(*) DESC, abs(sum(t.monto)) DESC, t.clave
            """
        )
        return [
            {
                "clave": clave,
                "cantidad": cantidad,
                "total": total,
                "desde": desde,
                "hasta": hasta,
                # Los pagos van antes que sus devoluciones: el primer ejemplo
                # es el que da nombre al grupo.
                "ejemplos": list(dict.fromkeys(ejemplos))[:3],
                "devoluciones": devoluciones,
            }
            for clave, cantidad, total, desde, hasta, ejemplos, devoluciones in cur.fetchall()
        ]
