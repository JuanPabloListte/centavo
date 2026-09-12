"""Fixtures compartidos.

`db` crea un esquema temporal en Postgres, le aplica `db/schema.sql` y lo borra
al terminar. Así los tests de memoria, reporte y API corren contra una base de
verdad sin tocar nunca tus datos. Si Postgres no está disponible, esos tests
se saltean en vez de fallar.
"""

import uuid
from pathlib import Path

import psycopg
import pytest

from app.store import DATABASE_URL

ESQUEMA_SQL = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


def sentencias_del_esquema() -> list[str]:
    """schema.sql sin comentarios, partido en sentencias. Alcanza para este
    archivo, que no tiene ';' ni '--' dentro de literales."""
    sql = ESQUEMA_SQL.read_text(encoding="utf-8")
    sin_comentarios = "\n".join(linea.split("--", 1)[0] for linea in sql.splitlines())
    return [s.strip() for s in sin_comentarios.split(";") if s.strip()]


@pytest.fixture
def db():
    try:
        conn = psycopg.connect(DATABASE_URL, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres no está disponible")

    esquema = f"test_{uuid.uuid4().hex[:10]}"
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA {esquema}")
        cur.execute(f"SET search_path TO {esquema}, public")
    conn.commit()
    with conn.cursor() as cur:
        for sentencia in sentencias_del_esquema():
            cur.execute(sentencia)
    conn.commit()

    try:
        yield conn
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA {esquema} CASCADE")
        conn.commit()
        conn.close()
