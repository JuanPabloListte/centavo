"""Observabilidad: una fila por ingesta, con conteos y nunca con movimientos.

Cada ingesta, por terminal o por la API, deja una fila en `corridas`: cuánto
tardó, cómo terminó, cuántos movimientos del resumen resolvió cada vía, cuántos
desacuerdos hubo entre los agentes, y cuánto costó el modelo en llamadas,
tokens, segundos y reparaciones de JSON.

Con eso se contesta con SQL lo que contestaría un tablero de trazas: si el
modelo se volvió más lento, cuántas reparaciones de JSON hacen falta, cuánto
resuelve la memoria mes a mes.

Lo que no guarda, a propósito: descripciones, montos, nombres ni el texto de un
error. Un error de parseo puede citar el renglón que no se pudo leer, y eso es un
dato del resumen: de un error queda sólo la clase.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import psycopg

RESULTADOS = frozenset({"cuadrado", "descuadrado", "ya_ingerido", "superposicion", "error"})


def conteo_del_resumen(conn: psycopg.Connection, statement_id: int) -> dict[str, int]:
    """Cómo quedó clasificado UN resumen: la vía de lo resuelto, el estado de lo
    que no. No mezcla lo pendiente de otros meses."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT CASE WHEN estado_clasificacion = 'resuelto' THEN via
                        ELSE estado_clasificacion END,
                   count(*)
            FROM transactions
            WHERE statement_id = %s
            GROUP BY 1
            ORDER BY 2 DESC, 1
            """,
            (statement_id,),
        )
        return dict(cur.fetchall())


@dataclass
class Corrida:
    """Se crea al empezar una ingesta y se guarda una vez, cuando termina."""

    origen: str                                   # 'terminal' | 'api'
    inicio: float = field(default_factory=time.perf_counter)

    def guardar(
        self,
        conn: psycopg.Connection,
        resultado: str,
        *,
        statement_id: int | None = None,
        cliente=None,
        error: BaseException | None = None,
    ) -> int:
        """Guarda la corrida y hace commit. `cliente` es el ClienteLLM, si hubo
        modelo: de ahí salen llamadas, tokens, segundos y reparaciones."""
        if resultado not in RESULTADOS:
            raise ValueError(f"resultado desconocido: {resultado!r}")
        milisegundos = round((time.perf_counter() - self.inicio) * 1000)
        por_via = {} if statement_id is None else conteo_del_resumen(conn, statement_id)
        uso = getattr(cliente, "uso", None)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO corridas (
                    origen, statement_id, milisegundos, resultado, movimientos, por_via,
                    desacuerdos, modelo, llamadas_modelo, tokens_entrada, tokens_salida,
                    reparaciones, segundos_modelo, error_tipo
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    (SELECT count(*) FROM transactions
                      WHERE statement_id = %s AND via = 'desacuerdo'),
                    %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    self.origen, statement_id, milisegundos, resultado,
                    sum(por_via.values()), json.dumps(por_via), statement_id,
                    getattr(cliente, "modelo", None),
                    uso.llamadas if uso else 0,
                    uso.tokens_entrada if uso else 0,
                    uso.tokens_salida if uso else 0,
                    uso.reparaciones if uso else 0,
                    round(uso.segundos, 2) if uso else 0,
                    type(error).__name__ if error else None,
                ),
            )
            corrida_id = cur.fetchone()[0]
        conn.commit()
        return corrida_id


def ultimas(conn: psycopg.Connection, limite: int = 20) -> list[dict]:
    """Las últimas corridas, la más nueva primero. Sólo conteos."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, origen, statement_id, empezo_en, milisegundos, resultado,
                   movimientos, por_via, desacuerdos, modelo, llamadas_modelo,
                   tokens_entrada, tokens_salida, reparaciones, segundos_modelo, error_tipo
            FROM corridas
            ORDER BY id DESC
            LIMIT %s
            """,
            (limite,),
        )
        columnas = [d.name for d in cur.description]
        return [dict(zip(columnas, fila)) for fila in cur.fetchall()]
