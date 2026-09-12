import { useEffect, useMemo, useState } from 'react'
import { api, mensajeDe } from './api'
import { esNegativo, fecha, NOMBRE_TIPO, pesos, plural } from './formato'
import type { Categoria, Grupo } from './tipos'

export default function Revision() {
  const [grupos, setGrupos] = useState<Grupo[] | null>(null)
  const [categorias, setCategorias] = useState<Categoria[]>([])
  const [elegidas, setElegidas] = useState<Record<string, string>>({})
  const [filtro, setFiltro] = useState('')
  const [enviando, setEnviando] = useState<string | null>(null)
  const [confirmacion, setConfirmacion] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let vigente = true
    Promise.all([api.grupos(), api.categorias()])
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
        (NOMBRE_TIPO[g.tipo] ?? g.tipo).toLowerCase().includes(buscado),
    )
  }, [grupos, filtro])

  async function aplicar(grupo: Grupo) {
    const categoria = elegidas[grupo.clave]
    if (!categoria) return
    setEnviando(grupo.clave)
    setError(null)
    try {
      const r = await api.decidir(grupo.clave, categoria)
      setGrupos((previos) => previos?.filter((g) => g.clave !== grupo.clave) ?? null)
      setConfirmacion(
        `${grupo.nombre} → ${categoria}: ${plural(r.cambiados, 'movimiento', 'movimientos')}` +
          (r.se_aprende ? ', y queda en memoria.' : '. Sin contraparte: no se aprende.'),
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
      <p className="cargando">Cargando lo pendiente…</p>
    )
  }

  if (grupos.length === 0) {
    return (
      <div className="vacio">
        <h1>No hay nada pendiente</h1>
        <p>Todo lo cargado está clasificado. El reporte del mes ya está completo.</p>
        {confirmacion && <p className="confirmacion" role="status">✓ {confirmacion}</p>}
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
          <h1>Revisión</h1>
          <p className="bajada">
            Una decisión resuelve todos los movimientos de esa contraparte y queda en memoria para
            los resúmenes que vengan.
          </p>
        </div>
        <p className="contador" aria-live="polite">
          <strong>{grupos.length}</strong> contrapartes · <strong>{movimientos}</strong> movimientos
        </p>
      </div>

      <div className="herramientas">
        <input
          type="search"
          placeholder="Buscar contraparte o tipo…"
          value={filtro}
          onChange={(e) => setFiltro(e.target.value)}
          aria-label="Buscar contraparte o tipo"
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
        {visibles.map((g) => (
          <li key={g.clave} className="grupo">
            <div className="grupo-cabeza">
              <span className="etiqueta">{NOMBRE_TIPO[g.tipo] ?? g.tipo}</span>
              <span className={`monto ${esNegativo(g.total) ? 'negativo' : 'positivo'}`}>
                {pesos(g.total)}
              </span>
            </div>
            <h2 className="contraparte">{g.nombre}</h2>
            <p className="detalle">
              {plural(g.cantidad, 'movimiento', 'movimientos')} ·{' '}
              {g.desde === g.hasta ? fecha(g.desde) : `${fecha(g.desde)} a ${fecha(g.hasta)}`}
            </p>
            {g.ejemplos[0] && <p className="ejemplo">{g.ejemplos[0]}</p>}
            {g.devoluciones > 0 && (
              <p className="nota">
                Incluye {plural(g.devoluciones, 'devolución unida', 'devoluciones unidas')} a su
                pago: se decide todo junto.
              </p>
            )}
            {!g.memorizable && (
              <p className="nota">Sin contraparte: se decide, pero no se aprende.</p>
            )}
            <div className="decision">
              <select
                value={elegidas[g.clave] ?? ''}
                onChange={(e) => setElegidas((p) => ({ ...p, [g.clave]: e.target.value }))}
                aria-label={`Categoría para ${g.nombre}`}
              >
                <option value="" disabled>
                  Elegí una categoría
                </option>
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
                onClick={() => aplicar(g)}
                disabled={!elegidas[g.clave] || enviando !== null}
                aria-label={`Aplicar categoría a ${g.nombre}`}
              >
                {enviando === g.clave ? 'Aplicando…' : 'Aplicar'}
              </button>
            </div>
          </li>
        ))}
      </ul>

      {visibles.length === 0 && (
        <p className="vacio-filtro">Ninguna contraparte coincide con “{filtro}”.</p>
      )}
    </section>
  )
}
