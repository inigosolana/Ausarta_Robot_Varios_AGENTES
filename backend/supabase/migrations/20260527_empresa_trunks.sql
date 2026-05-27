-- Troncales SIP configurables por empresa (multi-tenant)
-- Permite definir trunk de salida/entrada desde panel admin sin tocar .env

ALTER TABLE public.empresas
ADD COLUMN IF NOT EXISTS sip_outbound_trunk_id TEXT;

ALTER TABLE public.empresas
ADD COLUMN IF NOT EXISTS sip_inbound_trunk_id TEXT;
