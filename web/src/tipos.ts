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
