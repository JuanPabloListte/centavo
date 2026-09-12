"""Gastos recurrentes y proyección del mes. Es aritmética: el modelo no participa.

**Recurrente fijo.** Una contraparte que, en los últimos meses cargados, seguidos
y hasta el último inclusive, aparece:

- en tres meses o más,
- una sola vez por mes,
- siempre con el mismo signo,
- en días parecidos del mes: como mucho 5 días entre el más temprano y el más
  tardío,
- con montos que de un mes al siguiente no cambian más del 30%.

La tolerancia del monto es relativa y se aplica paso a paso, porque en
Argentina un servicio sube casi todos los meses: lo que descarta no es el
aumento sino el salto. Los números salieron de medir la base real: de las 27
contrapartes que aparecen en tres meses o más, sólo 3 tienen un movimiento por
mes, y las que varían menos del 5% son 3. Precisión antes que recall: un
recurrente inventado molesta más que uno que falta.

Lo que no se mira, a propósito: la categoría. Una transferencia mensual a una
persona, como un alquiler, es recurrente aunque nadie la haya clasificado.

**Proyección.** Para el mes siguiente al último cargado, en piezas que se
pueden sumar:

1. Los recurrentes fijos, con el último monto visto. No depende de que revises.
2. El promedio mensual del gasto variable ya clasificado, por categoría, sobre
   los últimos 3 meses. Depende de tu revisión.
3. Lo que queda sin clasificar, promedio mensual, aparte: es lo que la
   proyección no sabe.

Un mes cargado es un resumen cuadrado. El mes en curso, a medias, no se puede
cargar todavía: un resumen parcial choca con el completo que llega después. Por
eso la proyección es del mes que viene, no del que está corriendo.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median

import psycopg

from .agents.patrones import es_memorizable, nombre_legible
from .reporte import CATEGORIAS_INTERNAS

MESES_MINIMOS = 3
DIAS_TOLERANCIA = 5
SALTO_MAXIMO = Decimal("0.30")
MESES_PROMEDIO = 3
CERO = Decimal("0.00")


@dataclass(frozen=True)
class Aparicion:
    mes: date          # primer día del mes del resumen
    fecha: date
    monto: Decimal


@dataclass
class Recurrente:
    clave: str
    meses: list[date]          # la racha, de más viejo a más nuevo
    montos: list[Decimal]
    dias: list[int]

    @property
    def monto_esperado(self) -> Decimal:
        """El último visto: con inflación, es la mejor estimación del próximo."""
        return self.montos[-1]

    @property
    def dia_esperado(self) -> int:
        return int(median(self.dias))

    @property
    def tendencia(self) -> Decimal | None:
        """Variación entre el primer y el último monto de la racha."""
        primero = abs(self.montos[0])
        return None if primero == 0 else (abs(self.montos[-1]) - primero) / primero


def mes_de(fecha: date) -> date:
    return fecha.replace(day=1)


def mes_siguiente(mes: date) -> date:
    return date(mes.year + (mes.month == 12), mes.month % 12 + 1, 1)


def mes_anterior(mes: date) -> date:
    return date(mes.year - (mes.month == 1), (mes.month - 2) % 12 + 1, 1)


def _racha(meses, ultimo: date) -> list[date]:
    """Los meses seguidos que terminan en `ultimo`, de más viejo a más nuevo."""
    presentes, racha, m = set(meses), [], ultimo
    while m in presentes:
        racha.append(m)
        m = mes_anterior(m)
    return list(reversed(racha))


def evaluar(clave: str, apariciones: list[Aparicion], ultimo_mes: date) -> Recurrente | None:
    """Aplica los criterios a las apariciones de UNA contraparte."""
    por_mes: dict[date, list[Aparicion]] = defaultdict(list)
    for a in apariciones:
        por_mes[a.mes].append(a)
    racha = _racha(por_mes, ultimo_mes)
    if len(racha) < MESES_MINIMOS:
        return None
    if any(len(por_mes[m]) != 1 for m in racha):
        return None
    montos = [por_mes[m][0].monto for m in racha]
    if not (all(x < 0 for x in montos) or all(x > 0 for x in montos)):
        return None
    dias = [por_mes[m][0].fecha.day for m in racha]
    if max(dias) - min(dias) > DIAS_TOLERANCIA:
        return None
    if any(abs(b - a) > abs(a) * SALTO_MAXIMO for a, b in zip(montos, montos[1:])):
        return None
    return Recurrente(clave, racha, montos, dias)


def detectar(por_clave: dict[str, list[Aparicion]], ultimo_mes: date) -> list[Recurrente]:
    """Los recurrentes fijos, gastos más grandes primero."""
    encontrados = [
        r for clave, aps in por_clave.items() if (r := evaluar(clave, aps, ultimo_mes))
    ]
    return sorted(encontrados, key=lambda r: (r.monto_esperado, r.clave))


def _texto(valor: Decimal) -> str:
    return str(valor.quantize(CERO))


def _porcentaje(valor: Decimal | None) -> str | None:
    return None if valor is None else f"{valor:+.0%}"


def proyeccion(conn: psycopg.Connection) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.clave, t.monto, t.fecha, s.periodo_desde, t.via, t.estado_clasificacion,
                   c.nombre, t.descripcion_cruda, t.devuelve_a IS NOT NULL
            FROM transactions t
            JOIN statements s ON s.id = t.statement_id
            LEFT JOIN categories c ON c.id = t.categoria_id
            WHERE s.estado = 'cuadrado'
            ORDER BY s.periodo_desde, t.fecha, t.id
            """
        )
        filas = cur.fetchall()

    criterios = {
        "meses_minimos": MESES_MINIMOS,
        "dias_tolerancia": DIAS_TOLERANCIA,
        "salto_maximo": _texto(SALTO_MAXIMO),
        "meses_promedio": MESES_PROMEDIO,
    }
    if not filas:
        return {"mes_objetivo": None, "ultimo_mes": None, "meses_base": [], "recurrentes": [],
                "variable_por_categoria": [], "sin_clasificar": None, "totales": None,
                "criterios": criterios}

    meses = sorted({mes_de(periodo) for _, _, _, periodo, *_ in filas})
    ultimo = meses[-1]

    # Recurrentes: por contraparte, sin lo que resuelve la evidencia, sin claves
    # que no identifican a nadie y sin devoluciones, que ajustan a su pago.
    por_clave: dict[str, list[Aparicion]] = defaultdict(list)
    nombres: dict[str, str] = {}
    categorias: dict[str, Counter] = defaultdict(Counter)
    for clave, monto, fecha, periodo, via, estado, categoria, descripcion, devuelve in filas:
        if devuelve or via == "evidencia" or not es_memorizable(clave):
            continue
        por_clave[clave].append(Aparicion(mes_de(periodo), fecha, monto))
        nombres.setdefault(clave, nombre_legible(descripcion))
        if estado == "resuelto" and categoria:
            categorias[clave][categoria] += 1
    recurrentes = detectar(por_clave, ultimo)
    fijas = {r.clave for r in recurrentes}

    # Variable por categoría y sin clasificar: promedio mensual sobre la base.
    # Una devolución unida a su pago es plata que vuelve: resta de su categoría.
    base = meses[-MESES_PROMEDIO:]
    variable: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(lambda: CERO))
    sin_suma, sin_cantidad = CERO, 0
    for clave, monto, fecha, periodo, via, estado, categoria, descripcion, devuelve in filas:
        mes = mes_de(periodo)
        if mes not in base or clave in fijas or (monto >= 0 and not devuelve):
            continue
        if estado == "resuelto" and categoria:
            if categoria not in CATEGORIAS_INTERNAS:
                variable[categoria][mes] += monto
        else:
            sin_suma += monto
            sin_cantidad += 1
    n = len(base)
    variable_por_categoria = sorted(
        (
            {
                "categoria": cat,
                "promedio": _texto(sum(por_mes.values(), CERO) / n),
                "meses_con_datos": len(por_mes),
            }
            for cat, por_mes in variable.items()
        ),
        key=lambda x: Decimal(x["promedio"]),
    )
    recurrentes_gastos = sum((r.monto_esperado for r in recurrentes if r.monto_esperado < 0), CERO)
    recurrentes_ingresos = sum((r.monto_esperado for r in recurrentes if r.monto_esperado > 0), CERO)
    variable_gastos = sum((Decimal(v["promedio"]) for v in variable_por_categoria), CERO)
    sin_clasificar = (sin_suma / n).quantize(CERO)

    return {
        "mes_objetivo": mes_siguiente(ultimo).strftime("%Y-%m"),
        "ultimo_mes": ultimo.strftime("%Y-%m"),
        "meses_base": [m.strftime("%Y-%m") for m in base],
        "recurrentes": [
            {
                "clave": r.clave,
                "tipo": r.clave.split("|", 1)[0],
                "nombre": nombres[r.clave],
                "categoria": (categorias[r.clave].most_common(1) or [(None, 0)])[0][0],
                "meses": len(r.meses),
                "desde": r.meses[0].strftime("%Y-%m"),
                "dia_esperado": r.dia_esperado,
                "monto_esperado": _texto(r.monto_esperado),
                "tendencia": _porcentaje(r.tendencia),
            }
            for r in recurrentes
        ],
        "variable_por_categoria": variable_por_categoria,
        "sin_clasificar": {
            "promedio": _texto(sin_clasificar),
            "movimientos_por_mes": round(sin_cantidad / n, 1),
        },
        "totales": {
            "recurrentes_gastos": _texto(recurrentes_gastos),
            "recurrentes_ingresos": _texto(recurrentes_ingresos),
            "variable_gastos": _texto(variable_gastos),
            "sin_clasificar_gastos": _texto(sin_clasificar),
            "gastos_proyectados": _texto(recurrentes_gastos + variable_gastos + sin_clasificar),
        },
        "criterios": criterios,
    }
