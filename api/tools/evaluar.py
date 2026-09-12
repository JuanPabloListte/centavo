"""Harness de evaluación de la fase 1.

    python -m tools.evaluar                       # modelo por defecto
    python -m tools.evaluar --modelo gemma3:latest
    python -m tools.evaluar --umbral 0.6

Corre el clasificador sobre las descripciones etiquetadas y saca un scorecard.

Las tres métricas se leen JUNTAS, y ese es el punto:

  acierto    sobre los movimientos que resolvió
  cobertura  qué porcentaje resolvió en vez de mandar a revisión
  costo      tokens y segundos por movimiento

Un sistema que resuelve el 100% con 80% de acierto es PEOR que uno que
resuelve el 70% con 99% y pregunta el resto. Por eso el acierto solo no
significa nada sin la cobertura al lado.

Los resultados se guardan en tools/resultados/ para poder comparar corridas:
cambiar un prompt y no poder decir si mejoró es no tener harness.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.clasificar import cargar_categorias, cargar_reglas, construir
from app.llm import ClienteLLM, ping
from app.store import conectar

RAIZ = Path(__file__).resolve().parents[1]
ETIQUETAS = RAIZ / "tests" / "fixtures" / "etiquetas.json"
RESULTADOS = Path(__file__).parent / "resultados"


def cargar_etiquetas() -> list[dict]:
    if not ETIQUETAS.exists():
        print(
            f"No hay etiquetas en {ETIQUETAS}.\n"
            f"Corré: python -m tools.generar_fixtures",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return json.loads(ETIQUETAS.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Scorecard del clasificador")
    ap.add_argument("--modelo", default=None, help="tag de Ollama; default: el de .env")
    ap.add_argument("--umbral", type=float, default=None, help="confianza mínima para resolver")
    ap.add_argument("--limite", type=int, default=None, help="evaluar sólo N casos")
    ap.add_argument("--modo", choices=["solo", "flota"], default="solo",
                    help="solo = un agente; flota = dos agentes + supervisor")
    args = ap.parse_args()

    cliente = ClienteLLM(modelo=args.modelo) if args.modelo else ClienteLLM()

    ok, detalle = ping()
    if not ok and not args.modelo:
        print(f"  ! {detalle}", file=sys.stderr)
        return 2

    casos = cargar_etiquetas()
    if args.limite:
        casos = casos[: args.limite]

    with conectar() as conn:
        categorias = cargar_categorias(conn)
        reglas = cargar_reglas(conn)

    clas = construir(
        args.modo,
        categorias=categorias,
        reglas=reglas,
        cliente=cliente,
        **({"umbral": args.umbral} if args.umbral is not None else {}),
    )

    print(f"  modo     {args.modo}")
    print(f"  modelo   {cliente.modelo}")
    print(f"  umbral   {clas.umbral}")
    print(f"  memoria  {len(reglas)} contrapartes ya decididas por vos")
    print(f"  casos    {len(casos)}\n")

    filas = []
    errores = []
    for i, caso in enumerate(casos, start=1):
        desc, esperada = caso["descripcion"], caso["categoria"]
        try:
            r = clas.clasificar(desc, Decimal("-1000"))
        except Exception as exc:
            errores.append({"descripcion": desc, "error": f"{type(exc).__name__}: {exc}"})
            print(f"  {i:3}/{len(casos)}  ERROR  {desc[:34]:34}  {type(exc).__name__}")
            continue

        acerto = r.categoria == esperada
        filas.append(
            {
                "descripcion": desc,
                "esperada": esperada,
                "obtenida": r.categoria,
                "confianza": round(r.confianza, 2),
                "via": r.via,
                "estado": r.estado,
                "acerto": acerto,
                "comercio": r.comercio,
                "acuerdo": r.acuerdo,
                "opiniones": r.opiniones,
                "motivo": r.motivo,
            }
        )

        marca = "ok " if acerto else "MAL"
        rev = "" if r.estado == "resuelto" else "  -> a revisión"
        print(
            f"  {i:3}/{len(casos)}  {marca}  {desc[:34]:34}  "
            f"{r.categoria:24} "
            f"{r.confianza:.2f}{rev}"
        )

    resueltos = [f for f in filas if f["estado"] == "resuelto"]
    revision = [f for f in filas if f["estado"] == "needs_review"]
    aciertos_resueltos = sum(1 for f in resueltos if f["acerto"])
    aciertos_totales = sum(1 for f in filas if f["acerto"])

    uso = cliente.uso
    n = max(len(filas), 1)

    # --- ¿qué predice mejor el error: la confianza o el desacuerdo? ---------
    # Es la pregunta que dejó abierta la fase 1 y la razón de ser del abanico.
    def _tasa_error(sub):
        return round(sum(1 for f in sub if not f["acerto"]) / len(sub), 3) if sub else None

    con_acuerdo    = [f for f in filas if f["acuerdo"] is True]
    con_desacuerdo = [f for f in filas if f["acuerdo"] is False]
    conf_alta = [f for f in filas if f["confianza"] >= clas.umbral]
    conf_baja = [f for f in filas if f["confianza"] < clas.umbral]

    senal = {
        "error_si_acuerdo":     _tasa_error(con_acuerdo),
        "error_si_desacuerdo":  _tasa_error(con_desacuerdo),
        "n_acuerdo":            len(con_acuerdo),
        "n_desacuerdo":         len(con_desacuerdo),
        "error_si_conf_alta":   _tasa_error(conf_alta),
        "error_si_conf_baja":   _tasa_error(conf_baja),
        "n_conf_alta":          len(conf_alta),
        "n_conf_baja":          len(conf_baja),
    }

    scorecard = {
        "cuando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "modo": args.modo,
        "senal": senal,
        "modelo": cliente.modelo,
        "umbral": clas.umbral,
        "casos": len(casos),
        "errores": len(errores),
        "acierto_sobre_resueltos": round(aciertos_resueltos / max(len(resueltos), 1), 3),
        "acierto_sobre_todo": round(aciertos_totales / n, 3),
        "cobertura": round(len(resueltos) / n, 3),
        "a_revision": len(revision),
        "via_regla": sum(1 for f in filas if f["via"] == "regla"),
        "llamadas_modelo": uso.llamadas,
        "reparaciones": uso.reparaciones,
        "tokens_entrada": uso.tokens_entrada,
        "tokens_salida": uso.tokens_salida,
        "segundos_total": round(uso.segundos, 1),
        "segundos_por_caso": round(uso.segundos / n, 2),
    }

    print("\n  " + "-" * 58)
    print(f"  acierto sobre resueltos   {scorecard['acierto_sobre_resueltos']:.1%}"
          f"   ({aciertos_resueltos}/{len(resueltos)})")
    print(f"  cobertura                 {scorecard['cobertura']:.1%}"
          f"   ({len(resueltos)} resueltos, {len(revision)} a revisión)")
    print(f"  acierto sobre todo        {scorecard['acierto_sobre_todo']:.1%}")
    print(f"  resuelto sin modelo       {scorecard['via_regla']}   (reglas deterministas)")
    print(f"  reparaciones de JSON      {uso.reparaciones}   en {uso.llamadas} llamadas")
    print(f"  costo                     {uso.tokens_entrada + uso.tokens_salida} tokens, "
          f"{scorecard['segundos_por_caso']}s por movimiento")

    if senal["n_desacuerdo"] is not None and (senal["n_acuerdo"] or senal["n_desacuerdo"]):
        print("  " + "-" * 58)
        print("  ¿QUÉ PREDICE EL ERROR?      tasa de error   n")
        def _fmt(v):
            return "   --  " if v is None else f"{v:6.1%}"
        print(f"    agentes de acuerdo       {_fmt(senal['error_si_acuerdo'])}   {senal['n_acuerdo']}")
        print(f"    agentes en desacuerdo    {_fmt(senal['error_si_desacuerdo'])}   {senal['n_desacuerdo']}")
        print(f"    confianza alta           {_fmt(senal['error_si_conf_alta'])}   {senal['n_conf_alta']}")
        print(f"    confianza baja           {_fmt(senal['error_si_conf_baja'])}   {senal['n_conf_baja']}")
    if errores:
        print(f"  ERRORES                   {len(errores)}")
    print("  " + "-" * 58)

    RESULTADOS.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = cliente.modelo.replace(":", "_").replace("/", "_")
    destino = RESULTADOS / f"{marca}_{args.modo}_{slug}.json"
    destino.write_text(
        json.dumps(
            {"scorecard": scorecard, "detalle": filas, "errores": errores},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  -> {destino.relative_to(RAIZ)}")

    fallados = [f for f in filas if not f["acerto"]]
    if fallados:
        print("\n  Falló en:")
        for f in fallados:
            print(f"    {f['descripcion'][:34]:34} esperaba {f['esperada']:24} dijo {f['obtenida']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
