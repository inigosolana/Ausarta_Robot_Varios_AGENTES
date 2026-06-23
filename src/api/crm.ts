import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';

export type CrmIntegrationConfig = {
  crm_type?: string;
  crm_webhook_url?: string;
  webhook_url?: string | null;
};

export const crmKeys = {
  all: ['crm'] as const,
  config: (empresaId: number) => [...crmKeys.all, 'config', empresaId] as const,
};

export async function fetchCrmConfig(empresaId: number): Promise<CrmIntegrationConfig> {
  const res = await apiFetch(`/api/admin/empresas/${empresaId}/crm-config`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

export function useCrmConfig(empresaId: number | null, enabled = true) {
  return useQuery({
    queryKey: empresaId ? crmKeys.config(empresaId) : ['crm', 'config', 'none'],
    queryFn: () => fetchCrmConfig(empresaId!),
    enabled: enabled && empresaId != null,
    staleTime: 30_000,
  });
}

export function useInvalidateCrmConfig() {
  const queryClient = useQueryClient();
  return (empresaId: number) =>
    queryClient.invalidateQueries({ queryKey: crmKeys.config(empresaId) });
}
