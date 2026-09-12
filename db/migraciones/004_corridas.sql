-- Migración 004: una fila por ingesta, para observar el sistema sin mirar datos.
--
-- Guarda cuánto tardó, cómo terminó, cuántos movimientos del resumen resolvió cada
-- vía y cuánto costó el modelo. No guarda descripciones, montos, nombres ni el
-- texto de un error: de un error queda sólo la clase. Ver app/corridas.py.
--
-- Idempotente.
--
--     python -m tools.migrar

CREATE TABLE IF NOT EXISTS corridas (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    origen           TEXT          NOT NULL CHECK (origen IN ('terminal', 'api')),
    statement_id     BIGINT        REFERENCES statements(id) ON DELETE SET NULL,
    empezo_en        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    milisegundos     INTEGER       NOT NULL CHECK (milisegundos >= 0),
    resultado        TEXT          NOT NULL CHECK (resultado IN
                         ('cuadrado', 'descuadrado', 'ya_ingerido', 'superposicion', 'error')),
    movimientos      INTEGER       NOT NULL DEFAULT 0,
    por_via          JSONB         NOT NULL DEFAULT '{}'::jsonb,
    desacuerdos      INTEGER       NOT NULL DEFAULT 0,
    modelo           TEXT,
    llamadas_modelo  INTEGER       NOT NULL DEFAULT 0,
    tokens_entrada   INTEGER       NOT NULL DEFAULT 0,
    tokens_salida    INTEGER       NOT NULL DEFAULT 0,
    reparaciones     INTEGER       NOT NULL DEFAULT 0,
    segundos_modelo  NUMERIC(10,2) NOT NULL DEFAULT 0,
    error_tipo       TEXT
);

CREATE INDEX IF NOT EXISTS corridas_empezo_idx ON corridas (empezo_en DESC);
