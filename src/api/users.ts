import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';
import { supabase } from '../lib/supabase';
import type { Empresa, UserPermission, UserProfile } from '../types';

export type AdminUser = UserProfile & {
  permissions: UserPermission[];
  empresas?: Empresa | null;
};

export const userAdminKeys = {
  all: ['admin', 'users'] as const,
  list: (empresaId?: number) => [...userAdminKeys.all, 'list', empresaId ?? 'all'] as const,
  empresas: ['admin', 'users', 'empresas'] as const,
};

export async function fetchAdminEmpresasForUsers(empresaId?: number): Promise<Empresa[]> {
  const res = await apiFetch('/api/admin/empresas');
  if (!res.ok) return [];
  const data = await res.json();
  if (!Array.isArray(data)) return [];
  if (empresaId) return data.filter((e: Empresa) => e.id === empresaId);
  return data;
}

export async function fetchAdminUsersWithPermissions(empresaId?: number): Promise<AdminUser[]> {
  const res = await apiFetch('/api/admin/users');
  if (!res.ok) {
    console.error('[Users] GET /api/admin/users returned', res.status);
    return [];
  }
  const usersData = await res.json();
  if (!Array.isArray(usersData)) return [];

  let filteredUsers = usersData as UserProfile[];
  if (empresaId) {
    filteredUsers = filteredUsers.filter((u) => u.empresa_id === empresaId);
  }

  const userIds = filteredUsers.map((u) => u.id);
  if (!userIds.length) return [];

  const { data: allPerms } = await supabase
    .from('user_permissions')
    .select('*')
    .in('user_id', userIds);

  const permsMap: Record<string, UserPermission[]> = {};
  for (const p of allPerms || []) {
    if (!permsMap[p.user_id]) permsMap[p.user_id] = [];
    permsMap[p.user_id].push(p as UserPermission);
  }

  return filteredUsers.map((u) => ({
    ...u,
    permissions: permsMap[u.id] || [],
  }));
}

export function useAdminEmpresasForUsers(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: userAdminKeys.empresas,
    queryFn: () => fetchAdminEmpresasForUsers(empresaId),
    enabled,
    staleTime: 60_000,
  });
}

export function useAdminUsersList(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: userAdminKeys.list(empresaId),
    queryFn: () => fetchAdminUsersWithPermissions(empresaId),
    enabled,
    staleTime: 30_000,
  });
}

export function useInvalidateAdminUsers() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: userAdminKeys.all });
}
