-- ============================================================
-- MIGRACIÓN: Sistema de modos de agente (prompt / workflow / mixed)
-- Añade tres columnas a agent_config para soportar workflows
-- visuales sin romper el modo "prompt" existente.
-- ============================================================

-- 1. Columna de modo (prompt es el default para retrocompatibilidad)
ALTER TABLE public.agent_config
  ADD COLUMN IF NOT EXISTS agent_mode TEXT NOT NULL DEFAULT 'prompt'
    CONSTRAINT agent_config_mode_check CHECK (agent_mode IN ('prompt', 'workflow', 'mixed'));

-- 2. Definición del workflow (grafo de nodos/aristas en JSONB)
--    Estructura esperada:
--    {
--      "nodes": [{ "id", "type", "label", "content", "prompt",
--                  "variable", "options", "position" }],
--      "edges": [{ "id", "source", "target", "condition" }],
--      "start_node": "<node_id>"
--    }
ALTER TABLE public.agent_config
  ADD COLUMN IF NOT EXISTS workflow_definition JSONB DEFAULT NULL;

-- 3. Variables capturadas durante la llamada
--    { "nombre": null, "nota": null, ... }
ALTER TABLE public.agent_config
  ADD COLUMN IF NOT EXISTS workflow_variables JSONB DEFAULT '{}';

-- ============================================================
-- Índice funcional para filtrar agentes con workflow activo
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_agent_config_mode
  ON public.agent_config (agent_mode)
  WHERE agent_mode IN ('workflow', 'mixed');

-- ============================================================
-- Las políticas RLS existentes en agent_config ya cubren estas
-- columnas automáticamente (la política opera a nivel de fila,
-- no de columna), por lo que no se requieren políticas nuevas.
-- Se añade un comentario en tabla para documentación.
-- ============================================================
COMMENT ON COLUMN public.agent_config.agent_mode IS
  'Modo de operación del agente: prompt (texto libre), workflow (guion estructurado), mixed (guion con nodos libres).';

COMMENT ON COLUMN public.agent_config.workflow_definition IS
  'Definición JSON del grafo de workflow. Solo activo cuando agent_mode != ''prompt''.';

COMMENT ON COLUMN public.agent_config.workflow_variables IS
  'Variables semilla del workflow. Se inicializan a null al arrancar la llamada y se rellenan durante la conversación.';
