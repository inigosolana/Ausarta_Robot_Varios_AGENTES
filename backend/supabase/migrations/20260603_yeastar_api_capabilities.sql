-- Capacidades API Yeastar seleccionables por empresa.

ALTER TABLE public.company_yeastar_configs
ADD COLUMN IF NOT EXISTS enabled_capabilities text[] NOT NULL DEFAULT '{}';
