"""Cuánto puede resolver la memoria, medido antes de etiquetar nada.

    python -m tools.memoria_potencial

Simula que corregiste la primera quincena de cada resumen y cuenta cuánto de la
segunda se resolvería sin modelo, sólo porque la contraparte se repite. No
necesita etiquetas: la pregunta es estructural.

Corre después de `tools.ingerir`, que es el que separa lo que ya resuelve la
evidencia. Imprime conteos, nunca nombres ni montos.
"""

from __future__ import annotations

from collections import defaultdict

from app.store import conectar


def main() -> int:
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.periodo_desde, s.periodo_hasta, t.fecha, t.clave
            FROM transactions t
            JOIN statements s ON s.id = t.statement_id
            WHERE s.estado = 'cuadrado'
              AND t.via IS DISTINCT FROM 'evidencia'
            ORDER BY s.id, t.fecha, t.id
            """
        )
        filas = cur.fetchall()

    if not filas:
        print("No hay movimientos sin evidencia en resúmenes cuadrados.")
        return 0

    por_resumen = defaultdict(list)
    periodos = {}
    for sid, desde, hasta, fecha, clave in filas:
        por_resumen[sid].append((fecha, clave))
        periodos[sid] = (desde, hasta)

    for sid, movs in por_resumen.items():
        desde, hasta = periodos[sid]
        claves = [c for _, c in movs]
        distintas = len(set(claves))
        print(f"resumen {sid} ({desde} a {hasta})")
        print(f"  {len(movs)} movimientos sin evidencia, {distintas} contrapartes distintas: "
              f"{len(movs) / distintas:.2f} movimientos por decisión")

        primera = [c for f, c in movs if f.day <= 15]
        segunda = [c for f, c in movs if f.day > 15]
        aprendidas = set(primera)
        cubiertos = sum(1 for c in segunda if c in aprendidas)
        print(f"  corregir la 1ª quincena: {len(aprendidas)} decisiones para {len(primera)} movimientos")
        print(f"  la 2ª quincena se resolvería sin modelo: {cubiertos} de {len(segunda)} "
              f"({cubiertos / max(len(segunda), 1):.0%})")

        tipos = defaultdict(lambda: [0, 0])
        for c in segunda:
            tipo = c.split("|", 1)[0]
            tipos[tipo][0] += 1
            tipos[tipo][1] += c in aprendidas
        for tipo, (n, k) in sorted(tipos.items(), key=lambda x: -x[1][0]):
            print(f"    {tipo:16} {k:3} de {n:3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
