-- Esquema flexible de resultados por tipo de agente (encuestas = tabla de llamadas)
ALTER TABLE public.encuestas
  ADD COLUMN IF NOT EXISTS agent_type VARCHAR(50),
  ADD COLUMN IF NOT EXISTS agent_results JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_encuestas_agent_type
  ON public.encuestas (empresa_id, agent_type)
  WHERE agent_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_encuestas_agent_results_gin
  ON public.encuestas USING gin (agent_results);

-- Vista canónica para integraciones (calls + call_data)
CREATE OR REPLACE VIEW public.calls AS
SELECT
  e.id,
  e.telefono AS phone,
  e.nombre_cliente AS customer_name,
  e.fecha AS started_at,
  e.status,
  e.completada AS completed,
  e.empresa_id,
  e.agent_id,
  COALESCE(e.agent_type, ac.agent_type, ac.tipo_resultados) AS agent_type,
  e.campaign_id,
  e.campaign_name,
  e.seconds_used,
  e.transcription,
  e.resumen_llamada AS summary,
  e.agent_results AS call_data,
  e.datos_extra,
  e.puntuacion_comercial,
  e.puntuacion_instalador,
  e.puntuacion_rapidez,
  e.comentarios
FROM public.encuestas e
LEFT JOIN public.agent_config ac ON ac.id = e.agent_id;

COMMENT ON VIEW public.calls IS 'Vista de llamadas con call_data JSON flexible (agent_results)';
COMMENT ON COLUMN public.encuestas.agent_results IS 'Resultados estructurados por tipo de agente (scores, extracted, notes)';

-- Backfill: encuestas numéricas legacy → agent_results
UPDATE public.encuestas e
SET
  agent_type = COALESCE(e.agent_type, ac.agent_type, ac.tipo_resultados, 'ENCUESTA_NUMERICA'),
  agent_results = CASE
    WHEN e.agent_results IS NULL OR e.agent_results = '{}'::jsonb THEN
      jsonb_strip_nulls(jsonb_build_object(
        'schema_version', 1,
        'scores', jsonb_strip_nulls(jsonb_build_object(
          'comercial', e.puntuacion_comercial,
          'instalador', e.puntuacion_instalador,
          'rapidez', e.puntuacion_rapidez
        )),
        'notes', jsonb_strip_nulls(jsonb_build_object(
          'comentarios', e.comentarios
        )),
        'extracted', COALESCE(
          CASE WHEN jsonb_typeof(e.datos_extra) = 'object' THEN e.datos_extra ELSE '{}'::jsonb END,
          '{}'::jsonb
        )
      ))
    ELSE e.agent_results
  END
FROM public.agent_config ac
WHERE ac.id = e.agent_id
  AND (
    e.agent_type IS NULL
    OR e.agent_results IS NULL
    OR e.agent_results = '{}'::jsonb
  );
