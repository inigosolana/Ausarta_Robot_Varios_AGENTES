-- =============================================================
-- 20260507_enforce_all_rls.sql
-- Auditoría de Row Level Security: activar RLS y políticas
-- multi-tenant estrictas en todas las tablas de negocio.
--
-- Contexto: La tabla `empresas` ya tiene RLS (20260420).
-- Esta migración extiende el mismo nivel de seguridad al
-- resto de tablas que el frontend consulta directamente:
--   - user_profiles
--   - user_permissions
--   - agents
--   - call_logs
--   - audit_logs
--   - yeastar_tenant_config (si existe)
--
-- PATRÓN GENERAL de aislamiento multi-tenant:
--   SELECT/UPDATE: solo filas donde empresa_id = empresa_id del usuario
--   INSERT/DELETE: solo dentro del propio tenant
--   Superadmin: acceso total (bypass de las restricciones de tenant)
-- =============================================================


-- =============================================================
-- HELPER: función auxiliar para obtener el empresa_id del usuario
-- autenticado sin repetir la subquery en cada política.
-- =============================================================
CREATE OR REPLACE FUNCTION auth.user_empresa_id()
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT empresa_id
    FROM user_profiles
    WHERE id = auth.uid()
    LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION auth.user_role()
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT role
    FROM user_profiles
    WHERE id = auth.uid()
    LIMIT 1;
$$;


-- =============================================================
-- TABLA: user_profiles
-- =============================================================
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "up: superadmin acceso total"          ON user_profiles;
DROP POLICY IF EXISTS "up: usuario ve su propio perfil"      ON user_profiles;
DROP POLICY IF EXISTS "up: admin ve usuarios de su empresa"  ON user_profiles;
DROP POLICY IF EXISTS "up: usuario actualiza su perfil"      ON user_profiles;
DROP POLICY IF EXISTS "up: admin actualiza usuarios empresa" ON user_profiles;

-- Superadmin: acceso total a todos los perfiles
CREATE POLICY "up: superadmin acceso total" ON user_profiles
FOR ALL TO authenticated
USING (auth.user_role() = 'superadmin');

-- Admin y user: solo ven perfiles de su mismo empresa_id
CREATE POLICY "up: admin ve usuarios de su empresa" ON user_profiles
FOR SELECT TO authenticated
USING (
    empresa_id = auth.user_empresa_id()
    AND auth.user_role() IN ('admin', 'user')
);

-- Usuario: puede leer y actualizar su propio perfil (campos no sensibles)
CREATE POLICY "up: usuario actualiza su perfil" ON user_profiles
FOR UPDATE TO authenticated
USING (id = auth.uid())
WITH CHECK (id = auth.uid());

-- Admin: puede actualizar perfiles de usuarios de su empresa
CREATE POLICY "up: admin actualiza usuarios empresa" ON user_profiles
FOR UPDATE TO authenticated
USING (
    empresa_id = auth.user_empresa_id()
    AND auth.user_role() = 'admin'
)
WITH CHECK (
    empresa_id = auth.user_empresa_id()
    AND auth.user_role() = 'admin'
);


-- =============================================================
-- TABLA: user_permissions
-- =============================================================
ALTER TABLE user_permissions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "perm: superadmin acceso total"        ON user_permissions;
DROP POLICY IF EXISTS "perm: usuario ve sus permisos"        ON user_permissions;
DROP POLICY IF EXISTS "perm: admin ve permisos de empresa"   ON user_permissions;
DROP POLICY IF EXISTS "perm: admin gestiona permisos empresa" ON user_permissions;

-- Superadmin: acceso total
CREATE POLICY "perm: superadmin acceso total" ON user_permissions
FOR ALL TO authenticated
USING (auth.user_role() = 'superadmin');

-- Usuario: solo puede leer sus propios permisos
CREATE POLICY "perm: usuario ve sus permisos" ON user_permissions
FOR SELECT TO authenticated
USING (user_id = auth.uid());

-- Admin: ve los permisos de todos los usuarios de su empresa
CREATE POLICY "perm: admin ve permisos de empresa" ON user_permissions
FOR SELECT TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM user_profiles
        WHERE user_profiles.id = user_permissions.user_id
        AND user_profiles.empresa_id = auth.user_empresa_id()
    )
    AND auth.user_role() = 'admin'
);

-- Admin: puede insertar/actualizar/borrar permisos de usuarios de su empresa
CREATE POLICY "perm: admin gestiona permisos empresa" ON user_permissions
FOR ALL TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM user_profiles
        WHERE user_profiles.id = user_permissions.user_id
        AND user_profiles.empresa_id = auth.user_empresa_id()
    )
    AND auth.user_role() = 'admin'
)
WITH CHECK (
    EXISTS (
        SELECT 1 FROM user_profiles
        WHERE user_profiles.id = user_permissions.user_id
        AND user_profiles.empresa_id = auth.user_empresa_id()
    )
    AND auth.user_role() = 'admin'
);


