# Centavo

Un contador personal que ingiere resúmenes de banco y tarjeta, los categoriza, detecta
suscripciones y cuotas, y proyecta el flujo del mes. **Corre entero en la máquina: ningún
movimiento sale a internet.** Hasta el 12/09/2026 se llamó Libro Mayor Local.

Estado: **fase 4 en curso.** Cinco meses reales cargados, de abril a agosto, y los cinco
cuadran al centavo. API local y, en el navegador, reporte del mes, bandeja de revisión, corrección de decisiones y
proyección del mes que viene.
139 tests.
Documentos: [FASE-0.md](FASE-0.md) · [FASE-1.md](FASE-1.md) · [FASE-2.md](FASE-2.md) · [MERCADO-PAGO.md](MERCADO-PAGO.md) · [FASE-3.md](FASE-3.md) · [FASE-4.md](FASE-4.md).

## Arrancar

```bash
cp .env.example .env
docker compose up -d

cd api
python -m venv .venv
.venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
pytest

python -m tools.migrar                                         # una base de antes de un cambio de esquema
python -m tools.ingerir ruta/al/resumen.pdf                    # parsea, verifica, guarda y clasifica
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000    # la API local
```

```bash
cd web
npm install
npm run dev                   # http://127.0.0.1:5173 — bandeja de revisión y reporte del mes
```

`python -m tools.revisar` hace la misma revisión por terminal. Para probar la interfaz sin
tus datos: `python -m tools.demo` y `app.demo:app` en lugar de `app.main:app`
([FASE-4.md](FASE-4.md)).

Los resúmenes reales van en `privado/`, que está en `.gitignore`: tienen CVU, CUIT
y nombres de terceros. `tests/fixtures/` es sólo para sintéticos.

Postgres corre en Docker; el código Python corre local en un venv. La app todavía no se
containeriza: iterar contra un venv es mucho más rápido que reconstruir una imagen en cada
cambio.

## El principio rector

El modelo entra **sólo** donde un programa determinista no puede. Parsear, sumar, comparar
fechas, detectar periodicidad, aplicar una regexp: eso es código. El modelo aparece
únicamente donde hay ambigüedad de lenguaje — *¿«MERPAGO\*KIOSCO LA ESQ» y «Kiosco la
Esquina» son el mismo comercio?*

La consecuencia práctica: cuando algo falla, se sabe de qué lado está el error. Un total
que no cuadra es un bug de parseo; una categoría equivocada es una decisión del modelo.
Nunca se depuran las dos cosas a la vez.

## Fases

| | Qué | Entregable |
|---|---|---|
| **0** ✅ | Parseo, normalización, compuerta, persistencia | 7/7 tests; falta sumar un banco real |
| **1** ✅ | Un agente categorizador, local con Ollama | 80% acierto con qwen2.5:7b — y la confianza no sirve como señal |
| **2** ✅ | Dos agentes + evidencia determinista + supervisor | El desacuerdo predice el error 10× mejor que la confianza |
| **2½** ✅ | Parser del resumen de Mercado Pago, por coordenadas | Resumen real: 131 movimientos, 0 eslabones rotos, 25 resueltos sin modelo |
| **3** ✅ | Memoria por contraparte + revisión por grupos | Resumen real: 1,89 movimientos por decisión; 46% de la 2ª quincena sin modelo |
| **4** en curso | Reporte, bandeja, corrección de decisiones y proyección del mes en React + Vite; después observabilidad y contenedores | 5 meses reales, los 5 cuadran; cada devolución unida a su pago. Desde junio, 3 de cada 4 movimientos por revisar tienen una contraparte ya vista |

## Stack

Python · FastAPI · Pydantic · PostgreSQL 16 (imagen con pgvector) · Ollama con qwen2.5:7b,
local · React + Vite + TypeScript · Docker Compose
