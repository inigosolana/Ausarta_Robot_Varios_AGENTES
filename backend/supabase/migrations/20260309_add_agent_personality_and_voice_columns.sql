-- Campos avanzados de personalidad/voz para agentes
ALTER TABLE agent_config
ADD COLUMN IF NOT EXISTS company_context TEXT DEFAULT '';

ALTER TABLE agent_config
ADD COLUMN IF NOT EXISTS enthusiasm_level VARCHAR(20) DEFAULT 'Normal';

ALTER TABLE agent_config
ADD COLUMN IF NOT EXISTS voice_id TEXT;

ALTER TABLE agent_config
ADD COLUMN IF NOT EXISTS speaking_speed NUMERIC(4,2) DEFAULT 1.00;
