-- Registro normalizado de troncales salientes SIP por empresa.
-- Mantiene empresas.sip_outbound_trunk_id como campo rapido de compatibilidad.

CREATE TABLE IF NOT EXISTS public.empresa_sip_outbound_trunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  empresa_id integer NOT NULL REFERENCES public.empresas(id) ON DELETE CASCADE,
  provider text NOT NULL DEFAULT 'CITELIA_SBC',
  livekit_trunk_id text NOT NULL,
  ddi text NOT NULL,
  host text NOT NULL DEFAULT '212.63.112.35:38932',
  transport text NOT NULL DEFAULT 'UDP',
  domain text NOT NULL DEFAULT '212.63.112.35',
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (empresa_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_empresa_sip_outbound_trunks_empresa_id
  ON public.empresa_sip_outbound_trunks (empresa_id);

CREATE INDEX IF NOT EXISTS idx_empresa_sip_outbound_trunks_livekit_trunk_id
  ON public.empresa_sip_outbound_trunks (livekit_trunk_id);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS set_empresa_sip_outbound_trunks_updated_at
  ON public.empresa_sip_outbound_trunks;

CREATE TRIGGER set_empresa_sip_outbound_trunks_updated_at
BEFORE UPDATE ON public.empresa_sip_outbound_trunks
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.empresa_sip_outbound_trunks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "empresa_sip_outbound_trunks: select allowed" ON public.empresa_sip_outbound_trunks;
DROP POLICY IF EXISTS "empresa_sip_outbound_trunks: global insert" ON public.empresa_sip_outbound_trunks;
DROP POLICY IF EXISTS "empresa_sip_outbound_trunks: global update" ON public.empresa_sip_outbound_trunks;
DROP POLICY IF EXISTS "empresa_sip_outbound_trunks: global delete" ON public.empresa_sip_outbound_trunks;

CREATE POLICY "empresa_sip_outbound_trunks: select allowed"
ON public.empresa_sip_outbound_trunks
FOR SELECT
TO authenticated
USING (public.has_global_access() OR empresa_id = public.get_my_empresa_id());

CREATE POLICY "empresa_sip_outbound_trunks: global insert"
ON public.empresa_sip_outbound_trunks
FOR INSERT
TO authenticated
WITH CHECK (public.has_global_access());

CREATE POLICY "empresa_sip_outbound_trunks: global update"
ON public.empresa_sip_outbound_trunks
FOR UPDATE
TO authenticated
USING (public.has_global_access())
WITH CHECK (public.has_global_access());

CREATE POLICY "empresa_sip_outbound_trunks: global delete"
ON public.empresa_sip_outbound_trunks
FOR DELETE
TO authenticated
USING (public.has_global_access());
