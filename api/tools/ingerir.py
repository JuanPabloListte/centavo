"""Ingerir un resumen de punta a punta.

    python -m tools.ingerir ruta/al/resumen.pdf
    python -m tools.ingerir ruta/al/resumen.pdf --con-modelo

Parsea, verifica la compuerta, guarda y clasifica lo que se resuelve sin
modelo: la memoria y la evidencia. Con --con-modelo, lo que queda pasa por la
flota (dos agentes + supervisor), que en una notebook tarda minutos.

Deja una fila en `corridas` con cómo terminó y cuánto costó (`tools.corridas`).

Imprime conteos, nunca movimientos: el resumen tiene datos de terceros.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import psycopg

from app.clasificar import cargar_categorias, construir
from app.corridas import Corrida, conteo_del_resumen
from app.memoria import cargar_memoria, clasificar_pendientes, grupos_pendientes
from app.pipeline import procesar
from app.store import SuperposicionParcial, YaIngerido, conectar, guardar

VIAS = {
    "regla": "por tu memoria",
    "evidencia": "por evidencia en el texto",
    "consenso": "por consenso de los agentes",
    "modelo": "por el modelo",
    "needs_review": "a revisión",
    "sin_procesar": "sin resolver (para revisar)",
}


def devoluciones_unidas(conn: psycopg.Connection, statement_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM transactions WHERE statement_id = %s AND devuelve_a IS NOT NULL",
            (statement_id,),
        )
        return cur.fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingerir un resumen")
    ap.add_argument("archivo")
    ap.add_argument("--con-modelo", action="store_true",
                    help="clasificar con la flota lo que no resuelven memoria ni evidencia")
    args = ap.parse_args()

    corrida = Corrida("terminal")
    with conectar() as conn:
        try:
            resumen, resultado = procesar(Path(args.archivo))
        except Exception as exc:
            corrida.guardar(conn, "error", error=exc)
            raise
        print(f"  {resumen.banco} · {resumen.periodo_desde} a {resumen.periodo_hasta}")
        print(f"  {resultado.explicar()}")

        ya_estaba = False
        try:
            statement_id = guardar(resumen, resultado, conn=conn)
            print(f"  guardado como resumen {statement_id}")
            if unidas := devoluciones_unidas(conn, statement_id):
                print(f"  {unidas} devolución(es) unida(s) a su pago")
        except YaIngerido as exc:
            statement_id, ya_estaba = exc.statement_id, True
            print(f"  {exc}: no se guarda de nuevo")
        except SuperposicionParcial as exc:
            corrida.guardar(conn, "superposicion")
            print(f"  ! {exc}")
            return 1

        if not resultado.cuadra:
            corrida.guardar(conn, "descuadrado", statement_id=statement_id)
            print("  ! no cuadra: queda guardado como descuadrado y no se clasifica")
            return 1

        clasificador = None
        if args.con_modelo:
            clasificador = construir(
                "flota",
                categorias=cargar_categorias(conn),
                reglas=cargar_memoria(conn),
            )
        cliente = getattr(clasificador, "cliente", None)

        try:
            clasificar_pendientes(conn, clasificador)
        except Exception as exc:
            corrida.guardar(conn, "error", statement_id=statement_id, cliente=cliente, error=exc)
            raise
        numero = corrida.guardar(
            conn, "ya_ingerido" if ya_estaba else "cuadrado",
            statement_id=statement_id, cliente=cliente,
        )

        print("  este resumen:")
        for via, n in conteo_del_resumen(conn, statement_id).items():
            print(f"    {n:4}  {VIAS.get(via, via)}")

        grupos = grupos_pendientes(conn)
        pendientes = sum(g["cantidad"] for g in grupos)
        print(f"  para revisar, sumando todos los resúmenes: {pendientes} movimientos en "
              f"{len(grupos)} contrapartes"
              f"{'  ->  python -m tools.revisar' if grupos else ''}")
        print(f"  corrida {numero} registrada  ->  python -m tools.corridas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
