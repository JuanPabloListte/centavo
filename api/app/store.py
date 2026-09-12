"""Persistencia.

Tres reglas:

1. **Idempotencia por sha256.** El mismo archivo no se ingiere dos veces.
2. **Idempotencia por movimiento.** El sha256 no alcanza: el mismo mes
   descargado dos veces puede regenerarse con otra fecha de creación y otro
   hash, pero los movimientos son los mismos. Si todos ya están cargados, es
   el mismo resumen y no se hace nada.
3. **La compuerta marca, no borra.** Un resumen descuadrado SÍ se guarda, con
   estado 'descuadrado', para que quede registro de qué falló y por cuánto. Lo
   que no pasa es que las fases siguientes lo lean: de la fase 1 en adelante,
   todo consulta sólo estado = 'cuadrado'.

La identidad de un movimiento es ID de operación + fecha + monto, no el ID
solo. En resúmenes reales, la devolución de un pago trae el mismo ID que el
pago, a veces otro día y por otro monto: con el ID solo, la devolución chocaba
con su pago dentro del mismo archivo, y una devolución que cayera en el mes
siguiente habría parecido una superposición. Si dos movimientos de un archivo
coinciden en las tres cosas, `repeticion` los numera en orden.

Un archivo que trae movimientos ya cargados mezclados con movimientos nuevos
(dos resúmenes que se superponen en fechas) se rechaza entero. Aceptar sólo
los nuevos dejaría un resumen a medias cuyo saldo ya no encadena. Cómo
combinar rangos superpuestos es una decisión de la automatización, no de acá.

Cada movimiento se guarda con su clave de memoria, calculada en el momento: es
lo que agrupa la revisión y lo que la memoria de la fase 3 busca. Después de
guardar, cada devolución se une a su pago y toma la clave del pago
(`devoluciones.py`).
"""

from __future__ import annotations

import os
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from .agents.patrones import clave_memoria
from .devoluciones import vincular_devoluciones
from .models import CierrePorSaldos, CierrePorTotal, Resumen, ResultadoCuadratura

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# 127.0.0.1 y no localhost: en Windows, localhost resuelve primero a ::1, y con
# Postgres publicado sólo en 127.0.0.1 cada conexión esperaba a que venciera ese
# intento antes de probar IPv4. Ver FASE-4.md, "Todo en contenedores".
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://libro:libro@127.0.0.1:5433/libro_mayor",
)


class YaIngerido(Exception):
    """El archivo, o todos sus movimientos, ya están en la base. No es un error:
    es la idempotencia funcionando. Quien llama decide si lo ignora o lo informa."""

    def __init__(self, statement_id: int, archivo: str):
        self.statement_id = statement_id
        super().__init__(f"{archivo} ya fue ingerido (statement_id={statement_id})")


class SuperposicionParcial(Exception):
    """Algunos movimientos del archivo ya están cargados y otros no."""

    def __init__(self, repetidas: int, total: int, archivo: str):
        self.repetidas, self.total = repetidas, total
        super().__init__(
            f"{archivo}: {repetidas} de {total} movimientos ya están cargados desde "
            f"otro resumen. Cargar resúmenes que se superponen todavía no está "
            f"soportado: se rechaza entero en vez de dejar un resumen a medias."
        )


# Esquema opcional. Sirve para levantar la aplicación contra una base de
# demostración con datos sintéticos, sin tocar la tuya.
ESQUEMA = os.getenv("CENTAVO_DB_SCHEMA") or None
if ESQUEMA is not None and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", ESQUEMA):
    raise ValueError(f"CENTAVO_DB_SCHEMA inválido: {ESQUEMA!r}")


def conectar(url: str | None = None) -> psycopg.Connection:
    opciones = {"options": f"-c search_path={ESQUEMA},public"} if ESQUEMA else {}
    return psycopg.connect(url or DATABASE_URL, **opciones)


Identidad = tuple[str, date, Decimal, int]


