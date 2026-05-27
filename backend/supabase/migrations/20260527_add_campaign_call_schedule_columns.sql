-- FIX G — Control horario RGPD por campaña.
-- Problema: no había restricciones horarias por tenant/campaña, permitiendo
-- llamadas fuera de franja legal.
-- Solución: columnas parametrizables para horario, timezone y días prohibidos.

ALTER TABLE public.campaigns
ADD COLUMN IF NOT EXISTS call_start_hour INT DEFAULT 9,
ADD COLUMN IF NOT EXISTS call_end_hour INT DEFAULT 21,
ADD COLUMN IF NOT EXISTS call_timezone TEXT DEFAULT 'Europe/Madrid',
ADD COLUMN IF NOT EXISTS forbidden_weekdays INT[] DEFAULT '{0}';

COMMENT ON COLUMN public.campaigns.call_start_hour IS
'Hora local de inicio permitida para llamadas (0-23).';
COMMENT ON COLUMN public.campaigns.call_end_hour IS
'Hora local de fin permitida para llamadas (1-24, exclusivo).';
COMMENT ON COLUMN public.campaigns.call_timezone IS
'Timezone IANA usada para validar franja horaria (ej. Europe/Madrid).';
COMMENT ON COLUMN public.campaigns.forbidden_weekdays IS
'Días de semana prohibidos (0=lunes..6=domingo).';

-- FIX A — Distinguir campañas gestionadas por el orquestador nativo vs el scheduler drip.
ALTER TABLE public.campaigns
ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'drip',
ADD COLUMN IF NOT EXISTS use_orchestrator BOOLEAN DEFAULT false;

COMMENT ON COLUMN public.campaigns.type IS
'Tipo de campaña: drip (scheduler legacy) | orchestrated (campaign_orchestrator ARQ).';
COMMENT ON COLUMN public.campaigns.use_orchestrator IS
'Si true, el scheduler ARQ la omite y la gestiona campaign_orchestrator.';
