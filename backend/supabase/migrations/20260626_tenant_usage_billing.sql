-- ──────────────────────────────────────────────────────────────────────────────
-- Unit Economics: seguimiento de consumo por tenant (empresa_id)
-- Eventos granulares + agregados mensuales para dashboard y facturación.
-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.tenant_usage_events (
    id          BIGSERIAL PRIMARY KEY,
    empresa_id  INTEGER NOT NULL REFERENCES public.empresas(id) ON DELETE CASCADE,
    event_type  VARCHAR(32) NOT NULL,
    period      VARCHAR(7)  NOT NULL,
    quantity    NUMERIC(18, 4) NOT NULL,
    unit        VARCHAR(32) NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tenant_usage_events_event_type_chk CHECK (
        event_type IN ('llm_tokens', 'tts_characters', 'telephony_seconds')
    )
);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_events_empresa_period
    ON public.tenant_usage_events (empresa_id, period);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_events_created_at
    ON public.tenant_usage_events (created_at DESC);

CREATE TABLE IF NOT EXISTS public.tenant_usage_monthly (
    empresa_id  INTEGER NOT NULL REFERENCES public.empresas(id) ON DELETE CASCADE,
    period      VARCHAR(7)  NOT NULL,
    category    VARCHAR(32) NOT NULL,
    sub_key     VARCHAR(128) NOT NULL DEFAULT '',
    quantity    NUMERIC(18, 4) NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (empresa_id, period, category, sub_key),
    CONSTRAINT tenant_usage_monthly_category_chk CHECK (
        category IN ('llm_prompt_tokens', 'llm_completion_tokens', 'tts_characters', 'telephony_seconds')
    )
);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_monthly_period
    ON public.tenant_usage_monthly (period);

CREATE OR REPLACE FUNCTION public.upsert_tenant_usage_monthly(
    p_empresa_id INTEGER,
    p_period VARCHAR(7),
    p_category VARCHAR(32),
    p_sub_key VARCHAR(128),
    p_quantity NUMERIC
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    INSERT INTO public.tenant_usage_monthly (
        empresa_id, period, category, sub_key, quantity, updated_at
    )
    VALUES (
        p_empresa_id,
        p_period,
        p_category,
        COALESCE(p_sub_key, ''),
        p_quantity,
        now()
    )
    ON CONFLICT (empresa_id, period, category, sub_key)
    DO UPDATE SET
        quantity = tenant_usage_monthly.quantity + EXCLUDED.quantity,
        updated_at = now();
$$;

ALTER TABLE public.tenant_usage_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_usage_monthly ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_usage_events: superadmin" ON public.tenant_usage_events;
CREATE POLICY "tenant_usage_events: superadmin" ON public.tenant_usage_events
    FOR ALL TO authenticated
    USING (public.has_global_access())
    WITH CHECK (public.has_global_access());

DROP POLICY IF EXISTS "tenant_usage_events: tenant read" ON public.tenant_usage_events;
CREATE POLICY "tenant_usage_events: tenant read" ON public.tenant_usage_events
    FOR SELECT TO authenticated
    USING (
        public.get_my_empresa_id() IS NOT NULL
        AND empresa_id = public.get_my_empresa_id()
    );

DROP POLICY IF EXISTS "tenant_usage_monthly: superadmin" ON public.tenant_usage_monthly;
CREATE POLICY "tenant_usage_monthly: superadmin" ON public.tenant_usage_monthly
    FOR ALL TO authenticated
    USING (public.has_global_access())
    WITH CHECK (public.has_global_access());

DROP POLICY IF EXISTS "tenant_usage_monthly: tenant read" ON public.tenant_usage_monthly;
CREATE POLICY "tenant_usage_monthly: tenant read" ON public.tenant_usage_monthly
    FOR SELECT TO authenticated
    USING (
        public.get_my_empresa_id() IS NOT NULL
        AND empresa_id = public.get_my_empresa_id()
    );
