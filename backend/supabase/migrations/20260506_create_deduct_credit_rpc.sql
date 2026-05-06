-- ============================================================
-- Migration: deduct_credit_atomic
-- Propósito: Descuenta 1 crédito de llamada de forma atómica.
--
-- La operación es un UPDATE con condición (creditos_llamadas > 0)
-- en una sola sentencia SQL. Esto elimina la race condition del
-- patrón read-modify-write que existía en el código Python.
--
-- Retorna:
--   INTEGER: créditos restantes tras la deducción.
--   NULL:    si la empresa no existe o ya tenía 0 créditos
--            (el UPDATE no afectó ninguna fila).
-- ============================================================

CREATE OR REPLACE FUNCTION deduct_credit_atomic(empresa_id_param INTEGER)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER  -- Se ejecuta con permisos del owner, no del caller (anon/service_role)
AS $$
DECLARE
    remaining INTEGER;
BEGIN
    UPDATE empresas
    SET creditos_llamadas = creditos_llamadas - 1
    WHERE id = empresa_id_param
      AND creditos_llamadas > 0
    RETURNING creditos_llamadas INTO remaining;

    -- Si no se actualizó ninguna fila, remaining queda NULL.
    -- El código Python interpreta NULL como "sin créditos".
    RETURN remaining;
END;
$$;

-- Garantizar que solo el backend (service_role) puede ejecutar esta función.
-- El rol anon no debe poder restar créditos directamente desde el cliente.
REVOKE ALL ON FUNCTION deduct_credit_atomic(INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION deduct_credit_atomic(INTEGER) TO service_role;
