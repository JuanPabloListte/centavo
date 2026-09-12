"""Parser de PDF por coordenadas.

Para resúmenes sin tabla detectable que parten la descripción en varios
renglones. Es el caso del resumen de cuenta de Mercado Pago: en un mes real,
70 de 131 movimientos venían partidos y `extract_tables()` no encontraba nada.

Cómo reconstruye cada movimiento, por página:

1. Ubica el encabezado de la tabla (Fecha · Descripción · ID · Valor · Saldo)
   y deriva de él las columnas. No hay coordenadas fijas en el código: si la
   maquetación se corre unos puntos, se sigue leyendo.
2. Corta la tabla en el primer renglón que arranca a la izquierda de la columna
   de descripción sin ser una fecha. Es el pie ("Fecha de emisión", razón
   social): sin este corte, se pegaba a la descripción del último movimiento.
3. Un renglón con fecha es el ANCLA de un movimiento, y tiene que traer
   exactamente un ID y dos montos (valor y saldo). Si no, error.
4. Los renglones sueltos de la columna de descripción se asignan al ancla más
   cercana. En la maquetación real están a -13, -7, +5 y +11 puntos de su
   fecha, con unos 30 puntos entre movimientos: no hay ambigüedad. Un
   fragmento a más de DISTANCIA_MAXIMA de cualquier fecha no se asigna a la
   fuerza: es un error de lectura y se informa.

Una tabla con columnas que el perfil no conoce (la de operaciones en dólares
agrega cotización) se ignora si está vacía y levanta un error si trae filas:
leerla con la forma de la tabla en pesos daría basura con cara de dato.

`numero_linea` es página × 1000 + orden en la página: la línea 3007 es el
séptimo movimiento de la página 3. Así el control renglón por renglón señala
un lugar que se puede encontrar a ojo en el PDF.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import pdfplumber

from ..models import CierrePorSaldos, CierrePorTotal, FilaCruda, ResumenCrudo
from .base import Perfil, parse_fecha, parse_monto_ar, sha256_archivo

DISTANCIA_MAXIMA = 16.0      # puntos entre un fragmento y la fecha de su movimiento
TOLERANCIA_RENGLON = 2.5     # puntos: dos palabras a menos de esto están en el mismo renglón

# Un encabezado de columna angosta se parte en varios renglones alineados
# abajo: el primer renglón de un rótulo ("ID de la operación", "Cotización
# del dólar") puede quedar bastante por encima de "Descripción". Los rótulos
# del encabezado se buscan hasta esta altura por encima.
ALTO_ENCABEZADO = 40.0

RE_MONTO = re.compile(r"^-?[\d.]+,\d{2}$")
RE_ID = re.compile(r"^\d{6,20}$")
RE_PIE_PAGINA = re.compile(r"^\d{1,3}/\d{1,3}$")

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

RE_PERIODO = re.compile(
    r"Del\s+(?P<d1>\d{1,2})"
    r"(?:\s+de\s+(?P<m1>[a-záéíóú]+))?"
    r"(?:\s+de\s+(?P<a1>\d{4}))?"
    r"\s+al\s+(?P<d2>\d{1,2})\s+de\s+(?P<m2>[a-záéíóú]+)\s+de\s+(?P<a2>\d{4})",
    re.I,
)


def parse_periodo_texto(texto: str) -> tuple[date, date] | None:
    """'Del 1 al 31 de agosto de 2026' -> (2026-08-01, 2026-08-31).

    También 'Del 15 de julio al 14 de agosto de 2026', y un período que cruza
    el año ('Del 20 de diciembre al 19 de enero de 2027') sin año en la
    primera punta.
    """
    m = RE_PERIODO.search(texto)
    if m is None:
        return None
    mes2 = MESES.get(m["m2"].lower())
    mes1 = MESES.get(m["m1"].lower()) if m["m1"] else mes2
    if mes1 is None or mes2 is None:
        return None
    anio2 = int(m["a2"])
    anio1 = int(m["a1"]) if m["a1"] else (anio2 - 1 if mes1 > mes2 else anio2)
    return date(anio1, mes1, int(m["d1"])), date(anio2, mes2, int(m["d2"]))


def _en_renglones(palabras: list[dict]) -> list[tuple[float, list[dict]]]:
    """Agrupa palabras en renglones por altura, ordenadas de izquierda a derecha."""
    renglones: list[list] = []
    for w in sorted(palabras, key=lambda w: (w["top"], w["x0"])):
        if renglones and abs(renglones[-1][0] - w["top"]) < TOLERANCIA_RENGLON:
            renglones[-1][1].append(w)
        else:
            renglones.append([w["top"], [w]])
    return [(top, sorted(ws, key=lambda w: w["x0"])) for top, ws in renglones]


class PdfCoordenadasParser:
    def __init__(self, perfil: Perfil):
        self.perfil = perfil

    # -- detección ----------------------------------------------------------

    def acepta(self, path: Path) -> bool:
        p = self.perfil
        if path.suffix.lower() != ".pdf" or p.formato != "pdf" or p.estrategia != "coordenadas":
            return False
        try:
            with pdfplumber.open(path) as pdf:
                texto = pdf.pages[0].extract_text() or ""
        except Exception:
            return False
        return p.marcador in texto

    # -- parseo -------------------------------------------------------------

    def parse(self, path: Path) -> ResumenCrudo:
        p = self.perfil
        filas: list[FilaCruda] = []

        with pdfplumber.open(path) as pdf:
            texto_primera = pdf.pages[0].extract_text() or ""
            for numero_pagina, pagina in enumerate(pdf.pages, start=1):
                filas.extend(self._filas_de_pagina(pagina, numero_pagina, path.name))

        encabezado = FilaCruda(
            origen=path.name,
            numero_linea=0,
            celdas=[p.col_fecha, p.col_descripcion, p.col_id_operacion,
                    p.col_importe, p.col_saldo],
        )
        periodo = parse_periodo_texto(texto_primera)

        return ResumenCrudo(
            banco=p.banco,
            perfil_id=p.id,
            archivo=path.name,
            sha256=sha256_archivo(path),
            filas=[encabezado, *filas],
            cierre=self._cierre(texto_primera),
            periodo_desde=periodo[0] if periodo else None,
            periodo_hasta=periodo[1] if periodo else None,
            titular=self._titular(texto_primera),
        )

    # -- una página ---------------------------------------------------------

    def _filas_de_pagina(self, pagina, numero_pagina: int, origen: str) -> list[FilaCruda]:
        palabras = pagina.extract_words()
        enc = self._encabezado(palabras)
        if enc is None:
            return []

        x_desc, x_id = enc["x_desc"], enc["x_id"]
        cuerpo = [w for w in palabras if w["top"] > enc["piso"]]

        # 2. Cortar el pie.
        corte = pagina.height
        for w in sorted(cuerpo, key=lambda w: w["top"]):
            if w["x0"] < x_desc and not self._es_fecha(w["text"]):
                corte = w["top"] - 1
                break
        cuerpo = [w for w in cuerpo
                  if w["top"] < corte and not RE_PIE_PAGINA.match(w["text"])]

        # 3. Anclas: renglones con fecha.
        anclas = []
        for w in cuerpo:
            if w["x0"] < x_desc and self._es_fecha(w["text"]):
                banda = [v for v in cuerpo if abs(v["top"] - w["top"]) < TOLERANCIA_RENGLON]
                anclas.append({"top": w["top"], "fecha": w["text"], "banda": banda})
        anclas.sort(key=lambda a: a["top"])

        if enc["no_soportados"]:
            if anclas:
                raise ValueError(
                    f"{origen} página {numero_pagina}: tabla con columnas no soportadas "
                    f"({', '.join(enc['no_soportados'])}) y {len(anclas)} movimientos. "
                    f"Leerlos con la forma de otra tabla sería peor que no leerlos: "
                    f"hace falta un perfil para esta tabla."
                )
            return []
        if not anclas:
            return []

        fragmentos = self._fragmentos(cuerpo, anclas, x_desc, x_id, origen, numero_pagina)

        filas = []
        for orden, a in enumerate(anclas, start=1):
            linea = numero_pagina * 1000 + orden
            banda = a["banda"]

            ids = [w for w in banda if RE_ID.match(w["text"]) and w["x0"] >= x_id - 4]
            montos = sorted(
                (w for w in banda if RE_MONTO.match(w["text"]) and w["x0"] > x_id),
                key=lambda w: w["x0"],
            )
            if len(ids) != 1 or len(montos) != 2:
                # Esta es la red de seguridad de verdad. El chequeo de rótulos
                # no soportados depende de poder leer el encabezado, y si dos
                # rótulos se pisan en el PDF el texto sale intercalado y ningún
                # nombre coincide. Contar los montos no depende de eso.
                raise ValueError(
                    f"{origen} línea {linea}: el renglón con fecha {a['fecha']} trae "
                    f"{len(ids)} IDs y {len(montos)} montos; se esperaban 1 y 2. "
                    f"Si la página {numero_pagina} tiene una tabla con más columnas "
                    f"(por ejemplo, operaciones en dólares), hace falta un perfil "
                    f"para esa tabla: no se lee con la forma de la de pesos."
                )

            en_la_fecha = [w for w in banda
                           if x_desc <= w["x0"] < x_id - 2 and not RE_ID.match(w["text"])]
            renglones = sorted(
                ([(a["top"], sorted(en_la_fecha, key=lambda w: w["x0"]))] if en_la_fecha else [])
                + fragmentos.get(orden - 1, []),
                key=lambda r: r[0],
            )
            descripcion = " ".join(w["text"] for _, ws in renglones for w in ws)
            if not descripcion:
                raise ValueError(f"{origen} línea {linea}: movimiento sin descripción.")

            filas.append(FilaCruda(
                origen=origen,
                numero_linea=linea,
                celdas=[a["fecha"], descripcion, ids[0]["text"],
                        montos[0]["text"], montos[1]["text"]],
            ))
        return filas

    def _fragmentos(self, cuerpo, anclas, x_desc, x_id, origen, numero_pagina):
        """Renglones sueltos de la columna de descripción -> índice de su ancla."""
        tops = [a["top"] for a in anclas]
        sueltas = [w for w in cuerpo
                   if x_desc <= w["x0"] < x_id - 2
                   and all(abs(w["top"] - t) >= TOLERANCIA_RENGLON for t in tops)]

        asignados: dict[int, list] = defaultdict(list)
        for top, ws in _en_renglones(sueltas):
            i = min(range(len(anclas)), key=lambda i: abs(anclas[i]["top"] - top))
            distancia = top - anclas[i]["top"]
            if abs(distancia) > DISTANCIA_MAXIMA:
                raise ValueError(
                    f"{origen} página {numero_pagina}: hay texto en la columna de "
                    f"descripción a {distancia:+.1f} pt de la fecha más cercana. No se "
                    f"asigna a la fuerza: revisá si es un pie de página que no se cortó."
                )
            asignados[i].append((top, ws))
        return asignados

    # -- encabezado de tabla ------------------------------------------------

    def _encabezado(self, palabras: list[dict]) -> dict | None:
        p = self.perfil
        desc = next((w for w in palabras if w["text"] == p.col_descripcion), None)
        if desc is None:
            return None

        # Los rótulos se buscan desde ALTO_ENCABEZADO por encima de "Descripción"
        # hasta su mismo renglón. Si hay más de una coincidencia, gana la más
        # cercana en altura.
        zona = [w for w in palabras
                if desc["top"] - ALTO_ENCABEZADO <= w["top"] <= desc["top"] + TOLERANCIA_RENGLON]

        def mas_cercana(texto: str):
            candidatas = [w for w in zona if w["text"] == texto]
            return min(candidatas, key=lambda w: abs(w["top"] - desc["top"]), default=None)

        idw, fecha = mas_cercana(p.col_id_operacion), mas_cercana(p.col_fecha)
        if idw is None or fecha is None:
            return None

        # El piso sale del renglón de "Descripción": en un encabezado alineado
        # abajo, todos los rótulos terminan en ese renglón.
        piso = max(w["bottom"] for w in palabras
                   if abs(w["top"] - desc["top"]) < 10) + 2
        textos = {w["text"] for w in zona}
        return {
            "x_desc": desc["x0"] - 2,
            "x_id": idw["x0"] - 2,
            "piso": piso,
            "no_soportados": [r for r in p.rotulos_no_soportados if r in textos],
        }

    # -- metadatos ----------------------------------------------------------

    def _es_fecha(self, texto: str) -> bool:
        try:
            parse_fecha(texto, self.perfil.formatos_fecha)
            return True
        except ValueError:
            return False

    def _cierre(self, texto: str):
        p = self.perfil
        if p.re_saldo_inicial and p.re_saldo_final:
            mi = re.search(p.re_saldo_inicial, texto)
            mf = re.search(p.re_saldo_final, texto)
            if mi and mf:
                return CierrePorSaldos(
                    saldo_inicial=parse_monto_ar(mi.group(1)),
                    saldo_final=parse_monto_ar(mf.group(1)),
                )
        if p.re_total and (mt := re.search(p.re_total, texto)):
            return CierrePorTotal(total_declarado=parse_monto_ar(mt.group(1)))
        return None

    def _titular(self, texto: str) -> str | None:
        if not self.perfil.re_titular:
            return None
        m = re.search(self.perfil.re_titular, texto)
        return m.group(1).strip() if m else None
