-- ──────────────────────────────────────────────────────────────────────────────
-- Migración: health-check Yeastar por empresa + pausa automática de campañas
-- ──────────────────────────────────────────────────────────────────────────────

-- Estado de salud del PBX Yeastar por empresa
ALTER TABLE company_yeastar_configs
    ADD COLUMN IF NOT EXISTS health_status TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS last_health_check_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;

ALTER TABLE company_yeastar_configs
    DROP CONSTRAINT IF EXISTS company_yeastar_configs_health_status_check;

ALTER TABLE company_yeastar_configs
    ADD CONSTRAINT company_yeastar_configs_health_status_check
    CHECK (health_status IN ('ok', 'down', 'unknown'));

COMMENT ON COLUMN company_yeastar_configs.health_status IS
    'Estado del último health-check: ok, down, unknown';

-- Campos de pausa automática por health-check en campañas
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS paused_reason TEXT,
    ADD COLUMN IF NOT EXISTS paused_by_health_check BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS status_before_health_pause TEXT,
    ADD COLUMN IF NOT EXISTS health_paused_at TIMESTAMPTZ;

COMMENT ON COLUMN campaigns.paused_by_health_check IS
    'true si la campaña fue pausada automáticamente por el health-check de Yeastar';
COMMENT ON COLUMN campaigns.status_before_health_pause IS
    'Estado previo (active/running) antes de la pausa por health-check, para reanudar';
COMMENT ON COLUMN campaigns.health_paused_at IS
    'Timestamp de la pausa automática; si updated_at es posterior, no auto-reanudar';
