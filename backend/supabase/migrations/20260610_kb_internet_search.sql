-- Control de búsqueda en internet vs solo base de conocimiento
ALTER TABLE empresas
  ADD COLUMN IF NOT EXISTS kb_allow_internet_search BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE agent_config
  ADD COLUMN IF NOT EXISTS kb_allow_internet_search BOOLEAN DEFAULT NULL;

COMMENT ON COLUMN empresas.kb_allow_internet_search IS
  'Si true, los agentes pueden usar buscar_internet además de la base de conocimiento.';
COMMENT ON COLUMN agent_config.kb_allow_internet_search IS
  'Override por agente: NULL = heredar empresa, true/false = forzar comportamiento.';
