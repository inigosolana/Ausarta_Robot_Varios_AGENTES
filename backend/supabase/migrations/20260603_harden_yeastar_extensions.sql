-- Preparar extensiones Yeastar para sincronizacion repetible desde PBX.

ALTER TABLE public.yeastar_extensions
ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE OR REPLACE FUNCTION public.update_yeastar_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_yeastar_extensions_empresa_number
ON public.yeastar_extensions (empresa_id, extension_number);

DROP TRIGGER IF EXISTS set_yeastar_extensions_updated_at
  ON public.yeastar_extensions;

CREATE TRIGGER set_yeastar_extensions_updated_at
BEFORE UPDATE ON public.yeastar_extensions
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

DROP POLICY IF EXISTS "yeastar_extensions: superadmin acceso total" ON public.yeastar_extensions;
DROP POLICY IF EXISTS "yeastar_extensions: tenant solo ve los suyos" ON public.yeastar_extensions;
DROP POLICY IF EXISTS "yeastar_extensions: select allowed" ON public.yeastar_extensions;
DROP POLICY IF EXISTS "yeastar_extensions: modify allowed" ON public.yeastar_extensions;
DROP POLICY IF EXISTS "yeastar_extensions: insert allowed" ON public.yeastar_extensions;
DROP POLICY IF EXISTS "yeastar_extensions: update allowed" ON public.yeastar_extensions;
DROP POLICY IF EXISTS "yeastar_extensions: delete allowed" ON public.yeastar_extensions;

CREATE POLICY "yeastar_extensions: select allowed"
ON public.yeastar_extensions
FOR SELECT
TO authenticated
USING (public.has_global_access() OR empresa_id = public.get_my_empresa_id());

CREATE POLICY "yeastar_extensions: insert allowed"
ON public.yeastar_extensions
FOR INSERT
TO authenticated
WITH CHECK (
  public.has_global_access()
  OR (
    empresa_id = public.get_my_empresa_id()
    AND public.get_my_role() = ANY (ARRAY['admin'::text, 'superadmin'::text])
  )
);

CREATE POLICY "yeastar_extensions: update allowed"
ON public.yeastar_extensions
FOR UPDATE
TO authenticated
USING (
  public.has_global_access()
  OR (
    empresa_id = public.get_my_empresa_id()
    AND public.get_my_role() = ANY (ARRAY['admin'::text, 'superadmin'::text])
  )
)
WITH CHECK (
  public.has_global_access()
  OR (
    empresa_id = public.get_my_empresa_id()
    AND public.get_my_role() = ANY (ARRAY['admin'::text, 'superadmin'::text])
  )
);

CREATE POLICY "yeastar_extensions: delete allowed"
ON public.yeastar_extensions
FOR DELETE
TO authenticated
USING (
  public.has_global_access()
  OR (
    empresa_id = public.get_my_empresa_id()
    AND public.get_my_role() = ANY (ARRAY['admin'::text, 'superadmin'::text])
  )
);
