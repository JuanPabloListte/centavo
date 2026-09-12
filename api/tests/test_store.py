"""Idempotencia de la persistencia, contra un esquema temporal.

La motivó un hallazgo en resúmenes reales: la devolución de un pago trae el
mismo ID de operación que el pago, a veces otro día y por otro monto. El ID
identifica la operación, no el movimiento.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.pipeline import procesar
from app.store import SuperposicionParcial, YaIngerido, guardar

RESUMEN_MP = Path(__file__).parent / "fixtures" / "resumen_mp.pdf"
MIGRACION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migraciones" / "001_identidad_del_movimiento.sql"
)


@pytest.fixture(scope="module")
def sintetico():
    return procesar(RESUMEN_MP)


def _primer_pago(resumen):
    return next(m for m in resumen.movimientos if m.monto < 0 and m.id_operacion)


def _devolucion(pago, **cambios):
    datos = {
        "monto": -pago.monto,
        "descripcion_cruda": f"Devolución de dinero {pago.descripcion_cruda}",
        "linea_origen": 990_001,
    }
    return pago.model_copy(update=datos | cambios)


def _variante(resumen, sha: str, movimientos, **cambios):
    return resumen.model_copy(
        update={"sha256": sha * 64, "movimientos": movimientos} | cambios
    )


def _cantidad(db, statement_id) -> int:
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM transactions WHERE statement_id = %s", (statement_id,))
        return cur.fetchone()[0]


def test_un_pago_y_su_devolucion_comparten_id_y_se_guardan_los_dos(db, sintetico):
    resumen, resultado = sintetico
    movimientos = [*resumen.movimientos, _devolucion(_primer_pago(resumen))]

    sid = guardar(_variante(resumen, "a", movimientos), resultado, conn=db)

    assert _cantidad(db, sid) == len(resumen.movimientos) + 1


def test_el_mismo_mes_redescargado_con_devoluciones_es_ya_ingerido(db, sintetico):
    resumen, resultado = sintetico
    movimientos = [*resumen.movimientos, _devolucion(_primer_pago(resumen))]
    guardar(_variante(resumen, "a", movimientos), resultado, conn=db)

    with pytest.raises(YaIngerido):
        guardar(_variante(resumen, "b", movimientos), resultado, conn=db)


def test_una_devolucion_que_cae_en_el_mes_siguiente_no_es_superposicion(db, sintetico):
    resumen, resultado = sintetico
    guardar(resumen, resultado, conn=db)

    desde = resumen.periodo_hasta + timedelta(days=1)
    devolucion = _devolucion(
        _primer_pago(resumen), fecha=desde + timedelta(days=2), monto=Decimal("1000.00")
    )
    siguiente = _variante(
        resumen, "c", [devolucion],
        periodo_desde=desde, periodo_hasta=desde + timedelta(days=29),
    )

    assert _cantidad(db, guardar(siguiente, resultado, conn=db)) == 1


def test_un_resumen_que_repite_parte_de_otro_se_rechaza_entero(db, sintetico):
    resumen, resultado = sintetico
    guardar(resumen, resultado, conn=db)

    mitad = resumen.movimientos[: len(resumen.movimientos) // 2]
    nuevo = mitad[0].model_copy(update={"id_operacion": "999999999999", "linea_origen": 990_002})

    with pytest.raises(SuperposicionParcial):
        guardar(_variante(resumen, "d", [*mitad, nuevo]), resultado, conn=db)


def test_dos_movimientos_identicos_en_un_archivo_se_numeran(db, sintetico):
    resumen, resultado = sintetico
    original = next(m for m in resumen.movimientos if m.id_operacion)
    movimientos = [*resumen.movimientos, original.model_copy(update={"linea_origen": 990_003})]

    sid = guardar(_variante(resumen, "e", movimientos), resultado, conn=db)

    assert _cantidad(db, sid) == len(movimientos)
    with pytest.raises(YaIngerido):
        guardar(_variante(resumen, "f", movimientos), resultado, conn=db)


def test_la_migracion_lleva_una_base_vieja_a_la_identidad_nueva_y_se_puede_repetir(db, sintetico):
    with db.cursor() as cur:
        cur.execute("SELECT current_schema()")
        esquema = cur.fetchone()[0]
        # Sólo el esquema temporal en el search_path: en public están tus datos.
        cur.execute(f"SET search_path TO {esquema}")

        # La base como estaba antes del cambio.
        cur.execute("DROP INDEX transactions_identidad_uq")
        cur.execute("ALTER TABLE transactions DROP COLUMN repeticion")
        cur.execute(
            "CREATE UNIQUE INDEX transactions_fuente_operacion_uq "
            "ON transactions (fuente, id_operacion) WHERE id_operacion IS NOT NULL"
        )

        migracion = MIGRACION.read_text(encoding="utf-8")
        cur.execute(migracion)
        cur.execute(migracion)

        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = %s AND tablename = 'transactions'",
            (esquema,),
        )
        indices = {fila[0] for fila in cur.fetchall()}

    assert "transactions_identidad_uq" in indices
    assert "transactions_fuente_operacion_uq" not in indices

    resumen, resultado = sintetico
    movimientos = [*resumen.movimientos, _devolucion(_primer_pago(resumen))]
    sid = guardar(_variante(resumen, "a", movimientos), resultado, conn=db)
    assert _cantidad(db, sid) == len(movimientos)
