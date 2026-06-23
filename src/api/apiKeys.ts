import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';
import {
  fetchApiKeys,
  type ApiKeyListItem,
} from '../lib/apiKeys';

export type { ApiKeyCreateResult, ApiKeyListItem, ApiKeyScope } from '../lib/apiKeys';
export { createApiKey, revokeApiKey } from '../lib/apiKeys';

export type AdminEmpresaOption = { id: number; nombre: string };

export const apiKeyKeys = {
  all: ['api-keys'] as const,
  list: (empresaId?: number) => [...apiKeyKeys.all, 'list', empresaId ?? 'all'] as const,
  empresas: ['api-keys', 'admin-empresas'] as const,
};

export async function fetchAdminEmpresasOptions(): Promise<AdminEmpresaOption[]> {
  const res = await apiFetch('/api/admin/empresas');
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export function useApiKeysList(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: apiKeyKeys.list(empresaId),
    queryFn: async (): Promise<ApiKeyListItem[]> => {
      const data = await fetchApiKeys(empresaId);
      return data.filter((k) => k.is_active);
    },
    enabled,
    staleTime: 30_000,
  });
}

export function useAdminEmpresasOptions(enabled = true) {
  return useQuery({
    queryKey: apiKeyKeys.empresas,
    queryFn: fetchAdminEmpresasOptions,
    enabled,
    staleTime: 60_000,
  });
}

export function useInvalidateApiKeys() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: apiKeyKeys.all });
}