def identidades(resumen: Resumen) -> list[Identidad | None]:
    """La identidad de cada movimiento, en el orden del resumen: (ID de
    operación, fecha, monto, repetición). None si la fuente no trae ID."""
    vistas: Counter[tuple[str, date, Decimal]] = Counter()
    salida: list[Identidad | None] = []
    for m in resumen.movimientos:
        if m.id_operacion is None:
            salida.append(None)
            continue
        base = (m.id_operacion, m.fecha, m.monto)
        vistas[base] += 1
        salida.append((*base, vistas[base]))
    return salida


def guardar(
    resumen: Resumen,
    resultado: ResultadoCuadratura,
    conn: psycopg.Connection | None = None,
) -> int:
    propia = conn is None
    conn = conn or conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM statements WHERE sha256 = %s", (resumen.sha256,)
            )
            if (fila := cur.fetchone()) is not None:
                raise YaIngerido(fila[0], resumen.archivo)

            idents = identidades(resumen)
            con_id = [i for i in idents if i is not None]
            if con_id:
                ids, fechas, montos, repeticiones = (list(col) for col in zip(*con_id))
                cur.execute(
                    """
                    SELECT count(*), min(t.statement_id)
                    FROM transactions t
                    JOIN unnest(%s::text[], %s::date[], %s::numeric[], %s::smallint[])
                         AS u(id_operacion, fecha, monto, repeticion)
                      ON t.id_operacion = u.id_operacion
                     AND t.fecha = u.fecha
                     AND t.monto = u.monto
                     AND t.repeticion = u.repeticion
                    WHERE t.fuente = %s
                    """,
                    (ids, fechas, montos, repeticiones, resumen.banco),
                )
                repetidas, statement_previo = cur.fetchone()
                if repetidas:
                    if repetidas == len(con_id) == len(resumen.movimientos):
                        raise YaIngerido(statement_previo, resumen.archivo)
                    raise SuperposicionParcial(
                        repetidas, len(resumen.movimientos), resumen.archivo
                    )

            cierre = resumen.cierre
            total = cierre.total_declarado if isinstance(cierre, CierrePorTotal) else None
            s_ini = cierre.saldo_inicial if isinstance(cierre, CierrePorSaldos) else None
            s_fin = cierre.saldo_final if isinstance(cierre, CierrePorSaldos) else None

            cur.execute(
                """
                INSERT INTO statements (
                    banco, archivo, sha256, periodo_desde, periodo_hasta,
                    cierre_tipo, total_declarado, saldo_inicial, saldo_final,
                    esperado, calculado, estado, titular
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    resumen.banco, resumen.archivo, resumen.sha256,
                    resumen.periodo_desde, resumen.periodo_hasta,
                    cierre.tipo, total, s_ini, s_fin,
                    resultado.esperado, resultado.calculado,
                    "cuadrado" if resultado.cuadra else "descuadrado",
                    resumen.titular,
                ),
            )
            statement_id = cur.fetchone()[0]

            cur.executemany(
                """
                INSERT INTO transactions (
                    statement_id, fecha, monto, moneda, descripcion_cruda,
                    linea_origen, fuente, id_operacion, saldo, clave, repeticion
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [
                    (
                        statement_id, m.fecha, m.monto, m.moneda,
                        m.descripcion_cruda, m.linea_origen,
                        resumen.banco, m.id_operacion, m.saldo,
                        clave_memoria(m.descripcion_cruda, m.id_operacion),
                        identidad[3] if identidad else 1,
                    )
                    for m, identidad in zip(resumen.movimientos, idents)
                ],
            )

            # Cada devolución se une a su pago y toma su clave. Se recorre todo
            # lo que todavía no tiene vínculo, no sólo este resumen: si este
            # archivo trae el pago de una devolución cargada antes, también.
            vincular_devoluciones(conn)

        conn.commit()
        return statement_id
    except Exception:
        conn.rollback()
        raise
    finally:
        if propia:
            conn.close()
