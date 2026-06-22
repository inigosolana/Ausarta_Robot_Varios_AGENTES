-- Límite de llamadas concurrentes por empresa (contrato SaaS)
ALTER TABLE public.empresas
    ADD COLUMN IF NOT EXISTS max_concurrent_calls INT NOT NULL DEFAULT 1;

COMMENT ON COLUMN public.empresas.max_concurrent_calls IS
    'Máximo de llamadas SIP simultáneas para este tenant (goteo + burst).';
