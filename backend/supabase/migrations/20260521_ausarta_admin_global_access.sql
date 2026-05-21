-- Admin de empresa Ausarta = mismo acceso de datos que superadmin.
-- Superadmin conserva exclusividad en gestión de admins de Ausarta (vía API).

CREATE OR REPLACE FUNCTION public.has_global_access()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.user_profiles up
    WHERE up.id = auth.uid()
      AND (
        up.role = 'superadmin'
        OR (
          up.role = 'admin'
          AND up.empresa_id = (
            SELECT e.id FROM public.empresas e WHERE lower(trim(e.nombre)) = 'ausarta' LIMIT 1
          )
        )
      )
  );
$$;

-- Solo superadmin puede crear/gestionar admins de la empresa Ausarta (user_profiles)
CREATE OR REPLACE FUNCTION public.can_create_ausarta_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.user_profiles up
    WHERE up.id = auth.uid() AND up.role = 'superadmin'
  );
$$;

-- ── EMPRESAS ──
DROP POLICY IF EXISTS "Superadmins have full access" ON public.empresas;
CREATE POLICY "Superadmins have full access" ON public.empresas
  FOR ALL TO authenticated
  USING (public.has_global_access())
  WITH CHECK (public.has_global_access());

-- ── USER PROFILES ──
DROP POLICY IF EXISTS "up: superadmin acceso total" ON public.user_profiles;
CREATE POLICY "up: superadmin acceso total" ON public.user_profiles
  FOR ALL TO authenticated
  USING (public.has_global_access())
  WITH CHECK (
    public.has_global_access()
    AND (
      public.can_create_ausarta_admin()
      OR empresa_id IS DISTINCT FROM (SELECT e.id FROM public.empresas e WHERE lower(trim(e.nombre)) = 'ausarta' LIMIT 1)
      OR role IS DISTINCT FROM 'admin'
    )
  );

-- ── USER PERMISSIONS ──
DROP POLICY IF EXISTS "perm: superadmin acceso total" ON public.user_permissions;
CREATE POLICY "perm: superadmin acceso total" ON public.user_permissions
  FOR ALL TO authenticated
  USING (public.has_global_access());

-- ── AGENT CONFIG ──
DROP POLICY IF EXISTS "agents: superadmin acceso total" ON public.agent_config;
CREATE POLICY "agents: superadmin acceso total" ON public.agent_config
  FOR ALL TO authenticated
  USING (public.has_global_access());

-- ── AI CONFIG ──
DROP POLICY IF EXISTS "ai_config: superadmin acceso total" ON public.ai_config;
CREATE POLICY "ai_config: superadmin acceso total" ON public.ai_config
  FOR ALL TO authenticated
  USING (public.has_global_access());

-- ── CAMPAIGNS ──
DROP POLICY IF EXISTS "campaigns: superadmin acceso total" ON public.campaigns;
CREATE POLICY "campaigns: superadmin acceso total" ON public.campaigns
  FOR ALL TO authenticated
  USING (public.has_global_access());

-- ── CAMPAIGN LEADS ──
DROP POLICY IF EXISTS "leads: superadmin acceso total" ON public.campaign_leads;
CREATE POLICY "leads: superadmin acceso total" ON public.campaign_leads
  FOR ALL TO authenticated
  USING (public.has_global_access());

-- ── ENCUESTAS ──
DROP POLICY IF EXISTS "encuestas: superadmin acceso total" ON public.encuestas;
CREATE POLICY "encuestas: superadmin acceso total" ON public.encuestas
  FOR ALL TO authenticated
  USING (public.has_global_access());

-- ── AUDIT LOGS ──
DROP POLICY IF EXISTS "audit: superadmin acceso total" ON public.audit_logs;
CREATE POLICY "audit: superadmin acceso total" ON public.audit_logs
  FOR SELECT TO authenticated
  USING (public.has_global_access());

-- ── PROMPT TEMPLATES / CACHE ──
DROP POLICY IF EXISTS "prompts: admins gestionan" ON public.prompt_templates;
CREATE POLICY "prompts: admins gestionan" ON public.prompt_templates
  FOR ALL TO authenticated
  USING (public.has_global_access());

DROP POLICY IF EXISTS "yeastar: superadmin acceso total" ON public.company_yeastar_configs;
CREATE POLICY "yeastar: superadmin acceso total" ON public.company_yeastar_configs
  FOR ALL TO authenticated
  USING (public.has_global_access());

DROP POLICY IF EXISTS "cache: superadmin gestion total" ON public.api_usage_cache;
CREATE POLICY "cache: superadmin gestion total" ON public.api_usage_cache
  FOR ALL TO authenticated
  USING (public.has_global_access());

DROP POLICY IF EXISTS "ui_cache: superadmin gestion total" ON public.ui_cache;
CREATE POLICY "ui_cache: superadmin gestion total" ON public.ui_cache
  FOR ALL TO authenticated
  USING (public.has_global_access());
