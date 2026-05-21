-- Políticas legacy en encuestas (rol public) permitían SELECT sin filtro tenant.
-- Mantener solo las políticas multi-tenant authenticated.

DROP POLICY IF EXISTS "users_read_encuestas" ON public.encuestas;
DROP POLICY IF EXISTS "authenticated_read_encuestas" ON public.encuestas;
DROP POLICY IF EXISTS "superadmin_full_access_encuestas" ON public.encuestas;
DROP POLICY IF EXISTS "admins_manage_encuestas" ON public.encuestas;

ALTER TABLE public.encuestas ENABLE ROW LEVEL SECURITY;
