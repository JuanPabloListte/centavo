# Centavo — Fase 4

**Estado: cuarto incremento terminado.** API local y, en el navegador con React + Vite, el
reporte del mes, la bandeja de revisión, la corrección de decisiones y la proyección del mes
que viene. Cinco meses reales cargados, de abril a agosto, que cuadran al centavo, con cada
devolución unida a su pago. `pytest` pasa 139; uno más corre sólo contra el resumen real.

Lo que falta de la fase —observabilidad y la app en contenedores— no depende de tu revisión.

---

## Qué hay

| | Dónde | Qué hace |
|---|---|---|
| **Reporte del mes** | `api/app/reporte.py` | Ingresos, gastos, movimientos internos y lo que falta clasificar, por categoría. Cuadra al centavo con el resumen. |
| **Bandeja de revisión** | `web/src/Revision.tsx` | Lo mismo que `tools.revisar`, en el navegador: una decisión por contraparte. |
| **Reporte en pantalla** | `web/src/Reporte.tsx` | Sello de cuadratura, totales, cobertura y la tabla por categoría. |
| **Corregir una decisión** | `web/src/Resueltos.tsx` | Lo ya resuelto, por contraparte y con la vía; cambiar la categoría pisa lo anterior. |
| **Proyección** | `api/app/recurrentes.py`, `web/src/Proyeccion.tsx` | Recurrentes fijos y proyección del mes siguiente, en piezas que se suman. |
| **API local** | `api/app/main.py` | Lo que usan las pantallas. Escucha sólo en 127.0.0.1. |

Verificado en el navegador sobre el esquema `demo`: una decisión desde la bandeja (una
transferencia enviada con 2 movimientos → *Pagos y Transferencias*) bajó el contador de
18 contrapartes y 19 movimientos a 17 y 17. El reporte reflejó el gasto nuevo y siguió
cuadrando al centavo, con los internos aparte.

---

## Cinco meses reales

| Mes | Movimientos | Por evidencia | Por revisar | Con contraparte ya vista antes |
|---|---|---|---|---|
| abril | 141 | 20 | 121 | — es el primero |
| mayo | 129 | 28 | 101 | 56 · 55% |
| junio | 150 | 28 | 122 | 93 · 76% |
| julio | 115 | 29 | 86 | 66 · 77% |
| agosto | 131 | 25 | 106 | 78 · 74% |
| **Total** | **666** | **130** | **536**, en 166 contrapartes | |

Los cinco cuadran por saldos, y el saldo encadena renglón por renglón. Todavía no aparece
ningún gasto en los reportes: lo que se resolvió solo son reservas, rendimientos y
transferencias entre tus cuentas. Los gastos aparecen a medida que revisás.

**La última columna es la curva de la memoria** (`tools.curva`): de lo que queda por revisar
en cada mes, qué parte tiene una contraparte que ya había aparecido en un mes anterior. Es lo
que la memoria resolvería sola si hubieras revisado los meses previos. Desde el tercer mes se
estabiliza en **3 de cada 4**.

Cómo leerlo sin inflarlo: es un techo, no un acierto. Supone que una contraparte es siempre
la misma categoría, y con transferencias a personas eso no siempre se cumple: a la misma
persona le podés pagar el alquiler un mes y devolverle una cena el siguiente.

### Revisar rinde al principio

La bandeja ordena por cantidad de movimientos, así que las primeras decisiones son las que
más resuelven:

| Decisiones | Movimientos resueltos, de 536 |
|---|---|
| 10 | 243 · 45% |
| 20 | 308 · 57% |
| 50 | 398 · 74% |
| 100 | 470 · 88% |
| 166 | todos |

94 de las 166 contrapartes aparecen una sola vez en cinco meses: son la cola larga, y ahí
cada decisión resuelve un movimiento. Dos no tienen contraparte y no se aprenden.

---

## El ID de operación no identifica un movimiento

Apareció al cargar mayo y junio. La base exigía un ID de operación único por movimiento, y
**cinco devoluciones traen el mismo ID que el pago que devuelven**: cuatro el mismo día y por
el mismo monto, una otro día y por otro monto. No es un error del parser: cada uno de esos IDs
está impreso dos veces en el PDF, y el saldo encadena.

