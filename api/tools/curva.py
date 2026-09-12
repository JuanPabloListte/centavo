"""Curva de memoria entre meses.

    python -m tools.curva

Para cada resumen cargado, en orden cronológico: qué parte de sus movimientos
tiene una contraparte que ya apareció en un resumen ANTERIOR. Es lo que la
memoria resolvería sola si revisaste los meses previos.

No depende del orden en que cargaste ni en que revisaste los resúmenes: se
calcula por fechas de período. Los movimientos que resuelve la evidencia no
cuentan, porque para esos la memoria no hace falta. Las claves sin contraparte
cuentan en el total pero nunca como cubiertas: no se aprenden.

Imprime conteos, nunca nombres ni montos.
"""

from __future__ import annotations

from collections import defaultdict

from app.agents.patrones import es_memorizable
from app.store import conectar


def main() -> int:
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.periodo_desde, s.periodo_hasta, t.clave
            FROM transactions t
            JOIN statements s ON s.id = t.statement_id
            WHERE s.estado = 'cuadrado'
              AND t.via IS DISTINCT FROM 'evidencia'
            ORDER BY s.periodo_desde, s.id
            """
        )
        filas = cur.fetchall()

    if not filas:
        print("No hay resúmenes cuadrados con movimientos para medir.")
        return 0

    por_resumen: dict[int, list[str]] = defaultdict(list)
    periodos: dict[int, tuple] = {}
    for sid, desde, hasta, clave in filas:
        por_resumen[sid].append(clave)
        periodos[sid] = (desde, hasta)

    orden = sorted(por_resumen, key=lambda sid: (periodos[sid][0], sid))
    vistas: set[str] = set()

    print(f"{'período':25} {'movimientos':>11} {'cubiertos':>10} {'':>6}")
    for sid in orden:
        claves = por_resumen[sid]
        cubiertos = sum(1 for c in claves if c in vistas)
        desde, hasta = periodos[sid]
        etiqueta = f"{desde} a {hasta}"
        porcentaje = f"{cubiertos / len(claves):.0%}" if claves else "-"
        print(f"{etiqueta:25} {len(claves):>11} {cubiertos:>10} {porcentaje:>6}")
        vistas |= {c for c in claves if es_memorizable(c)}

    if len(orden) == 1:
        print("\nCon un solo resumen no hay curva: el primero siempre da 0%, porque no hay "
              "meses anteriores de donde aprender. Cargá otro mes con tools.ingerir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
