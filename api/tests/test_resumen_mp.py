"""Tests del parser por coordenadas.

Sobre el resumen sintético con maquetación de Mercado Pago —versionable— y, si
está disponible, sobre un resumen real.

El sintético se compara contra los datos exactos que lo generaron: cada
descripción partida tiene que volver a armarse palabra por palabra. El real no
se versiona (tiene CVU, CUIT y nombres de terceros): su test corre sólo si
CENTAVO_RESUMEN_REAL apunta a un archivo, y verifica invariantes estructurales,
nunca contenido.
"""

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.balance import verificar_cuadratura
from app.parsers.pdf_coordenadas import parse_periodo_texto
from app.pipeline import procesar
from tools import resumen_mp_sintetico as sint

FIXTURE = Path(__file__).parent / "fixtures" / "resumen_mp.pdf"


@pytest.fixture(scope="module")
def procesado():
    if not FIXTURE.exists():
        pytest.fail(
            "Falta tests/fixtures/resumen_mp.pdf. Corré: python -m tools.generar_fixtures"
        )
    return procesar(FIXTURE)


def test_cuadra_por_saldos_y_encadena_renglon_por_renglon(procesado):
    _, r = procesado
    assert r.cuadra, r.explicar()
    assert r.tipo_cierre == "saldos"
    assert r.cadena_verificada, "trae saldo por renglón: la cadena tiene que verificarse"


def test_rearma_cada_descripcion_partida_palabra_por_palabra(procesado):
    """El test que importa. Cubre de una vez las descripciones de dos y tres
    renglones, el pie que no se tiene que pegar al último movimiento, el
    encabezado repetido en cada página y el anexo que se tiene que ignorar."""
    resumen, _ = procesado
    leidas = [m.descripcion_cruda for m in resumen.movimientos]
    esperadas = [d for _, d, _ in sint.MOVIMIENTOS]

    assert len(leidas) == len(esperadas), (
        f"leyó {len(leidas)} movimientos y el resumen tiene {len(esperadas)}"
    )
    for i, (leida, esperada) in enumerate(zip(leidas, esperadas)):
        assert leida == esperada, f"movimiento {i}: leyó {leida!r}, era {esperada!r}"


def test_trae_id_y_saldo_de_cada_movimiento(procesado):
    resumen, _ = procesado
    assert [m.id_operacion for m in resumen.movimientos] == sint.ids()
    assert [m.saldo for m in resumen.movimientos] == [s for *_, s in sint.filas()]


def test_lee_titular_y_periodo(procesado):
    resumen, _ = procesado
    assert resumen.titular == sint.TITULAR
    assert (resumen.periodo_desde, resumen.periodo_hasta) == sint.PERIODO


def test_un_saldo_mal_leido_senala_la_linea_exacta(procesado):
    """Por qué el control renglón por renglón vale más que el del período."""
    resumen, _ = procesado
    roto = resumen.model_copy(deep=True)
    victima = roto.movimientos[7]
    victima.saldo += Decimal("0.01")

    r = verificar_cuadratura(roto)

    assert not r.cuadra
    assert r.eslabon_roto == victima.linea_origen
    assert r.diferencia == 0, "el período sigue cuadrando: sólo la cadena detecta el error"
    assert str(victima.linea_origen) in r.explicar()


@pytest.mark.parametrize("texto, esperado", [
    ("Periodo: Del 1 al 31 de agosto de 2026",
     (date(2026, 8, 1), date(2026, 8, 31))),
    ("Periodo: Del 15 de julio al 14 de agosto de 2026",
     (date(2026, 7, 15), date(2026, 8, 14))),
    ("Periodo: Del 20 de diciembre al 19 de enero de 2027",
     (date(2026, 12, 20), date(2027, 1, 19))),
    ("Periodo: Del 1 al 30 de setiembre de 2026",
     (date(2026, 9, 1), date(2026, 9, 30))),
])
def test_periodo_en_castellano(texto, esperado):
    assert parse_periodo_texto(texto) == esperado


def test_periodo_ilegible_devuelve_none():
    assert parse_periodo_texto("Periodo: agosto 2026") is None


def _hay_chrome() -> bool:
    from tools.generar_fixtures import _buscar_chrome
    return _buscar_chrome() is not None


@pytest.mark.skipif(not _hay_chrome(), reason="hace falta Chrome para generar el PDF")
def test_tabla_no_soportada_con_filas_falla_fuerte(tmp_path):
    """Una tabla con columnas de cotización leída como si fuera la de pesos
    daría basura con cara de dato. Vacía se ignora; con filas, error."""
    from tools.generar_fixtures import html_a_pdf

    destino = tmp_path / "anexo_con_filas.pdf"
    assert sint.generar(destino, html_a_pdf, anexo_con_filas=True)

    with pytest.raises(ValueError, match="no soportadas"):
        procesar(destino)


# ---------------------------------------------------------------------------
# Resumen real — nunca versionado
# ---------------------------------------------------------------------------

REAL = os.getenv("CENTAVO_RESUMEN_REAL")
TIPOS_MERCADO_PAGO = {"Transferencia", "Pago", "Rendimientos", "Dinero", "Pedido"}


@pytest.mark.skipif(
    not REAL or not Path(REAL).exists(),
    reason="sin resumen real: definí CENTAVO_RESUMEN_REAL con la ruta al PDF",
)
def test_resumen_real_cuadra_encadena_y_se_rearma():
    resumen, r = procesar(Path(REAL))

    assert r.cuadra, r.explicar()
    assert r.cadena_verificada

    ids = [m.id_operacion for m in resumen.movimientos]
    assert all(ids) and len(set(ids)) == len(ids), "cada operación tiene que traer un ID único"

    iniciales = {m.descripcion_cruda.split()[0] for m in resumen.movimientos}
    assert iniciales <= TIPOS_MERCADO_PAGO, (
        f"hay descripciones que empiezan con {sorted(iniciales - TIPOS_MERCADO_PAGO)}. "
        "O Mercado Pago agregó un tipo de movimiento, o un fragmento quedó asignado "
        "al movimiento equivocado: fijate cuál de las dos antes de tocar la lista."
    )
