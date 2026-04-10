-- Add logo_url column to empresas table
ALTER TABLE empresas
  ADD COLUMN IF NOT EXISTS logo_url TEXT DEFAULT NULL;

-- Create public storage bucket for company logos (run once in Supabase Dashboard
-- or via the management API; SQL alone cannot create storage buckets).
-- Bucket name: empresa-logos  |  Public: true
--
-- If running via psql against the Supabase DB directly, use the Storage API instead:
--   INSERT INTO storage.buckets (id, name, public)
--   VALUES ('empresa-logos', 'empresa-logos', true)
--   ON CONFLICT (id) DO NOTHING;
INSERT INTO storage.buckets (id, name, public)
VALUES ('empresa-logos', 'empresa-logos', true)
ON CONFLICT (id) DO NOTHING;

-- Allow authenticated users to upload/update their company logos
CREATE POLICY IF NOT EXISTS "empresa_logos_upload"
  ON storage.objects FOR INSERT
  TO authenticated
  WITH CHECK (bucket_id = 'empresa-logos');

CREATE POLICY IF NOT EXISTS "empresa_logos_update"
  ON storage.objects FOR UPDATE
  TO authenticated
  USING (bucket_id = 'empresa-logos');

-- Allow anyone (anon + authenticated) to read/download logos
CREATE POLICY IF NOT EXISTS "empresa_logos_public_read"
  ON storage.objects FOR SELECT
  TO public
  USING (bucket_id = 'empresa-logos');
