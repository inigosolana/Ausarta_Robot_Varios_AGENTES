-- Evita recursión infinita en RLS al consultar user_profiles/empresas desde el cliente.
-- Error Postgres: infinite recursion detected in policy for relation "user_profiles"

CREATE OR REPLACE FUNCTION public.get_my_empresa_id()
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path TO public
AS $$
  SELECT empresa_id FROM public.user_profiles WHERE id = auth.uid() LIMIT 1;
$$;

DROP POLICY IF EXISTS "up: superadmin acceso total" ON public.user_profiles;
DROP POLICY IF EXISTS "up: tenant ve sus usuarios" ON public.user_profiles;

CREATE POLICY "up: superadmin acceso total" ON public.user_profiles
  FOR ALL TO authenticated
  USING (public.get_my_role() = 'superadmin')
  WITH CHECK (public.get_my_role() = 'superadmin');

CREATE POLICY "up: tenant ve sus usuarios" ON public.user_profiles
  FOR SELECT TO authenticated
  USING (
    public.get_my_empresa_id() IS NOT NULL
    AND empresa_id = public.get_my_empresa_id()
    AND public.get_my_role() IN ('admin', 'user')
  );

DROP POLICY IF EXISTS "Superadmins have full access" ON public.empresas;
DROP POLICY IF EXISTS "Users can view their own company" ON public.empresas;
DROP POLICY IF EXISTS "Admins can update their own company" ON public.empresas;

CREATE POLICY "Superadmins have full access" ON public.empresas
  FOR ALL TO authenticated
  USING (public.get_my_role() = 'superadmin')
  WITH CHECK (public.get_my_role() = 'superadmin');

CREATE POLICY "Users can view their own company" ON public.empresas
  FOR SELECT TO authenticated
  USING (id = public.get_my_empresa_id());

CREATE POLICY "Admins can update their own company" ON public.empresas
  FOR UPDATE TO authenticated
  USING (
    id = public.get_my_empresa_id()
    AND public.get_my_role() IN ('admin', 'superadmin')
  )
  WITH CHECK (
    id = public.get_my_empresa_id()
    AND public.get_my_role() IN ('admin', 'superadmin')
  );
