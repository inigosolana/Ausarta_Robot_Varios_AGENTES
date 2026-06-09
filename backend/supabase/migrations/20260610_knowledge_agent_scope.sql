-- Conocimiento por empresa (agent_id NULL) vs por agente (agent_id set)
ALTER TABLE knowledge_base
  ADD COLUMN IF NOT EXISTS agent_id BIGINT REFERENCES agent_config(id) ON DELETE CASCADE;

ALTER TABLE empresas
  ADD COLUMN IF NOT EXISTS company_context TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_kb_agent ON knowledge_base(agent_id)
  WHERE agent_id IS NOT NULL;

DROP FUNCTION IF EXISTS search_knowledge_base(BIGINT, VECTOR, INT, FLOAT);

CREATE OR REPLACE FUNCTION search_knowledge_base(
  p_empresa_id BIGINT,
  p_embedding  VECTOR(1536),
  p_limit      INT DEFAULT 5,
  p_threshold  FLOAT DEFAULT 0.75,
  p_agent_id   BIGINT DEFAULT NULL
)
RETURNS TABLE(id BIGINT, titulo TEXT, contenido TEXT, similarity FLOAT)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
  IF p_empresa_id IS NULL OR p_empresa_id <= 0 OR p_embedding IS NULL THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT
    kb.id,
    kb.titulo,
    kb.contenido,
    (1 - (kb.embedding <=> p_embedding))::FLOAT AS similarity
  FROM knowledge_base kb
  WHERE
    kb.empresa_id = p_empresa_id
    AND kb.embedding IS NOT NULL
    AND (1 - (kb.embedding <=> p_embedding)) >= LEAST(GREATEST(p_threshold, 0.0), 1.0)
    AND (
      (p_agent_id IS NULL AND kb.agent_id IS NULL)
      OR (p_agent_id IS NOT NULL AND (kb.agent_id IS NULL OR kb.agent_id = p_agent_id))
    )
  ORDER BY kb.embedding <=> p_embedding
  LIMIT LEAST(GREATEST(p_limit, 1), 20);
END;
$$;

GRANT EXECUTE ON FUNCTION search_knowledge_base(BIGINT, VECTOR, INT, FLOAT, BIGINT) TO authenticated;
GRANT EXECUTE ON FUNCTION search_knowledge_base(BIGINT, VECTOR, INT, FLOAT, BIGINT) TO service_role;
