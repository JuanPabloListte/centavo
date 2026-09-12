-- Migración 001: la identidad de un movimiento.
--
-- Hasta acá, (fuente, id_operacion) era único. En los resúmenes reales de mayo
-- y junio, la devolución de un pago trae el mismo ID de operación que el pago,
-- a veces otro día y por otro monto, y el índice rechazaba el resumen entero.
-- La identidad pasa a ser ID + fecha + monto + repetición.
--
-- Idempotente: sobre una base que ya la tiene, o creada con el schema.sql
-- actual, no cambia nada. El índice viejo se borra sólo del esquema actual,
-- nunca de otro que esté más atrás en el search_path.
--
--     python -m tools.migrar

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS repeticion SMALLINT NOT NULL DEFAULT 1;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = current_schema()
          AND indexname = 'transactions_fuente_operacion_uq'
    ) THEN
        EXECUTE 'DROP INDEX ' || quote_ident(current_schema())
             || '.transactions_fuente_operacion_uq';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS transactions_identidad_uq
    ON transactions (fuente, id_operacion, fecha, monto, repeticion)
    WHERE id_operacion IS NOT NULL;
