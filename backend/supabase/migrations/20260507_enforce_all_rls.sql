-- =============================================================
-- 20260507_enforce_all_rls.sql
-- Auditoría de Row Level Security: activar RLS y políticas
-- multi-tenant estrictas en todas las tablas de negocio.
--
-- Tablas cubiertas:
--   - empresas
--   - user_profiles
--   - user_permissions
--   - agent_config
--   - ai_config
--   - campaigns
--   - campaign_leads
--   - encuestas
--   - audit_logs
--   - prompt_templates
--   - company_yeastar_configs
--   - api_usage_cache
--   - ui_cache
--
-- PATRÓN GENERAL de aislamiento multi-tenant:
--   SELECT/UPDATE: solo filas donde empresa_id = empresa_id del usuario
--   INSERT/DELETE: solo dentro del propio tenant
--   Superadmin: acceso total (bypass de las restricciones de tenant)
-- =============================================================

-- 1. EMPRESAS
ALTER TABLE public.empresas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Superadmins have full access" ON public.empresas;
DROP POLICY IF EXISTS "Users can view their own company" ON public.empresas;
DROP POLICY IF EXISTS "Admins can update their own company" ON public.empresas;

CREATE POLICY "Superadmins have full access" ON public.empresas FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));

CREATE POLICY "Users can view their own company" ON public.empresas FOR SELECT TO authenticated
USING (id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1));

CREATE POLICY "Admins can update their own company" ON public.empresas FOR UPDATE TO authenticated
USING (id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'superadmin')))
WITH CHECK (id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role IN ('admin', 'superadmin')));

-- 2. USER PROFILES
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "up: superadmin acceso total" ON public.user_profiles;
DROP POLICY IF EXISTS "up: tenant ve sus usuarios" ON public.user_profiles;
DROP POLICY IF EXISTS "up: usuario ve su propio perfil" ON public.user_profiles;
DROP POLICY IF EXISTS "up: usuario actualiza su perfil" ON public.user_profiles;

CREATE POLICY "up: superadmin acceso total" ON public.user_profiles FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.id = auth.uid() AND up.role = 'superadmin'));

CREATE POLICY "up: tenant ve sus usuarios" ON public.user_profiles FOR SELECT TO authenticated
USING (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1));

CREATE POLICY "up: usuario ve su propio perfil" ON public.user_profiles FOR SELECT TO authenticated USING (id = auth.uid());
CREATE POLICY "up: usuario actualiza su perfil" ON public.user_profiles FOR UPDATE TO authenticated USING (id = auth.uid()) WITH CHECK (id = auth.uid());

-- 3. USER PERMISSIONS
ALTER TABLE public.user_permissions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "perm: superadmin acceso total" ON public.user_permissions;
DROP POLICY IF EXISTS "perm: usuario ve sus permisos" ON public.user_permissions;
DROP POLICY IF EXISTS "perm: admin gestiona permisos empresa" ON public.user_permissions;

CREATE POLICY "perm: superadmin acceso total" ON public.user_permissions FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));

CREATE POLICY "perm: usuario ve sus permisos" ON public.user_permissions FOR SELECT TO authenticated USING (user_id = auth.uid());

CREATE POLICY "perm: admin gestiona permisos empresa" ON public.user_permissions FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.id = user_permissions.user_id AND up.empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1)) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'))
WITH CHECK (EXISTS (SELECT 1 FROM public.user_profiles up WHERE up.id = user_permissions.user_id AND up.empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1)) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'));

-- 4. AGENT CONFIG
ALTER TABLE public.agent_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "agents: superadmin acceso total" ON public.agent_config;
DROP POLICY IF EXISTS "agents: tenant solo ve los suyos" ON public.agent_config;
DROP POLICY IF EXISTS "agents: admin gestiona los suyos" ON public.agent_config;

CREATE POLICY "agents: superadmin acceso total" ON public.agent_config FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));

CREATE POLICY "agents: tenant solo ve los suyos" ON public.agent_config FOR SELECT TO authenticated
USING (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1));

CREATE POLICY "agents: admin gestiona los suyos" ON public.agent_config FOR ALL TO authenticated
USING (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'))
WITH CHECK (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'));

-- 5. AI CONFIG (linked to agent_config)
ALTER TABLE public.ai_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "ai_config: superadmin acceso total" ON public.ai_config;
DROP POLICY IF EXISTS "ai_config: tenant solo ve los suyos" ON public.ai_config;
DROP POLICY IF EXISTS "ai_config: admin gestiona los suyos" ON public.ai_config;

CREATE POLICY "ai_config: superadmin acceso total" ON public.ai_config FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));

CREATE POLICY "ai_config: tenant solo ve los suyos" ON public.ai_config FOR SELECT TO authenticated
USING (EXISTS (SELECT 1 FROM public.agent_config WHERE agent_config.id = ai_config.agent_id AND agent_config.empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1)));

CREATE POLICY "ai_config: admin gestiona los suyos" ON public.ai_config FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.agent_config WHERE agent_config.id = ai_config.agent_id AND agent_config.empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1)) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'));

