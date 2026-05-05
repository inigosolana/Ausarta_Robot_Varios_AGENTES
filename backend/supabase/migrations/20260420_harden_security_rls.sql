-- 20260420_harden_security_rls.sql
-- Active RLS on empresas table and set multi-tenant policies

-- Enable RLS
ALTER TABLE empresas ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if any to avoid conflicts
DROP POLICY IF EXISTS "Users can view their own company" ON empresas;
DROP POLICY IF EXISTS "Admins can update their own company" ON empresas;
DROP POLICY IF EXISTS "Superadmins have full access" ON empresas;

-- Policy: Superadmins have full access (Ausarta team or superadmin role)
CREATE POLICY "Superadmins have full access" ON empresas
FOR ALL
TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM user_profiles 
        WHERE user_profiles.id = auth.uid() 
        AND (user_profiles.role = 'superadmin' OR user_profiles.empresa_id = (SELECT id FROM empresas WHERE nombre ILIKE 'Ausarta' LIMIT 1))
    )
);

-- Policy: Users can only view their own company
CREATE POLICY "Users can view their own company" ON empresas
FOR SELECT
TO authenticated
USING (
    id = (SELECT empresa_id FROM user_profiles WHERE id = auth.uid())
);

-- Policy: Admins can update their own company
CREATE POLICY "Admins can update their own company" ON empresas
FOR UPDATE
TO authenticated
USING (
    id = (SELECT empresa_id FROM user_profiles WHERE id = auth.uid())
    AND EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
)
WITH CHECK (
    id = (SELECT empresa_id FROM user_profiles WHERE id = auth.uid())
    AND EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
);
