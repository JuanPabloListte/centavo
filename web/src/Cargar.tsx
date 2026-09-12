import { useEffect, useRef, useState } from 'react'
import { api, mensajeDe } from './api'
import { plural } from './formato'
import type { ErrorCarga, FinCarga, PasoCarga, ProgresoCarga } from './tipos'

const PASOS: { paso: PasoCarga['paso']; titulo: string }[] = [
  { paso: 'lectura', titulo: 'Leer el archivo' },
  { paso: 'compuerta', titulo: 'Verificar que cuadre' },
  { paso: 'guardado', titulo: 'Guardar en la base' },
  { paso: 'clasificacion', titulo: 'Clasificar con memoria y evidencia' },
  { paso: 'modelo', titulo: 'Clasificar con la flota local' },
]

const ICONO: Record<string, string> = { hecho: '✓', fallo: '✗', en_curso: '…', pendiente: '○' }

const MOTIVO: Record<ErrorCarga['motivo'], string> = {
  lectura: 'No se pudo leer el archivo',
  ya_ingerido: 'Ese resumen ya estaba cargado',
  superposicion: 'Se superpone con un resumen ya cargado',
  base: 'La base de datos no responde',
  modelo: 'El modelo local falló a mitad de camino',
  inesperado: 'La carga se cortó',
}

const VIA: Record<string, string> = {
  regla: 'por tu memoria',
  evidencia: 'por evidencia',
  consenso: 'por consenso de los agentes',
  modelo: 'por el modelo',
  needs_review: 'a revisión',
  sin_procesar: 'para revisar',
}

type Props = { irARevision: () => void; irAReporte: (statementId: number) => void }

/** Subir un resumen y seguir su carga. El servidor hace todo en segundo plano y
 *  avisa cada paso por SSE; acá sólo se muestra. Si al volver a esta solapa la
 *  carga sigue en curso, se retoma. */