Con la identidad vieja, mayo y junio se habrían rechazado enteros. Y una devolución que cae en
el mes siguiente al pago habría parecido una superposición entre resúmenes.

La identidad de un movimiento pasó a ser **ID de operación + fecha + monto**, más un número de
repetición para el caso raro de dos movimientos iguales en esas tres cosas dentro de un mismo
archivo. Una redescarga del mismo mes sigue siendo `YaIngerido`, y un resumen que repite parte
de otro se sigue rechazando entero. Seis tests nuevos fijan esos casos y la migración.

### La primera migración

Tu base ya tenía datos, así que el cambio no podía ser editar `schema.sql` y recrear el
volumen. Ahora hay:

- **`db/migraciones/001_identidad_del_movimiento.sql`**, idempotente: sobre una base que ya la
  tiene, no cambia nada. Borra el índice viejo sólo del esquema actual, nunca de otro que esté
  más atrás en el `search_path`.
- **`python -m tools.migrar`**, que las aplica todas en orden, cada una en su transacción.
- **`schema.sql`** con el cambio incluido, para una base nueva.

Postgres, al crear el volumen, corre sólo los archivos de primer nivel de `db/`: la subcarpeta
`migraciones/` no se mezcla con `schema.sql`.

---

## El reporte tiene dos reglas

**1. Los movimientos internos no son gastos ni ingresos.** Apartar plata en una reserva o
mandártela a otra cuenta tuya no cambia cuánto gastaste. Son dos categorías —*Ahorro y
reservas* y *Movimientos entre cuentas propias*— y van en su propio renglón.

Con el resumen sintético se ve por qué importa: una reserva de −120.000, un retiro de
+40.000 y una transferencia propia de +250.000 suman **+170.000**. Contados como ingreso,
el mes parecería 170.000 pesos mejor de lo que fue.

*Rendimientos e intereses* sí es ingreso: es plata que antes no estaba.

**2. El reporte cuadra con el resumen.**

    ingresos + gastos + internos + sin clasificar  =  lo que declara el resumen

Lo que declara es el total, o saldo final menos saldo inicial, según cómo cierre. Es la
compuerta de la fase 0 aplicada a la salida: si da distinto, algún movimiento se contó dos
veces o ninguna. El reporte devuelve `cuadra: false` con la diferencia y la pantalla lo
muestra, en vez de números que parecen buenos.

Un resumen que no cuadró al ingerirse **no tiene reporte** (409): sus movimientos no son de
fiar.

Lo que falta clasificar no se esconde ni se reparte: tiene su propio total, y la pantalla
avisa cuántos movimientos quedan en la bandeja.

---

## La plata viaja como texto

En el JSON, todo monto es un string: `"-8600.00"`, nunca `-8600`. Un `float` en JavaScript
pierde centavos, y con eso el reporte dejaría de cuadrar. El servidor suma con `Decimal`; la
interfaz sólo muestra. Convertir a número para dibujar el largo de una barra está permitido,
porque ese número nunca vuelve a un cálculo. Hay un test que fija el contrato.

---

## La clave compara, el nombre se muestra

Apareció al ver la bandeja con datos: la clave de memoria de la fase 3 ordena las palabras
de los nombres y los pasa a mayúsculas. "Pago con QR Carnicería Los Hermanos" tiene clave
`QR|CARNICERIA HERMANOS LOS`. Identifica bien, pero no se lee.

Ahora cada grupo trae dos campos:

- **`contraparte`**: la clave normalizada. Sirve para comparar.
- **`nombre`**: como lo imprime el resumen, "Carnicería Los Hermanos". Es lo que se muestra.

Al decidir se sigue mandando la clave, así que la memoria no cambió en nada.

---

## Una devolución unida a su pago

Apareció al cargar mayo y junio: **cinco devoluciones**, y cada una trae el mismo ID de
operación que el pago que devuelve. Cuatro son del mismo día y por el mismo monto, así que
se anulan; una es de otro día y por una parte. Hasta acá, cada devolución era un movimiento
suelto: caía en una clave propia (`COMERCIO|DEVOLUCION DE PAGO ...`), se revisaba aparte y,
una vez clasificada, habría figurado como ingreso de su categoría.

