-- =============================================================================
-- A/B testing de agentes en campañas (variante A vs B)
-- =============================================================================

ALTER TABLE public.campaigns
  ADD COLUMN IF NOT EXISTS ab_test_enabled BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS agent_id_b BIGINT REFERENCES public.agent_config(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS ab_split_ratio REAL NOT NULL DEFAULT 0.5;

ALTER TABLE public.campaigns
  DROP CONSTRAINT IF EXISTS campaigns_ab_split_ratio_range;

ALTER TABLE public.campaigns
  ADD CONSTRAINT campaigns_ab_split_ratio_range
  CHECK (ab_split_ratio >= 0.0 AND ab_split_ratio <= 1.0);

ALTER TABLE public.campaign_leads
  ADD COLUMN IF NOT EXISTS ab_variant TEXT;

ALTER TABLE public.encuestas
  ADD COLUMN IF NOT EXISTS ab_variant TEXT;

CREATE INDEX IF NOT EXISTS idx_encuestas_campaign_ab_variant
  ON public.encuestas (campaign_id, ab_variant)
  WHERE ab_variant IS NOT NULL;

COMMENT ON COLUMN public.campaigns.ab_test_enabled IS 'Si true, reparte leads entre agent_id (A) y agent_id_b (B)';
COMMENT ON COLUMN public.campaigns.ab_split_ratio IS 'Fracción de leads asignados a variante A (0.5 = 50/50)';
