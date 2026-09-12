-- Centavo — esquema de la fase 0.
-- Sólo lo que hace falta para parsear, normalizar y cuadrar.
-- Comercios, categorías, correcciones y embeddings entran en fases posteriores.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Un resumen ingerido. El sha256 es la clave de idempotencia: el mismo archivo
-- no se procesa dos veces.
--
-- Un resumen cierra de una de dos formas, y el CHECK obliga a que sea
-- exactamente una:
--   'total'  -> tarjeta: declara un total que es la suma de los consumos
--   'saldos' -> cuenta: declara saldo inicial y final, cierra la diferencia
-- ---------------------------------------------------------------------------
CREATE TABLE statements (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    banco           TEXT        NOT NULL,
    archivo         TEXT        NOT NULL,
    sha256          CHAR(64)    NOT NULL UNIQUE,
    periodo_desde   DATE        NOT NULL,
    periodo_hasta   DATE        NOT NULL,

    cierre_tipo     TEXT        NOT NULL CHECK (cierre_tipo IN ('total', 'saldos')),

    -- Plata SIEMPRE en NUMERIC. Nunca DOUBLE PRECISION.
    total_declarado NUMERIC(14,2),
    saldo_inicial   NUMERIC(14,2),
    saldo_final     NUMERIC(14,2),

    -- Lo que la compuerta esperaba y lo que efectivamente sumó.
    esperado        NUMERIC(14,2) NOT NULL,
    calculado       NUMERIC(14,2) NOT NULL,

    -- 'cuadrado'    -> la suma coincide; los movimientos son de fiar
    -- 'descuadrado' -> no coincide; queda el registro pero las fases
    --                  siguientes NO leen de acá
    estado          TEXT        NOT NULL
                    CHECK (estado IN ('cuadrado', 'descuadrado')),

    ingerido_en     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT periodo_coherente CHECK (periodo_hasta >= periodo_desde),

    CONSTRAINT cierre_coherente CHECK (
        (cierre_tipo = 'total'
            AND total_declarado IS NOT NULL
            AND saldo_inicial   IS NULL
            AND saldo_final     IS NULL)
     OR (cierre_tipo = 'saldos'
            AND total_declarado IS NULL
            AND saldo_inicial   IS NOT NULL
            AND saldo_final     IS NOT NULL)
    )
);

-- ---------------------------------------------------------------------------
-- Un movimiento normalizado.
-- Convención de signo: negativo = débito (sale), positivo = crédito (entra).
-- ---------------------------------------------------------------------------
CREATE TABLE transactions (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    statement_id       BIGINT      NOT NULL
                       REFERENCES statements(id) ON DELETE CASCADE,

    fecha              DATE        NOT NULL,
    monto              NUMERIC(14,2) NOT NULL,
    moneda             TEXT        NOT NULL CHECK (moneda IN ('ARS', 'USD')),

    -- La descripción del banco, intacta. No limpiar acá: los agentes de la
    -- fase 2 necesitan el texto crudo para normalizar el comercio.
    descripcion_cruda  TEXT        NOT NULL,
    linea_origen       INTEGER     NOT NULL,

    CONSTRAINT monto_no_cero CHECK (monto <> 0)
);

CREATE INDEX transactions_statement_idx ON transactions (statement_id);
CREATE INDEX transactions_fecha_idx     ON transactions (fecha);

-- ---------------------------------------------------------------------------
-- Vista de control: qué resumen no cuadra y por cuánto, sin salir de psql.
-- ---------------------------------------------------------------------------
CREATE VIEW v_cuadratura AS
SELECT
    s.id,
    s.banco,
    s.archivo,
    s.cierre_tipo,
    s.estado,
    s.esperado,
    COALESCE(SUM(t.monto), 0)              AS suma_movimientos,
    s.esperado - COALESCE(SUM(t.monto), 0) AS diferencia,
    COUNT(t.id)                            AS cantidad_movimientos
FROM statements s
LEFT JOIN transactions t ON t.statement_id = s.id
GROUP BY s.id;


-- ===========================================================================
-- FASE 1 — clasificación
-- ===========================================================================

CREATE TABLE categories (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre      TEXT NOT NULL UNIQUE,
    descripcion TEXT NOT NULL
);

INSERT INTO categories (nombre, descripcion) VALUES
 ('Supermercado y Almacén', 'Supermercados, kioscos, verdulerías, panaderías, carnicerías'),
 ('Gastronomía',            'Restaurantes, bares, cafeterías, delivery de comida'),
 ('Transporte',             'Taxis, apps de viaje, colectivo, subte, peajes, estacionamiento'),
 ('Combustible',            'Estaciones de servicio, carga de nafta o gas'),
 ('Servicios',              'Luz, agua, gas, expensas, ABL'),
 ('Telefonía e Internet',   'Celular, internet, cable'),
 ('Suscripciones',          'Streaming, software, membresías con débito recurrente'),
 ('Salud y Farmacia',       'Farmacias, obra social, consultas, estudios'),
 ('Indumentaria',           'Ropa, calzado, accesorios'),
 ('Hogar y Electro',        'Muebles, electrodomésticos, ferretería, decoración'),
 ('Educación',              'Cursos, librerías, material de estudio, matrículas'),
 ('Entretenimiento',        'Cine, espectáculos, juegos, salidas'),
 ('Impuestos y Comisiones', 'Impuestos, sellados, comisiones e intereses bancarios'),
 ('Pagos y Transferencias', 'Pagos de tarjeta, transferencias, acreditaciones, sueldos'),
 ('Otros',                  'No encaja en ninguna de las anteriores');

-- La memoria determinista vive en la sección FASE 3, al final del archivo.

