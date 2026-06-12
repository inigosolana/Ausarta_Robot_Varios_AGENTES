-- ──────────────────────────────────────────────────────────────────────────────
-- Migración: añadir outbound_prefix a company_yeastar_configs
--
-- Este campo almacena el dígito (o dígitos) de acceso a la ruta saliente del PBX
-- que se antepone a los números externos en las transferencias de llamada.
-- Ej: "0" (para PBX que requieren marcar 0 para línea exterior), "" (sin prefijo).
-- ──────────────────────────────────────────────────────────────────────────────

ALTER TABLE company_yeastar_configs
    ADD COLUMN IF NOT EXISTS outbound_prefix TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN company_yeastar_configs.outbound_prefix IS
    'Dígito(s) de acceso a ruta saliente para números externos (ej. "0", "9"). '
    'Vacío si el PBX puede marcar números externos directamente sin prefijo.';

-- Ejemplo: configurar prefijo "0" para empresa_id=42
-- UPDATE company_yeastar_configs SET outbound_prefix = '0' WHERE empresa_id = 42;
