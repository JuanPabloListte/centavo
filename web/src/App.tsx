import { useState } from 'react'
import Cargar from './Cargar'
import Proyeccion from './Proyeccion'
import Reporte from './Reporte'
import Resueltos from './Resueltos'
import Revision from './Revision'

type Vista = 'cargar' | 'revision' | 'resueltos' | 'reporte' | 'proyeccion'

const SOLAPAS: { vista: Vista; titulo: string }[] = [
  { vista: 'cargar', titulo: 'Cargar' },
  { vista: 'revision', titulo: 'Revisión' },
  { vista: 'resueltos', titulo: 'Resueltos' },
  { vista: 'reporte', titulo: 'Reporte del mes' },
  { vista: 'proyeccion', titulo: 'Proyección' },
]

export default function App() {
  const [vista, setVista] = useState<Vista>('revision')
  const [resumenParaReporte, setResumenParaReporte] = useState<number | null>(null)

  const irARevision = () => setVista('revision')
  const irACargar = () => setVista('cargar')
  const irAReporte = (statementId: number) => {
    setResumenParaReporte(statementId)
    setVista('reporte')
  }

  return (
    <div className="app">
      <header className="cabecera">
        <div className="marca">
          <span className="marca-nombre">Centavo</span>
          <span className="marca-nota">local · nada sale de esta máquina</span>
        </div>
        <nav className="pestanas" aria-label="Secciones">
          {SOLAPAS.map((s) => (
            <button
              key={s.vista}
              type="button"
              className={vista === s.vista ? 'activa' : ''}
              aria-current={vista === s.vista ? 'page' : undefined}
              onClick={() => setVista(s.vista)}
            >
              {s.titulo}
            </button>
          ))}
        </nav>
      </header>

      <main className="contenido">
        {vista === 'cargar' && <Cargar irARevision={irARevision} irAReporte={irAReporte} />}
        {vista === 'revision' && <Revision />}
        {vista === 'resueltos' && <Resueltos />}
        {vista === 'reporte' && (
          <Reporte irARevision={irARevision} irACargar={irACargar} resumenInicial={resumenParaReporte} />
        )}
        {vista === 'proyeccion' && <Proyeccion irARevision={irARevision} />}
      </main>
    </div>
  )
}