**El vínculo va por ID, no por texto.** De las cinco, sólo dos repiten el texto del pago
después de "Devolución de"; las otras tres lo acortan. Un movimiento positivo que arranca con
"Devolución de" se une a un movimiento negativo con el mismo (fuente, ID de operación), de
fecha igual o anterior y por un monto igual o mayor. Si hay más de un candidato, gana el del
mismo resumen y el más reciente. Se calcula al guardar cada resumen, sobre todo lo que todavía
no tiene vínculo: si cargás mayo antes que abril, la devolución se une cuando aparece su pago.
Queda en `transactions.devuelve_a` (`app/devoluciones.py`).

Con el vínculo, tres cosas pasan solas:

- **La devolución toma la clave del pago.** Cae en el grupo del pago en la bandeja, y una
  decisión sobre el comercio resuelve las dos. La bandeja avisa: "incluye 1 devolución unida
  a su pago". En la base real, las devoluciones dejaron de ser contrapartes aparte: de 169
  a 166.
- **Hereda la categoría del pago**, si el pago ya está resuelto por otra vía que la memoria;
  si no, espera a que se decida con él. El modelo no ve devoluciones nunca. Hay un test con
  un clasificador testigo que lo fija.
- **En el reporte resta del gasto** de su categoría, con el tipo del pago, en vez de sumarse
  como ingreso. El reporte sigue cuadrando: un movimiento se cuenta una vez, en un solo lugar.

**Lo que no hace, a propósito.** Una devolución cuyo pago no está cargado, por ejemplo de un
pago anterior al primer resumen, queda suelta y se revisa aparte, como cualquier otro
movimiento. Una "devolución" más grande que el pago tampoco se une: no es una devolución de
ese pago. Ante la duda, a revisión. `tools.migrar` dice cuántas quedan sin pago cargado; hoy,
cero.

**La segunda migración.** `db/migraciones/002_devoluciones.sql` agrega la columna y es
idempotente. El vínculo para lo ya cargado no lo hace el SQL: lo hace `python -m tools.migrar`
después de aplicar los `.sql`, con el mismo código que corre al guardar. Sobre la base real:
5 unidas, 0 sin pago, y los cinco reportes cuadran igual que antes.

La curva de la memoria se movió apenas: mayo pasó de 53% a 55% y junio de 75% a 76%. Las
devoluciones ahora llevan la clave de su pago, y en tres de las cinco esa contraparte ya se
había visto en un mes anterior.

---

## Corregir una decisión

Un grupo resuelto salía de la bandeja y no había forma de volver a abrirlo. Ahora hay una
solapa **Resueltos**: lo que ya tiene categoría, por contraparte, con la vía por la que se
resolvió, búsqueda y cambio de categoría. Usa la misma decisión que la bandeja: pisa lo que
haya, venga de la memoria, de la evidencia o del modelo, y queda en memoria.

**Pisar la evidencia está permitido.** Es la regla del proyecto: una decisión tuya es
absoluta. La solapa avisa cuando el grupo lo resolvió la evidencia del texto del resumen,
porque ahí lo más probable es que la evidencia tenga razón, y la corrección queda registrada
con lo que había antes.

**Dos cosas que no estaban bien.**

- Cambiar la categoría de una contraparte sumaba una confirmación en la memoria, como si
  la hubieras ratificado. Ahora reinicia el conteo: una contraparte recién cambiada no está
  confirmada ocho veces.
- `correcciones` guardaba la categoría anterior pero no cómo se había llegado a ella.
  Migración 003: guarda también la vía y el estado anteriores. Las filas viejas quedan en
  NULL; en la base real no había ninguna.

**Con eso la curva deja de ser un techo.** Un movimiento lo resolvió la memoria sola si
tiene vía `regla` y ninguna decisión directa tuya encima. Si después lo corregís, esa
primera corrección es un error de la memoria; una segunda corrección sobre el mismo
movimiento es un cambio de opinión tuyo y no cuenta. `tools.curva` lo imprime al final:
cuántos resolvió sola, cuántos corregiste y el acierto. Hoy, en la base real, es 0 y 0:
todavía no revisaste, así que la memoria no resolvió nada sola. El número aparece cuando
cargues un mes después de revisar.

