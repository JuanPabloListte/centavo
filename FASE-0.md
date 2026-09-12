# Centavo — Fase 0

**Estado: terminada contra resúmenes sintéticos.** `pytest` pasa 7/7 y el pipeline persiste
en Postgres. Lo que falta es un banco real — ver *Agregar un banco* al final.

---

## Qué hace

Ingiere un resumen (CSV o PDF), lo normaliza a movimientos, y **valida que la suma cuadre
con lo que el resumen declara.** Si no cuadra, queda registrado como `descuadrado` y las
fases siguientes no lo leen.

Sin IA de ningún tipo: es un parser y una resta.

## Correrlo

```bash
cp .env.example .env
docker compose up -d

cd api
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt

python -m tools.generar_fixtures    # resúmenes sintéticos
pytest                              # 7 passed
uvicorn app.main:app --reload       # POST /api/ingest {"path": "..."}
```

Postgres corre en Docker; el código Python corre local en un venv. La app se containeriza
en la fase 4 — iterar contra un venv es más rápido que reconstruir una imagen por cambio.

> **Trampa de Docker:** `db/schema.sql` corre **una sola vez**, al crear el volumen. Si
> cambiás el esquema, `docker compose restart` no lo reaplica. Hay que hacer
> `docker compose down -v && docker compose up -d`. Cuando haya datos que perder, van
> migraciones de verdad. *Desde la fase 4 las hay: `db/migraciones/`, aplicadas con
> `python -m tools.migrar`.*

---

## Las dos formas de cierre

El primer diseño asumía que todo resumen declara **un total**. Es falso, y modelarlo mal
habría obligado a reescribir los parsers después. Hay dos formas, las dos soportadas:

| | Quién | Qué declara | Qué tiene que cerrar |
|---|---|---|---|
| `total` | Tarjeta de crédito | "Total a pagar" | `total == suma(movimientos)` |
| `saldos` | Cuenta bancaria | Saldo inicial y final | `saldo_final - saldo_inicial == suma(movimientos)` |

Está modelado como unión discriminada (`CierrePorTotal` / `CierrePorSaldos`), así que es
imposible meter un saldo final en un campo llamado "total" y que la compuerta compare
cualquier cosa. En la base, un `CHECK` obliga a que las columnas correspondan al tipo —
verificado: rechaza la mezcla.

---

## Las cuatro decisiones que sostienen todo

**1. Plata en `Decimal`, nunca `float`.** En Postgres, `NUMERIC(14,2)`. Un float produce
`1234.5599999999999` y la cuadratura deja de significar algo.

**2. Convención de signo única.** Negativo = débito (sale), positivo = crédito (entra). El
perfil traduce desde como sea que lo exprese el banco: columna única con signo, columnas
débito/crédito separadas, o paréntesis.

**3. Idempotencia por `sha256`** del archivo, con índice único. Reingerir el mismo archivo
levanta `YaIngerido`, no duplica. Verificado.

**4. La compuerta marca, no borra.** Un resumen descuadrado se guarda con
`estado = 'descuadrado'` para que quede el registro de qué falló y por cuánto. De la fase 1
en adelante, todo consulta sólo `estado = 'cuadrado'`.

---

## Estructura

```
api/app/
├── models.py         contratos Pydantic; la unión discriminada del cierre
├── parsers/
│   ├── base.py       parse_monto_ar, parse_fecha, sha256, dataclass Perfil
│   ├── perfiles.py   el registro de bancos  ← acá se agrega uno nuevo
│   ├── csv_parser.py genérico, manejado por perfil
│   ├── pdf_parser.py pdfplumber: extract_table primero, texto como fallback
│   └── __init__.py   parsear(path): detecta por contenido, no por nombre
├── normalize.py      ResumenCrudo -> Resumen
├── balance.py        la compuerta (12 líneas; es todo el criterio de aceptación)
├── pipeline.py       procesar(path) -> (Resumen, ResultadoCuadratura)
├── store.py          persistencia idempotente
└── main.py           la API local (desde la fase 4, bajo /api)
api/tools/
└── generar_fixtures.py
```

**Los parsers no son específicos de un banco: los perfiles sí.** Agregar un banco es
agregar un `Perfil`, no escribir código. Eso es a propósito — es el mismo principio que en
la fase 3 se convierte en "layouts aprendidos": la maquetación es dato, no código.

---

## Los fixtures sintéticos

`python -m tools.generar_fixtures` produce tres archivos deterministas (semilla fija):

| Archivo | Cierre | Importe |
|---|---|---|
| `tarjeta_visa.csv` | total | columna única con signo |
| `cuenta_corriente.csv` | saldos | columnas débito/crédito |
| `tarjeta_visa.pdf` | total | tabla en PDF con capa de texto |

Traen a propósito lo que las fases siguientes van a tener que detectar: suscripciones con
monto fijo y día fijo, un plan de cuotas (`CUOTA 4/12`), descripciones sucias tipo
`MERPAGO*KIOSCO LA ESQ`, y un crédito para que el signo se ejercite en las dos direcciones.

El PDF se arma como HTML y se imprime con Chrome headless. Sale un PDF con capa de texto
real —lo que pdfplumber necesita— sin agregar una dependencia de Python sólo para fixtures.

> **Esto prueba que el pipeline funciona. NO prueba que funcione contra un banco real.**
> La maquetación de un resumen de verdad es otra cosa, y ahí es donde el parser de PDF se
> va a tener que ganar el sueldo.

---

## Agregar un banco real

Es lo único que falta, y es un trámite:

1. Poné el resumen en `api/tests/fixtures/`.
2. Agregá un `Perfil` en `app/parsers/perfiles.py`: el marcador que lo identifica, los
   nombres de las columnas, y las regexps para encontrar el cierre y el período.
3. `pytest`. El test recorre todo lo que haya en `fixtures/`, así que el nuevo entra solo.
4. Si falla, el mensaje dice el esperado, el calculado y la diferencia. **Se corrige el
   perfil, nunca el test.**

Si el resumen es un PDF sin tabla detectable, `pdf_parser` cae al camino de texto
(`fecha  descripción  importe` por renglón). Si un banco cae siempre ahí, conviene darle un
perfil con posiciones de columna en vez de pelear con la regexp.

---

## Qué sigue

Fase 1: Ollama con Qwen3 4B y **un** agente, el categorizador. Y lo que nadie espera —
hacen falta unos doscientos movimientos etiquetados a mano para poder medir.
