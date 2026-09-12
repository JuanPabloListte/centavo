# Traspaso — Centavo

Escrito el 12/09/2026 para un agente que retoma el proyecto sin el historial de la
conversación. Las reglas fijas están en [CLAUDE.md](CLAUDE.md); acá está lo que pasó, en qué
estado quedó todo y qué sigue.

---

## Contexto

**Qué es.** Un contador personal que ingiere resúmenes de cuenta, verifica que cuadren al
centavo, clasifica los movimientos, arma el reporte del mes y, cuando esté terminado, detecta
gastos recurrentes y proyecta el mes. Todo local: la privacidad es la premisa del producto, no
una limitación.

**El usuario.** Lo que es de la persona y no del proyecto —para qué lo usa, cómo prefiere
trabajar, dónde están sus PDF y sus otros repositorios— está en `privado/NOTAS.md`, fuera
del repositorio, porque el repo es público. Si ese archivo no está, preguntale al usuario.

**La especificación original** es un artifact: https://claude.ai/code/artifact/6e12ae51-31d5-4a11-9698-2859ae546794.
Explica el principio rector, el pipeline, las reglas del supervisor, el modelo de datos y el
orden de fases. La implementación se apartó de ella en varios puntos, con razones medidas. Están
más abajo.

---

## Lo que se hizo, fase por fase

| Fase | Qué se construyó | Resultado que la cierra | Documento |
|---|---|---|---|
| **0** | Parseo, normalización, compuerta aritmética, persistencia idempotente | Cierre por total o por saldos, como unión discriminada | `FASE-0.md` |
| **1** | Un agente categorizador local, con salida Pydantic y loop de reparación de JSON | 80% de acierto con `qwen2.5:7b`, y la confianza autodeclarada no sirve como señal | `FASE-1.md` |
| **2** | Dos agentes con modelo, un analizador determinista y un supervisor por reglas | El desacuerdo entre agentes separa el error casi 10 veces mejor que la confianza (6,7% contra 63,6%). La flota no acierta más, pero sabe cuándo duda | `FASE-2.md` |
| **2½** | Parser del resumen de Mercado Pago por coordenadas, y categorías que asigna sólo el código | Resumen real: 131 movimientos, 70 descripciones partidas bien armadas, 0 eslabones rotos en la cadena de saldos | `MERCADO-PAGO.md` |
| **3** | Memoria por clave exacta de contraparte y revisión por grupos | Agosto real: 1,89 movimientos por decisión | `FASE-3.md` |
| **4**, primer incremento | API local, reporte del mes, bandeja de revisión en React + Vite, identidad del movimiento, primera migración, cinco meses cargados | Los cinco cuadran; desde junio, 3 de cada 4 movimientos por revisar tienen una contraparte ya vista | `FASE-4.md` |
| **4**, segundo incremento | Cada devolución unida a su pago por ID de operación (`devuelve_a`, migración 002): toma su clave, hereda su categoría y resta del gasto | Base real: 5 unidas, 0 sin pago; de 169 a 166 contrapartes; los cinco reportes siguen cuadrando | `FASE-4.md` |
| **4**, tercer incremento | Corregir una decisión desde la solapa Resueltos; cambiar la categoría reinicia las confirmaciones; `correcciones` guarda vía y estado anteriores (migración 003); `tools.curva` mide el acierto de la memoria | 122 tests. En la base real la memoria todavía no resolvió nada sola: el acierto se mide cuando entre un mes después de revisar | `FASE-4.md` |
| **4**, cuarto incremento | Detector determinista de recurrentes fijos y proyección del mes siguiente en tres piezas: recurrentes, promedio del gasto variable clasificado, sin clasificar aparte. Solapa Proyección | Base real: 2 recurrentes fijos, 0 ingresos recurrentes, 90 movimientos por mes sin clasificar | `FASE-4.md` |
| **4**, quinto incremento | Stack en contenedores (db, api, web) publicado sólo en 127.0.0.1, y tabla `corridas` para observar cada ingesta sin datos | 130 MiB en reposo entre los tres; 147 tests; el CI construye las imágenes | `FASE-4.md` |
| **4**, sexto incremento | Solapa Cargar: el resumen se sube desde el navegador y se procesa en un hilo de la API, con progreso por SSE y la flota opcional limitada a ese resumen | Verificado con `demo` en el navegador y, con el modelo, a través de nginx; 156 tests | `FASE-4.md` |

