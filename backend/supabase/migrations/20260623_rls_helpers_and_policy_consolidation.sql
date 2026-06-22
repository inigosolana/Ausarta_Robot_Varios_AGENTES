-- =============================================================================
-- RLS helpers + consolidación de políticas tenant
-- Elimina subconsultas repetidas a user_profiles por fila (N+1 en Postgres)
-- y define get_my_role() referenciada por migraciones previas sin crearla.
-- =============================================================================

-- ── Helpers SECURITY DEFINER (evaluados una vez por statement, no por fila) ──

CREATE OR REPLACE FUNCTION public.get_my_role()
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT role FROM public.user_profiles WHERE id = auth.uid() LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.is_tenant_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT COALESCE(public.get_my_role() IN ('admin', 'superadmin'), false);
$$;

CREATE OR REPLACE FUNCTION public.tenant_matches(target_empresa_id bigint)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT target_empresa_id IS NOT NULL
    AND public.get_my_empresa_id() IS NOT NULL
    AND target_empresa_id = public.get_my_empresa_id();
$$;

CREATE OR REPLACE FUNCTION public.tenant_admin_can_manage(target_empresa_id bigint)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT public.has_global_access()
    OR (public.tenant_matches(target_empresa_id) AND public.is_tenant_admin());
$$;

CREATE OR REPLACE FUNCTION public.user_in_my_tenant(target_user_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.user_profiles up
    WHERE up.id = target_user_id
      AND public.tenant_matches(up.empresa_id)
  );
$$;

GRANT EXECUTE ON FUNCTION public.get_my_role() TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_tenant_admin() TO authenticated;
GRANT EXECUTE ON FUNCTION public.tenant_matches(bigint) TO authenticated;
GRANT EXECUTE ON FUNCTION public.tenant_admin_can_manage(bigint) TO authenticated;
GRANT EXECUTE ON FUNCTION public.user_in_my_tenant(uuid) TO authenticated;

-- ── Índices para lookups RLS frecuentes ──

CREATE INDEX IF NOT EXISTS idx_user_profiles_empresa_id ON public.user_profiles(empresa_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_role ON public.user_profiles(role);
CREATE INDEX IF NOT EXISTS idx_campaigns_empresa_status ON public.campaigns(empresa_id, status);
CREATE INDEX IF NOT EXISTS idx_campaign_leads_campaign_id ON public.campaign_leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON public.audit_logs(user_id);

-- ── USER PROFILES ──

DROP POLICY IF EXISTS "up: tenant ve sus usuarios" ON public.user_profiles;
CREATE POLICY "up: tenant ve sus usuarios" ON public.user_profiles
  FOR SELECT TO authenticated
  USING (
    public.has_global_access()
    OR (
      public.get_my_empresa_id() IS NOT NULL
      AND empresa_id = public.get_my_empresa_id()
      AND public.get_my_role() IN ('admin', 'user')
    )
  );

-- ── EMPRESAS (políticas tenant de 20260514; superadmin ya usa has_global_access) ──

DROP POLICY IF EXISTS "Users can view their own company" ON public.empresas;
CREATE POLICY "Users can view their own company" ON public.empresas
  FOR SELECT TO authenticated
  USING (public.has_global_access() OR id = public.get_my_empresa_id());

DROP POLICY IF EXISTS "Admins can update their own company" ON public.empresas;
CREATE POLICY "Admins can update their own company" ON public.empresas
  FOR UPDATE TO authenticated
  USING (public.tenant_admin_can_manage(id))
  WITH CHECK (public.tenant_admin_can_manage(id));

-- ── USER PERMISSIONS ──

DROP POLICY IF EXISTS "perm: admin gestiona permisos empresa" ON public.user_permissions;
CREATE POLICY "perm: admin gestiona permisos empresa" ON public.user_permissions
  FOR ALL TO authenticated
  USING (
    public.has_global_access()
    OR (public.user_in_my_tenant(user_id) AND public.is_tenant_admin())
  )
  WITH CHECK (
    public.has_global_access()
    OR (public.user_in_my_tenant(user_id) AND public.is_tenant_admin())
  );

-- ── AGENT CONFIG ──

DROP POLICY IF EXISTS "agents: tenant solo ve los suyos" ON public.agent_config;
CREATE POLICY "agents: tenant solo ve los suyos" ON public.agent_config
  FOR SELECT TO authenticated
  USING (public.tenant_matches(empresa_id));

DROP POLICY IF EXISTS "agents: admin gestiona su empresa" ON public.agent_config;
CREATE POLICY "agents: admin gestiona su empresa" ON public.agent_config
  FOR ALL TO authenticated
  USING (public.tenant_admin_can_manage(empresa_id))
  WITH CHECK (public.tenant_admin_can_manage(empresa_id));

-- ── AI CONFIG ──

DROP POLICY IF EXISTS "ai_config: tenant solo ve los suyos" ON public.ai_config;
CREATE POLICY "ai_config: tenant solo ve los suyos" ON public.ai_config
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.agent_config ac
      WHERE ac.id = ai_config.agent_id
        AND public.tenant_matches(ac.empresa_id)
    )
  );

DROP POLICY IF EXISTS "ai_config: admin gestiona su empresa" ON public.ai_config;
CREATE POLICY "ai_config: admin gestiona su empresa" ON public.ai_config
  FOR ALL TO authenticated
  USING (
    public.has_global_access()
    OR (
      public.is_tenant_admin()
      AND EXISTS (
        SELECT 1 FROM public.agent_config ac
        WHERE ac.id = ai_config.agent_id
          AND public.tenant_matches(ac.empresa_id)
      )
    )
  );

