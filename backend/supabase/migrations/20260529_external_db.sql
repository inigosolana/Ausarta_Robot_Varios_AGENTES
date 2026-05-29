-- =============================================================================
-- Fase 2 — Conexión a BD Externa del Cliente
-- Almacena la configuración de acceso a sistemas externos (CRM, ERP, etc.)
-- para que el agente pueda consultar datos del cliente en tiempo real.
-- =============================================================================

CREATE TABLE IF NOT EXISTS empresa_external_db (
  id              BIGSERIAL PRIMARY KEY,
  empresa_id      BIGINT NOT NULL UNIQUE REFERENCES empresas(id) ON DELETE CASCADE,
  db_type         TEXT NOT NULL DEFAULT 'rest',     -- 'postgresql' | 'rest'
  connection_url  TEXT,                             -- cifrado con crypto_service
  api_url         TEXT,
  api_key_enc     TEXT,                             -- API key cifrada
  api_key_header  TEXT DEFAULT 'Authorization',
  queries         JSONB DEFAULT '{}'::JSONB,         -- {nombre: sql_o_path}
  activo          BOOLEAN DEFAULT true,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE empresa_external_db ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS ext_db_superadmin ON empresa_external_db
  FOR ALL
  USING (EXISTS (
    SELECT 1 FROM user_profiles
    WHERE id = auth.uid() AND role IN ('superadmin', 'admin')
  ));

CREATE POLICY IF NOT EXISTS ext_db_tenant ON empresa_external_db
  FOR ALL
  USING (
    empresa_id = (
      SELECT empresa_id FROM user_profiles WHERE id = auth.uid() LIMIT 1
    )
  );
