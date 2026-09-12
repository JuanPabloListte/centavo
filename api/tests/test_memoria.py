"""Tests de la memoria de la fase 3.

Dos partes:

- La clave de memoria, sin base de datos.
- Aplicar decisiones y clasificar pendientes, contra Postgres. Cada test crea
  su propio esquema temporal y lo borra al terminar: nunca toca tus datos. Si
  Postgres no está disponible, esos tests se saltean.
"""

import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from app.agents.patrones import clave_memoria
from app.memoria import (
    aplicar_decision,
    cargar_memoria,
    clasificar_pendientes,
    grupos_pendientes,
)
from app.pipeline import procesar
from app.store import DATABASE_URL, guardar

ESQUEMA_SQL = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
RESUMEN_MP = Path(__file__).parent / "fixtures" / "resumen_mp.pdf"


# ---------------------------------------------------------------------------
# Clave de memoria
# ---------------------------------------------------------------------------

def test_mismo_comercio_con_distinta_cantidad_de_productos_es_la_misma_clave():
    assert clave_memoria("Pedido de 3 productos Sushi Ejemplo") == \
           clave_memoria("Pedido de 2 productos Sushi Ejemplo")


def test_el_codigo_de_sucursal_no_cuenta():
    assert clave_memoria("SUPERMERCADO DIA 4821") == clave_memoria("SUPERMERCADO DIA 0911")


def test_el_prefijo_del_medio_de_pago_no_cuenta():
    assert clave_memoria("MERPAGO*KIOSCO LA ESQ") == clave_memoria("KIOSCO LA ESQ")


def test_la_direccion_de_la_transferencia_es_parte_de_la_clave():
    """Mandarle plata a alguien y recibirla de esa persona pueden ser cosas distintas."""
    assert clave_memoria("Transferencia enviada Gomez Ana") != \
           clave_memoria("Transferencia recibida Gomez Ana")


def test_la_misma_persona_con_el_nombre_reordenado_es_la_misma_clave():
    assert clave_memoria("Transferencia enviada GOMEZ ANA LAURA") == \
           clave_memoria("Transferencia enviada Ana Laura Gómez")


def test_el_mismo_apellido_con_otro_nombre_es_otra_clave():
    """El caso peligroso: nunca se mezclan dos personas por parecido."""
    assert clave_memoria("Transferencia enviada Perez Carlos Alberto") != \
           clave_memoria("Transferencia enviada Perez Maria Laura")


def test_un_nombre_truncado_es_otra_clave():
    """Ante la duda, se pregunta: no se supone que es la misma persona."""
    assert clave_memoria("Transferencia enviada PEREZ MARIA LAU") != \
           clave_memoria("Transferencia enviada PEREZ MARIA LAURA")


@pytest.mark.parametrize("descripcion, tipo", [
    ("Transferencia enviada Gomez Ana", "TRANSF_ENVIADA"),
    ("Transferencia recibida Gomez Ana", "TRANSF_RECIBIDA"),
    ("Pago con QR Farmacia del Centro", "QR"),
    ("Pedido de 2 productos Pizzería", "PEDIDO"),
    ("Pago de suscripción Música Ejemplo", "SUSCRIPCION"),
    ("Pago SUBE Viajes", "PAGO"),
    ("NETFLIX.COM", "COMERCIO"),
])
def test_tipo_de_clave(descripcion, tipo):
    assert clave_memoria(descripcion).split("|", 1)[0] == tipo


# ---------------------------------------------------------------------------
# Contra Postgres, en un esquema temporal
# ---------------------------------------------------------------------------

# El fixture `db` —esquema temporal en Postgres— vive en conftest.py.


@pytest.fixture
def cargado(db):
    """El resumen sintético guardado y clasificado sin modelo."""
    resumen, resultado = procesar(RESUMEN_MP)
    guardar(resumen, resultado, conn=db)
    return resumen, resultado, clasificar_pendientes(db)


def _contar(db, sql: str, *args) -> int:
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def test_sin_memoria_se_resuelve_solo_la_evidencia(cargado):
    _, _, conteo = cargado
    # 6 rendimientos + 2 de reserva + 1 transferencia a la propia titular
    assert conteo == {"evidencia": 9, "sin_procesar": 23}


def test_la_revision_agrupa_por_contraparte(cargado, db):
    grupos = {g["clave"]: g["cantidad"] for g in grupos_pendientes(db)}
    assert grupos[clave_memoria("Pago SUBE Viajes")] == 4
    assert grupos[clave_memoria("Transferencia enviada Perez Carlos Alberto")] == 2
    assert sum(grupos.values()) == 23


