-- Añadir columna agent_type a agent_config
ALTER TABLE agent_config 
ADD COLUMN IF NOT EXISTS agent_type VARCHAR(50) DEFAULT 'ENCUESTA_NUMERICA';

-- Añadir columna datos_extra a encuestas (tipo JSON)
ALTER TABLE encuestas 
ADD COLUMN IF NOT EXISTS datos_extra JSONB DEFAULT '{}'::jsonb;
