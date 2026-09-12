import { useState } from 'react'
import Reporte from './Reporte'
import Revision from './Revision'

type Vista = 'revision' | 'reporte'

export default function App() {
  const [vista, setVista] = useState<Vista>('revision')

  return (
    <div className="app">
      <header className="cabecera">
        <div className="marca">
          <span className="marca-nombre">Centavo</span>
          <span className="marca-nota">local · nada sale de esta máquina</span>
        </div>
        <nav className="pestanas" aria-label="Secciones">
          <button
            type="button"
            className={vista === 'revision' ? 'activa' : ''}
            aria-current={vista === 'revision' ? 'page' : undefined}
            onClick={() => setVista('revision')}
          >
            Revisión
          </button>
          <button
            type="button"
            className={vista === 'reporte' ? 'activa' : ''}
            aria-current={vista === 'reporte' ? 'page' : undefined}
            onClick={() => setVista('reporte')}
          >
            Reporte del mes
          </button>
        </nav>
      </header>

      <main className="contenido">
        {vista === 'revision' ? (
          <Revision />
        ) : (
          <Reporte irARevision={() => setVista('revision')} />
        )}
      </main>
    </div>
  )
}
