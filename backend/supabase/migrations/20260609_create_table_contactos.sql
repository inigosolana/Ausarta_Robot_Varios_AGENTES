CREATE TABLE IF NOT EXISTS contactos (
    id BIGSERIAL PRIMARY KEY,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id),
    telefono VARCHAR(20) NOT NULL,
    nombre VARCHAR(200),
    email VARCHAR(200),
    empresa_nombre VARCHAR(200),
    cargo VARCHAR(200),
    notas TEXT,
    historial_llamadas JSONB DEFAULT '[]',
    datos_crm JSONB DEFAULT '{}',
    ultima_llamada_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(empresa_id, telefono)
);

ALTER TABLE contactos
    ADD COLUMN IF NOT EXISTS email VARCHAR(200),
    ADD COLUMN IF NOT EXISTS empresa_nombre VARCHAR(200),
    ADD COLUMN IF NOT EXISTS cargo VARCHAR(200),
    ADD COLUMN IF NOT EXISTS notas TEXT,
    ADD COLUMN IF NOT EXISTS historial_llamadas JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS datos_crm JSONB DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS ultima_llamada_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_contactos_empresa_telefono
    ON contactos(empresa_id, telefono);