### Decisiones que conviene conocer antes de tocar código

- **Categorías deterministas.** *Ahorro y reservas*, *Rendimientos e intereses* y *Movimientos
  entre cuentas propias* las asigna sólo el código, por textos fijos de Mercado Pago ("Dinero
  reservado", "Dinero retirado", "Rendimientos") o comparando con el titular. Están marcadas
  `solo_determinista` y el modelo no las ve.
- **Transferencia a uno mismo.** Todas las palabras de la contraparte tienen que estar en el
  nombre del titular, y tienen que ser al menos dos. Compartir el apellido no alcanza, a
  propósito: una transferencia a un familiar no es un movimiento interno.
- **Clave de memoria** (`clave_memoria`): `TIPO|CONTRAPARTE`, normalizada. Los nombres de
  persona van con las palabras ordenadas. Una transferencia sin contraparte recibe una clave con
  su ID de operación y no se aprende (`es_memorizable`). Para mostrar se usa `nombre_legible`,
  no la clave.
- **No hay búsqueda por parecido.** En los datos reales, varias palabras de nombres se repetían
  entre personas distintas: una búsqueda difusa le pasaría la categoría de una a otra.
- **Identidad de un movimiento:** ID de operación + fecha + monto + repetición. La devolución de
  un pago trae el mismo ID que el pago. Ver `FASE-4.md`.
- **Orden del supervisor:** memoria, después evidencia determinista, después consenso de los
  agentes. Si los agentes discrepan, va a revisión.
- **El reporte** separa los internos y exige ingresos + gastos + internos + sin clasificar =
  lo que declara el resumen.
- **Devolución unida a su pago** (`transactions.devuelve_a`, `app/devoluciones.py`): un
  movimiento positivo que arranca con "Devolución de" se une al negativo con el mismo (fuente,
  ID de operación), de fecha igual o anterior y por monto igual o mayor. Toma la clave del
  pago; hereda su categoría si el pago está resuelto, y si no espera; el modelo nunca la ve;
  en el reporte resta del gasto. Sin pago cargado queda suelta y se revisa aparte.

---

## Estado al 12/09/2026

### Base real (esquema `public`)

| id | Mes | Movimientos | Por evidencia | Por revisar |
|---|---|---|---|---|
| 2 | abril | 141 | 20 | 121 |
| 4 | mayo | 129 | 28 | 101 |
| 5 | junio | 150 | 28 | 122 |
| 3 | julio | 115 | 29 | 86 |
| 1 | agosto | 131 | 25 | 106 |
| | **Total** | **666** | **130** | **536**, en 166 contrapartes |

- Los cinco cuadran por saldos y encadenan renglón por renglón.
- Todos son "Resumen de cuenta en pesos" de Mercado Pago, sin movimientos en dólares.
- **Decisiones en memoria: 0** cuando se cargó abril. El usuario puede haber revisado después:
  verificalo con un conteo antes de medir nada.
- Migración `001_identidad_del_movimiento.sql`: aplicada.
- Migración `002_devoluciones.sql`: aplicada. 5 devoluciones unidas a su pago, 0 sin pago
  cargado.
- Migración `003_correcciones_con_via.sql`: aplicada.
- Migración `004_corridas.sql`: aplicada. Todavía no hay corridas: la primera será la próxima
  ingesta.
- Ningún reporte muestra gastos todavía, porque lo único resuelto son internos y rendimientos.

**Curva de la memoria** (`tools.curva`): qué parte de lo que queda por revisar en cada mes tiene
una contraparte que ya había aparecido en un mes anterior.

| mayo | junio | julio | agosto |
|---|---|---|---|
| 55% | 76% | 77% | 74% |

Es un techo, no un acierto.

**Lo que rinde revisar**, con la bandeja ordenada por cantidad de movimientos:

| Decisiones | Movimientos resueltos, de 536 |
|---|---|
| 10 | 243 · 45% |
| 20 | 308 · 57% |
| 50 | 398 · 74% |
| 100 | 470 · 88% |

94 contrapartes aparecen una sola vez. Dos no tienen contraparte y no se aprenden.

### Renombrado a Centavo, el 12/09/2026

El proyecto se llamaba Libro Mayor Local. Cambió el nombre visible: títulos de los documentos,
la API, la marca de la interfaz, `package.json`, y las variables `LIBRO_*` pasaron a
`CENTAVO_*`. El ejemplo de titular en `patrones.py`, `FASE-3.md` y el fixture `tarjeta_visa`
pasó a ser el sintético ("María Laura Pérez Gómez"): el nombre real del usuario no va al repo.

**Lo que conserva el nombre viejo, a propósito:**

- **Dentro de Postgres**, el usuario `libro` y la base `libro_mayor`, y por eso también las
  variables `POSTGRES_*` y `DATABASE_URL` en `.env.example`, `docker-compose.yml`,
  `app/store.py` y el CI. Renombrarlos toca la base con datos y esta sesión no tenía permiso
  para hacerlo. Si el usuario lo quiere, con la API apagada:

      docker exec centavo-db psql -U libro -d postgres -c "CREATE ROLE tmp LOGIN SUPERUSER"
      docker exec centavo-db psql -U tmp -d postgres -c "ALTER DATABASE libro_mayor RENAME TO centavo" -c "ALTER ROLE libro RENAME TO centavo" -c "ALTER ROLE centavo PASSWORD 'centavo'"
      docker exec centavo-db psql -U centavo -d centavo -c "DROP ROLE tmp"

  y después cambiar `libro`/`libro_mayor` por `centavo` en esos cuatro archivos. El usuario
  `libro` es el superusuario inicial: se puede renombrar, no borrar.
- **El volumen de Docker** `libro-mayor_pgdata`, con los cinco meses. `docker-compose.yml` lo
  apunta por nombre y fija `name: centavo` como proyecto, así que ni el volumen ni el
  contenedor `centavo-db` dependen del nombre de la carpeta. Con eso no se copió nada.
- **La carpeta** ya se llama `centavo`. La renombró el usuario con la sesión movida a otro
  directorio: Windows no deja renombrar el directorio de trabajo de un proceso, y los de la
  sesión arrancan ahí.

### Entorno y archivos

- **Docker:** `docker compose up -d` levanta `centavo-db`, `centavo-api` y `centavo-web`. Al
  escribir esto quedaron corriendo, con la API sobre la base real. Si Docker está apagado,
  pedile al usuario que lo prenda: un `psycopg.connect` sin base puede quedar colgado en vez
  de fallar.
- **Tests:** 156 pasan y 1 se saltea: el del PDF real, que corre con `CENTAVO_RESUMEN_REAL`
  apuntando al archivo. `npm run build` pasa.
- **Esquema `demo`:** además del resumen sintético con una devolución unida a su pago, que
  agrega `tools.demo`, quedaron dos CSV sintéticos de las pruebas de la solapa Cargar: una
  cuenta corriente de 45 movimientos sin clasificar y uno de 3 que clasificó la flota.
  `python -m tools.demo` lo rearma desde cero.
- **PDF reales:** fuera del repositorio; dónde están, en `privado/NOTAS.md`. La base ya no
  los necesita.
- **Git:** rama `main`, con remoto `origin` en https://github.com/JuanPabloListte/centavo, que
  es **público**. El push usa la cuenta que el usuario guardó en Git Credential Manager; no
  hay `gh`. Cada tarea terminada se commitea y se sube, nunca con push forzado. El CI corre en
  cada push y se puede consultar sin autenticarse en la API de GitHub.
- **Nada privado en el repo.** Antes del primer push se reescribió la historia local, que
  todavía no estaba publicada, para sacar dos cosas: un ejemplo de `FASE-3.md` con nombres de
  personas que aparecen en 9 movimientos reales, y lo personal del usuario, que pasó a
  `privado/NOTAS.md`. Antes de cada push, revisá que no entren nombres, montos ni datos del
  usuario: un cruce de las palabras de las contrapartes reales contra los archivos
  versionados, que imprima sólo archivo y línea, lo encuentra.
- **Comandos largos del agente.** En esta máquina, un comando de shell de más de unos 8 KB se
  corta antes de correr y falla con un error de comillas. Un archivo grande se escribe en
  partes de menos de 6 KB y se juntan con `cat`.

---

## Desvíos de la especificación

| La especificación decía | Lo que hay | Por qué |
|---|---|---|
| Qwen3 4B | `qwen2.5:7b` | Es el que está instalado en Ollama; las fases 1 y 2 se midieron con él |
| Memoria con embeddings en pgvector | Clave exacta por contraparte | Los nombres de personas se pisan; ver `FASE-3.md`. Los embeddings quedan, a lo sumo, como sugerencia |
| Plantillas de banco aprendidas por el modelo | Perfiles deterministas (`Perfil`) | El PDF de Mercado Pago se resolvió por coordenadas, sin modelo |
| Cuatro agentes | Dos con modelo, más analizador determinista y supervisor | Ver `FASE-2.md`. Suscripciones y cuotas siguen pendientes |
| Celery + Redis | Un hilo de la API por carga, con progreso por SSE | Una persona y una carga por vez: no hacen falta dos servicios más. Ver `FASE-4.md` |
| Tailwind | CSS propio, con tokens de tema claro y oscuro | No hizo falta |
| OpenTelemetry + Langfuse | Tabla `corridas` en Postgres | Langfuse autohospedado suma cinco servicios; ver `FASE-4.md` |
| Contexto argentino | Pendiente | Sin orden fijo, al final |
| Tablas `merchants`, `subscriptions`, `installments`, `bank_layouts` y de trazas | No existen | Se crean cuando una tarea las necesite, con migración |

**Automatizar la descarga.** El usuario no quiere bajar el resumen a mano todos los meses. Se
investigó la API de reportes de Mercado Pago (Release Report: `POST /v1/account/release_report`
con `begin_date` y `end_date`, listar y descargar, con access token), pero no se implementó. Lo
que se construyó es el parser del PDF que el usuario genera desde la web. Sigue abierto:
confirmá con el usuario antes de retomarlo.

---

## Tareas, en orden

Para cada una: tests primero, verificación sobre la base real con conteos, interfaz probada con
`demo`, y `FASE-4.md` y `README.md` actualizados al terminar.

### Tarea 0: versionar el proyecto — hecha en parte el 12/09/2026

`git init` con rama `main` y primer commit, revisado: sin PDF reales, sin `.env`, sin
`privado/`. `.gitignore` ignora todo `*.pdf` salvo los sintéticos de `tests/fixtures/`.
Falta lo que decide el usuario: crear el repo remoto y hacer el primer push. Recién ahí se
ve si `.github/workflows/ci.yml` (pytest con `pgvector/pgvector:pg16` como servicio, y
`npm run build`) pasa.

### Tarea 1: unir cada devolución con su pago — hecha el 12/09/2026

Está en `FASE-4.md`, "Una devolución unida a su pago". Quedó como estaba sugerido: vínculo
determinista por (fuente, ID de operación) en `transactions.devuelve_a`, la devolución toma
la clave del pago, hereda su categoría si el pago está resuelto, y en el reporte resta del
gasto. Verificado en la base real con conteos: 5 unidas, 0 sin pago, de 169 a 166
contrapartes, los cinco reportes cuadran. 17 tests en `tests/test_devoluciones.py`.

### Tarea 2: gastos recurrentes y proyección del mes — hecha el 12/09/2026

Está en `FASE-4.md`, "Recurrentes fijos y proyección del mes". Se midió primero (los
conteos están ahí) y de eso salieron los criterios: 3 meses seguidos hasta el último cargado,
un movimiento por mes, mismo signo, días con 5 de diferencia como mucho, saltos de hasta 30%
mes a mes. `app/recurrentes.py`, `GET /api/proyeccion`, solapa Proyección, 17 tests en
`tests/test_recurrentes.py`. Las tres preguntas para el usuario se resolvieron con supuestos,
dichos en el documento: las transferencias recurrentes a personas entran; se proyecta el mes
siguiente al último cargado; el mes en curso a medias no se soporta todavía. Si el usuario
quiere otra cosa, son constantes al principio del módulo y una decisión de diseño para el
resumen parcial.

### Tarea 3: corregir una decisión desde la bandeja — hecha el 12/09/2026

Está en `FASE-4.md`, "Corregir una decisión". Solapa **Resueltos** con `GET
/api/revision/resueltos`, búsqueda y cambio de categoría con la misma decisión de la bandeja.
Las confirmaciones se reinician al cambiar de categoría. `correcciones` guarda vía y estado
anteriores (migración 003) y `app.memoria.precision_de_la_memoria` cuenta lo que la memoria
resolvió sola y cuánto corregiste; `tools.curva` lo imprime. La pregunta abierta se resolvió
con la regla del proyecto: una decisión del usuario pisa a la evidencia, con aviso en la
solapa y traza en `correcciones`. 7 tests en `tests/test_resueltos.py`.

### Tarea 4: contenedores y observabilidad — hecha el 12/09/2026

Está en `FASE-4.md`, "Todo en contenedores" y "Observabilidad". Compose con `db`, `api` y
`web`: la API no se publica al host, la web queda en 127.0.0.1:8080 con nginx y Ollama
sigue en el host. Medido en reposo: 130 MiB entre los tres. Para observabilidad se eligió
la alternativa liviana que sugería este documento: la tabla `corridas` (migración 004,
`app/corridas.py`, `tools.corridas`, `GET /api/corridas`), sin spans de OpenTelemetry. El
usuario no llegó a elegir: si quiere Langfuse u OpenTelemetry, se agrega sobre los mismos
puntos. 8 tests en `tests/test_corridas.py`.

### Después, sin orden fijo

- Cancelar una carga en curso desde la interfaz.
- Contexto argentino, para comparar meses: inflación y tipo de cambio. Se pueden bajar datos
  públicos; los movimientos nunca suben.
- Volver a medir la flota de la fase 2 con las decisiones del usuario como etiquetas reales. Hoy
  su benchmark es sintético, de 26 casos.
- Detector de duplicados.
- Guardar cada proyección y compararla contra lo real cuando el mes cierra.
- Cargar el mes en curso a medias: reemplazar un resumen parcial por el completo.
- Automatizar la descarga del resumen, confirmándolo antes con el usuario.

---

## Detalles conocidos

- **Probar la solapa Cargar en el navegador.** El selector de archivos del sistema no se maneja
  desde las herramientas: se arma el archivo dentro de la página con `DataTransfer`, se asigna
  a `input.files` y se dispara `change`. Con un CSV sintético alcanza.
- **El panel del navegador busca `.claude/launch.json` en la carpeta donde arrancó la sesión.**
  Si arrancó en el Escritorio, hace falta una copia temporal ahí, con rutas absolutas y barras
  hacia adelante. Se borra al terminar.
- Para la base, 127.0.0.1 y no `localhost`: con Postgres publicado sólo en IPv4, `localhost`
  prueba primero `::1` y cada conexión espera a que venza. Ver `FASE-4.md`.
- La bandeja muestra todas las contrapartes sin paginar: hoy, 166 tarjetas.
- Los grupos sin contraparte comparten el `aria-label` "Categoría para Sin contraparte".
- En las herramientas del navegador, `read_page` nombra el `select` por la opción elegida, no
  por su `aria-label`. Para ubicarlo, usá la ref del combobox que está justo antes del botón
  "Aplicar categoría a …".
- Un resumen que no cuadra se guarda igual, como descuadrado. Reingerirlo después de arreglar
  el parser choca con su sha256: habría que borrarlo antes, y eso se le pregunta al usuario.

---

## Lo que hace el usuario, en paralelo

1. Revisar en la bandeja: 20 decisiones resuelven 308 de los 536 movimientos.
2. A principios de octubre, generar el resumen de septiembre completo (del 1 al 30), cargarlo y
   correr `tools.curva`.
3. Levantar Docker cuando se vaya a trabajar.

---

## Fuera de este proyecto

- ScalistAI es otro proyecto del usuario, con contenedores Docker propios.
- Lo demás que es del usuario y no del proyecto, en `privado/NOTAS.md`.
