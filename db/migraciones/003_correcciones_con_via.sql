-- Migración 003: qué había antes de cada corrección.
--
-- `correcciones` guardaba la categoría anterior, pero no cómo se había llegado
-- a ella. Para medir cuánto acierta la memoria hace falta saber si el
-- movimiento corregido lo había resuelto la memoria sola (vía 'regla', sin una
-- decisión directa antes), la evidencia o el modelo. Las filas viejas quedan
-- con NULL: no se inventa lo que no se registró.
--
-- Idempotente.
--
--     python -m tools.migrar

ALTER TABLE correcciones
    ADD COLUMN IF NOT EXISTS via_anterior    TEXT,
    ADD COLUMN IF NOT EXISTS estado_anterior TEXT;
