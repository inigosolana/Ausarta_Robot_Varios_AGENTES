-- Límite de gasto mensual por empresa (unit economics / FinOps).
ALTER TABLE public.empresas
    ADD COLUMN IF NOT EXISTS monthly_spend_limit_eur NUMERIC(12, 4);

COMMENT ON COLUMN public.empresas.monthly_spend_limit_eur IS
    'Tope de gasto mensual en EUR (NULL = sin límite). Superado → HTTP 402 en nuevas llamadas.';
