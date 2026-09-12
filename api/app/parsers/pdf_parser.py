"""Parser de PDF, manejado por perfil.

Estrategia, en este orden y por una razón:

1. `extract_table()` de pdfplumber. Si el PDF tiene una tabla con líneas o
   con columnas bien separadas, esto la devuelve limpia y no hay más que hacer.
2. Si eso no da filas, `extract_words()` y agrupar por coordenada Y para
   reconstruir renglones, y por X para asignar columnas.

NO se usa OCR. Estos PDF tienen capa de texto; si algún día aparece uno
escaneado, ese es un problema distinto y merece su propio camino.
"""

from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from ..models import CierrePorSaldos, CierrePorTotal, FilaCruda, ResumenCrudo
from .base import Perfil, parse_fecha, parse_monto_ar, sha256_archivo


class PdfParser:
    def __init__(self, perfil: Perfil):
        self.perfil = perfil

    def acepta(self, path: Path) -> bool:
        if path.suffix.lower() != ".pdf" or self.perfil.formato != "pdf":
            return False
        try:
            with pdfplumber.open(path) as pdf:
                texto = pdf.pages[0].extract_text() or ""
        except Exception:
            return False
        return self.perfil.marcador in texto

    def parse(self, path: Path) -> ResumenCrudo:
        p = self.perfil

        with pdfplumber.open(path) as pdf:
            texto_completo = "\n".join(pg.extract_text() or "" for pg in pdf.pages)
            tablas = [t for pg in pdf.pages for t in (pg.extract_tables() or [])]

        cierre = self._buscar_cierre(texto_completo)
        desde, hasta = self._buscar_periodo(texto_completo)
        filas = self._filas_de_tablas(tablas, path.name)

        if not filas:
            filas = self._filas_de_texto(texto_completo, path.name)

        return ResumenCrudo(
            banco=p.banco,
            perfil_id=p.id,
            archivo=path.name,
            sha256=sha256_archivo(path),
            filas=filas,
            cierre=cierre,
            periodo_desde=desde,
            periodo_hasta=hasta,
        )

    # -- metadatos ----------------------------------------------------------

    def _buscar_cierre(self, texto: str):
        p = self.perfil

        if p.re_total:
            m = re.search(p.re_total, texto)
            if m:
                return CierrePorTotal(total_declarado=parse_monto_ar(m.group(1)))

        if p.re_saldo_inicial and p.re_saldo_final:
            mi = re.search(p.re_saldo_inicial, texto)
            mf = re.search(p.re_saldo_final, texto)
            if mi and mf:
                return CierrePorSaldos(
                    saldo_inicial=parse_monto_ar(mi.group(1)),
                    saldo_final=parse_monto_ar(mf.group(1)),
                )
        return None

    def _buscar_periodo(self, texto: str):
        p = self.perfil
        if not p.re_periodo:
            return None, None
        m = re.search(p.re_periodo, texto)
        if not m:
            return None, None
        return (
            parse_fecha(m.group(1), p.formatos_fecha),
            parse_fecha(m.group(2), p.formatos_fecha),
        )

    # -- camino 1: tabla extraída -------------------------------------------

    def _filas_de_tablas(self, tablas, origen: str) -> list[FilaCruda]:
        p = self.perfil
        salida: list[FilaCruda] = []
        encabezado: list[str] | None = None
        numero = 0

        for tabla in tablas:
            for cruda in tabla:
                celdas = [(c or "").strip() for c in cruda]
                numero += 1
                if not any(celdas):
                    continue

                if encabezado is None:
                    if p.col_fecha in celdas and p.col_descripcion in celdas:
                        encabezado = celdas
                        salida.append(
                            FilaCruda(origen=origen, numero_linea=0, celdas=celdas)
                        )
                    continue

                idx = encabezado.index(p.col_fecha)
                if idx >= len(celdas):
                    continue
                try:
                    parse_fecha(celdas[idx], p.formatos_fecha)
                except ValueError:
                    continue

                salida.append(
                    FilaCruda(origen=origen, numero_linea=numero, celdas=celdas)
                )

        return salida if encabezado else []

    # -- camino 2: reconstruir renglones desde palabras ----------------------

    def _filas_de_texto(self, texto: str, origen: str) -> list[FilaCruda]:
        """Último recurso: partir cada renglón con la forma
        `fecha  descripción  importe`.

        Sirve para maquetaciones sin tabla detectable. Es más frágil que el
        camino 1 y por eso va segundo: si un banco cae siempre acá, conviene
        darle su propio perfil con posiciones de columna.
        """
        p = self.perfil
        patron = re.compile(
            r"^\s*(?P<fecha>\d{2}/\d{2}/\d{2,4})\s+"
            r"(?P<desc>.+?)\s+"
            r"(?P<importe>[\-\$\(]?[\d\.]+,\d{2}\)?)\s*$"
        )

        salida = [
            FilaCruda(
                origen=origen,
                numero_linea=0,
                celdas=[p.col_fecha, p.col_descripcion, p.col_importe or "Importe"],
            )
        ]

        for numero, linea in enumerate(texto.splitlines(), start=1):
            m = patron.match(linea)
            if not m:
                continue
            try:
                parse_fecha(m.group("fecha"), p.formatos_fecha)
                parse_monto_ar(m.group("importe"))
            except ValueError:
                continue
            salida.append(
                FilaCruda(
                    origen=origen,
                    numero_linea=numero,
                    celdas=[
                        m.group("fecha"),
                        m.group("desc").strip(),
                        m.group("importe"),
                    ],
                )
            )

        return salida if len(salida) > 1 else []
