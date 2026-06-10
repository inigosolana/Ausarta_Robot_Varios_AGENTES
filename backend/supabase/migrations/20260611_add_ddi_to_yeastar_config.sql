-- Añade columna ddi a company_yeastar_configs
-- ddi: número de teléfono entrante del cliente (E.164), ej: +34911234501
ALTER TABLE company_yeastar_configs
ADD COLUMN IF NOT EXISTS ddi VARCHAR(32);
