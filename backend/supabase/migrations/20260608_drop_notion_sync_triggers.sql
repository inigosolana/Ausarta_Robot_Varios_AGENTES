-- Elimina sync operativo Supabase → Notion (ya no se usa).
-- Notion queda solo para documentación de código e ideas.

DROP TRIGGER IF EXISTS notion_sync_empresas ON public.empresas;
DROP TRIGGER IF EXISTS notion_sync_user_profiles ON public.user_profiles;
DROP TRIGGER IF EXISTS notion_sync_agent_config ON public.agent_config;
DROP TRIGGER IF EXISTS notion_sync_encuestas ON public.encuestas;

DROP FUNCTION IF EXISTS public.notion_sync_webhook_notify();
