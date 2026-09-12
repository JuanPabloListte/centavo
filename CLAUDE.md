# Centavo

Contador personal, hasta el 12/09/2026 llamado Libro Mayor Local: ingiere resúmenes de cuenta (hoy, el PDF de Mercado Pago), verifica que
cuadren al centavo, clasifica los movimientos y arma el reporte del mes. **Corre entero en la
máquina: ningún movimiento sale a internet.**

**Antes de trabajar, leé [TRASPASO.md](TRASPASO.md):** qué se hizo, en qué estado quedó la base
y las tareas que siguen, en orden. El detalle de cada fase está en `FASE-0.md` a `FASE-4.md` y
en `MERCADO-PAGO.md`.

## Reglas que no se negocian

### Privacidad y costo

- **Sin modelos pagos.** El usuario no tiene presupuesto. El único modelo es local, con Ollama.
- **Ningún componente que vea un movimiento sale de la máquina:** ni APIs externas, ni tiers
  gratuitos, ni servicios en la nube.
- **Sobre datos reales, la salida lleva sólo conteos y banderas.** Nunca nombres, CVU, CUIT,
  descripciones ni montos. Para verificar algo en la base real, un script que cuenta. La
  interfaz se prueba con el esquema `demo`, no con la base real.
- Los PDF reales nunca van a `api/tests/fixtures/` ni a un repo: van en `privado/`, que está en
  `.gitignore`.
- **El repositorio es público** (github.com/JuanPabloListte/centavo). Antes de cada push:
  ningún nombre, monto ni dato de un movimiento real, ni nada personal del usuario, que va en
  `privado/NOTAS.md`. Un ejemplo en la documentación se inventa, no se copia de la base. Cómo
  verificarlo, en TRASPASO.md.
- Si se usa la API de Mercado Pago, el token lo genera y lo guarda el usuario en `.env`. Nunca
  pasa por el chat ni por el código.

### Plata

- `Decimal` en Python y `NUMERIC(14,2)` en Postgres. Nunca `float`.
- En el JSON viaja como texto. La interfaz muestra, no suma.
- Signo único: negativo sale, positivo entra.

### Diseño

- **Determinista primero.** El modelo entra sólo donde hay ambigüedad de lenguaje, y nunca hace
  cuentas.
- **La compuerta manda.** Un resumen que no cuadra no se clasifica ni se reporta, y todo reporte
  tiene que cuadrar con lo que declara el resumen.
- Los movimientos internos (reservas, transferencias entre cuentas propias) no son gasto ni
  ingreso.
- Una devolución unida a su pago no es ingreso: lleva la clave y la categoría del pago y resta
  del gasto. Sin pago cargado, se revisa aparte.
- La memoria es por clave exacta de contraparte, no por parecido. Una decisión del usuario pisa
  a la evidencia y al modelo.
- Ante la duda, a revisión: preguntar es mejor que adivinar.

### Base de datos

- **Tiene cinco meses reales.** Nunca `docker compose down -v`, ni borrar filas, ni reingerir,
  sin pedido explícito del usuario.
- Un cambio de esquema son dos cosas: editar `db/schema.sql`, para una base nueva, y agregar
  `db/migraciones/00N_*.sql`, idempotente, para la que ya existe. Se aplica con
  `python -m tools.migrar` y toca sólo `current_schema()`.
- Los tests de base usan el fixture `db`, un esquema temporal, y nunca escriben en `public`. Si
  un test corre SQL genérico, limitá el `search_path` al esquema temporal.

### Forma de trabajo

- **Git:** rama `main`. Se commitea cada tarea terminada, con los tests pasando. Push sólo al
  remoto que configuró el usuario, nunca forzado; no se crean otros remotos.
- Documentación en castellano rioplatense, con el estilo de los `FASE-*.md`: cada decisión con la
  evidencia que la sostiene, los números sin inflar y lo que el sistema no hace, dicho.
- **Antes de dar algo por terminado:** `pytest` en `api/` (hoy 147 pasan y 1 se saltea),
  `npm run build` en `web/`, y la interfaz probada en el navegador con el esquema `demo`.
