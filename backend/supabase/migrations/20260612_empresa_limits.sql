-- ──────────────────────────────────────────────────────────────────────────────
-- Migración: empresa_limits
-- Tabla de límites de rate limiting por empresa (multi-tenant).
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS empresa_limits (
    empresa_id  integer     PRIMARY KEY REFERENCES empresas(id) ON DELETE CASCADE,
    rpm         integer     NOT NULL DEFAULT 120,   -- requests por minuto
    burst       integer     NOT NULL DEFAULT 240,   -- pico momentáneo (reservado)
    notas       text,                               -- comentario libre (ej. "plan PRO")
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- RLS: solo superadmin puede leer/modificar
ALTER TABLE empresa_limits ENABLE ROW LEVEL SECURITY;

CREATE POLICY "superadmin_full_access" ON empresa_limits
    FOR ALL
    TO authenticated
    USING  (auth.jwt() ->> 'role' = 'superadmin')
    WITH CHECK (auth.jwt() ->> 'role' = 'superadmin');

-- Índice (PK ya lo crea automáticamente)

-- Trigger para actualizar updated_at
CREATE OR REPLACE FUNCTION _set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'empresa_limits_updated_at'
    ) THEN
        CREATE TRIGGER empresa_limits_updated_at
            BEFORE UPDATE ON empresa_limits
            FOR EACH ROW EXECUTE FUNCTION _set_updated_at();
    END IF;
END;
$$;

-- Ejemplo: reducir límite a 60 rpm para empresa_id=42
-- INSERT INTO empresa_limits (empresa_id, rpm, notas)
-- VALUES (42, 60, 'Plan básico')
-- ON CONFLICT (empresa_id) DO UPDATE SET rpm = EXCLUDED.rpm, notas = EXCLUDED.notas;
