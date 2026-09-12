"""API local de Centavo.

Escucha sólo en 127.0.0.1, y eso es parte de la premisa del producto: ningún
movimiento sale de la máquina, lo que incluye no exponer la API a la red local.

    uvicorn app.main:app --host 127.0.0.1 --port 8000

La plata viaja como texto en el JSON, nunca como número. Un float en JavaScript
pierde centavos, y el reporte tiene que cuadrar al centavo.

La conexión a la base se inyecta (`get_conn`), así los tests corren la API
contra un esquema temporal y nunca contra tus datos.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agents.patrones import es_memorizable, nombre_legible
from .clasificar import cargar_categorias
from .memoria import aplicar_decision, clasificar_pendientes, grupos_pendientes
from .pipeline import procesar
from .reporte import (
    CATEGORIAS_INTERNAS,
    ResumenDescuadrado,
    ResumenNoEncontrado,
    reporte_de_resumen,
)
from .store import SuperposicionParcial, YaIngerido, conectar, guardar

app = FastAPI(title="Centavo", version="0.4.0")


def get_conn() -> Iterator[psycopg.Connection]:
    try:
        conn = conectar()
    except psycopg.OperationalError as exc:
        raise HTTPException(
            503, "La base de datos no responde. ¿Está corriendo Docker?"
        ) from exc
    try:
        yield conn
    finally:
        conn.close()


def _pendientes(conn: psycopg.Connection) -> dict:
    grupos = grupos_pendientes(conn)
    return {"grupos": len(grupos), "movimientos": sum(g["cantidad"] for g in grupos)}


@app.get("/api/salud")
def salud(conn: psycopg.Connection = Depends(get_conn)) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return {"ok": True}


@app.get("/api/resumenes")
def resumenes(conn: psycopg.Connection = Depends(get_conn)) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.banco, s.archivo, s.periodo_desde, s.periodo_hasta, s.estado,
                   count(t.id),
                   count(t.id) FILTER (WHERE t.estado_clasificacion = 'resuelto')
            FROM statements s
            LEFT JOIN transactions t ON t.statement_id = s.id
            GROUP BY s.id
            ORDER BY s.periodo_desde DESC, s.id DESC
            """
        )
        return [
            {
                "id": sid,
                "banco": banco,
                "archivo": archivo,
                "periodo_desde": desde.isoformat(),
                "periodo_hasta": hasta.isoformat(),
                "estado": estado,
                "movimientos": movimientos,
                "resueltos": resueltos,
            }
            for sid, banco, archivo, desde, hasta, estado, movimientos, resueltos in cur.fetchall()
        ]


@app.get("/api/categorias")
def categorias(conn: psycopg.Connection = Depends(get_conn)) -> list[dict]:
    todas = cargar_categorias(conn, para_modelo=False)
    with conn.cursor() as cur:
        cur.execute("SELECT nombre, solo_determinista FROM categories")
        deterministas = dict(cur.fetchall())
    return [
        {
            "nombre": nombre,
            "descripcion": descripcion,
            "solo_determinista": deterministas[nombre],
            "interna": nombre in CATEGORIAS_INTERNAS,
        }
        for nombre, descripcion in todas.items()
    ]


@app.get("/api/revision/grupos")
def revision_grupos(conn: psycopg.Connection = Depends(get_conn)) -> dict:
    grupos = grupos_pendientes(conn)
    salida = []
    for g in grupos:
        tipo, contraparte = g["clave"].split("|", 1)
        salida.append({
            "clave": g["clave"],
            "tipo": tipo,
            # La clave, normalizada para comparar; `nombre`, como lo imprime el
            # resumen, para mostrar.
            "contraparte": contraparte,
            "nombre": nombre_legible(g["ejemplos"][0]) if g["ejemplos"] else contraparte,
            "cantidad": g["cantidad"],
            "devoluciones": g["devoluciones"],
            "total": str(g["total"]),
            "desde": g["desde"].isoformat(),
            "hasta": g["hasta"].isoformat(),
            "ejemplos": g["ejemplos"],
            "memorizable": es_memorizable(g["clave"]),
        })
    return {
        "total_grupos": len(salida),
        "total_movimientos": sum(g["cantidad"] for g in salida),
        "grupos": salida,
    }


class DecisionPedido(BaseModel):
    clave: str = Field(min_length=3)
    categoria: str = Field(min_length=1)


@app.post("/api/revision/decisiones")
def decidir(pedido: DecisionPedido, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM transactions t
            JOIN statements s ON s.id = t.statement_id
            WHERE t.clave = %s AND s.estado = 'cuadrado'
            """,
            (pedido.clave,),
        )
        if cur.fetchone()[0] == 0:
            raise HTTPException(404, f"No hay movimientos con la clave {pedido.clave!r}.")

    try:
        cambiados = aplicar_decision(conn, pedido.clave, pedido.categoria)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    return {
        "cambiados": cambiados,
        "se_aprende": es_memorizable(pedido.clave),
        "pendientes": _pendientes(conn),
    }


@app.get("/api/resumenes/{statement_id}/reporte")
def reporte(statement_id: int, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    try:
        return reporte_de_resumen(conn, statement_id)
    except ResumenNoEncontrado as exc:
        raise HTTPException(404, f"No existe el resumen {statement_id}.") from exc
    except ResumenDescuadrado as exc:
        raise HTTPException(409, str(exc)) from exc


class IngestPedido(BaseModel):
    path: str


@app.post("/api/ingest")
def ingest(pedido: IngestPedido, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    path = Path(pedido.path)
    if not path.exists():
        raise HTTPException(404, f"No existe: {path}")

    try:
        resumen, resultado = procesar(path)
    except ValueError as exc:
        # Un archivo que no se puede parsear es un 422, no un 500: el problema
        # está en el archivo o en el perfil, no en el servidor.
        raise HTTPException(422, str(exc)) from exc

    try:
        statement_id = guardar(resumen, resultado, conn=conn)
    except (YaIngerido, SuperposicionParcial) as exc:
        raise HTTPException(409, str(exc)) from exc

    return {
        "statement_id": statement_id,
        "cuadra": resultado.cuadra,
        "detalle": resultado.explicar(),
        "clasificacion": clasificar_pendientes(conn) if resultado.cuadra else {},
        "pendientes": _pendientes(conn),
    }
