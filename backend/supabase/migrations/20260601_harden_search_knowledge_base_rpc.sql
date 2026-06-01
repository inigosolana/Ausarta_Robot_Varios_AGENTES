-- =============================================================================
-- Hardening Fase 2 KB: permisos y validaciones de RPC search_knowledge_base
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- Asegurar estructura mínima esperada
ALTER TABLE IF EXISTS knowledge_base
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_kb_empresa ON knowledge_base(empresa_id);
CREATE INDEX IF NOT EXISTS idx_kb_embedding ON knowledge_base
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- Recrear función con validaciones básicas de parámetros
CREATE OR REPLACE FUNCTION search_knowledge_base(
  p_empresa_id BIGINT,
  p_embedding  VECTOR(1536),
  p_limit      INT DEFAULT 5,
  p_threshold  FLOAT DEFAULT 0.75
)
RETURNS TABLE(id BIGINT, titulo TEXT, contenido TEXT, similarity FLOAT)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
  IF p_empresa_id IS NULL OR p_empresa_id <= 0 THEN
    RETURN;
  END IF;

  IF p_embedding IS NULL THEN
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
  ORDER BY kb.embedding <=> p_embedding
  LIMIT LEAST(GREATEST(p_limit, 1), 20);
END;
$$;

GRANT EXECUTE ON FUNCTION search_knowledge_base(BIGINT, VECTOR, INT, FLOAT) TO authenticated;
GRANT EXECUTE ON FUNCTION search_knowledge_base(BIGINT, VECTOR, INT, FLOAT) TO service_role;