Verificado en el navegador con el esquema `demo`: la solapa lista los cuatro grupos que
resolvió la evidencia, y al cambiar uno lo muestra con la categoría nueva y la vía "por tu
decisión".

---

## Recurrentes fijos y proyección del mes

Es la parte central del producto, y sale de aritmética: el modelo no participa.

**Medir primero.** Sobre la base real, sin lo que resuelve la evidencia, sin claves sin
contraparte y con las devoluciones ya unidas a su pago:

| | |
|---|---|
| Contrapartes que aparecen en 3 meses o más | 27 |
| Con exactamente un movimiento por mes | 3 |
| En meses seguidos | 17 |
| Con menos del 5% de variación en el monto | 3 |
| Con saltos mes a mes del 30% o más, en la mediana | 16 |
| Movimientos con cuotas en el texto | 0 |
| "Pago de suscripción" | 10, en 2 contrapartes |

Casi todo lo que se repite es variable: SUBE, supermercado, transferencias. Lo fijo es
poco y sube todos los meses, así que una tolerancia fija sobre el monto no sirve. Lo que
distingue un servicio de otra cosa no es que cambie: es que no salte.

**El detector** (`app/recurrentes.py`) mira cada contraparte en los últimos meses seguidos,
hasta el último cargado inclusive, y la llama recurrente fija si aparece en 3 meses o más,
una sola vez por mes, siempre con el mismo signo, en días parecidos (5 de diferencia como
mucho) y sin saltos de más del 30% de un mes al siguiente. Un servicio que dejó de aparecer
el último mes no se proyecta. No mira la categoría: una transferencia mensual a una
persona, como un alquiler, es recurrente aunque nadie la haya clasificado. Precisión antes
que recall: sobre la base real detecta 2, una suscripción con 4 meses de racha y un pago
con 3, y ningún ingreso. Los tests lo prueban con series sintéticas: estable, con aumentos,
irregular, de una sola vez, con un salto, con el día corrido y con dos por mes.

**La proyección** es del mes siguiente al último cargado, en tres piezas que se suman:

1. Los recurrentes fijos, con el último monto visto. No depende de que revises.
2. El promedio de los últimos 3 meses del gasto variable ya clasificado, por categoría,
   restando las devoluciones. Depende de tu revisión.
3. Lo sin clasificar, promedio mensual, aparte. Hoy son 90 movimientos por mes: casi toda
   la proyección real está ahí hasta que revises.

`GET /api/proyeccion` devuelve las piezas, los meses que usó y los criterios; la solapa
**Proyección** las muestra. Hay un test que fija que el total se reconstruye sumando.

**Lo que se decidió sin preguntar, y por qué.** Las tres preguntas abiertas del traspaso:

- *Transferencias recurrentes a personas*: entran, porque el detector no mira el tipo. En
  la tabla se ven con su tipo.
- *Hasta cuándo proyectar*: el mes siguiente al último cargado.
- *De dónde sale el mes en curso*: de ningún lado, todavía. Un resumen parcial de mitad de
  mes choca con el completo que llega después, porque un resumen que comparte movimientos
  con otro se rechaza entero. Soportarlo es reemplazar un resumen por otro, y esa es una
  decisión aparte.

**Lo que no hace.** No detecta cuotas: en cinco meses reales no hay una sola descripción
con cuotas. No guarda las proyecciones, así que todavía no compara proyectado contra real
cuando el mes cierra.

---

## Cómo se usa

Con Docker corriendo, en dos terminales:

```bash
cd api
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd web
npm install        # la primera vez
npm run dev        # http://127.0.0.1:5173
```

Vite reenvía `/api` a la API, así que el navegador habla con un solo origen. Las dos
escuchan sólo en `127.0.0.1`: ningún movimiento queda expuesto, ni siquiera a tu red local.

### Sin tus datos

