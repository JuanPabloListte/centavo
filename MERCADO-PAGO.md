# Centavo — Resumen de Mercado Pago

**Estado: terminado y verificado de punta a punta.** El parser, contra un resumen real; la
persistencia y la deduplicación, contra Postgres. `pytest` pasa 58/58.

Es la primera fuente de datos reales del proyecto: el "Resumen de cuenta en pesos" que se
genera desde la web de Mercado Pago, en PDF.

---

## Verificación sobre un resumen real

Agosto de 2026, 11 páginas. Todo lo de esta tabla se comprobó con código:

| Control | Resultado |
|---|---|
| Movimientos leídos | 131, en 10 páginas + 1 anexo |
| Descripciones partidas en varios renglones | 70 |
| Cabecera: inicial + entradas + salidas = final | ✓ |
| Compuerta por saldos | ✓ |
| **Saldo renglón por renglón** | **✓ 0 eslabones rotos** |
| IDs de operación únicos | ✓ 131/131 |
| Texto de pie pegado a una descripción | ninguno |
| Descripciones que no arrancan con un tipo de Mercado Pago | ninguna |

El PDF real **no está en el repo**: tiene CVU, CUIT y nombres de terceros. Para correr su
test:

```bash
CENTAVO_RESUMEN_REAL="ruta/al/resumen.pdf" pytest tests/test_resumen_mp.py
```

Sin esa variable, el test se saltea. Los resúmenes reales van en `privado/`, que está en
`.gitignore`.

---

## Por qué va por coordenadas

`extract_tables()` no encuentra ninguna tabla, y 70 de 131 descripciones vienen partidas:
la mitad del texto arriba del renglón de la fecha y la otra mitad abajo. Leído como texto
plano, un fragmento como el apellido de un destinatario queda pegado al movimiento
equivocado.

`app/parsers/pdf_coordenadas.py` reconstruye cada movimiento por la posición de las
palabras:

1. **Encabezado.** Por página, ubica Fecha · Descripción · ID · Valor · Saldo y deriva de
   ahí las columnas. No hay coordenadas fijas en el código.
