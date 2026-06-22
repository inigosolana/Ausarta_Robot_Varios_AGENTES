import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';

export interface CampaignSummary {
  id: number;
  name: string;
  status?: string;
  empresa_id?: number;
}

export const campaignKeys = {
  all: ['campaigns'] as const,
  byEmpresa: (empresaId: number | 'all') => [...campaignKeys.all, empresaId] as const,
  detail: (id: number) => [...campaignKeys.all, 'detail', id] as const,
};

export function useCampaigns(empresaId?: number) {
  const key = empresaId ?? 'all';
  return useQuery({
    queryKey: campaignKeys.byEmpresa(key),
    queryFn: async () => {
      const url = empresaId
        ? `/api/campaigns?empresa_id=${empresaId}`
        : '/api/campaigns';
      return apiFetch<CampaignSummary[]>(url);
    },
    staleTime: 30_000,
  });
}

export function useCampaignSimulate(campaignId: number, enabled = false) {
  return useQuery({
    queryKey: [...campaignKeys.detail(campaignId), 'simulate'],
    queryFn: () =>
      apiFetch<Record<string, unknown>>(`/api/campaigns/${campaignId}/simulate`, {
        method: 'POST',
      }),
    enabled: enabled && campaignId > 0,
  });
}