-- 6. CAMPAIGNS
ALTER TABLE public.campaigns ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "campaigns: superadmin acceso total" ON public.campaigns;
DROP POLICY IF EXISTS "campaigns: tenant solo ve los suyos" ON public.campaigns;
DROP POLICY IF EXISTS "campaigns: admin gestiona los suyos" ON public.campaigns;

CREATE POLICY "campaigns: superadmin acceso total" ON public.campaigns FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));

CREATE POLICY "campaigns: tenant solo ve los suyos" ON public.campaigns FOR SELECT TO authenticated
USING (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1));

CREATE POLICY "campaigns: admin gestiona los suyos" ON public.campaigns FOR ALL TO authenticated
USING (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'))
WITH CHECK (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'));

-- 7. CAMPAIGN LEADS (linked to campaigns)
ALTER TABLE public.campaign_leads ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "leads: superadmin acceso total" ON public.campaign_leads;
DROP POLICY IF EXISTS "leads: tenant solo ve los suyos" ON public.campaign_leads;
DROP POLICY IF EXISTS "leads: admin gestiona los suyos" ON public.campaign_leads;

CREATE POLICY "leads: superadmin acceso total" ON public.campaign_leads FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));

CREATE POLICY "leads: tenant solo ve los suyos" ON public.campaign_leads FOR SELECT TO authenticated
USING (EXISTS (SELECT 1 FROM public.campaigns WHERE campaigns.id = campaign_leads.campaign_id AND campaigns.empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1)));

CREATE POLICY "leads: admin gestiona los suyos" ON public.campaign_leads FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.campaigns WHERE campaigns.id = campaign_leads.campaign_id AND campaigns.empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1)) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'));

-- 8. ENCUESTAS
ALTER TABLE public.encuestas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "encuestas: superadmin acceso total" ON public.encuestas;
DROP POLICY IF EXISTS "encuestas: tenant solo ve los suyos" ON public.encuestas;
DROP POLICY IF EXISTS "encuestas: admin gestiona los suyos" ON public.encuestas;

CREATE POLICY "encuestas: superadmin acceso total" ON public.encuestas FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));

CREATE POLICY "encuestas: tenant solo ve los suyos" ON public.encuestas FOR SELECT TO authenticated
USING (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1));

CREATE POLICY "encuestas: admin gestiona los suyos" ON public.encuestas FOR ALL TO authenticated
USING (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'))
WITH CHECK (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'));

-- 9. AUDIT LOGS
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "audit: superadmin acceso total" ON public.audit_logs;
DROP POLICY IF EXISTS "audit: admin ve logs de empresa" ON public.audit_logs;

CREATE POLICY "audit: superadmin acceso total" ON public.audit_logs FOR SELECT TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));

CREATE POLICY "audit: admin ve logs de empresa" ON public.audit_logs FOR SELECT TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles actor WHERE actor.id = auth.uid() AND actor.role = 'admin') AND EXISTS (SELECT 1 FROM public.user_profiles target WHERE target.id = audit_logs.user_id AND target.empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1)));

-- 10. PROMPT TEMPLATES
ALTER TABLE public.prompt_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "prompts: admins gestionan" ON public.prompt_templates;
DROP POLICY IF EXISTS "prompts: lectura autenticada" ON public.prompt_templates;

CREATE POLICY "prompts: admins gestionan" ON public.prompt_templates FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE user_profiles.id = auth.uid() AND user_profiles.role IN ('superadmin', 'admin')));

CREATE POLICY "prompts: lectura autenticada" ON public.prompt_templates FOR SELECT TO authenticated USING (true);

-- 11. COMPANY YEASTAR CONFIGS
ALTER TABLE public.company_yeastar_configs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "yeastar: superadmin acceso total" ON public.company_yeastar_configs;
DROP POLICY IF EXISTS "yeastar: admin gestiona su config" ON public.company_yeastar_configs;

CREATE POLICY "yeastar: superadmin acceso total" ON public.company_yeastar_configs FOR ALL TO authenticated
USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));

CREATE POLICY "yeastar: admin gestiona su config" ON public.company_yeastar_configs FOR ALL TO authenticated
USING (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'))
WITH CHECK (empresa_id = (SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1) AND EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'admin'));

-- 12. CACHE TABLES
ALTER TABLE public.api_usage_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ui_cache ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "cache: superadmin gestion total" ON public.api_usage_cache;
DROP POLICY IF EXISTS "cache: lectura autenticada" ON public.api_usage_cache;
DROP POLICY IF EXISTS "ui_cache: superadmin gestion total" ON public.ui_cache;
DROP POLICY IF EXISTS "ui_cache: lectura autenticada" ON public.ui_cache;

CREATE POLICY "cache: superadmin gestion total" ON public.api_usage_cache FOR ALL TO authenticated USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));
CREATE POLICY "cache: lectura autenticada" ON public.api_usage_cache FOR SELECT TO authenticated USING (true);
CREATE POLICY "ui_cache: superadmin gestion total" ON public.ui_cache FOR ALL TO authenticated USING (EXISTS (SELECT 1 FROM public.user_profiles WHERE id = auth.uid() AND role = 'superadmin'));
CREATE POLICY "ui_cache: lectura autenticada" ON public.ui_cache FOR SELECT TO authenticated USING (true);
