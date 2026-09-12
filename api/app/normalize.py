"""De ResumenCrudo a Resumen.

Acá se resuelven las conversiones que después nadie puede revisar a ojo:
fecha, monto con signo, moneda y —si la fuente los trae— ID de operación y
saldo por renglón. Si algo no se puede convertir, se levanta ValueError con el
número de línea — nunca se descarta la fila en silencio. Una fila que
desaparece sin ruido es exactamente lo que hace que la compuerta de
cuadratura falle por un monto raro y no se entienda por qué.
"""

from __future__ import annotations

from .models import Movimiento, Resumen, ResumenCrudo
from .parsers.base import Perfil, parse_fecha, parse_monto_ar
from .parsers.perfiles import PERFILES


def _perfil_de(perfil_id: str) -> Perfil:
    for p in PERFILES:
        if p.id == perfil_id:
            return p
    raise ValueError(f"perfil desconocido: {perfil_id!r}")


def normalizar(crudo: ResumenCrudo) -> Resumen:
    perfil = _perfil_de(crudo.perfil_id)

    if crudo.cierre is None:
        raise ValueError(
            f"{crudo.archivo}: el parser no encontró ni el total ni los saldos. "
            f"Sin cierre no hay contra qué cuadrar — revisá las regexps del "
            f"perfil {perfil.id!r}."
        )
    if crudo.periodo_desde is None or crudo.periodo_hasta is None:
        raise ValueError(f"{crudo.archivo}: el parser no encontró el período.")

    if not crudo.filas:
        raise ValueError(f"{crudo.archivo}: el parser no devolvió ninguna fila.")

    encabezado, *cuerpo = crudo.filas
    if encabezado.numero_linea != 0:
        raise ValueError(
            f"{crudo.archivo}: la primera fila tiene que ser el encabezado "
            f"(numero_linea == 0). El parser no respetó el contrato."
        )

    columnas = encabezado.celdas
    movimientos: list[Movimiento] = []

    for fila in cuerpo:
        celdas = dict(zip(columnas, fila.celdas))
        try:
            monto = perfil.importe_de(celdas)
            if monto == 0:
                # Un movimiento de cero no aporta y rompe el CHECK de la base.
                continue
            movimientos.append(
                Movimiento(
                    fecha=parse_fecha(celdas[perfil.col_fecha], perfil.formatos_fecha),
                    monto=monto,
                    moneda=perfil.moneda,
                    descripcion_cruda=celdas[perfil.col_descripcion],
                    linea_origen=fila.numero_linea,
                    id_operacion=(
                        celdas[perfil.col_id_operacion].strip() or None
                        if perfil.col_id_operacion else None
                    ),
                    saldo=(
                        parse_monto_ar(celdas[perfil.col_saldo])
                        if perfil.col_saldo else None
                    ),
                )
            )
        except (ValueError, KeyError) as exc:
            raise ValueError(
                f"{crudo.archivo} línea {fila.numero_linea}: {exc}"
            ) from exc

    return Resumen(
        banco=crudo.banco,
        archivo=crudo.archivo,
        sha256=crudo.sha256,
        periodo_desde=crudo.periodo_desde,
        periodo_hasta=crudo.periodo_hasta,
        cierre=crudo.cierre,
        movimientos=movimientos,
        titular=crudo.titular,
    )
