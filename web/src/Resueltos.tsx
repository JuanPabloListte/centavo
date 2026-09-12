import { useEffect, useMemo, useState } from 'react'
import { api, mensajeDe } from './api'
import { esNegativo, fecha, NOMBRE_TIPO, NOMBRE_VIA, pesos, plural } from './formato'
import type { Categoria, GrupoResuelto } from './tipos'

/** Lo que ya tiene categoría, para cambiarla. Una decisión pisa lo que haya:
 *  la memoria, la evidencia o el modelo. Después de cambiar se vuelve a pedir
 *  la lista al servidor: es él quien sabe cómo quedó cada grupo. */
export default function Resueltos() {
  const [grupos, setGrupos] = useState<GrupoResuelto[] | null>(null)
  const [categorias, setCategorias] = useState<Categoria[]>([])
  const [elegidas, setElegidas] = useState<Record<string, string>>({})
  const [filtro, setFiltro] = useState('')
  const [enviando, setEnviando] = useState<string | null>(null)
  const [confirmacion, setConfirmacion] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let vigente = true
    Promise.all([api.resueltos(), api.categorias()])
      .then(([datos, cats]) => {
        if (!vigente) return
        setGrupos(datos.grupos)
        setCategorias(cats)
      })
      .catch((e: unknown) => vigente && setError(mensajeDe(e)))
    return () => {
      vigente = false
    }
  }, [])

  const visibles = useMemo(() => {
    if (!grupos) return []
    const buscado = filtro.trim().toLowerCase()
    if (!buscado) return grupos
    return grupos.filter(
      (g) =>
        g.nombre.toLowerCase().includes(buscado) ||
        g.contraparte.toLowerCase().includes(buscado) ||
        g.categoria.toLowerCase().includes(buscado) ||
        (NOMBRE_TIPO[g.tipo] ?? g.tipo).toLowerCase().includes(buscado),
    )
  }, [grupos, filtro])

  async function cambiar(grupo: GrupoResuelto) {
    const categoria = elegidas[grupo.clave]
    if (!categoria || categoria === grupo.categoria) return
    setEnviando(grupo.clave)
    setError(null)
    try {
      const r = await api.decidir(grupo.clave, categoria)
      const datos = await api.resueltos()
      setGrupos(datos.grupos)
      setElegidas((p) => {
        const { [grupo.clave]: _quitada, ...resto } = p
        return resto
      })
      setConfirmacion(
        `${grupo.nombre}: ${grupo.categoria} → ${categoria}, ` +
          `${plural(r.cambiados, 'movimiento', 'movimientos')}` +
          (r.se_aprende ? '. Queda en memoria.' : '. Sin contraparte: no se aprende.'),
      )
    } catch (e) {
      setError(mensajeDe(e))
    } finally {
      setEnviando(null)
    }
  }

  if (!grupos) {
    return error ? (
      <p className="aviso aviso-error" role="alert">{error}</p>
    ) : (
      <p className="cargando">Cargando lo resuelto…</p>
    )
  }

  if (grupos.length === 0) {
    return (
      <div className="vacio">
        <h1>Todavía no hay nada resuelto</h1>
        <p>Lo que decidas en la bandeja, y lo que resuelva la evidencia, aparece acá.</p>
      </div>
    )
  }

  const movimientos = grupos.reduce((n, g) => n + g.cantidad, 0)
  const comunes = categorias.filter((c) => !c.interna)
  const internas = categorias.filter((c) => c.interna)

  return (
    <section>
      <div className="encabezado-seccion">
        <div>
          <h1>Resueltos</h1>
          <p className="bajada">
            Lo que ya tiene categoría. Cambiarla pisa la decisión anterior, venga de vos, de la
            evidencia o del modelo, y queda en memoria para los resúmenes que vengan.
          </p>
        </div>
        <p className="contador" aria-live="polite">
          <strong>{grupos.length}</strong> contrapartes · <strong>{movimientos}</strong> movimientos
        </p>
      </div>

      <div className="herramientas">
        <input
          type="search"
          placeholder="Buscar contraparte, categoría o tipo…"
          value={filtro}
          onChange={(e) => setFiltro(e.target.value)}
          aria-label="Buscar contraparte, categoría o tipo"
        />
        {confirmacion && (
          <p className="confirmacion" role="status">
            ✓ {confirmacion}
          </p>
        )}
      </div>

      {error && (
        <p className="aviso aviso-error" role="alert">
          {error}
        </p>
      )}

      <ul className="grupos">
        {visibles.map((g) => {
          const elegida = elegidas[g.clave] ?? g.categoria
          return (
            <li key={`${g.clave}|${g.categoria}`} className="grupo">
              <div className="grupo-cabeza">
                <span className="etiqueta">{NOMBRE_TIPO[g.tipo] ?? g.tipo}</span>
                <span className={`monto ${esNegativo(g.total) ? 'negativo' : 'positivo'}`}>
                  {pesos(g.total)}
                </span>
              </div>
              <h2 className="contraparte">{g.nombre}</h2>
              <p className="detalle">
                <strong>{g.categoria}</strong> · {NOMBRE_VIA[g.via] ?? g.via}
              </p>
              <p className="detalle">
                {plural(g.cantidad, 'movimiento', 'movimientos')} ·{' '}
                {g.desde === g.hasta ? fecha(g.desde) : `${fecha(g.desde)} a ${fecha(g.hasta)}`}
              </p>
              {g.ejemplos[0] && <p className="ejemplo">{g.ejemplos[0]}</p>}
              {g.via === 'evidencia' && (
                <p className="nota">
                  La resolvió la evidencia del texto del resumen: cambiarla pisa lo que el resumen
                  dice.
                </p>
              )}
              {!g.memorizable && (
                <p className="nota">Sin contraparte: se cambia, pero no se aprende.</p>
              )}
              <div className="decision">
                <select
                  value={elegida}
                  onChange={(e) => setElegidas((p) => ({ ...p, [g.clave]: e.target.value }))}
                  aria-label={`Nueva categoría para ${g.nombre}`}
                >
                  <optgroup label="Gastos e ingresos">
                    {comunes.map((c) => (
                      <option key={c.nombre} value={c.nombre}>
                        {c.nombre}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="Movimientos internos">
                    {internas.map((c) => (
                      <option key={c.nombre} value={c.nombre}>
                        {c.nombre}
                      </option>
                    ))}
                  </optgroup>
                </select>
                <button
                  type="button"
                  onClick={() => cambiar(g)}
                  disabled={elegida === g.categoria || enviando !== null}
                  aria-label={`Cambiar categoría de ${g.nombre}`}
                >
                  {enviando === g.clave ? 'Cambiando…' : 'Cambiar'}
                </button>
              </div>
            </li>
          )
        })}
      </ul>

      {visibles.length === 0 && (
        <p className="vacio-filtro">Ninguna contraparte coincide con “{filtro}”.</p>
      )}
    </section>
  )
}
