-- =============================================================================
-- RAG híbrido: full-text search (BM25 proxy) sobre knowledge_base
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE public.knowledge_base
  ADD COLUMN IF NOT EXISTS search_vector tsvector
  GENERATED ALWAYS AS (
    to_tsvector(
      'spanish',
      coalesce(titulo, '') || ' ' || coalesce(contenido, '')
    )
  ) STORED;

CREATE INDEX IF NOT EXISTS idx_kb_search_vector
  ON public.knowledge_base USING GIN (search_vector);

CREATE OR REPLACE FUNCTION public.search_knowledge_base_keyword(
  p_empresa_id BIGINT,
  p_query      TEXT,
  p_limit      INT DEFAULT 10,
  p_agent_id   BIGINT DEFAULT NULL
)
RETURNS TABLE(id BIGINT, titulo TEXT, contenido TEXT, keyword_score FLOAT)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_query tsquery;
BEGIN
  IF p_empresa_id IS NULL OR p_empresa_id <= 0 THEN
    RETURN;
  END IF;

  IF p_query IS NULL OR length(trim(p_query)) < 2 THEN
    RETURN;
  END IF;

  v_query := plainto_tsquery('spanish', trim(p_query));
  IF v_query IS NULL THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT
    kb.id,
    kb.titulo,
    kb.contenido,
    ts_rank_cd(kb.search_vector, v_query)::FLOAT AS keyword_score
  FROM public.knowledge_base kb
  WHERE
    kb.empresa_id = p_empresa_id
    AND kb.search_vector @@ v_query
    AND (
      (p_agent_id IS NULL AND kb.agent_id IS NULL)
      OR (p_agent_id IS NOT NULL AND (kb.agent_id IS NULL OR kb.agent_id = p_agent_id))
    )
  ORDER BY keyword_score DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 30);
END;
$$;

GRANT EXECUTE ON FUNCTION public.search_knowledge_base_keyword(BIGINT, TEXT, INT, BIGINT)
  TO authenticated, service_role;