export default function Cargar({ irARevision, irAReporte }: Props) {
  const [archivo, setArchivo] = useState<File | null>(null)
  const [conModelo, setConModelo] = useState(false)
  const [cargaId, setCargaId] = useState<string | null>(null)
  const [nombre, setNombre] = useState('')
  const [pasos, setPasos] = useState<Partial<Record<PasoCarga['paso'], PasoCarga>>>({})
  const [progreso, setProgreso] = useState<ProgresoCarga | null>(null)
  const [fin, setFin] = useState<FinCarga | null>(null)
  const [falla, setFalla] = useState<ErrorCarga | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [arrastrando, setArrastrando] = useState(false)
  const entrada = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let vigente = true
    api
      .cargaActiva()
      .then((c) => {
        if (vigente && c) {
          setNombre(c.archivo)
          setCargaId(c.id)
        }
      })
      .catch((e: unknown) => vigente && setError(mensajeDe(e)))
    return () => {
      vigente = false
    }
  }, [])

  useEffect(() => {
    if (!cargaId) return
    let terminada = false
    setPasos({})
    setProgreso(null)
    setFin(null)
    setFalla(null)
    const fuente = new EventSource(`/api/cargas/${cargaId}/eventos`)
    const datos = <T,>(e: Event) => JSON.parse((e as MessageEvent<string>).data) as T
    fuente.addEventListener('paso', (e) => {
      const p = datos<PasoCarga>(e)
      setPasos((previos) => ({ ...previos, [p.paso]: p }))
    })
    fuente.addEventListener('progreso', (e) => setProgreso(datos<ProgresoCarga>(e)))
    fuente.addEventListener('fin', (e) => {
      terminada = true
      setFin(datos<FinCarga>(e))
      fuente.close()
    })
    fuente.addEventListener('falla', (e) => {
      terminada = true
      setFalla(datos<ErrorCarga>(e))
      fuente.close()
    })
    fuente.onerror = () => {
      // Un corte de conexión se reintenta solo; si el navegador se rinde, se avisa.
      if (!terminada && fuente.readyState === EventSource.CLOSED) {
        setError('Se perdió el seguimiento de la carga. Si la API se reinició, la carga se cortó.')
      }
    }
    return () => fuente.close()
  }, [cargaId])

  async function enviar() {
    if (!archivo) return
    setEnviando(true)
    setError(null)
    try {
      const c = await api.cargar(archivo, conModelo)
      setNombre(c.archivo)
      setCargaId(c.id)
      setArchivo(null)
      if (entrada.current) entrada.current.value = ''
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setEnviando(false)
    }
  }

  function otra() {
    setCargaId(null)
    setFin(null)
    setFalla(null)
    setPasos({})
    setProgreso(null)
    setError(null)
  }

  const enCurso = cargaId !== null && !fin && !falla
  const porcentaje =
    progreso && progreso.total > 0 ? Math.round((progreso.hechos / progreso.total) * 100) : 0
  const minutos =
    progreso?.segundos_restantes != null
      ? Math.max(1, Math.ceil(progreso.segundos_restantes / 60))
      : null
  const reporteDeFin = fin?.cuadra ? fin.statement_id : undefined
  const reporteDeFalla = falla?.statement_id

  return (
    <section className="carga">
      <div className="encabezado-seccion">
        <div>
          <h1>Cargar un resumen</h1>
          <p className="bajada">
            Se lee, se verifica que cuadre al centavo y se clasifica en esta máquina. El archivo no
            queda guardado: en la base queda el resumen, igual que al cargarlo por terminal.
          </p>
        </div>
      </div>

      {error && (
        <p className="aviso aviso-error" role="alert">
          {error}
        </p>
      )}

      {cargaId === null ? (
        <>
          <label
            className={`zona-carga${arrastrando ? ' zona-activa' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setArrastrando(true)
            }}
            onDragLeave={() => setArrastrando(false)}
            onDrop={(e) => {
              e.preventDefault()
              setArrastrando(false)
              const elegido = e.dataTransfer.files[0]
              if (elegido) setArchivo(elegido)
            }}
          >
            <input
              ref={entrada}
              type="file"
              accept=".pdf,.csv,application/pdf,text/csv"
              className="solo-lectores"
              aria-label="Archivo del resumen"
              onChange={(e) => setArchivo(e.target.files?.[0] ?? null)}
            />
            <strong>{archivo ? archivo.name : 'Elegí o arrastrá un resumen'}</strong>
            <span className="detalle">
              {archivo
                ? `${Math.ceil(archivo.size / 1024)} KB`
                : 'PDF de Mercado Pago, o CSV de un banco con perfil. Hasta 20 MB.'}
            </span>
          </label>

          <label className="opcion">
            <input
              type="checkbox"
              checked={conModelo}
              onChange={(e) => setConModelo(e.target.checked)}
            />
            <span>
              <strong>Clasificar también con el modelo local</strong>
              <span className="detalle">
                Lo que no resuelvan la memoria ni la evidencia pasa por la flota de dos agentes, en
                la GPU. Cargar el modelo lleva cerca de un minuto y cada movimiento, algunos
                segundos más. Lo que los agentes no acuerden queda para revisar.
              </span>
            </span>
          </label>

          <button
            type="button"
            className="boton-principal"
            disabled={!archivo || enviando}
            onClick={enviar}
          >
            {enviando ? 'Enviando…' : 'Cargar'}
          </button>
        </>
      ) : (
        <>
          <p className="detalle" aria-live="polite">
            {enCurso ? 'Cargando' : 'Carga de'} <strong>{nombre}</strong>
          </p>
          <ol className="pasos">
            {PASOS.filter((p) => p.paso !== 'modelo' || pasos.modelo).map((p) => {
              const actual = pasos[p.paso]
              // Si la carga falló, el paso que estaba en curso es el que falló.
              const estado =
                falla && actual?.estado === 'en_curso' ? 'fallo' : (actual?.estado ?? 'pendiente')
              return (
                <li key={p.paso} className={`paso paso-${estado}`}>
                  <span className="paso-icono" aria-hidden="true">
                    {ICONO[estado]}
                  </span>
                  <span>
                    <strong>{p.titulo}</strong>
                    {actual && <span className="detalle"> · {actual.detalle}</span>}
                  </span>
                </li>
              )
            })}
          </ol>

          {progreso && pasos.modelo?.estado === 'en_curso' && (
            <div className="cobertura">
              <div className="cobertura-texto">
                <strong>{progreso.hechos}</strong> de{' '}
                {plural(progreso.total, 'movimiento', 'movimientos')}
                {minutos !== null && ` · faltan unos ${minutos} min`}
              </div>
              <div className="cobertura-barra" aria-hidden="true">
                <div style={{ width: `${porcentaje}%` }} />
              </div>
            </div>
          )}

          {fin && (
            <div className={`sello ${fin.cuadra ? 'sello-ok' : 'sello-mal'}`} role="status">
              {fin.cuadra ? '✓ Cuadra: ' : '✗ No cuadra: '}
              {fin.detalle}
            </div>
          )}
          {fin?.cuadra && (
            <p className="detalle">
              Este resumen:{' '}
              {Object.entries(fin.clasificacion)
                .map(([via, n]) => `${n} ${VIA[via] ?? via}`)
                .join(' · ')}
              . Para revisar, sumando todos los resúmenes:{' '}
              {plural(fin.pendientes.movimientos, 'movimiento', 'movimientos')}.
            </p>
          )}
          {fin && !fin.cuadra && (
            <p className="aviso aviso-error">
              Quedó guardado como descuadrado y no se clasifica: sus movimientos no son de fiar.
            </p>
          )}

          {falla && (
            <div className="aviso aviso-error" role="alert">
              <strong>{MOTIVO[falla.motivo]}.</strong> {falla.mensaje}
            </div>
          )}

          {!enCurso && (
            <div className="acciones">
              {fin?.cuadra && fin.pendientes.movimientos > 0 && (
                <button type="button" className="boton-principal" onClick={irARevision}>
                  Ir a revisión
                </button>
              )}
              {reporteDeFin !== undefined && (
                <button type="button" onClick={() => irAReporte(reporteDeFin)}>
                  Ver el reporte
                </button>
              )}
              {reporteDeFalla !== undefined && (
                <button type="button" onClick={() => irAReporte(reporteDeFalla)}>
                  Ver su reporte
                </button>
              )}
              <button type="button" onClick={otra}>
                Cargar otro
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
