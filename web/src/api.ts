import type {
  CargaCreada,
  Categoria,
  DecisionRespuesta,
  Grupos,
  Proyeccion,
  Reporte,
  Resueltos,
  ResumenItem,
} from './tipos'

export class ErrorApi extends Error {
  readonly estado: number

  constructor(estado: number, mensaje: string) {
    super(mensaje)
    this.estado = estado
  }
}

async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  let respuesta: Response
  try {
    respuesta = await fetch(ruta, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ErrorApi(0, 'No hay conexión con la interfaz local.')
  }

  if (!respuesta.ok) {
    let detalle = ''
    try {
      const cuerpo: unknown = await respuesta.json()
      if (cuerpo && typeof cuerpo === 'object' && 'detail' in cuerpo && typeof cuerpo.detail === 'string') {
        detalle = cuerpo.detail
      }
    } catch {
      // Sin cuerpo JSON: casi siempre es el proxy de Vite sin API detrás.
    }
    throw new ErrorApi(
      respuesta.status,
      detalle || 'La API local no responde. ¿Está corriendo en el puerto 8000?',
    )
  }
  return (await respuesta.json()) as T
}

export const api = {
  grupos: () => pedir<Grupos>('/api/revision/grupos'),
  categorias: () => pedir<Categoria[]>('/api/categorias'),
  resueltos: () => pedir<Resueltos>('/api/revision/resueltos'),
  decidir: (clave: string, categoria: string) =>
    pedir<DecisionRespuesta>('/api/revision/decisiones', {
      method: 'POST',
      body: JSON.stringify({ clave, categoria }),
    }),
  resumenes: () => pedir<ResumenItem[]>('/api/resumenes'),
  reporte: (id: number) => pedir<Reporte>(`/api/resumenes/${id}/reporte`),
  proyeccion: () => pedir<Proyeccion>('/api/proyeccion'),
  cargaActiva: () => pedir<CargaCreada | null>('/api/cargas/activa'),
  cargar: (archivo: File, conModelo: boolean) =>
    pedir<CargaCreada>(
      `/api/cargas?nombre=${encodeURIComponent(archivo.name)}&con_modelo=${conModelo}`,
      { method: 'POST', headers: { 'Content-Type': tipoDeArchivo(archivo) }, body: archivo },
    ),
}

export function mensajeDe(error: unknown): string {
  return error instanceof ErrorApi ? error.message : 'Pasó algo inesperado. Mirá la consola.'
}

/** El tipo con el que viaja el archivo. Windows suele declarar un CSV como planilla
 *  de Excel: lo que no es PDF ni CSV va como binario genérico, y el servidor
 *  detecta el formato por el contenido. */
function tipoDeArchivo(archivo: File): string {
  return archivo.type === 'application/pdf' || archivo.type === 'text/csv'
    ? archivo.type
    : 'application/octet-stream'
}