2. **Corte del pie.** La tabla termina en el primer renglón que arranca a la izquierda de la
   descripción sin ser una fecha. Sin este corte, el pie de la página 10 ("Fecha de
   emisión…", la razón social) se pegaba al último movimiento.
3. **Anclas.** Cada renglón con fecha es un movimiento, y tiene que traer exactamente un ID y
   dos montos. Si no, error.
4. **Fragmentos.** Cada renglón suelto de la columna de descripción va a la fecha más
   cercana. En el resumen real están a −13, −7, +5 y +11 puntos, con unos 30 entre
   movimientos. Uno a más de 16 puntos no se asigna a la fuerza: es error.

`numero_linea` es página × 1000 + orden, así que la línea 3007 es el séptimo movimiento de
la página 3. Cuando el control renglón por renglón falla, señala un lugar que se encuentra
a ojo en el PDF.

**Agregar otro banco con esta maquetación es agregar un `Perfil`**, no escribir código:
`estrategia="coordenadas"` más los nombres de las columnas y las regexps de cabecera.

---

## Las decisiones que sostienen al parser

**Control renglón por renglón.** El resumen imprime el saldo después de cada movimiento, así
que `balance.py` exige saldo anterior + monto = saldo en cada fila. Es más fuerte que el
control del período: un parser que lee mal una fila puede compensarse con otra y dejar el
total intacto, y la cadena no perdona eso. Cuando falla, dice la línea exacta. Hay un test
que lo demuestra: corre un saldo un centavo, el período sigue cuadrando, y la cadena marca
la fila.

**La tabla de dólares falla fuerte.** La última página trae una tabla con columnas de
cotización. Vacía se ignora; con filas levanta un error, porque leerla con la forma de la
de pesos daría basura con cara de dato. Hay **dos** defensas, y la segunda es la importante:

- El rótulo "Cotización" en el encabezado. Se busca hasta 40 puntos por encima de
  "Descripción", porque un rótulo de columna angosta se parte en renglones alineados abajo
  y el primero queda arriba.
- Contar los montos. Si dos rótulos se pisan en el PDF, el texto sale intercalado y ningún
  chequeo por nombre ve nada. Contar cuatro montos donde tiene que haber dos no depende de
  leer el encabezado.

Las dos las encontró un test contra el resumen sintético: el primer intento de chequear el
rótulo no funcionaba, y lo que atajó la tabla fue el conteo de montos.

**No duplicar movimientos.** El sha256 del archivo no alcanza: el mismo mes descargado dos
veces puede regenerarse con otra fecha de creación y otro hash. `store.py` compara los
movimientos. Si todos ya están, es el mismo resumen y no se hace nada. Si están algunos, se
rechaza entero: cómo combinar rangos superpuestos es decisión de la automatización, no del
parser.

La identidad de un movimiento es **ID de operación + fecha + monto**, no el ID solo. La
primera versión usaba el ID, y los resúmenes reales de mayo y junio la desmintieron: la
devolución de un pago trae el mismo ID que el pago. Ver [FASE-4.md](FASE-4.md).

---

## Movimientos que no son gastos ni ingresos

Hay movimientos del resumen real que no entran en ninguna categoría del catálogo, y
contados como gasto o como ingreso distorsionan el mes entero. Se agregaron tres
categorías que **asigna sólo el código**:

| Categoría | Cómo se detecta | En el resumen real |
|---|---|---|
| Ahorro y reservas | `Dinero reservado` (resta) y `Dinero retirado` (suma) | 2 |
| Rendimientos e intereses | `Rendimientos` (suma) | 20 |
| Movimientos entre cuentas propias | transferencia a nombre del propio titular | 3 |

Se resuelven **25 de 131 sin llamar al modelo**. El resto, 106, va a los agentes.

**El signo está verificado sobre el resumen real**, y un movimiento con el signo contrario no
se resuelve por el texto: contradice lo que se sabe, y no se adivina.

**Transferencias a uno mismo.** Mercado Pago imprime el nombre reordenado y en mayúsculas,
así que comparar strings no sirve. La regla: todas las palabras de la contraparte tienen que
estar en el nombre del titular, y tienen que ser al menos dos. **Compartir el apellido no
alcanza**, y ese es el caso peligroso: una transferencia a un familiar con el mismo apellido
no es un movimiento entre cuentas propias. Hay un test que fija justo eso.

**El modelo no ve estas categorías.** Están marcadas `solo_determinista` en la base y
`cargar_categorias()` las excluye del catálogo de los agentes. Ofrecérselas nada más le
sumaría opciones para equivocarse, y cambiaría el catálogo sobre el que se midió la fase 2.
El benchmark queda comparable.

---

## Lo que esto le cambia a la fase 3

Del resumen real, **al menos 54 de 131 movimientos son transferencias entre personas**, más
del 40%. La categoría de esas no está en el texto: una transferencia a una persona puede ser
el alquiler, dividir una cena o un regalo, y ningún modelo lo puede saber.

Van a `needs_review` la primera vez, y sólo la memoria de la fase 3 las resuelve: le decís
una vez qué es cada destinatario y queda aprendido. La fase 3 deja de ser una mejora y pasa
a ser la condición para clasificar casi la mitad de los movimientos reales.

---

## El resumen sintético

`tools/resumen_mp_sintetico.py` genera `tests/fixtures/resumen_mp.pdf` con la misma
maquetación y datos inventados: descripciones de dos y tres renglones, fechas con guiones,
saldo por renglón, encabezado repetido en cada página, un pie que tiene que cortarse, y una
página de dólares vacía.

El test compara **cada descripción palabra por palabra** contra los datos que la generaron.
Es lo que permite tocar el parser sin tener el PDF real a mano.

---

## Persistencia verificada

Con la base recreada desde `db/schema.sql` y el resumen sintético:

| Caso | Resultado |
|---|---|
| Primera carga | guardado; cuadra por saldos y encadena |
| El mismo archivo otra vez | `YaIngerido`, por sha256 |
| El mismo resumen con otro hash (una redescarga) | `YaIngerido`, **por movimiento** |
| Mitad de los movimientos ya cargados y mitad nuevos | `SuperposicionParcial`, rechazado entero |

Lo que quedó en la base después de los cuatro intentos:

- **1 resumen, no 4.** Los rechazos no dejan nada a medias.
- 32 movimientos, todos con ID y saldo.
- `v_cuadratura`: cuadrado, diferencia 0.
- **La cadena de saldos recalculada en SQL a partir de lo guardado: 0 eslabones rotos.** Lo
  que se guarda es exactamente lo que se verificó al parsear.
- El modelo ve 15 categorías; la base tiene 18.
- **El índice único rechaza un movimiento duplicado en la propia base**, aunque la
  aplicación no lo atajara. Desde la fase 4, el índice es sobre ID + fecha + monto +
  repetición.

El caso 3 es el que justifica deduplicar por movimiento: con el sha256 como único control,
esa redescarga habría duplicado los 32 movimientos.
