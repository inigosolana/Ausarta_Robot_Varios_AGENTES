import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';

export interface AgentSummary {
  id: number;
  name: string;
  empresa_id?: number;
  agent_type?: string;
}

export const agentKeys = {
  all: ['agents'] as const,
  byEmpresa: (empresaId: number | 'all') => [...agentKeys.all, empresaId] as const,
};

export function useAgents(empresaId?: number) {
  const key = empresaId ?? 'all';
  return useQuery({
    queryKey: agentKeys.byEmpresa(key),
    queryFn: async () => {
      const url = empresaId
        ? `/api/agents?empresa_id=${empresaId}`
        : '/api/agents';
      return apiFetch<AgentSummary[]>(url);
    },
    staleTime: 30_000,
  });
}
