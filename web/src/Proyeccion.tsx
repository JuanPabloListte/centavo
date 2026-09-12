import { useEffect, useState } from 'react'
import { api, mensajeDe } from './api'
import { esNegativo, mesLargo, NOMBRE_TIPO, pesos, plural } from './formato'
import type { Proyeccion as DatosProyeccion } from './tipos'

/** El mes que viene, en piezas que se pueden sumar: recurrentes fijos con su
 *  último monto, promedio del gasto variable ya clasificado, y lo sin
 *  clasificar aparte. Todo viene calculado del servidor; acá sólo se muestra. */
export default function Proyeccion({ irARevision }: { irARevision: () => void }) {
  const [datos, setDatos] = useState<DatosProyeccion | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let vigente = true
    api
      .proyeccion()
      .then((p) => vigente && setDatos(p))
      .catch((e: unknown) => vigente && setError(mensajeDe(e)))
    return () => {
      vigente = false
    }
  }, [])

  if (error) return <p className="aviso aviso-error" role="alert">{error}</p>
  if (!datos) return <p className="cargando">Calculando la proyección…</p>

  if (!datos.mes_objetivo || !datos.totales || !datos.sin_clasificar) {
    return (
      <div className="vacio">
        <h1>Todavía no hay meses cargados</h1>
        <p>La proyección sale de los resúmenes cuadrados. Cargá uno con <code>tools.ingerir</code>.</p>
      </div>
    )
  }

  const { totales, sin_clasificar, criterios } = datos
  const hayIngresos = !esNegativo(totales.recurrentes_ingresos) && totales.recurrentes_ingresos !== '0.00'

  return (
    <section>
      <div className="encabezado-seccion">
        <div>
          <h1>Proyección de {mesLargo(datos.mes_objetivo)}</h1>
          <p className="bajada">
            Aritmética sobre lo cargado hasta {mesLargo(datos.ultimo_mes!)}: los recurrentes fijos
            con su último monto, más el promedio de {criterios.meses_promedio} meses del gasto
            variable que ya clasificaste. Lo que falta clasificar va aparte.
          </p>
        </div>
      </div>

      <div className="totales">
        <Tile titulo="Gastos proyectados" monto={totales.gastos_proyectados} destacado />
        <Tile titulo="Recurrentes fijos" monto={totales.recurrentes_gastos} />
        <Tile titulo="Variable, ya clasificado" monto={totales.variable_gastos} />
        <Tile titulo="Sin clasificar" monto={totales.sin_clasificar_gastos} tenue />
        {hayIngresos && <Tile titulo="Ingresos recurrentes" monto={totales.recurrentes_ingresos} />}
      </div>

      {sin_clasificar.movimientos_por_mes > 0 && (
        <div className="aviso aviso-pendiente">
          <p>
            Quedan en promedio {sin_clasificar.movimientos_por_mes} movimientos por mes sin
            clasificar, por {pesos(sin_clasificar.promedio)}: hasta que los revises, el gasto
            variable por categoría está incompleto y esa plata se proyecta como un bloque.
          </p>
          <button type="button" onClick={irARevision}>
            Ir a revisión
          </button>
        </div>
      )}

      <h2 className="subtitulo">Recurrentes esperados</h2>
      {datos.recurrentes.length === 0 ? (
        <p className="vacio-filtro">
          Ninguna contraparte cumple los criterios todavía: hacen falta {criterios.meses_minimos}{' '}
          meses seguidos con un movimiento por mes.
        </p>
      ) : (
        <div className="tabla-envoltura">
          <table className="tabla">
            <thead>
              <tr>
                <th scope="col">Contraparte</th>
                <th scope="col">Categoría</th>
                <th scope="col" className="num">Día</th>
                <th scope="col" className="num">Meses</th>
                <th scope="col" className="num">Tendencia</th>
                <th scope="col" className="num">Monto esperado</th>
              </tr>
            </thead>
            <tbody>
              {datos.recurrentes.map((r) => (
                <tr key={r.clave}>
                  <th scope="row">
                    {r.nombre}
                    <span className="detalle"> · {NOMBRE_TIPO[r.tipo] ?? r.tipo}</span>
                  </th>
                  <td>{r.categoria ?? <span className="detalle">sin categoría todavía</span>}</td>
                  <td className="num">{r.dia_esperado}</td>
                  <td className="num">{r.meses}</td>
                  <td className="num">{r.tendencia ?? '—'}</td>
                  <td className={`num monto ${esNegativo(r.monto_esperado) ? 'negativo' : 'positivo'}`}>
                    {pesos(r.monto_esperado)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="subtitulo">Gasto variable por categoría, promedio mensual</h2>
      {datos.variable_por_categoria.length === 0 ? (
        <p className="vacio-filtro">
          Todavía no hay gastos clasificados en {datos.meses_base.map(mesLargo).join(', ')}.
        </p>
      ) : (
        <div className="tabla-envoltura">
          <table className="tabla">
            <thead>
              <tr>
                <th scope="col">Categoría</th>
                <th scope="col" className="num">Meses con datos</th>
                <th scope="col" className="num">Promedio</th>
              </tr>
            </thead>
            <tbody>
              {datos.variable_por_categoria.map((v) => (
                <tr key={v.categoria}>
                  <th scope="row">{v.categoria}</th>
                  <td className="num">{v.meses_con_datos} de {datos.meses_base.length}</td>
                  <td className="num monto negativo">{pesos(v.promedio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="nota">
        Un recurrente fijo aparece {plural(criterios.meses_minimos, 'mes seguido', 'meses seguidos')}{' '}
        hasta el último cargado, una vez por mes, con el mismo signo, en días parecidos (hasta{' '}
        {criterios.dias_tolerancia} de diferencia) y sin saltos de más del{' '}
        {Math.round(Number(criterios.salto_maximo) * 100)}% de un mes al siguiente.
      </p>
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