- Si el usuario pide una explicación o dice "no ejecutes", no toques nada.

## Entorno

- Windows 11, PowerShell.
- Python 3.14 global, con paquetes instalados con `pip install --user`: el venv que describe el
  README no está armado.
- Node 24.
- Dentro de Postgres, el usuario y la base siguen siendo `libro` y `libro_mayor`, y el volumen de
  Docker `libro-mayor_pgdata`: quedaron de cuando el proyecto se llamaba Libro Mayor, y
  renombrarlos toca la base con datos. Ver TRASPASO.md.
- Docker Desktop lo prende el usuario. `docker compose up -d` desde esta carpeta levanta
  Postgres en 127.0.0.1:5433, la API y la interfaz compilada en http://127.0.0.1:8080. La API
  del contenedor no se publica al host: no choca con la de desarrollo en el 8000. Para probar
  el stack sin datos reales: `CENTAVO_DB_SCHEMA=demo docker compose up -d`.
- Ollama con `qwen2.5:7b` y `llama3.2:3b`.
- Notebook con RTX 3060 de 6 GB y 16 GB de RAM: cualquier servicio nuevo tiene que entrar en ese
  presupuesto.

El usuario tiene otro proyecto, ScalistAI, con sus propios contenedores, uno de ellos con
Ollama. Si el modelo no aparece, verificá qué Ollama responde en `localhost:11434`.

## Comandos

Desde `api/`:

```bash
pytest
python -m tools.migrar                        # migraciones, idempotentes
python -m tools.ingerir ruta/al/resumen.pdf   # parsea, verifica, guarda y clasifica sin modelo
python -m tools.curva                         # memoria entre meses; sólo conteos
python -m tools.corridas                      # últimas ingestas: tiempos, vías y costo; sólo conteos
python -m tools.revisar                       # revisión por terminal
python -m tools.demo                          # rearma el esquema demo con datos sintéticos
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000   # API sobre la base real
python -m uvicorn app.demo:app --host 127.0.0.1 --port 8000   # API sobre el esquema demo
```

Desde `web/`: `npm run dev` (http://127.0.0.1:5173) y `npm run build`.

`.claude/launch.json` define `api-demo` y `web`, para levantar la interfaz de prueba desde el
panel del navegador.

## Mapa

```
api/app/
  parsers/             detección por contenido y perfiles por banco; pdf_coordenadas.py lee Mercado Pago
  models.py            contratos Pydantic; el cierre es por total o por saldos
  normalize.py         filas crudas -> movimientos
  balance.py           la compuerta y la cadena de saldos renglón por renglón
  pipeline.py          procesar(pdf) -> (Resumen, ResultadoCuadratura)
  store.py             persistencia, idempotencia e identidad del movimiento
  devoluciones.py      una devolución se une a su pago por ID de operación y toma su clave
  agents/patrones.py   evidencia determinista, clave de memoria, nombre legible
  agents/categorizador.py, agents/comercio.py   los dos agentes con modelo
  supervisor.py        arbitraje por reglas
  clasificar.py        clasificador solo y flota
  llm.py               cliente de Ollama, con loop de reparación de JSON
  memoria.py           memoria, decisiones, grupos pendientes y resueltos, precisión de la memoria
  reporte.py           reporte del mes
  recurrentes.py       recurrentes fijos por contraparte y proyección del mes siguiente, en piezas
  corridas.py          una fila por ingesta: tiempos, vías y costo del modelo, sin datos
  main.py, demo.py     API local; la misma API sobre el esquema demo
api/tools/             un comando por archivo, más evaluar.py (benchmark de las fases 1 y 2)
api/tests/             conftest.py (fixture db) y un test_*.py por tema
web/src/               App.tsx (solapas), Revision.tsx, Resueltos.tsx, Reporte.tsx, Proyeccion.tsx, api.ts, tipos.ts, formato.ts
db/                    schema.sql y migraciones/
api/Dockerfile, web/Dockerfile, web/nginx.conf, docker-compose.yml   el stack en contenedores
```
