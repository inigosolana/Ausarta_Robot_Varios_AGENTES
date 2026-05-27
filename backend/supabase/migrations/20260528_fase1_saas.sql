-- =============================================================================
-- Fase 1 SaaS — Planes, Contactos unificados, Extensiones Yeastar y Resumen
-- =============================================================================
-- Problema: el sistema no distinguía entre planes de empresa ni acumulaba
-- contactos de forma centralizada; tampoco guardaba un resumen legible de
-- cada llamada. Esta migración habilita la base para escalar a 200 empresas.
-- =============================================================================

-- Añadir Planes y Límites a las empresas
ALTER TABLE empresas 
ADD COLUMN IF NOT EXISTS plan VARCHAR(50) DEFAULT 'basico',
ADD COLUMN IF NOT EXISTS max_llamadas_mes INT DEFAULT 100,
ADD COLUMN IF NOT EXISTS max_agentes INT DEFAULT 1,
ADD COLUMN IF NOT EXISTS llamadas_consumidas_mes INT DEFAULT 0;

-- Crear tabla de Ficha de Cliente (Contactos) unificada por empresa
-- Nota: empresas.id es INTEGER (serial), no UUID.
CREATE TABLE IF NOT EXISTS contactos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    empresa_id INTEGER REFERENCES empresas(id) ON DELETE CASCADE,
    telefono VARCHAR(20) NOT NULL,
    nombre VARCHAR(100),
    email VARCHAR(100),
    datos_extra JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(empresa_id, telefono)
);

-- Políticas RLS para contactos (patrón consistente con campaigns/encuestas)
ALTER TABLE contactos ENABLE ROW LEVEL SECURITY;
CREATE POLICY "contactos: superadmin acceso total" ON contactos
    FOR ALL USING (has_global_access());
CREATE POLICY "contactos: tenant solo ve los suyos" ON contactos
    FOR ALL USING (
        empresa_id = (
            SELECT user_profiles.empresa_id
            FROM user_profiles
            WHERE user_profiles.id = auth.uid()
            LIMIT 1
        )
    );

-- Crear tabla de Extensiones Yeastar dinámicas por empresa
CREATE TABLE IF NOT EXISTS yeastar_extensions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    empresa_id INTEGER REFERENCES empresas(id) ON DELETE CASCADE,
    extension_number VARCHAR(20) NOT NULL,
    extension_name VARCHAR(100),
    departamento VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Políticas RLS para extensiones (patrón consistente con campaigns/encuestas)
ALTER TABLE yeastar_extensions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "yeastar_extensions: superadmin acceso total" ON yeastar_extensions
    FOR ALL USING (has_global_access());
CREATE POLICY "yeastar_extensions: tenant solo ve los suyos" ON yeastar_extensions
    FOR ALL USING (
        empresa_id = (
            SELECT user_profiles.empresa_id
            FROM user_profiles
            WHERE user_profiles.id = auth.uid()
            LIMIT 1
        )
    );

-- Añadir columna de resumen a encuestas para guardar el nuevo output del call_analyzer
ALTER TABLE encuestas ADD COLUMN IF NOT EXISTS resumen_llamada TEXT;

-- Función RPC para incrementar llamadas atómicamente y evitar condiciones de carrera (race conditions)
CREATE OR REPLACE FUNCTION increment_llamadas_consumidas(p_empresa_id INTEGER)
RETURNS void AS $$
BEGIN
    UPDATE empresas
    SET llamadas_consumidas_mes = COALESCE(llamadas_consumidas_mes, 0) + 1
    WHERE id = p_empresa_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
