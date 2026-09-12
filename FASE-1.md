# Centavo — Fase 1

**Estado: terminada.** Un agente clasificador contra Ollama local, harness de evaluación
corriendo, y un número. `pytest` pasa 17/17.

---

## Correrlo

```bash
python -m tools.generar_fixtures     # resúmenes + etiquetas
python -m tools.evaluar              # scorecard con el modelo por defecto
python -m tools.evaluar --modelo llama3.2:3b --umbral 0.6
```

Cada corrida deja un JSON en `tools/resultados/` con el scorecard y el detalle caso por
caso. Cambiar un prompt y no poder decir si mejoró es no tener harness.

---

## El número

Sobre 15 descripciones etiquetadas, en la RTX 3060 de 6 GB:

| modelo | acierto s/resueltos | cobertura | s / movimiento |
|---|---|---|---|
| `qwen2.5:7b` | **80,0 %** | 100 % | 11,7 |
| `llama3.2:3b` | 64,3 % | 93,3 % | 6,6 |

El 7B acierta 16 puntos más y tarda casi el doble. Con este tamaño de muestra la
diferencia es orientativa, no concluyente — es lo que hay hasta que entren movimientos
reales.

---

## El hallazgo: la confianza no sirve

Esto es lo que el harness existe para encontrar, y aparece en la primera corrida.

| modelo | confianza media cuando **acierta** | cuando **falla** |
|---|---|---|
| `qwen2.5:7b` | 0,900 | 0,900 |
| `llama3.2:3b` | 0,740 | 0,820 |

**qwen2.5:7b devolvió exactamente 0.90 en los 15 casos**, incluidos los tres que erró. La
señal es una constante: cero información.

**llama3.2:3b es peor todavía**: está *más* seguro cuando se equivoca que cuando acierta.

La consecuencia es incómoda y hay que decirla: **el umbral de confianza —el guardrail que
definía el producto— hoy no hace nada.** La cobertura da 100 % no porque el sistema esté
seguro, sino porque el modelo dice 0.90 siempre. Un modelo chico no sabe lo que no sabe, y
pedirle que se autoevalúe no arregla eso.

El mecanismo está construido y probado (`test_confianza_baja_va_a_revision` pasa). Lo que
falla es la **entrada**: la confianza autodeclarada.

### Y esto es exactamente el argumento de la fase 2

Si un solo modelo no puede señalar su propia incertidumbre, hace falta una señal externa.
**El desacuerdo entre agentes es esa señal.** Cuando el categorizador dice «Suscripciones»
y el normalizador de comercios dice «Hogar y Electro», eso sí es información — y no
depende de que ninguno de los dos sea honesto sobre su propia duda.

O sea: el abanico de la fase 2 deja de ser una decisión de arquitectura y pasa a ser la
respuesta a un problema medido.

---

## Dónde falló, y por qué importa

`qwen2.5:7b` erró tres:

| descripción | esperaba | dijo |
|---|---|---|
| `MUSIMUNDO CUOTA 7/12` | Hogar y Electro | Suscripciones |
| `PEDIDOSYA` | Gastronomía | Pagos y Transferencias |
| `NETFLIX.COM` | Suscripciones | Entretenimiento |

Los dos primeros son errores del modelo. **El tercero es un problema de mi taxonomía, no
del modelo**: Netflix es entretenimiento *y* es una suscripción, y las dos categorías
existen en el catálogo. El harness no encontró un modelo malo ahí, encontró un catálogo
ambiguo — que es un hallazgo igual de útil y que ninguna corrida a ojo habría detectado.

Es un buen recordatorio de que cuando el acierto baja, el error puede estar de este lado.

---

## Arquitectura

**El orden de la clasificación es el principio rector del proyecto aplicado acá:**

1. **Regla determinista.** Si esa descripción ya fue resuelta —porque vos la corregiste—,
   se usa. Cero tokens, instantáneo, exacto.
2. **Recién si no hay regla, el modelo.**
3. **Umbral.** Por debajo, a `needs_review` en vez de resolverse mal en silencio.

Hoy `merchant_rules` está vacía a propósito, así que el paso 1 resuelve 0. Ese número es
la métrica que tiene que subir en la fase 3, y por eso ya está en el scorecard.

**Piezas:**

```
app/llm.py                  cliente compatible con OpenAI + loop de reparación + contador de uso
app/agents/categorizador.py el agente: prompt, esquema Pydantic, defensa anti-invención
app/clasificar.py           orquestación: regla -> modelo -> umbral
tools/evaluar.py            el harness
tools/resultados/           un JSON por corrida, para comparar
```

**El cliente habla API de OpenAI**, que es la que expone Ollama —y también Groq, Cerebras y
OpenRouter—. Por eso `--modelo` funciona sin tocar una línea del agente. Pero ojo: en este
producto la privacidad es la premisa, así que **nada que vea un movimiento puede salir de
la máquina.** Los proveedores remotos sirven para comparar sobre datos sintéticos, no para
producción.

**Cuatro defensas contra modelos chicos**, todas con test:

- Loop de reparación: si el JSON no valida, se reintenta **con el error de validación en el
  prompt**. Reintentar con «devolvé JSON válido» no sirve; con el error, sí.
- Rescate de JSON envuelto en ```` ```json ````: más barato que reintentar.
- Categoría fuera del catálogo → forzada a `Otros` con confianza 0. La restricción vive en
  el tipo, no en la buena voluntad del modelo.
- Umbral inclusivo y explícito.

---

## Las etiquetas

`tests/fixtures/etiquetas.json`, generado junto con los resúmenes. 15 descripciones.

**Lo que esto mide, dicho con precisión:** son comercios sintéticos, más limpios que los de
un resumen real. El 80 % es una medida honesta de la **cañería** y una medida optimista de
la **tarea**. Se vuelve honesto del todo cuando entren movimientos reales etiquetados a
mano — y ahí van a hacer falta unos doscientos, no quince.

---

## Qué sigue

Fase 2: los otros tres agentes, el supervisor y el arbitraje. Con una pregunta ya
formulada por la medición, en vez de por el diseño: **¿el desacuerdo entre agentes predice
el error mejor que la confianza autodeclarada?**

Si la respuesta es que sí, el `needs_review` vuelve a tener sentido. Si es que no, eso
también es un resultado y hay que decirlo.
