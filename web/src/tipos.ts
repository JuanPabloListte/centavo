// Contratos de la API local. La plata llega SIEMPRE como texto: se muestra,
// nunca se suma acá. Los totales vienen calculados del servidor, con Decimal.

export type Grupo = {
  clave: string
  tipo: string
  /** La clave normalizada: sirve para comparar, no para mostrar. */
  contraparte: string
  /** El nombre tal como lo imprime el resumen. Es lo que se muestra. */
  nombre: string
  cantidad: number
  /** Devoluciones unidas a su pago, ya contadas en `cantidad` y en `total`. */
  devoluciones: number
  total: string
  desde: string
  hasta: string
  ejemplos: string[]
  memorizable: boolean
}

export type Grupos = {
  total_grupos: number
  total_movimientos: number
  grupos: Grupo[]
}

export type Categoria = {
  nombre: string
  descripcion: string
  solo_determinista: boolean
  interna: boolean
}

export type DecisionRespuesta = {
  cambiados: number
  se_aprende: boolean
  pendientes: { grupos: number; movimientos: number }
}

export type ResumenItem = {
  id: number
  banco: string
  archivo: string
  periodo_desde: string
  periodo_hasta: string
  estado: 'cuadrado' | 'descuadrado'
  movimientos: number
  resueltos: number
}

export type TipoLinea = 'ingreso' | 'gasto' | 'interno'

export type LineaCategoria = {
  categoria: string
  tipo: TipoLinea
  monto: string
  movimientos: number
}

export type Reporte = {
  resumen: {
    id: number
    banco: string
    archivo: string
    periodo_desde: string
    periodo_hasta: string
    cierre_tipo: 'total' | 'saldos'
    esperado: string
    saldo_inicial: string | null
    saldo_final: string | null
  }
  totales: {
    ingresos: string
    gastos: string
    internos: string
    sin_clasificar: string
    neto: string
  }
  cuadra: boolean
  diferencia: string
  cobertura: { movimientos: number; resueltos: number; pendientes: number }
  /** Devoluciones unidas a su pago: restan del gasto de su categoría. */
  devoluciones: number
  por_categoria: LineaCategoria[]
}

export type GrupoResuelto = Grupo & {
  categoria: string
  /** Cómo se resolvió la mayoría del grupo: regla, evidencia, consenso o modelo. */
  via: string
}

export type Resueltos = {
  total_grupos: number
  total_movimientos: number
  grupos: GrupoResuelto[]
}

export type Recurrente = {
  clave: string
  tipo: string
  nombre: string
  categoria: string | null
  meses: number
  desde: string
  dia_esperado: number
  monto_esperado: string
  tendencia: string | null
}

export type Proyeccion = {
  mes_objetivo: string | null
  ultimo_mes: string | null
  meses_base: string[]
  recurrentes: Recurrente[]
  variable_por_categoria: { categoria: string; promedio: string; meses_con_datos: number }[]
  sin_clasificar: { promedio: string; movimientos_por_mes: number } | null
  totales: {
    recurrentes_gastos: string
    recurrentes_ingresos: string
    variable_gastos: string
    sin_clasificar_gastos: string
    gastos_proyectados: string
  } | null
  criterios: {
    meses_minimos: number
    dias_tolerancia: number
    salto_maximo: string
    meses_promedio: number
  }
}

export type CargaCreada = { id: string; archivo: string; con_modelo: boolean; terminada: boolean }

export type PasoCarga = {
  paso: 'lectura' | 'compuerta' | 'guardado' | 'clasificacion' | 'modelo'
  estado: 'en_curso' | 'hecho' | 'fallo'
  detalle: string
}

export type ProgresoCarga = { hechos: number; total: number; segundos_restantes: number | null }

export type FinCarga = {
  statement_id: number
  cuadra: boolean
  detalle: string
  /** Cómo quedó clasificado ESTE resumen: vía de lo resuelto, estado de lo que no. */
  clasificacion: Record<string, number>
  pendientes: { grupos: number; movimientos: number }
  corrida: number
}

export type ErrorCarga = {
  motivo: 'lectura' | 'ya_ingerido' | 'superposicion' | 'base' | 'modelo' | 'inesperado'
  mensaje: string
  statement_id?: number
}