Para probar la interfaz sin tocar lo real hay un esquema `demo`, con el resumen sintético:

```bash
cd api
python -m tools.demo                                          # borra y rearma sólo el esquema demo
python -m uvicorn app.demo:app --host 127.0.0.1 --port 8000
```

`app.demo` es la misma API con `CENTAVO_DB_SCHEMA=demo`. El nombre del esquema se valida
contra una expresión regular antes de usarse, porque va dentro de las opciones de la
conexión.

---

## La API

| | Ruta | Qué |
|---|---|---|
| GET | `/api/salud` | La base responde. |
| GET | `/api/resumenes` | Los resúmenes cargados, con cuántos movimientos están resueltos. |
| GET | `/api/resumenes/{id}/reporte` | El reporte. 404 si no existe; 409 si no cuadró al ingerirse. |
| GET | `/api/categorias` | Las 18, marcando cuáles son internas y cuáles decide sólo la evidencia. |
| GET | `/api/revision/grupos` | Lo pendiente, agrupado por contraparte. |
| POST | `/api/revision/decisiones` | `{clave, categoria}`: resuelve el grupo y lo guarda en memoria. 404 si la clave no tiene movimientos; 422 si la categoría no existe. |
| GET | `/api/revision/resueltos` | Lo resuelto, por contraparte y categoría, con la vía. La misma decisión lo cambia. |
| GET | `/api/proyeccion` | Recurrentes fijos y proyección del mes siguiente al último cargado, en piezas. |
| POST | `/api/ingest` | `{path}`: lo mismo que `tools.ingerir`. 409 si ya estaba cargado o se superpone con otro. |

Si Postgres no responde, cualquier ruta da 503 con un mensaje que dice qué revisar. Las
rutas de la fase 0 (`/health`, `/ingest`) pasaron a `/api/...`.

---

## Cargar un mes nuevo

- **Un PDF por mes, sin pisarse.** Un resumen que comparte algunos movimientos con uno ya
  cargado se rechaza entero: si el PDF de septiembre empieza el 31 de agosto, choca con
  agosto.
- **Si revisaste antes de cargar**, el mes nuevo entra con lo que la memoria ya aprendió.
- **Si cargás varios antes de revisar**, una decisión resuelve esa contraparte en todos a la
  vez: la bandeja agrupa entre resúmenes.

```bash
cd api
python -m tools.ingerir ../privado/2026-09.pdf
python -m tools.curva
```

`tools.ingerir` dice cómo quedó clasificado ese resumen y, aparte, cuánto queda por revisar
sumando todos. `tools.curva` imprime conteos, nunca nombres ni montos.

---

## Otros cambios

- **`tools.ingerir` cuenta el resumen que cargás.** Antes mezclaba lo pendiente de los meses
  anteriores: al cargar abril decía "227 sin resolver" para un mes de 141 movimientos.
- **`requirements.txt`** tenía `pandas` y `openpyxl`, que el código no usa. Ahora lista lo
  que se usa, con las versiones con las que pasa la suite.
- **Tests de la API**: reemplazan la conexión por la del esquema temporal
  (`dependency_overrides`), así que tampoco tocan tus datos.

---

## Lo que todavía no hace

- **Comparar proyectado contra real.** No guarda las proyecciones: cuando cierre un mes, no
  dice cuánto le erró.
- **Cargar el mes en curso a medias.** Un resumen parcial choca con el completo que llega
  después.
- **Reportar por mes calendario.** El reporte es por resumen. Si cada PDF cubre un mes, es
  el reporte del mes.
- **Cargar un PDF desde el navegador.** La ingesta sigue siendo por terminal, o por
  `POST /api/ingest` con una ruta local.

---

## Qué sigue

1. **Vos**: revisar en la bandeja. Con las primeras 20 decisiones quedan resueltos 308 de
   los 536 movimientos, los reportes empiezan a mostrar gastos y la proyección deja de ser
   un bloque sin clasificar.
2. **Con septiembre cargado después de revisar**: la curva de la memoria pasa a ser un
   acierto medido, y la proyección de septiembre se puede comparar contra lo que pasó.
3. **Contenedores y observabilidad**: lo que queda de la fase.
