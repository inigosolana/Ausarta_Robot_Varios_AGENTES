import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fetchAgentsList,
  fetchCampaignsList,
  fetchEmpresasList,
  type CampaignRow,
} from '../lib/campaignsSupabase';
import { apiFetch } from '../lib/apiFetch';
import type { Empresa } from '../types';

export type { CampaignRow };

export const campaignKeys = {
  all: ['campaigns'] as const,
  list: (empresaId?: number) => [...campaignKeys.all, 'list', empresaId ?? 'all'] as const,
  detail: (id: number) => [...campaignKeys.all, 'detail', id] as const,
};

export const empresaKeys = {
  all: ['empresas'] as const,
  list: (empresaId?: number) => [...empresaKeys.all, empresaId ?? 'all'] as const,
};

export const agentKeys = {
  all: ['agents'] as const,
  list: (empresaId?: number) => [...agentKeys.all, empresaId ?? 'all'] as const,
};

export function useCampaignsList(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: campaignKeys.list(empresaId),
    queryFn: () => fetchCampaignsList(empresaId),
    enabled,
    staleTime: 30_000,
  });
}

export function useEmpresasList(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: empresaKeys.list(empresaId),
    queryFn: () => fetchEmpresasList(empresaId) as Promise<Empresa[]>,
    enabled,
    staleTime: 60_000,
  });
}

export function useAgentsList(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: agentKeys.list(empresaId),
    queryFn: () => fetchAgentsList(empresaId),
    enabled,
    staleTime: 30_000,
  });
}

export function useInvalidateCampaigns() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: campaignKeys.all });
}

export async function simulateCampaign(campaignId: number) {
  return apiFetch<Record<string, unknown>>(`/api/campaigns/${campaignId}/simulate`, {
    method: 'POST',
  });
}

export function campaignExportUrl(campaignId: number) {
  const base = (import.meta as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL || '';
  return `${base}/api/campaigns/${campaignId}/export?format=csv`;
}