ALTER TABLE transactions
    ADD COLUMN categoria_id BIGINT REFERENCES categories(id),
    ADD COLUMN confianza    NUMERIC(3,2) CHECK (confianza BETWEEN 0 AND 1),
    ADD COLUMN via          TEXT CHECK (via IN ('regla', 'evidencia', 'modelo', 'consenso', 'desacuerdo')),
    ADD COLUMN estado_clasificacion TEXT NOT NULL DEFAULT 'sin_procesar'
        CHECK (estado_clasificacion IN ('sin_procesar', 'resuelto', 'needs_review'));

CREATE INDEX transactions_estado_clas_idx ON transactions (estado_clasificacion);

-- Un movimiento resuelto tiene categoría; uno a revisión puede tenerla como
-- sugerencia. Lo que no puede pasar es resolverse sin categoría.
ALTER TABLE transactions
    ADD CONSTRAINT resuelto_tiene_categoria CHECK (
        estado_clasificacion <> 'resuelto' OR categoria_id IS NOT NULL
    );


-- ===========================================================================
-- RESUMEN DE MERCADO PAGO — movimientos que no son gastos ni ingresos
-- ===========================================================================

-- Categorías que asigna sólo el código, nunca el modelo. Se detectan por
-- textos fijos de la fuente ("Dinero reservado", "Rendimientos") o
-- comparando con el titular del resumen. Ofrecérselas al modelo sólo le
-- sumaría opciones para equivocarse, y movería el benchmark de la fase 2.
ALTER TABLE categories
    ADD COLUMN solo_determinista BOOLEAN NOT NULL DEFAULT false;

INSERT INTO categories (nombre, descripcion, solo_determinista) VALUES
 ('Ahorro y reservas',
  'Plata apartada en una reserva propia o retirada de ella. No es gasto ni ingreso', true),
 ('Movimientos entre cuentas propias',
  'Transferencias entre cuentas del mismo titular. No es gasto ni ingreso', true),
 ('Rendimientos e intereses',
  'Rendimientos del saldo invertido e intereses cobrados', true);

ALTER TABLE transactions
    ADD COLUMN fuente       TEXT,
    ADD COLUMN id_operacion TEXT,
    ADD COLUMN saldo        NUMERIC(14,2),
    ADD COLUMN repeticion   SMALLINT NOT NULL DEFAULT 1;

-- Idempotencia a nivel movimiento. El sha256 del archivo no alcanza: si el
-- mismo mes se descarga dos veces, el PDF puede regenerarse con otra fecha de
-- creación y otro hash. Los movimientos, en cambio, son los mismos.
--
-- El ID de operación solo no identifica un movimiento: en resúmenes reales, la
-- devolución de un pago trae el mismo ID que el pago, a veces otro día y por
-- otro monto. La identidad es ID + fecha + monto, y `repeticion` numera en
-- orden los que coinciden en las tres cosas dentro de un mismo archivo.
-- Para una base creada antes de este cambio: db/migraciones/001_identidad_del_movimiento.sql
CREATE UNIQUE INDEX transactions_identidad_uq
    ON transactions (fuente, id_operacion, fecha, monto, repeticion)
    WHERE id_operacion IS NOT NULL;


-- ===========================================================================
-- FASE 3 — memoria
-- ===========================================================================

-- La memoria se indexa por CLAVE DE CONTRAPARTE, no por descripción exacta:
-- "Pedido de 3 productos X" y "Pedido de 2 productos X" son el mismo comercio.
-- La clave la calcula el código (app/agents/patrones.py: clave_memoria) y es
-- exacta a propósito. No hay búsqueda por parecido: en un resumen real, cuatro
-- palabras aparecían en dos o más destinatarios distintos de transferencias, y
-- una búsqueda difusa le pasaría la categoría de una persona a otra.
CREATE TABLE memoria (
    clave           TEXT   PRIMARY KEY,
    categoria_id    BIGINT NOT NULL REFERENCES categories(id),
    confirmaciones  INTEGER NOT NULL DEFAULT 1 CHECK (confirmaciones >= 1),
    creada_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizada_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cada decisión tuya, movimiento por movimiento. Es el conjunto etiquetado del
-- proyecto, generado por el uso: de acá sale la curva de corrección.
CREATE TABLE correcciones (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_id         BIGINT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    clave                  TEXT   NOT NULL,
    categoria_anterior_id  BIGINT REFERENCES categories(id),
    categoria_nueva_id     BIGINT NOT NULL REFERENCES categories(id),
    corregido_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- El titular hace falta para reconocer transferencias entre cuentas propias al
-- clasificar después de guardar; la clave, para agrupar la revisión.
ALTER TABLE statements   ADD COLUMN titular TEXT;
ALTER TABLE transactions ADD COLUMN clave   TEXT;

CREATE INDEX transactions_clave_idx ON transactions (clave);


-- ===========================================================================
-- FASE 4 — una devolución unida a su pago
-- ===========================================================================

-- La devolución de un pago trae el mismo ID de operación que el pago. Se une
-- al movimiento que devuelve y toma su clave: una decisión sobre el comercio
-- resuelve las dos, y en el reporte la devolución resta del gasto en vez de
-- contarse como ingreso. Lo calcula app/devoluciones.py al guardar. Una
-- devolución cuyo pago no está cargado queda sin vínculo y se revisa aparte.
-- Para una base creada antes de este cambio: db/migraciones/002_devoluciones.sql
ALTER TABLE transactions
    ADD COLUMN devuelve_a BIGINT REFERENCES transactions(id) ON DELETE SET NULL;

CREATE INDEX transactions_devuelve_a_idx ON transactions (devuelve_a);
