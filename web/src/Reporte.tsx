import { useEffect, useMemo, useState } from 'react'
import { api, mensajeDe } from './api'
import { esNegativo, fecha, magnitud, pesos, plural } from './formato'
import type { Reporte as DatosReporte, ResumenItem, TipoLinea } from './tipos'

const TIPO: Record<TipoLinea, string> = {
  ingreso: 'Ingreso',
  gasto: 'Gasto',
  interno: 'Interno',
}

export default function Reporte({ irARevision }: { irARevision: () => void }) {
  const [resumenes, setResumenes] = useState<ResumenItem[] | null>(null)
  const [elegido, setElegido] = useState<number | null>(null)
  const [reporte, setReporte] = useState<DatosReporte | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let vigente = true
    api
      .resumenes()
      .then((lista) => {
        if (!vigente) return
        setResumenes(lista)
        const primero = lista.find((r) => r.estado === 'cuadrado')
        if (primero) setElegido(primero.id)
      })
      .catch((e: unknown) => vigente && setError(mensajeDe(e)))
    return () => {
      vigente = false
    }
  }, [])

  useEffect(() => {
    if (elegido === null) return
    let vigente = true
    setReporte(null)
    setError(null)
    api
      .reporte(elegido)
      .then((datos) => vigente && setReporte(datos))
      .catch((e: unknown) => vigente && setError(mensajeDe(e)))
    return () => {
      vigente = false
    }
  }, [elegido])

  // Ancho de barra relativo al mayor de su mismo tipo. Sólo visual.
  const maximos = useMemo(() => {
    const m: Record<TipoLinea, number> = { ingreso: 0, gasto: 0, interno: 0 }
    for (const l of reporte?.por_categoria ?? []) {
      m[l.tipo] = Math.max(m[l.tipo], magnitud(l.monto))
    }
    return m
  }, [reporte])

  if (!resumenes) {
    return error ? (
      <p className="aviso aviso-error" role="alert">{error}</p>
    ) : (
      <p className="cargando">Cargando resúmenes…</p>
    )
  }

  if (resumenes.length === 0) {
    return (
      <div className="vacio">
        <h1>Todavía no hay resúmenes</h1>
        <p>
          Cargá uno con <code>python -m tools.ingerir ruta/al/resumen.pdf</code>.
        </p>
      </div>
    )
  }

  const cobertura = reporte?.cobertura
  const porcentaje = cobertura && cobertura.movimientos > 0
    ? Math.round((cobertura.resueltos / cobertura.movimientos) * 100)
    : 0

  return (
    <section>
      <div className="encabezado-seccion">
        <div>
          <h1>Reporte del mes</h1>
          <p className="bajada">
            Los movimientos internos —reservas y transferencias entre tus cuentas— no cuentan como
            gasto ni como ingreso.
          </p>
        </div>
        <label className="selector">
          <span>Resumen</span>
          <select
            value={elegido ?? ''}
            onChange={(e) => setElegido(Number(e.target.value))}
          >
            {resumenes.map((r) => (
              <option key={r.id} value={r.id} disabled={r.estado !== 'cuadrado'}>
                {fecha(r.periodo_desde)} a {fecha(r.periodo_hasta)} · {r.banco}
                {r.estado !== 'cuadrado' ? ' (no cuadra)' : ''}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <p className="aviso aviso-error" role="alert">
          {error}
        </p>
      )}
      {!reporte && !error && <p className="cargando">Armando el reporte…</p>}

      {reporte && cobertura && (
        <>
          <div className={`sello ${reporte.cuadra ? 'sello-ok' : 'sello-mal'}`} role="status">
            {reporte.cuadra
              ? '✓ Cuadra con el resumen, al centavo'
              : `✗ No cuadra con el resumen: diferencia de ${pesos(reporte.diferencia)}`}
          </div>

          <div className="totales">
            <Tile titulo="Ingresos" monto={reporte.totales.ingresos} />
            <Tile titulo="Gastos" monto={reporte.totales.gastos} />
            <Tile titulo="Neto" monto={reporte.totales.neto} destacado />
            <Tile titulo="Movimientos internos" monto={reporte.totales.internos} tenue />
            <Tile titulo="Sin clasificar" monto={reporte.totales.sin_clasificar} tenue />
          </div>

          <div className="cobertura">
            <div className="cobertura-texto">
              <strong>{cobertura.resueltos}</strong> de {plural(cobertura.movimientos, 'movimiento', 'movimientos')} clasificados
            </div>
            <div className="cobertura-barra" aria-hidden="true">
              <div style={{ width: `${porcentaje}%` }} />
            </div>
          </div>

          {reporte.devoluciones > 0 && (
            <p className="nota">
              {plural(reporte.devoluciones, 'devolución unida', 'devoluciones unidas')} a su pago:
              restan del gasto de su categoría, no cuentan como ingreso.
            </p>
          )}

          {cobertura.pendientes > 0 && (
            <div className="aviso aviso-pendiente">
              <p>
                Faltan {plural(cobertura.pendientes, 'movimiento', 'movimientos')} por clasificar
                ({pesos(reporte.totales.sin_clasificar)}): hasta que los revises, los gastos y los
                ingresos están incompletos.
              </p>
              <button type="button" onClick={irARevision}>
                Ir a revisión
              </button>
            </div>
          )}

          {reporte.por_categoria.length > 0 ? (
            <div className="tabla-envoltura">
              <table className="tabla">
                <thead>
                  <tr>
                    <th scope="col">Categoría</th>
                    <th scope="col">Tipo</th>
                    <th scope="col" className="num">Mov.</th>
                    <th scope="col" className="num">Monto</th>
                    <th scope="col" className="columna-barra">
                      <span className="solo-lectores">Proporción</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {reporte.por_categoria.map((l) => (
                    <tr key={`${l.tipo}-${l.categoria}`}>
                      <th scope="row">{l.categoria}</th>
                      <td>
                        <span className={`tipo tipo-${l.tipo}`}>{TIPO[l.tipo]}</span>
                      </td>
                      <td className="num">{l.movimientos}</td>
                      <td className={`num monto ${esNegativo(l.monto) ? 'negativo' : 'positivo'}`}>
                        {pesos(l.monto)}
                      </td>
                      <td className="columna-barra" aria-hidden="true">
                        <div className={`barra barra-${l.tipo}`}>
                          <div
                            style={{
                              width: `${maximos[l.tipo] ? (magnitud(l.monto) / maximos[l.tipo]) * 100 : 0}%`,
                            }}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="vacio-filtro">Todavía no hay movimientos clasificados en este resumen.</p>
          )}
        </>
      )}
    </section>
  )
}

function Tile({
  titulo,
  monto,
  destacado = false,
  tenue = false,
}: {
  titulo: string
  monto: string
  destacado?: boolean
  tenue?: boolean
}) {
  return (
    <div className={`tile${destacado ? ' tile-destacado' : ''}${tenue ? ' tile-tenue' : ''}`}>
      <span className="tile-titulo">{titulo}</span>
      <span className={`tile-monto ${esNegativo(monto) ? 'negativo' : ''}`}>{pesos(monto)}</span>
    </div>
  )
}
