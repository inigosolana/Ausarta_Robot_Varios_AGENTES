-- =============================================================================
-- RAG híbrido: full-text search (BM25 proxy) sobre knowledge_base
-- FTS en la RPC (sin índice GIN) para evitar picos de maintenance_work_mem
-- en tablas grandes. Para >50k chunks, añadir search_vector + GIN en ventana
-- de mantenimiento.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

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
    ts_rank_cd(
      to_tsvector('spanish', coalesce(kb.titulo, '') || ' ' || coalesce(kb.contenido, '')),
      v_query
    )::FLOAT AS keyword_score
  FROM public.knowledge_base kb
  WHERE
    kb.empresa_id = p_empresa_id
    AND to_tsvector('spanish', coalesce(kb.titulo, '') || ' ' || coalesce(kb.contenido, '')) @@ v_query
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
