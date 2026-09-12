-- Migración 002: una devolución unida a su pago.
--
-- En los resúmenes reales de Mercado Pago, la devolución de un pago trae el
-- mismo ID de operación que el pago. `devuelve_a` apunta al movimiento que se
-- devuelve. Lo calcula el código (app/devoluciones.py), al guardar cada
-- resumen y, para lo que ya estaba cargado, al correr `python -m tools.migrar`,
-- que después de aplicar los .sql une lo que falte.
--
-- Idempotente: sobre una base que ya la tiene, o creada con el schema.sql
-- actual, no cambia nada.
--
--     python -m tools.migrar

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS devuelve_a BIGINT
        REFERENCES transactions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS transactions_devuelve_a_idx ON transactions (devuelve_a);
