"""Arma o rearma el esquema `demo`, con el resumen sintético.

    python -m tools.demo

Borra y recrea el esquema `demo` en la misma base, le aplica db/schema.sql,
carga tests/fixtures/resumen_mp.pdf y lo clasifica sin modelo. Nunca toca el
esquema `public`, que es donde están tus datos.

Después: `uvicorn app.demo:app --host 127.0.0.1 --port 8000`.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import psycopg

from app.memoria import clasificar_pendientes, grupos_pendientes
from app.pipeline import procesar
from app.store import DATABASE_URL, guardar
from tools.resumen_mp_sintetico import con_devolucion

RAIZ = Path(__file__).resolve().parents[1]
ESQUEMA_SQL = RAIZ.parent / "db" / "schema.sql"
RESUMEN = RAIZ / "tests" / "fixtures" / "resumen_mp.pdf"


def _sentencias() -> list[str]:
    sql = ESQUEMA_SQL.read_text(encoding="utf-8")
    sin_comentarios = "\n".join(linea.split("--", 1)[0] for linea in sql.splitlines())
    return [s.strip() for s in sin_comentarios.split(";") if s.strip()]


def main() -> int:
    conn = psycopg.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS demo CASCADE")
            cur.execute("CREATE SCHEMA demo")
            cur.execute("SET search_path TO demo, public")
        conn.commit()

        with conn.cursor() as cur:
            for sentencia in _sentencias():
                cur.execute(sentencia)
        conn.commit()

        resumen, resultado = procesar(RESUMEN)
        # El PDF sintético no trae devoluciones: se agrega una en memoria, para
        # ver en la interfaz cómo se une a su pago.
        pago = next(m for m in resumen.movimientos
                    if m.descripcion_cruda == "Pago con QR Farmacia del Centro")
        resumen, resultado = con_devolucion(resumen, pago, monto=Decimal("5000.00"))
        statement_id = guardar(resumen, resultado, conn=conn)
        conteo = clasificar_pendientes(conn)
        grupos = grupos_pendientes(conn)
        print(f"esquema demo listo: resumen {statement_id} · {resultado.explicar()}")
        print(f"  clasificación: {conteo} · {len(grupos)} contrapartes para revisar")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
