const formatoPesos = new Intl.NumberFormat('es-AR', {
  style: 'currency',
  currency: 'ARS',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** Sólo para mostrar. La plata llega como texto y nunca se suma en la
 *  interfaz: los totales ya vienen calculados del servidor, con Decimal. */
export function pesos(texto: string): string {
  return formatoPesos.format(Number(texto))
}

/** Sólo para el ancho de una barra. Nunca vuelve a un cálculo. */
export function magnitud(texto: string): number {
  return Math.abs(Number(texto))
}

export function esNegativo(texto: string): boolean {
  return texto.trim().startsWith('-')
}

export function fecha(iso: string): string {
  const [anio, mes, dia] = iso.split('-')
  return `${dia}/${mes}/${anio}`
}

export function plural(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`
}

export const NOMBRE_TIPO: Record<string, string> = {
  TRANSF_ENVIADA: 'Transferencia enviada',
  TRANSF_RECIBIDA: 'Transferencia recibida',
  QR: 'Pago con QR',
  PEDIDO: 'Pedido',
  SUSCRIPCION: 'Suscripción',
  PAGO: 'Pago',
  COMERCIO: 'Comercio',
}

export const NOMBRE_VIA: Record<string, string> = {
  regla: 'por tu decisión',
  evidencia: 'por evidencia en el texto',
  consenso: 'por consenso de los agentes',
  modelo: 'por el modelo',
  desacuerdo: 'en desacuerdo',
}

/** "2026-09" -> "septiembre de 2026". */
export function mesLargo(anioMes: string): string {
  const [anio, mes] = anioMes.split('-').map(Number)
  return new Date(anio, mes - 1, 1).toLocaleDateString('es-AR', { month: 'long', year: 'numeric' })
}