-- =============================================================
-- TABLA: agents
-- =============================================================
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "agents: superadmin acceso total"    ON agents;
DROP POLICY IF EXISTS "agents: tenant solo ve los suyos"   ON agents;
DROP POLICY IF EXISTS "agents: admin gestiona los suyos"   ON agents;

-- Superadmin: acceso total
CREATE POLICY "agents: superadmin acceso total" ON agents
FOR ALL TO authenticated
USING (auth.user_role() = 'superadmin');

-- Admin y user: solo ven los agentes de su empresa
CREATE POLICY "agents: tenant solo ve los suyos" ON agents
FOR SELECT TO authenticated
USING (
    empresa_id = auth.user_empresa_id()
    AND auth.user_role() IN ('admin', 'user')
);

-- Admin: puede crear, modificar y borrar agentes de su empresa
CREATE POLICY "agents: admin gestiona los suyos" ON agents
FOR ALL TO authenticated
USING (
    empresa_id = auth.user_empresa_id()
    AND auth.user_role() = 'admin'
)
WITH CHECK (
    empresa_id = auth.user_empresa_id()
    AND auth.user_role() = 'admin'
);


-- =============================================================
-- TABLA: call_logs
-- =============================================================
ALTER TABLE call_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "calls: superadmin acceso total"   ON call_logs;
DROP POLICY IF EXISTS "calls: tenant solo ve los suyos"  ON call_logs;

-- Superadmin: acceso total
CREATE POLICY "calls: superadmin acceso total" ON call_logs
FOR ALL TO authenticated
USING (auth.user_role() = 'superadmin');

-- Admin y user: solo ven logs de llamadas de su empresa
-- (call_logs es read-only para usuarios finales)
CREATE POLICY "calls: tenant solo ve los suyos" ON call_logs
FOR SELECT TO authenticated
USING (
    empresa_id = auth.user_empresa_id()
    AND auth.user_role() IN ('admin', 'user')
);


-- =============================================================
-- TABLA: audit_logs
-- Auditoría: los usuarios solo ven eventos de su empresa.
-- Nadie puede modificar ni borrar entradas de auditoría.
-- =============================================================
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "audit: superadmin acceso total"   ON audit_logs;
DROP POLICY IF EXISTS "audit: admin ve logs de empresa"  ON audit_logs;

-- Superadmin: acceso total de lectura
CREATE POLICY "audit: superadmin acceso total" ON audit_logs
FOR SELECT TO authenticated
USING (auth.user_role() = 'superadmin');

-- Admin: solo logs generados por usuarios de su empresa
CREATE POLICY "audit: admin ve logs de empresa" ON audit_logs
FOR SELECT TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM user_profiles
        WHERE user_profiles.id = audit_logs.user_id
        AND user_profiles.empresa_id = auth.user_empresa_id()
    )
    AND auth.user_role() = 'admin'
);

-- NOTA: No hay política de INSERT/UPDATE/DELETE para usuarios normales.
-- Los registros de auditoría solo los inserta el backend con service_role_key.


-- =============================================================
-- TABLA: yeastar_tenant_config (si existe en el proyecto)
-- Configuración sensible de integración telefónica por tenant.
-- =============================================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'yeastar_tenant_config') THEN
        ALTER TABLE yeastar_tenant_config ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS "yeastar: superadmin acceso total"  ON yeastar_tenant_config;
        DROP POLICY IF EXISTS "yeastar: admin ve su config"       ON yeastar_tenant_config;
        DROP POLICY IF EXISTS "yeastar: admin gestiona su config" ON yeastar_tenant_config;

        EXECUTE $pol$
            CREATE POLICY "yeastar: superadmin acceso total" ON yeastar_tenant_config
            FOR ALL TO authenticated
            USING (auth.user_role() = 'superadmin');
        $pol$;

        EXECUTE $pol$
            CREATE POLICY "yeastar: admin ve su config" ON yeastar_tenant_config
            FOR SELECT TO authenticated
            USING (
                empresa_id = auth.user_empresa_id()
                AND auth.user_role() = 'admin'
            );
        $pol$;

        EXECUTE $pol$
            CREATE POLICY "yeastar: admin gestiona su config" ON yeastar_tenant_config
            FOR ALL TO authenticated
            USING (
                empresa_id = auth.user_empresa_id()
                AND auth.user_role() = 'admin'
            )
            WITH CHECK (
                empresa_id = auth.user_empresa_id()
                AND auth.user_role() = 'admin'
            );
        $pol$;

        RAISE NOTICE 'RLS aplicado a yeastar_tenant_config';
    ELSE
        RAISE NOTICE 'Tabla yeastar_tenant_config no encontrada, omitida.';
    END IF;
END;
$$;


-- =============================================================
-- VERIFICACIÓN FINAL
-- Lista todas las tablas con RLS activo para confirmar el estado.
-- =============================================================
SELECT
    schemaname,
    tablename,
    rowsecurity AS rls_enabled
FROM pg_tables
WHERE schemaname = 'public'
AND tablename IN (
    'empresas', 'user_profiles', 'user_permissions',
    'agents', 'call_logs', 'audit_logs', 'yeastar_tenant_config'
)
ORDER BY tablename;
