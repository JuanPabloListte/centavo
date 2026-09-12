"""Generador de resúmenes sintéticos.

Existe por una razón práctica: sin un resumen real a mano, el pipeline no se
puede construir ni probar. Esto produce resúmenes que cierran por
construcción, con las dos formas de cierre y las dos formas de expresar el
importe que hay en la calle.

    python -m tools.generar_fixtures

Genera en tests/fixtures/:
    tarjeta_visa.csv        cierre por TOTAL,  importe en columna única
    cuenta_corriente.csv    cierre por SALDOS, columnas débito/crédito
    tarjeta_visa.pdf        el mismo resumen de tarjeta, en PDF con tabla

El PDF se arma como HTML y se imprime con Chrome headless. Sale un PDF con
capa de texto real —que es lo que pdfplumber necesita— sin agregar una
dependencia de Python sólo para fixtures.

IMPORTANTE: estos archivos prueban que el pipeline funciona. NO prueban que
funcione contra un banco real: la maquetación de un resumen de verdad es otra
cosa. Cuando tengas uno, agregá su Perfil y su fixture.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / "tests" / "fixtures"

SEMILLA = 20260901  # determinista: el mismo fixture en cada corrida

COMERCIOS = [
    "MERPAGO*KIOSCO LA ESQ", "SUPERMERCADO DIA 4821", "YPF FULL CBA CENTRO",
    "NETFLIX.COM", "SPOTIFY AB", "RAPPI ARG", "FARMACITY 0231",
    "MERPAGO*VERDULERIA DON", "EDESUR SA", "AYSA SERVICIOS",
    "UBER *TRIP", "MCDONALDS PATIO OLMOS", "LIBRERIA YENNY",
    "PEDIDOSYA", "CLARO AR PREPAGO", "MERPAGO*PANADERIA SANT",
    # A partir de acá, casos deliberadamente ambiguos. Son los que importan:
    # si todos los comercios son obvios, los agentes siempre coinciden y el
    # desacuerdo no mide nada.
    "COTO CICSA 0034", "DLO*SPOTIFY", "MERPAGO*LA ESQUINA",
    "SHELL SELECT RUTA 9", "STARBUCKS ALTO PALERMO", "CABIFY ARG",
    "AUTOPISTA AUSOL TELEPEAJE", "SUBE CARGA ONLINE", "DECATHLON ARG",
    "MERCADOLIBRE*COMPRA", "PAGOFACIL EDECOR", "OSDE 210 CUOTA MENSUAL",
    "GARBARINO 12 CUOTAS", "OPENAI *CHATGPT SUBSCR", "MUSIMUNDO ONLINE",
]

SUSCRIPCIONES = ["NETFLIX.COM", "SPOTIFY AB", "CLARO AR PREPAGO"]

# Verdad de referencia. Como los fixtures los genera este script, las etiquetas
# salen gratis: no hay que etiquetar a mano para tener un harness que corra.
#
# OJO con lo que esto mide: son comercios sintéticos, más limpios que los de un
# resumen real. El número que sale es una medida honesta de la CAÑERÍA, y una
# medida optimista de la TAREA. Se vuelve honesto del todo cuando entren
# movimientos reales etiquetados a mano.
CATEGORIA_DE = {
    "MERPAGO*KIOSCO LA ESQ":   "Supermercado y Almacén",
    "SUPERMERCADO DIA 4821":   "Supermercado y Almacén",
    "MERPAGO*VERDULERIA DON":  "Supermercado y Almacén",
    "MERPAGO*PANADERIA SANT":  "Supermercado y Almacén",
    "YPF FULL CBA CENTRO":     "Combustible",
    "NETFLIX.COM":             "Suscripciones",
    "SPOTIFY AB":              "Suscripciones",
    "CLARO AR PREPAGO":        "Telefonía e Internet",
    "RAPPI ARG":               "Gastronomía",
    "PEDIDOSYA":               "Gastronomía",
    "MCDONALDS PATIO OLMOS":   "Gastronomía",
    "FARMACITY 0231":          "Salud y Farmacia",
    "EDESUR SA":               "Servicios",
    "AYSA SERVICIOS":          "Servicios",
    "UBER *TRIP":              "Transporte",
    "LIBRERIA YENNY":          "Educación",
    "SU PAGO - GRACIAS":       "Pagos y Transferencias",
    # Ambiguos
    "COTO CICSA 0034":         "Supermercado y Almacén",
    "DLO*SPOTIFY":             "Suscripciones",
    "MERPAGO*LA ESQUINA":      "Supermercado y Almacén",
    "SHELL SELECT RUTA 9":     "Combustible",
    "STARBUCKS ALTO PALERMO":  "Gastronomía",
    "CABIFY ARG":              "Transporte",
    "AUTOPISTA AUSOL TELEPEAJE": "Transporte",
    "SUBE CARGA ONLINE":       "Transporte",
    "DECATHLON ARG":           "Indumentaria",
    "MERCADOLIBRE*COMPRA":     "Otros",
    "PAGOFACIL EDECOR":        "Servicios",
    "OSDE 210 CUOTA MENSUAL":  "Salud y Farmacia",
    "GARBARINO 12 CUOTAS":     "Hogar y Electro",
    "OPENAI *CHATGPT SUBSCR":  "Suscripciones",
    "MUSIMUNDO ONLINE":        "Hogar y Electro",
}

PREFIJO_CATEGORIA = {
    "MUSIMUNDO CUOTA": "Hogar y Electro",
}


def categoria_de(descripcion: str) -> str:
    if (c := CATEGORIA_DE.get(descripcion)) is not None:
        return c
    for prefijo, categoria in PREFIJO_CATEGORIA.items():
        if descripcion.startswith(prefijo):
            return categoria
    raise KeyError(f"sin etiqueta para {descripcion!r}: agregala a CATEGORIA_DE")


def _ar(valor: Decimal) -> str:
    """Decimal -> formato argentino: 1.234,56"""
    signo = "-" if valor < 0 else ""
    entero, _, dec = f"{abs(valor):.2f}".partition(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return f"{signo}{'.'.join(grupos)},{dec}"


def _movimientos(rng: random.Random, desde: date, cantidad: int):
    """Devuelve [(fecha, descripcion, monto)] con monto negativo = gasto."""
    salida = []

    # Suscripciones: mismo monto, mismo día del mes. Le dan al detector de la
    # fase 2 algo real que encontrar.
    for i, nombre in enumerate(SUSCRIPCIONES):
        monto = Decimal(rng.randrange(3_500, 15_000))
        salida.append((desde + timedelta(days=3 + i * 2), nombre, -monto))

    # Un plan de cuotas, que es muy argentino y la fase 2 tiene que detectar.
    plan_total = 12
    plan_cuota = Decimal(rng.randrange(20_000, 45_000))
    plan_n = rng.randrange(2, 9)
    salida.append(
        (desde + timedelta(days=9), f"MUSIMUNDO CUOTA {plan_n}/{plan_total}", -plan_cuota)
    )

    # Consumo suelto.
    while len(salida) < cantidad:
        dia = rng.randrange(0, 28)
        comercio = rng.choice(COMERCIOS)
        monto = Decimal(rng.randrange(800, 90_000))
        salida.append((desde + timedelta(days=dia), comercio, -monto))

    # Un pago / acreditación, para que haya un crédito y el signo se ejercite
    # en las dos direcciones.
    salida.append((desde + timedelta(days=25), "SU PAGO - GRACIAS", Decimal(rng.randrange(50_000, 200_000))))

    salida.sort(key=lambda m: m[0])
    return salida


# ---------------------------------------------------------------------------
# Tarjeta: cierre por TOTAL, importe en columna única
# ---------------------------------------------------------------------------

def generar_tarjeta_csv(desde: date, hasta: date, movs) -> str:
    total = sum((m[2] for m in movs), start=Decimal("0.00"))
    lineas = [
        "Banco Ejemplo S.A.",
        "Resumen de Tarjeta de Credito VISA",
        f"Periodo;{desde:%d/%m/%Y};{hasta:%d/%m/%Y}",
        f"Total a pagar;{_ar(total)}",
        "",
        "Fecha;Descripcion;Importe",
    ]
    lineas += [f"{f:%d/%m/%Y};{d};{_ar(m)}" for f, d, m in movs]
    lineas += ["", "Los importes expresados corresponden al periodo informado."]
    return "\n".join(lineas) + "\n"


def generar_tarjeta_html(desde: date, hasta: date, movs) -> str:
    total = sum((m[2] for m in movs), start=Decimal("0.00"))
    filas = "\n".join(
        f"<tr><td>{f:%d/%m/%Y}</td><td>{d}</td>"
        f"<td class='n'>{_ar(m)}</td></tr>"
        for f, d, m in movs
    )
    return f"""<!doctype html>
