-- Webhook event log para auditoría y replay
CREATE TABLE IF NOT EXISTS public.webhook_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    CONSTRAINT webhook_events_status_chk CHECK (
        status IN ('pending', 'processed', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_source_created
    ON public.webhook_events (source, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_webhook_events_status
    ON public.webhook_events (status) WHERE status = 'pending';

ALTER TABLE public.webhook_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "webhook_events: superadmin" ON public.webhook_events;
CREATE POLICY "webhook_events: superadmin" ON public.webhook_events
    FOR ALL TO authenticated
    USING (public.has_global_access())
    WITH CHECK (public.has_global_access());
