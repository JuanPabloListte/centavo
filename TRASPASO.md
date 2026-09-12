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
- **La carpeta** sigue siendo `libro-mayor`: renombrarla desde adentro de la sesión la rompe.
  Lo hace el usuario: cerrar la sesión, renombrar a `centavo`, abrir el proyecto de nuevo. La
  memoria del agente ya está copiada a la clave de la carpeta nueva.

### Entorno y archivos

- **Docker:** al escribir esto, el contenedor de Postgres de este proyecto estaba **apagado**;
  sólo corrían los de ScalistAI. Pedile al usuario que lo levante (`docker compose up -d` desde
  esta carpeta) antes de cualquier cosa que use la base. Un `psycopg.connect` sin base puede
  quedar colgado en vez de fallar.
- **Tests:** 115 pasan y 1 se saltea: el del PDF real, que corre con `CENTAVO_RESUMEN_REAL`
  apuntando al archivo. `npm run build` pasa.
- **Esquema `demo`:** trae una devolución sintética unida a su pago (la agrega `tools.demo`,
  no el PDF) y una decisión aplicada en la prueba de la interfaz. `python -m tools.demo` lo
  rearma desde cero.
- **PDF reales:** fuera del repositorio; dónde están, en `privado/NOTAS.md`. La base ya no
  los necesita.
- **Git:** repositorio local iniciado el 12/09/2026, rama `main`, sin remoto. Commits, push y
  remotos, sólo con pedido explícito del usuario. `.github/workflows/ci.yml` existe pero no
  corrió nunca: se prueba recién cuando haya remoto.
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
| Celery + Redis | Ingesta sincrónica, por terminal | Sin modelo, un resumen tarda segundos. Si la carga pasa al navegador con la flota, que tarda minutos, ahí hace falta un proceso en segundo plano |
| Tailwind | CSS propio, con tokens de tema claro y oscuro | No hizo falta |
| OpenTelemetry + Langfuse, SSE, cuotas, contexto argentino, GitHub Actions | Pendiente | Resto de la fase 4 |
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

### Tarea 2: gastos recurrentes y proyección del mes

Es la parte central del producto. La especificación pide que la proyección salga de aritmética
(suscripciones activas, cuotas pendientes, promedio por rubro) y que el modelo, como mucho,
redacte la explicación de un número ya calculado.

1. **Medir primero, con conteos.**
   - Cuántas claves aparecen en 3, 4 y 5 meses, por tipo.
   - Qué tan estable es el monto y el día del mes.
   - Si el resumen de cuenta muestra cuotas: contá cuántas descripciones las mencionan.
2. **Detector determinista por clave.**
   - Criterios: meses consecutivos, monto parecido, día del mes parecido.
   - Excluí internos, rendimientos y lo que resuelve la evidencia. Una devolución unida a su
     pago (`devuelve_a`) resta de ese pago: para medir recurrencia, netearla.
   - Ojo con la inflación: en Argentina un servicio sube mes a mes, así que una tolerancia fija
     sobre el monto no alcanza. Probá tolerancia relativa o tendencia, y fijala con los datos.
   - **Precisión antes que recall:** detectar un recurrente que no existe molesta más que no
     detectar uno.
3. **Proyección, en dos niveles.**
   - Recurrentes esperados que todavía no aparecieron: no depende de que el usuario revise.
   - Promedio del gasto variable por categoría: depende de la revisión, y hay que decir cuánto
     está sin clasificar.
4. **API y una solapa nueva** con lo detectado y la proyección. Si hace falta persistir,
   migración con tabla propia.

**Para consultar con el usuario:**
- Qué hacer con transferencias recurrentes a personas, como un alquiler.
- Hasta cuándo proyectar: fin del mes en curso o el mes siguiente.
- De dónde sale el mes en curso: un resumen parcial generado a mitad de mes.

**Aceptación.**
- Tests con series sintéticas: mensual estable, con aumentos, irregular y de una sola vez.
- Sobre datos reales, sólo conteos.
- Toda cifra proyectada se puede reconstruir sumando.

### Tarea 3: corregir una decisión desde la bandeja

**Qué hay.** `aplicar_decision(conn, clave, categoria)` ya aplica a todos los movimientos con
esa clave, pisa lo resuelto, actualiza la memoria y registra cada cambio en `correcciones`, con
la categoría anterior. Falta:

- Un endpoint que liste lo resuelto por contraparte: clave, nombre, categoría, vía y cantidad.
- Una vista "Resueltos" en la web, con búsqueda y cambio de categoría.
- **Un detalle a corregir, con test:** hoy cambiar la categoría suma una confirmación en
  `memoria.confirmaciones`. Cambiarla debería reiniciar el conteo, no sumar.

**Por qué importa.** Las correcciones sobre movimientos que resolvió la memoria (`via = 'regla'`)
son el error de la memoria. Con eso la curva deja de ser un techo y pasa a medir cuánto acierta.

**Para consultar:** si se permite pisar lo que decidió la evidencia (una reserva, una
transferencia propia), y con qué aviso.

### Tarea 4: contenedores y observabilidad

- **Compose con `api` y `web`** además de `db`.
  - Ollama queda en el host, por la GPU: desde el contenedor, `host.docker.internal:11434`.
  - Los puertos se publican sólo en `127.0.0.1`.
  - Límites de memoria pensados para 16 GB con Ollama cargado.
- **Observabilidad.** La especificación pide OpenTelemetry con Langfuse autohospedado. Antes de
  elegirlo, verificá sus requisitos actuales: autohospedado suma varios servicios, y puede no
  entrar en la RAM junto a Ollama. Alternativa liviana: una tabla de corridas en Postgres (vías,
  desacuerdos, tokens y latencia por resumen) más spans de OpenTelemetry. Decidilo con el
  usuario.
- **Aceptación:** `docker compose up` levanta todo, los tests siguen corriendo en local y nada
  escucha fuera de `127.0.0.1`.

### Después, sin orden fijo

- Cargar un PDF desde el navegador, con progreso por SSE.
- Contexto argentino, para comparar meses: inflación y tipo de cambio. Se pueden bajar datos
  públicos; los movimientos nunca suben.
- Volver a medir la flota de la fase 2 con las decisiones del usuario como etiquetas reales. Hoy
  su benchmark es sintético, de 26 casos.
- Detector de duplicados.
- Automatizar la descarga del resumen, confirmándolo antes con el usuario.

---

## Detalles conocidos

- `POST /api/ingest` devuelve `clasificacion` sumando lo pendiente de todos los meses.
  `tools.ingerir` ya se corrigió con `conteo_del_resumen`; la API no.
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
