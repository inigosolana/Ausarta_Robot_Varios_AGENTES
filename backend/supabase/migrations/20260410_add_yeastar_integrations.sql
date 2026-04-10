-- ──────────────────────────────────────────────────────────────────────────────
-- Yeastar PBX integration config per company (multi-tenant)
-- empresa_id is INTEGER to match the existing empresas.id column type.
--
-- Password storage note:
--   api_password is stored as TEXT. For production hardening, enable
--   pgcrypto and wrap writes/reads with:
--     pgp_sym_encrypt(value, current_setting('app.encryption_key'))
--     pgp_sym_decrypt(value::bytea, current_setting('app.encryption_key'))
--   or use Supabase Vault secrets instead.
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS company_yeastar_configs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id  INTEGER     NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    api_url     VARCHAR(255) NOT NULL,
    api_port    INTEGER     NOT NULL DEFAULT 8088,
    api_username VARCHAR(100) NOT NULL,
    api_password TEXT        NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One config per company (upsert pattern)
    CONSTRAINT uq_yeastar_empresa UNIQUE (empresa_id)
);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_yeastar_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_yeastar_updated_at ON company_yeastar_configs;
CREATE TRIGGER trg_yeastar_updated_at
    BEFORE UPDATE ON company_yeastar_configs
    FOR EACH ROW EXECUTE FUNCTION update_yeastar_updated_at();

-- ── Row Level Security ──────────────────────────────────────────────────────
ALTER TABLE company_yeastar_configs ENABLE ROW LEVEL SECURITY;

-- Admins/users can only read their own company config
CREATE POLICY "yeastar_select_own_company"
    ON company_yeastar_configs FOR SELECT
    TO authenticated
    USING (
        empresa_id = (
            SELECT empresa_id FROM user_profiles
            WHERE id = auth.uid()
            LIMIT 1
        )
    );

-- Only admins of the company (or superadmins) can insert
CREATE POLICY "yeastar_insert_admin"
    ON company_yeastar_configs FOR INSERT
    TO authenticated
    WITH CHECK (
        empresa_id = (
            SELECT empresa_id FROM user_profiles
            WHERE id = auth.uid()
              AND role IN ('admin', 'superadmin')
            LIMIT 1
        )
    );

-- Only admins of the company (or superadmins) can update
CREATE POLICY "yeastar_update_admin"
    ON company_yeastar_configs FOR UPDATE
    TO authenticated
    USING (
        empresa_id = (
            SELECT empresa_id FROM user_profiles
            WHERE id = auth.uid()
              AND role IN ('admin', 'superadmin')
            LIMIT 1
        )
    );

-- Only admins of the company (or superadmins) can delete
CREATE POLICY "yeastar_delete_admin"
    ON company_yeastar_configs FOR DELETE
    TO authenticated
    USING (
        empresa_id = (
            SELECT empresa_id FROM user_profiles
            WHERE id = auth.uid()
              AND role IN ('admin', 'superadmin')
            LIMIT 1
        )
    );

-- Service-role bypasses RLS (backend uses service role key)
-- No additional policy needed; service role ignores RLS by default.
