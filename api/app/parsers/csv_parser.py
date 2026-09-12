"""Parser de CSV, manejado por perfil.

Un CSV de banco típicamente trae un preámbulo con metadatos (período, total,
saldos) y recién después la tabla. Este parser separa las dos cosas: busca el
cierre con las regexps del perfil sobre el texto completo, y la tabla a partir
de la fila que contiene el encabezado esperado.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal
from pathlib import Path

from ..models import CierrePorSaldos, CierrePorTotal, FilaCruda, ResumenCrudo
from .base import Perfil, parse_fecha, parse_monto_ar, sha256_archivo


class CsvParser:
    def __init__(self, perfil: Perfil):
        self.perfil = perfil

    def acepta(self, path: Path) -> bool:
        if path.suffix.lower() != ".csv" or self.perfil.formato != "csv":
            return False
        cabeza = path.read_text(encoding=self.perfil.encoding, errors="replace")[:600]
        return self.perfil.marcador in cabeza

    def parse(self, path: Path) -> ResumenCrudo:
        p = self.perfil
        texto = path.read_text(encoding=p.encoding, errors="replace")

        cierre = self._buscar_cierre(texto)
        desde, hasta = self._buscar_periodo(texto)
        filas = self._leer_tabla(texto, path.name)

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

    # -- preámbulo ----------------------------------------------------------

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

        # No encontrarlo no es un error del parser: es información. La
        # normalización decide qué hacer con un resumen sin cierre.
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

    # -- tabla --------------------------------------------------------------

    def _leer_tabla(self, texto: str, origen: str) -> list[FilaCruda]:
        p = self.perfil
        lector = csv.reader(io.StringIO(texto), delimiter=p.delimitador)

        encabezado: list[str] | None = None
        filas: list[FilaCruda] = []

        for numero, celdas in enumerate(lector, start=1):
            celdas = [c.strip() for c in celdas]
            if not any(celdas):
                continue

            if encabezado is None:
                # La fila de encabezado es la primera que trae las columnas
                # que el perfil espera.
                if p.col_fecha in celdas and p.col_descripcion in celdas:
                    encabezado = celdas
                continue

            # Una fila de datos tiene que empezar con algo parseable como fecha.
            idx_fecha = encabezado.index(p.col_fecha)
            if idx_fecha >= len(celdas):
                continue
            try:
                parse_fecha(celdas[idx_fecha], p.formatos_fecha)
            except ValueError:
                continue  # pie de página, subtotales, líneas sueltas

            filas.append(
                FilaCruda(origen=origen, numero_linea=numero, celdas=celdas)
            )

        if encabezado is None:
            raise ValueError(
                f"{origen}: no encontré la fila de encabezado con "
                f"{p.col_fecha!r} y {p.col_descripcion!r}"
            )

        # El encabezado viaja como primera fila para que normalize sepa
        # mapear columnas sin volver a abrir el archivo.
        return [FilaCruda(origen=origen, numero_linea=0, celdas=encabezado), *filas]
