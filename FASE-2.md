# Centavo — Fase 2

**Estado: terminada.** Dos agentes por rutas independientes, un analizador determinista y
un supervisor que arbitra. `pytest` pasa 29/29.

La fase 1 dejó una pregunta medida: *si la confianza autodeclarada no tiene señal, ¿el
desacuerdo entre agentes predice el error mejor?* Esta fase la responde.

---

## La respuesta

Sobre 26 descripciones etiquetadas, con `qwen2.5:7b` local:

| señal | tasa de error | n |
|---|---|---|
| **agentes de acuerdo** | **6,7 %** | 15 |
| **agentes en desacuerdo** | **63,6 %** | 11 |
| confianza alta (≥ 0,75) | 28,6 % | 21 |
| confianza baja | 40,0 % | 5 |

**El desacuerdo separa el error casi diez veces mejor que la confianza.** Cuando los dos
agentes coinciden, se equivoca 1 de cada 15; cuando discrepan, 2 de cada 3. La confianza
autodeclarada apenas distingue 28,6 % de 40,0 % — dentro del ruido con esta muestra.

La hipótesis era que un modelo chico no sabe cuándo no sabe, pero que **dos rutas
independientes sí revelan la duda al chocar.** Quedó confirmada.

---

## Qué compró, y qué no

| | solo | flota |
|---|---|---|
| acierto sobre lo que resuelve | 69,2 % | **87,5 %** |
| cobertura | 100 % | 61,5 % |
| **acierto sobre todo** | **69,2 %** | **69,2 %** |
| tokens | 17.428 | 34.005 |
| segundos por movimiento | 10,0 | 14,8 |

Hay que leer la tercera fila y decirla sin maquillaje: **la flota no acierta más.** El
acierto total es idéntico. Dos agentes no hacen al modelo más inteligente.

Lo que compró es otra cosa: **saber cuándo se está equivocando.** De lo que ahora afirma,
el 87,5 % está bien —contra 69,2 % antes— y las 10 difíciles te las pasa a vos en vez de
adivinarlas en silencio.

Ese es exactamente el intercambio que el proyecto decidió al principio: un sistema que
resuelve el 70 % con 87,5 % de acierto es mejor que uno que resuelve el 100 % con 69 %,
porque en el segundo no sabés cuáles creerle.

**El costo es real**: el doble de tokens y 1,5× el tiempo. Con 26 casos y una notebook, la
corrida completa son ~6 minutos.

---

## Cómo está armado

Tres participantes, y ninguno es un clon del otro:

**`agents/categorizador.py`** — opina desde la cadena cruda, tal como la imprime el banco.

**`agents/comercio.py`** — llega al mismo tipo de respuesta **por otra ruta**: primero
descifra qué comercio es (sacando prefijos de medio de pago), y recién después clasifica
esa entidad. Que el camino sea distinto es el punto: dos agentes con el mismo prompt y la
misma entrada son un agente corriendo dos veces, coinciden siempre, y su acuerdo no informa
nada.

**`agents/patrones.py`** — **no usa el modelo.** Aporta hechos verificables del texto:
prefijo de medio de pago, plan de cuotas (`7/12`, `12 CUOTAS`, `CUOTA 3 DE 6`), signo del
monto. Y aporta **restricciones**: si hay un plan de cuotas, la categoría no puede ser
«Suscripciones», por más que se repita todos los meses.

**`supervisor.py`** — arbitra con cuatro reglas en orden estricto:

| | regla | resultado |
|---|---|---|
| 1 | Una corrección tuya es absoluta | `resuelto`, sin llamar al modelo |
| 2 | La evidencia determinista descarta opiniones que la contradicen | `resuelto` por evidencia |
| 3 | Los dos agentes coinciden | `resuelto` por consenso |
| 4 | Discrepan | `needs_review` |

**La regla 4 no elige un ganador.** Hay un test que lo fija: aunque un agente declare 0,99
y el otro 0,30, sigue siendo desacuerdo. Elegir por confianza sería decidir al azar con
cara de rigor, y la fase 1 lo midió.

---

## Un caso que muestra el mecanismo y su límite

`MUSIMUNDO CUOTA 7/12`, etiquetado como *Hogar y Electro*.

- **Fase 1**: el categorizador dijo *Suscripciones*, con confianza 0,90. Resuelto y mal.
- **Fase 2**: el analizador detecta `7/12` → veta *Suscripciones*. El supervisor descarta
  esa opinión y toma la del agente de comercios, que dijo *Indumentaria*.

**El mecanismo funcionó y el resultado sigue estando mal.** El veto hizo lo suyo —eliminó
la respuesta que contradecía un hecho— pero la candidata que quedaba tampoco servía.

Vale decirlo así: la evidencia determinista puede descartar lo falso sin poder producir lo
verdadero. Es una mejora real y acotada, no una solución.

---

## Correrlo

```bash
python -m tools.evaluar --modo solo      # un agente
python -m tools.evaluar --modo flota     # dos agentes + supervisor
python -m tools.evaluar --modo flota --modelo llama3.2:3b
```

El scorecard imprime la tabla de señal —acuerdo contra confianza— en cada corrida, y cada
resultado queda en `tools/resultados/` con el detalle caso por caso, incluidas las
opiniones de cada agente. Comparar dos corridas es abrir dos JSON.

**El conjunto se hizo más difícil a propósito.** Pasó de 15 a 26 descripciones, sumando
casos ambiguos (`MERPAGO*LA ESQUINA`, `MERCADOLIBRE*COMPRA`, `PAGOFACIL EDECOR`,
`SHELL SELECT`). Si todos los comercios son obvios los agentes coinciden siempre y el
desacuerdo no mide nada: el benchmark tiene que tener casos difíciles o no es un benchmark.
Por eso el baseline bajó de 80 % a 69,2 % — no empeoró el sistema, se endureció la prueba.

---

## Lo que sigue valiendo la pena aclarar

Son comercios sintéticos. El 87,5 % mide la **cañería**, no la tarea. Y con 26 casos, una
diferencia de un par de puntos es ruido — lo que **no** es ruido es la brecha 6,7 % contra
63,6 %, que es demasiado grande para atribuirla al azar de esta muestra.

---

## Qué sigue

Fase 3: memoria. Y ahora tiene un objetivo numérico claro en vez de una intuición.

Hoy hay **10 movimientos en `needs_review`** por corrida. Cada uno que corrijas se vuelve
una regla determinista: la próxima vez se resuelve con cero tokens, cero latencia y sin
posibilidad de error. La métrica de la fase 3 es **`resuelto sin modelo`**, que hoy vale 0
y ya está en el scorecard esperando subir.
