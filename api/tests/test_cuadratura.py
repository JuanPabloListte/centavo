"""El único test que define si la fase 0 está terminada.

Recorre `fixtures/`, corre el pipeline completo sobre cada archivo y exige que
la suma de los movimientos coincida al centavo con lo que el resumen declara
—un total, o la diferencia entre saldo final e inicial, según cómo cierre.

Cuando falla, el mensaje dice el número. Un `assert False` pelado no permite
depurar un parser.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.balance import verificar_cuadratura
from app.models import CierrePorSaldos, CierrePorTotal, Movimiento, Resumen
from app.pipeline import procesar

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# La compuerta en sí, sin depender de ningún parser.
# ---------------------------------------------------------------------------

def _resumen(montos: list[str], cierre=None) -> Resumen:
    movs = [
        Movimiento(
            fecha=date(2026, 8, 1),
            monto=Decimal(m),
            moneda="ARS",
            descripcion_cruda=f"MOV {i}",
            linea_origen=i,
        )
        for i, m in enumerate(montos, start=1)
    ]
    if cierre is None:
        cierre = CierrePorTotal(
            total_declarado=sum((x.monto for x in movs), start=Decimal("0.00"))
        )
    return Resumen(
        banco="test",
        archivo="sintetico.csv",
        sha256="0" * 64,
        periodo_desde=date(2026, 8, 1),
        periodo_hasta=date(2026, 8, 31),
        cierre=cierre,
        movimientos=movs,
    )


def test_compuerta_acepta_cierre_por_total():
    r = verificar_cuadratura(_resumen(["-1500.50", "-320.00", "45000.00"]))
    assert r.cuadra, r.explicar()
    assert r.tipo_cierre == "total"
    assert r.diferencia == Decimal("0.00")


def test_compuerta_acepta_cierre_por_saldos():
    # -1820.50 de neto sobre un saldo inicial de 10000 deja 8179.50
    resumen = _resumen(
        ["-1500.50", "-320.00"],
        cierre=CierrePorSaldos(
            saldo_inicial=Decimal("10000.00"),
            saldo_final=Decimal("8179.50"),
        ),
    )
    r = verificar_cuadratura(resumen)
    assert r.cuadra, r.explicar()
    assert r.tipo_cierre == "saldos"


def test_compuerta_rechaza_por_un_centavo():
    resumen = _resumen(["-1500.50", "-320.00"])
    resumen.cierre.total_declarado += Decimal("0.01")

    r = verificar_cuadratura(resumen)
    assert not r.cuadra
    assert r.diferencia == Decimal("0.01")
    assert "NO cuadra" in r.explicar()


# ---------------------------------------------------------------------------
# El pipeline completo sobre archivos.
# ---------------------------------------------------------------------------

def _archivos_fixture() -> list[Path]:
    if not FIXTURES.exists():
        return []
    return sorted(
        p for p in FIXTURES.iterdir()
        if p.suffix.lower() in {".csv", ".pdf", ".xlsx"}
    )


@pytest.mark.parametrize("archivo", _archivos_fixture(), ids=lambda p: p.name)
def test_resumen_cuadra(archivo: Path):
    resumen, resultado = procesar(archivo)
    assert resultado.cuadra, f"{archivo.name}: {resultado.explicar()}"
    assert resumen.movimientos, f"{archivo.name}: no se extrajo ningún movimiento"


def test_hay_fixtures_de_los_dos_tipos_de_cierre():
    """La fase 0 no está terminada sin ejercitar las dos formas de cierre."""
    tipos = set()
    for archivo in _archivos_fixture():
        resumen, _ = procesar(archivo)
        tipos.add(resumen.cierre.tipo)

    assert tipos == {"total", "saldos"}, (
        f"Faltan fixtures. Tipos de cierre cubiertos: {tipos or 'ninguno'}. "
        "Corré `python -m tools.generar_fixtures` para generarlos."
    )