-- ── CAMPAIGNS ──

DROP POLICY IF EXISTS "campaigns: tenant solo ve los suyos" ON public.campaigns;
CREATE POLICY "campaigns: tenant solo ve los suyos" ON public.campaigns
  FOR SELECT TO authenticated
  USING (public.tenant_matches(empresa_id));

DROP POLICY IF EXISTS "campaigns: admin gestiona su empresa" ON public.campaigns;
CREATE POLICY "campaigns: admin gestiona su empresa" ON public.campaigns
  FOR ALL TO authenticated
  USING (public.tenant_admin_can_manage(empresa_id))
  WITH CHECK (public.tenant_admin_can_manage(empresa_id));

-- ── CAMPAIGN LEADS ──

DROP POLICY IF EXISTS "leads: tenant solo ve los suyos" ON public.campaign_leads;
CREATE POLICY "leads: tenant solo ve los suyos" ON public.campaign_leads
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.campaigns c
      WHERE c.id = campaign_leads.campaign_id
        AND public.tenant_matches(c.empresa_id)
    )
  );

DROP POLICY IF EXISTS "leads: admin gestiona su empresa" ON public.campaign_leads;
CREATE POLICY "leads: admin gestiona su empresa" ON public.campaign_leads
  FOR ALL TO authenticated
  USING (
    public.has_global_access()
    OR (
      public.is_tenant_admin()
      AND EXISTS (
        SELECT 1 FROM public.campaigns c
        WHERE c.id = campaign_leads.campaign_id
          AND public.tenant_matches(c.empresa_id)
      )
    )
  );

-- ── ENCUESTAS ──

DROP POLICY IF EXISTS "encuestas: tenant solo ve los suyos" ON public.encuestas;
CREATE POLICY "encuestas: tenant solo ve los suyos" ON public.encuestas
  FOR SELECT TO authenticated
  USING (public.tenant_matches(empresa_id));

DROP POLICY IF EXISTS "encuestas: admin gestiona su empresa" ON public.encuestas;
CREATE POLICY "encuestas: admin gestiona su empresa" ON public.encuestas
  FOR ALL TO authenticated
  USING (public.tenant_admin_can_manage(empresa_id))
  WITH CHECK (public.tenant_admin_can_manage(empresa_id));

-- ── AUDIT LOGS ──

DROP POLICY IF EXISTS "audit: admin ve logs de empresa" ON public.audit_logs;
CREATE POLICY "audit: admin ve logs de empresa" ON public.audit_logs
  FOR SELECT TO authenticated
  USING (
    public.has_global_access()
    OR (public.is_tenant_admin() AND public.user_in_my_tenant(user_id))
  );

-- ── COMPANY YEASTAR CONFIGS ──

DROP POLICY IF EXISTS "yeastar: admin gestiona su config" ON public.company_yeastar_configs;
CREATE POLICY "yeastar: admin gestiona su config" ON public.company_yeastar_configs
  FOR ALL TO authenticated
  USING (public.tenant_admin_can_manage(empresa_id))
  WITH CHECK (public.tenant_admin_can_manage(empresa_id));

-- ── API KEYS ──

DROP POLICY IF EXISTS "api_keys: superadmin acceso total" ON public.api_keys;
CREATE POLICY "api_keys: superadmin acceso total" ON public.api_keys
  FOR ALL TO authenticated
  USING (public.has_global_access());

DROP POLICY IF EXISTS "api_keys: admin ve y gestiona su empresa" ON public.api_keys;
CREATE POLICY "api_keys: admin ve y gestiona su empresa" ON public.api_keys
  FOR ALL TO authenticated
  USING (public.tenant_admin_can_manage(empresa_id))
  WITH CHECK (public.tenant_admin_can_manage(empresa_id));

-- ── KNOWLEDGE BASE ──

DROP POLICY IF EXISTS kb_superadmin ON public.knowledge_base;
CREATE POLICY kb_superadmin ON public.knowledge_base
  FOR ALL TO authenticated
  USING (public.has_global_access());

DROP POLICY IF EXISTS kb_tenant ON public.knowledge_base;
CREATE POLICY kb_tenant ON public.knowledge_base
  FOR ALL TO authenticated
  USING (public.tenant_matches(empresa_id));

-- ── EXTERNAL DB ──

DROP POLICY IF EXISTS ext_db_superadmin ON public.empresa_external_db;
CREATE POLICY ext_db_superadmin ON public.empresa_external_db
  FOR ALL TO authenticated
  USING (public.has_global_access());

DROP POLICY IF EXISTS ext_db_tenant ON public.empresa_external_db;
CREATE POLICY ext_db_tenant ON public.empresa_external_db
  FOR ALL TO authenticated
  USING (public.tenant_matches(empresa_id));

-- ── CONTACTOS ──

DROP POLICY IF EXISTS "contactos: tenant solo ve los suyos" ON public.contactos;
CREATE POLICY "contactos: tenant solo ve los suyos" ON public.contactos
  FOR ALL TO authenticated
  USING (public.tenant_matches(empresa_id));

-- ── EMPRESA LIMITS ──

DROP POLICY IF EXISTS "superadmin_full_access" ON public.empresa_limits;
CREATE POLICY "superadmin_full_access" ON public.empresa_limits
  FOR ALL TO authenticated
  USING (public.has_global_access())
  WITH CHECK (public.has_global_access());
