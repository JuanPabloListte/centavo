"""Aplica las migraciones de db/migraciones/ a una base que ya tiene datos.

    python -m tools.migrar

`db/schema.sql` corre una sola vez, cuando Docker crea el volumen. Una base con
datos no se recrea: los cambios de esquema le llegan como migraciones.

Cada migración es idempotente —sobre una base que ya la tiene, o creada con el
schema.sql actual, no cambia nada—, así que se aplican todas, en orden, cada
vez, sin llevar registro. Cada una corre en su propia transacción: si falla, no
queda a medias.

Después de los .sql, une con su pago las devoluciones que todavía no lo están
(migración 002): la columna la agrega el SQL, el vínculo lo calcula el código.
También idempotente: lo ya unido no se toca.
"""

from __future__ import annotations

from pathlib import Path

from app.devoluciones import devoluciones_sueltas, vincular_devoluciones
from app.store import conectar

MIGRACIONES = Path(__file__).resolve().parents[2] / "db" / "migraciones"


def main() -> int:
    archivos = sorted(MIGRACIONES.glob("*.sql"))
    if not archivos:
        print("No hay migraciones.")
        return 0
    with conectar() as conn:
        for archivo in archivos:
            with conn.transaction():
                conn.execute(archivo.read_text(encoding="utf-8"))
            print(f"  {archivo.name}: aplicada")
        with conn.transaction():
            unidas = vincular_devoluciones(conn)
        sueltas = devoluciones_sueltas(conn)
        print(f"  devoluciones: {unidas} unidas a su pago ahora, {sueltas} sin pago cargado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
