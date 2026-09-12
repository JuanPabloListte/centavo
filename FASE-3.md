# Centavo — Fase 3

**Estado: primer incremento terminado.** Memoria por contraparte, revisión por grupos y
medición del potencial sobre un resumen real. `pytest` pasa 81/81.

La curva de corrección *real* necesita dos cosas que el código no puede poner: tus
decisiones y un segundo mes. Lo que hay hoy es su techo estructural, medido antes de que
etiquetes nada.

---

## Qué cambió respecto del plan

El plan decía embeddings de comercios en pgvector: buscar por parecido. **Lo que se
construyó es una clave exacta**, y la razón salió de los datos reales:

- Más del 40% de los movimientos reales son transferencias entre personas.
- Entre esos destinatarios, **cuatro palabras aparecían en dos o más personas distintas**.

Una búsqueda por parecido acercaría "Ana Laura Fernández" a "Ana Laura Gómez" y le
pasaría a una la categoría de la otra. En un contador personal, ese error cae justo sobre la
parte de la plata que ningún modelo puede verificar.

Los embeddings no están descartados. Pueden entrar después como **sugerencia** para
comercios, nunca como resolución automática, y requerirían bajar un modelo de embeddings:
hoy no hay ninguno instalado.

---

## La clave de memoria

`clave_memoria()` en `app/agents/patrones.py`. Es la identidad exacta de una contraparte:

| Descripción | Clave |
|---|---|
| Pedido de 3 productos Sushi Ejemplo | `PEDIDO\|SUSHI EJEMPLO` |
| Pedido de 2 productos Sushi Ejemplo | `PEDIDO\|SUSHI EJEMPLO` — la misma |
| SUPERMERCADO DIA 4821 | `COMERCIO\|SUPERMERCADO DIA` |
| Transferencia enviada Gomez Ana | `TRANSF_ENVIADA\|ANA GOMEZ` |
| Transferencia recibida Gomez Ana | `TRANSF_RECIBIDA\|ANA GOMEZ` — otra |
| Transferencia enviada | `TRANSF_ENVIADA\|SIN CONTRAPARTE <ID>` — no se aprende |

Las reglas:

- **Normaliza** mayúsculas, tildes y espacios, y descarta el código de sucursal y los
  prefijos de medio de pago.
- **Descarta lo que varía y no identifica**, como la cantidad de productos de un pedido.
- **La dirección de una transferencia cuenta**: mandarle plata a alguien y recibirla de esa
  persona pueden ser cosas distintas.
- **Los nombres de persona se comparan como conjunto de palabras.** "PEREZ MARIA LAURA" y
  "MARIA LAURA PEREZ" son la misma persona; con el mismo apellido y otro nombre, el conjunto
  es otro y la clave también.

---

## Un hallazgo que sólo aparece con datos reales

El resumen real trae **transferencias sin destinatario**: el renglón dice sólo
"Transferencia enviada". Con la primera versión de la clave, todas las transferencias
anónimas compartían una sola clave, y **una decisión tuya habría etiquetado a todas —las de
este mes y las de los que vienen— como la misma cosa**.

Ahora cada una recibe una clave propia con su ID de operación. Se puede decidir, pero
`es_memorizable()` la rechaza: no identifica a nadie, así que no se aprende. Hay un test que
fija justo eso.

---

## Cómo se usa

```bash
python -m tools.ingerir ruta/al/resumen.pdf     # parsea, verifica, guarda y clasifica
python -m tools.revisar                         # decidís por contraparte
python -m tools.memoria_potencial               # cuánto podría resolver la memoria
```

**`tools.ingerir`** clasifica lo que se resuelve sin modelo: memoria y evidencia. Con
`--con-modelo`, lo que queda pasa por la flota de la fase 2, que en una notebook tarda
minutos. Imprime conteos, nunca movimientos.

**`tools.revisar`** muestra lo pendiente agrupado por contraparte. **Una decisión resuelve el
grupo entero** y queda en memoria: la próxima vez que aparezca esa contraparte, en este
resumen o en uno futuro, se resuelve sola. Se corta en cualquier momento con `q`, y lo
decidido ya quedó guardado.

El orden de clasificación queda así:

1. **Memoria**: una decisión tuya es absoluta.
2. **Evidencia**: la categoría escrita en el texto o deducida del titular.
3. **Modelo**, sólo si se pide.

---

## El número, sobre un resumen real

| | |
|---|---|
| Movimientos | 131 |
| Resueltos por evidencia | 25 |
| Pendientes | 106, en **56 contrapartes** |
| Movimientos por decisión | **1,89** |
| Corregir la primera quincena | 36 decisiones para 52 movimientos |
| **Segunda quincena resuelta sin modelo** | **25 de 54 — 46%** |

Por tipo, en la segunda quincena:

| Tipo | Resueltos por memoria |
|---|---|
| Pago con QR | 6 de 9 |
| Pago | 8 de 15 |
| Transferencia enviada | 8 de 21 |
| Transferencia recibida | 3 de 9 |

**Cómo leerlo, sin inflarlo:** es un techo estructural, no un acierto. Mide cuánto se repiten
tus contrapartes, y supone que tus decisiones son correctas, cosa que por definición lo son.
El modelo no participa, así que no dice nada sobre si acierta.

El 54% que falta son contrapartes que aparecen por primera vez en la segunda quincena. A
esas la memoria no llega; las resuelve la evidencia, el modelo o vos.

La lectura por tipo es la esperable: los comercios y servicios se repiten más, y la mayoría
de las transferencias enviadas van a personas a las que les transferiste una sola vez.

---

## Lo que la memoria no hace, a propósito

- **No busca por parecido.** Dos contrapartes que se parecen tienen claves distintas.
- **No aprende claves sin contraparte.**
- **No toca resúmenes descuadrados**: ni los clasifica ni los corrige.
- **No negocia con tus decisiones**: pisan a la evidencia y al modelo.

---

## Base de datos

- **`memoria`**: clave → categoría, con cuántas veces la confirmaste.
- **`correcciones`**: una fila por cada movimiento que cambió por una decisión tuya. Es el
  conjunto etiquetado del proyecto, generado por el uso.
- **`statements.titular`** y **`transactions.clave`**, con índice.
- **`merchant_rules` se eliminó.** Se indexaba por descripción exacta.

Un detalle que apareció al persistir por primera vez: el `CHECK` de `transactions.via` sólo
aceptaba `regla` y `modelo`. Hasta esta fase nunca se había guardado una clasificación en la
base —el harness mide en memoria—, así que nadie lo había notado. Habría rechazado cualquier
resultado del supervisor (`evidencia`, `consenso`, `desacuerdo`). Ahora acepta las cinco
vías que produce el sistema.

---

## Tests

81/81. Los de base de datos crean **su propio esquema temporal** en Postgres y lo borran al
terminar: nunca tocan tus datos. Si Postgres no está disponible, se saltean.

---

## Qué sigue

1. **Vos**: `python -m tools.revisar` sobre agosto. Con 56 decisiones quedan resueltos los
   106 movimientos.
2. **Con el resumen de septiembre**: la curva de corrección real. Cuánto de un mes nuevo
   resuelve la memoria de los meses anteriores, medido sobre movimientos, no estimado.
3. **Con tus correcciones como conjunto etiquetado**: volver a medir la flota de la fase 2
   sobre datos reales. Hoy su benchmark es sintético.
