-- =============================================================================
-- Fase 2 — Base de Conocimiento (RAG) con pgvector
-- Permite al agente IA consultar documentación interna de la empresa
-- usando búsqueda semántica por embeddings.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_base (
  id            BIGSERIAL PRIMARY KEY,
  empresa_id    BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  titulo        TEXT NOT NULL,
  contenido     TEXT NOT NULL,
  chunk_index   INT NOT NULL DEFAULT 0,
  embedding     VECTOR(1536),
  source_type   TEXT DEFAULT 'manual',
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_empresa    ON knowledge_base(empresa_id);
CREATE INDEX IF NOT EXISTS idx_kb_embedding  ON knowledge_base
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS kb_superadmin ON knowledge_base
  FOR ALL
  USING (EXISTS (
    SELECT 1 FROM user_profiles
    WHERE id = auth.uid() AND role IN ('superadmin', 'admin')
  ));

CREATE POLICY IF NOT EXISTS kb_tenant ON knowledge_base
  FOR ALL
  USING (
    empresa_id = (
      SELECT empresa_id FROM user_profiles WHERE id = auth.uid() LIMIT 1
    )
  );

-- Función de búsqueda semántica (cosine similarity)
CREATE OR REPLACE FUNCTION search_knowledge_base(
  p_empresa_id BIGINT,
  p_embedding  VECTOR(1536),
  p_limit      INT DEFAULT 5,
  p_threshold  FLOAT DEFAULT 0.75
)
RETURNS TABLE(id BIGINT, titulo TEXT, contenido TEXT, similarity FLOAT)
LANGUAGE sql STABLE AS $$
  SELECT
    id,
    titulo,
    contenido,
    (1 - (embedding <=> p_embedding))::FLOAT AS similarity
  FROM knowledge_base
  WHERE
    empresa_id = p_empresa_id
    AND embedding IS NOT NULL
    AND (1 - (embedding <=> p_embedding)) >= p_threshold
  ORDER BY embedding <=> p_embedding
  LIMIT p_limit;
$$;
