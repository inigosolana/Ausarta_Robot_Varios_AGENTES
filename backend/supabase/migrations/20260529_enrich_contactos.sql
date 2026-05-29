-- =============================================================================
-- Fase 2 — Ficha de Cliente Enriquecida
-- Añade campos adicionales a la tabla contactos para historial unificado,
-- scoring y seguimiento de interacciones.
-- =============================================================================

ALTER TABLE contactos
  ADD COLUMN IF NOT EXISTS email               TEXT,
  ADD COLUMN IF NOT EXISTS empresa_nombre      TEXT,
  ADD COLUMN IF NOT EXISTS notas               TEXT,
  ADD COLUMN IF NOT EXISTS etiquetas           TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS ultima_llamada      TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS total_llamadas      INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ultima_disposicion  TEXT,
  ADD COLUMN IF NOT EXISTS score               INT DEFAULT 0;

-- Índice para búsqueda por nombre/teléfono
CREATE INDEX IF NOT EXISTS idx_contactos_telefono ON contactos(empresa_id, telefono);
CREATE INDEX IF NOT EXISTS idx_contactos_nombre   ON contactos(empresa_id, nombre);
