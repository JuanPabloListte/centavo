"""Revisión por contraparte.

    python -m tools.revisar

Muestra lo que falta clasificar, agrupado por clave de contraparte. Una
decisión tuya resuelve todo el grupo y queda en memoria: la próxima vez que
aparezca esa contraparte, en este resumen o en uno futuro, se resuelve sola,
sin modelo.

Se corta en cualquier momento con q: lo decidido ya quedó guardado.
"""

from __future__ import annotations

from decimal import Decimal

from app.clasificar import cargar_categorias
from app.memoria import aplicar_decision, grupos_pendientes
from app.store import conectar

TIPOS = {
    "TRANSF_ENVIADA": "Transferencia enviada",
    "TRANSF_RECIBIDA": "Transferencia recibida",
    "QR": "Pago con QR",
    "PEDIDO": "Pedido",
    "SUSCRIPCION": "Suscripción",
    "PAGO": "Pago",
    "COMERCIO": "Comercio",
}


def _ar(valor: Decimal) -> str:
    signo = "-" if valor < 0 else ""
    entero, _, dec = f"{abs(valor):.2f}".partition(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return f"{signo}{'.'.join(grupos)},{dec}"


def main() -> int:
    with conectar() as conn:
        categorias = list(cargar_categorias(conn, para_modelo=False))
        grupos = grupos_pendientes(conn)
        if not grupos:
            print("No hay nada pendiente de revisión.")
            return 0

        menu = "\n".join(f"  {i:2}. {c}" for i, c in enumerate(categorias, start=1))
        total = sum(g["cantidad"] for g in grupos)
        print(f"{total} movimientos pendientes en {len(grupos)} contrapartes.")
        print("Una decisión resuelve el grupo entero y queda en memoria.\n")
        print(menu)

        resueltos = 0
        for n, g in enumerate(grupos, start=1):
            tipo, contraparte = g["clave"].split("|", 1)
            print(f"\n[{n}/{len(grupos)}] {TIPOS.get(tipo, tipo)} · {contraparte}")
            print(f"      {g['cantidad']} movimiento(s) · total $ {_ar(g['total'])} · "
                  f"{g['desde']:%d/%m} a {g['hasta']:%d/%m}")
            if g["devoluciones"]:
                print(f"      incluye {g['devoluciones']} devolución(es) unida(s) a su pago: "
                      f"se decide todo junto")
            for ejemplo in g["ejemplos"]:
                print(f"      · {ejemplo}")

            while True:
                try:
                    resp = input("  número de categoría · s saltear · ? ver lista · q salir: ")
                except EOFError:
                    resp = "q"
                resp = resp.strip().lower()

                if resp == "?":
                    print(menu)
                    continue
                if resp in {"s", ""}:
                    break
                if resp == "q":
                    print(f"\nListo por ahora: {resueltos} movimientos resueltos.")
                    return 0
                if resp.isdigit() and 1 <= int(resp) <= len(categorias):
                    categoria = categorias[int(resp) - 1]
                    cambiados = aplicar_decision(conn, g["clave"], categoria)
                    resueltos += cambiados
                    print(f"  ✓ {categoria}: {cambiados} movimiento(s), y queda en memoria.")
                    break
                print("  No entendí: un número de la lista, s, ? o q.")

        print(f"\nRevisión terminada: {resueltos} movimientos resueltos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
