-- =============================================================
-- 20260622_api_keys.sql
-- API keys por tenant (hash SHA-256, nunca en claro en BD).
-- =============================================================

CREATE TABLE IF NOT EXISTS public.api_keys (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id    integer NOT NULL REFERENCES public.empresas(id) ON DELETE CASCADE,
    key_hash      text NOT NULL UNIQUE,
    key_prefix    text NOT NULL,
    description   text,
    scopes        text[] NOT NULL DEFAULT ARRAY['outbound_call']::text[],
    is_active     boolean NOT NULL DEFAULT true,
    expires_at    timestamptz,
    created_by    uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz,
    CONSTRAINT api_keys_scopes_not_empty CHECK (array_length(scopes, 1) >= 1)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_empresa ON public.api_keys(empresa_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash_active ON public.api_keys(key_hash) WHERE is_active = true;

ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "api_keys: superadmin acceso total" ON public.api_keys;
DROP POLICY IF EXISTS "api_keys: admin ve y gestiona su empresa" ON public.api_keys;

CREATE POLICY "api_keys: superadmin acceso total" ON public.api_keys
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role = 'superadmin'
        )
    );

CREATE POLICY "api_keys: admin ve y gestiona su empresa" ON public.api_keys
    FOR ALL TO authenticated
    USING (
        empresa_id = (
            SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1
        )
        AND EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'superadmin')
        )
    )
    WITH CHECK (
        empresa_id = (
            SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1
        )
        AND EXISTS (
            SELECT 1 FROM public.user_profiles
            WHERE id = auth.uid() AND role IN ('admin', 'superadmin')
        )
    );
