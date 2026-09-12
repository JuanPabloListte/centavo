"""Las últimas ingestas, con conteos.

    python -m tools.corridas
    python -m tools.corridas --limite 50

Una fila por corrida: cuándo, desde dónde, cómo terminó, cuánto tardó, cuántos
movimientos del resumen resolvió cada vía y cuánto costó el modelo. Nunca imprime
movimientos: la tabla no los tiene.
"""

from __future__ import annotations

import argparse

from app.corridas import ultimas
from app.store import conectar

CORTO = {
    "regla": "mem",
    "evidencia": "evi",
    "consenso": "cons",
    "modelo": "mod",
    "needs_review": "rev",
    "sin_procesar": "pend",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Últimas corridas de ingesta")
    ap.add_argument("--limite", type=int, default=20)
    args = ap.parse_args()

    with conectar() as conn:
        filas = ultimas(conn, args.limite)
    if not filas:
        print("Todavía no hay corridas: se registran al ingerir un resumen.")
        return 0

    print(f"{'id':>4}  {'cuándo':16}  {'origen':8}  {'resultado':13}  {'ms':>6}  {'mov':>4}  "
          f"{'llam':>4}  {'tokens':>7}  {'rep':>3}  {'desac':>5}  por vía")
    for c in filas:
        vias = " ".join(f"{CORTO.get(v, v)}={n}" for v, n in c["por_via"].items())
        print(f"{c['id']:>4}  {c['empezo_en'].astimezone():%Y-%m-%d %H:%M}  {c['origen']:8}  "
              f"{c['resultado']:13}  {c['milisegundos']:>6}  {c['movimientos']:>4}  "
              f"{c['llamadas_modelo']:>4}  {c['tokens_entrada'] + c['tokens_salida']:>7}  "
              f"{c['reparaciones']:>3}  {c['desacuerdos']:>5}  {vias}")
    print("\nvías: mem = tu memoria · evi = evidencia · cons = consenso · mod = modelo · "
          "rev = a revisión · pend = sin resolver")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