def test_una_decision_resuelve_el_grupo_entero_y_deja_correcciones(cargado, db):
    clave = clave_memoria("Pago SUBE Viajes")

    cambiados = aplicar_decision(db, clave, "Transporte")

    assert cambiados == 4
    assert _contar(db, "SELECT count(*) FROM correcciones WHERE clave = %s", clave) == 4
    assert _contar(db, """
        SELECT count(*) FROM transactions
        WHERE clave = %s AND estado_clasificacion = 'resuelto' AND via = 'regla'
    """, clave) == 4
    assert cargar_memoria(db) == {clave: "Transporte"}


def test_decidir_lo_mismo_otra_vez_no_cambia_nada_pero_confirma(cargado, db):
    clave = clave_memoria("Pago SUBE Viajes")
    aplicar_decision(db, clave, "Transporte")

    assert aplicar_decision(db, clave, "Transporte") == 0
    assert _contar(db, "SELECT confirmaciones FROM memoria WHERE clave = %s", clave) == 2
    assert _contar(db, "SELECT count(*) FROM correcciones WHERE clave = %s", clave) == 4


def test_decidir_sobre_un_familiar_no_toca_a_otra_persona_con_el_mismo_apellido(cargado, db):
    aplicar_decision(db, clave_memoria("Transferencia enviada Perez Carlos Alberto"), "Otros")

    otra = clave_memoria("Transferencia enviada Gomez Ana")
    assert _contar(db, """
        SELECT count(*) FROM transactions
        WHERE clave = %s AND estado_clasificacion = 'sin_procesar'
    """, otra) == 1
    # La transferencia a la propia titular ya estaba resuelta por evidencia y sigue igual.
    assert _contar(db, """
        SELECT count(*) FROM transactions WHERE via = 'evidencia'
    """) == 9


def test_lo_decidido_resuelve_un_resumen_nuevo_sin_modelo(cargado, db):
    resumen, resultado, _ = cargado
    aplicar_decision(db, clave_memoria("Pago SUBE Viajes"), "Transporte")

    siguiente = resumen.model_copy(deep=True)
    siguiente.sha256, siguiente.archivo = "a" * 64, "septiembre.pdf"
    for m in siguiente.movimientos:
        m.id_operacion = "9" + m.id_operacion
    nuevo = guardar(siguiente, resultado, conn=db)

    conteo = clasificar_pendientes(db)          # sin clasificador: sin modelo

    assert conteo["regla"] == 4, "los 4 SUBE del resumen nuevo salen de la memoria"
    assert _contar(db, """
        SELECT count(*) FROM transactions
        WHERE statement_id = %s AND clave = %s AND via = 'regla'
    """, nuevo, clave_memoria("Pago SUBE Viajes")) == 4


def test_un_resumen_descuadrado_no_se_clasifica_ni_se_corrige(db):
    resumen, resultado = procesar(RESUMEN_MP)
    roto = resultado.model_copy(update={"cuadra": False})
    guardar(resumen, roto, conn=db)

    assert clasificar_pendientes(db) == {}
    assert aplicar_decision(db, clave_memoria("Pago SUBE Viajes"), "Transporte") == 0
    assert grupos_pendientes(db) == []


# ---------------------------------------------------------------------------
# Movimientos sin contraparte
# ---------------------------------------------------------------------------

def test_una_transferencia_sin_nombre_no_comparte_clave_ni_se_aprende():
    from app.agents.patrones import es_memorizable

    a = clave_memoria("Transferencia enviada", "111")
    b = clave_memoria("Transferencia enviada", "222")

    assert a != b, "dos transferencias anónimas no son la misma contraparte"
    assert a.startswith("TRANSF_ENVIADA|")
    assert not es_memorizable(a)
    assert es_memorizable(clave_memoria("Transferencia enviada Gomez Ana"))


def test_decidir_una_transferencia_sin_nombre_resuelve_solo_esa_y_no_se_aprende(db):
    resumen, resultado = procesar(RESUMEN_MP)
    # Dos transferencias pasan a no tener destinatario, como en el resumen real.
    # Los montos no cambian: la cadena de saldos sigue cerrando.
    anonimas = [i for i, m in enumerate(resumen.movimientos)
                if m.descripcion_cruda.startswith("Transferencia enviada")][:2]
    for i in anonimas:
        resumen.movimientos[i].descripcion_cruda = "Transferencia enviada"
    guardar(resumen, resultado, conn=db)
    clasificar_pendientes(db)

    claves = [clave_memoria("Transferencia enviada", resumen.movimientos[i].id_operacion)
              for i in anonimas]
    grupos = {g["clave"]: g["cantidad"] for g in grupos_pendientes(db)}
    assert [grupos[c] for c in claves] == [1, 1], "cada transferencia anónima es su propio grupo"

    assert aplicar_decision(db, claves[0], "Otros") == 1
    assert cargar_memoria(db) == {}, "se decide, pero no queda en memoria"