<html lang="es"><meta charset="utf-8">
<style>
  @page {{ size:A4; margin:16mm 14mm; }}
  body {{ font-family:"Segoe UI",Arial,sans-serif; font-size:10pt; color:#111; }}
  h1 {{ font-size:13pt; margin:0; }}
  h2 {{ font-size:11pt; margin:2px 0 14px; font-weight:600; }}
  .meta td {{ padding:2px 14px 2px 0; }}
  table.mov {{ width:100%; border-collapse:collapse; margin-top:16px; }}
  table.mov th, table.mov td {{ border:1px solid #999; padding:4px 7px; text-align:left; }}
  table.mov th {{ background:#eee; }}
  td.n, th.n {{ text-align:right; white-space:nowrap; }}
  .total {{ margin-top:16px; font-weight:700; font-size:11pt; }}
</style>
<h1>Banco Ejemplo S.A.</h1>
<h2>Resumen de Tarjeta de Credito VISA</h2>
<table class="meta">
  <tr><td>Periodo</td><td>{desde:%d/%m/%Y} a {hasta:%d/%m/%Y}</td></tr>
  <tr><td>Titular</td><td>MARIA LAURA PEREZ</td></tr>
</table>
<table class="mov">
  <thead><tr><th>Fecha</th><th>Descripcion</th><th class="n">Importe</th></tr></thead>
  <tbody>
{filas}
  </tbody>
</table>
<p class="total">Total a pagar {_ar(total)}</p>
</html>"""


# ---------------------------------------------------------------------------
# Cuenta corriente: cierre por SALDOS, columnas débito/crédito
# ---------------------------------------------------------------------------

def generar_cuenta_csv(desde: date, hasta: date, movs) -> str:
    saldo_inicial = Decimal("485000.00")
    neto = sum((m[2] for m in movs), start=Decimal("0.00"))
    saldo_final = saldo_inicial + neto

    lineas = [
        "Banco Ejemplo S.A.",
        "Cuenta Corriente en Pesos",
        f"Periodo;{desde:%d/%m/%Y};{hasta:%d/%m/%Y}",
        f"Saldo inicial;{_ar(saldo_inicial)}",
        f"Saldo final;{_ar(saldo_final)}",
        "",
        "Fecha;Descripcion;Debito;Credito",
    ]
    for f, d, m in movs:
        # El banco escribe los débitos en positivo en su propia columna.
        debito = _ar(abs(m)) if m < 0 else ""
        credito = _ar(m) if m > 0 else ""
        lineas.append(f"{f:%d/%m/%Y};{d};{debito};{credito}")
    return "\n".join(lineas) + "\n"


# ---------------------------------------------------------------------------
# HTML -> PDF con Chrome headless
# ---------------------------------------------------------------------------

CANDIDATOS_CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def _buscar_chrome() -> str | None:
    for c in CANDIDATOS_CHROME:
        if Path(c).exists():
            return c
    return shutil.which("chrome") or shutil.which("chromium") or shutil.which("google-chrome")


def html_a_pdf(html: str, destino: Path) -> bool:
    chrome = _buscar_chrome()
    if not chrome:
        print("  ! Chrome no encontrado: me salteo el PDF.", file=sys.stderr)
        print("    El CSV alcanza para probar el pipeline; el PDF ejercita el "
              "parser de tablas.", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmp:
        origen = Path(tmp) / "resumen.html"
        origen.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                chrome, "--headless=new", "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={destino}",
                origen.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    return destino.exists()


def main() -> int:
    rng = random.Random(SEMILLA)
    desde = date(2026, 8, 1)
    hasta = date(2026, 8, 31)
    movs = _movimientos(rng, desde, cantidad=44)

    FIXTURES.mkdir(parents=True, exist_ok=True)

    tarjeta = FIXTURES / "tarjeta_visa.csv"
    tarjeta.write_text(generar_tarjeta_csv(desde, hasta, movs), encoding="utf-8")
    print(f"  + {tarjeta.relative_to(RAIZ)}  ({len(movs)} movimientos, cierre por total)")

    cuenta = FIXTURES / "cuenta_corriente.csv"
    cuenta.write_text(generar_cuenta_csv(desde, hasta, movs), encoding="utf-8")
    print(f"  + {cuenta.relative_to(RAIZ)}  ({len(movs)} movimientos, cierre por saldos)")

    etiquetas = FIXTURES / "etiquetas.json"
    vistas = {d: categoria_de(d) for _, d, _ in movs}
    etiquetas.write_text(
        json.dumps(
            [{"descripcion": d, "categoria": c} for d, c in sorted(vistas.items())],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  + {etiquetas.relative_to(RAIZ)}  ({len(vistas)} descripciones etiquetadas)")

    pdf = FIXTURES / "tarjeta_visa.pdf"
    if html_a_pdf(generar_tarjeta_html(desde, hasta, movs), pdf):
        print(f"  + {pdf.relative_to(RAIZ)}  (mismo resumen, tabla en PDF)")

    from .resumen_mp_sintetico import generar as generar_resumen_mp

    resumen_mp = FIXTURES / "resumen_mp.pdf"
    if generar_resumen_mp(resumen_mp, html_a_pdf):
        print(f"  + {resumen_mp.relative_to(RAIZ)}  (maquetación de Mercado Pago: "
              f"descripciones partidas, saldo por renglón)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
