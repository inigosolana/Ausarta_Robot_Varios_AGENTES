import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';
import { supabase } from '../lib/supabase';
import type { AgentConfig, AIConfig, UserProfile } from '../types';

export { useAgentsList, agentKeys } from './campaigns';

export const agentsDetailKeys = {
  all: ['agents', 'detail'] as const,
  list: (empresaId?: number) => [...agentsDetailKeys.all, empresaId ?? 'all'] as const,
};

export const companyUserKeys = {
  all: ['users', 'company'] as const,
  list: (empresaId: number) => [...companyUserKeys.all, empresaId] as const,
};

function normalizeAgentId<T extends { id?: number | string }>(agent: T): T & { id?: number } {
  if (agent.id == null) return agent as T & { id?: number };
  const numeric = typeof agent.id === 'string' ? Number(agent.id) : agent.id;
  return { ...agent, id: Number.isFinite(numeric) ? numeric : agent.id as number };
}

export async function fetchAgentsWithAI(
  empresaId?: number,
): Promise<(AgentConfig & { ai_config?: AIConfig })[]> {
  const qs = empresaId ? `?empresa_id=${empresaId}` : '';
  const res = await apiFetch(`/api/agents${qs}`);
  const data = await res.json();
  if (!Array.isArray(data)) return [];
  return data.map((agent) => normalizeAgentId(agent as AgentConfig & { ai_config?: AIConfig }));
}

export async function fetchCompanyUsers(empresaId: number): Promise<UserProfile[]> {
  const { data, error } = await supabase
    .from('user_profiles')
    .select('*')
    .eq('empresa_id', empresaId);
  if (error) throw error;
  return data || [];
}

export function useAgentsWithAI(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: agentsDetailKeys.list(empresaId),
    queryFn: () => fetchAgentsWithAI(empresaId),
    enabled,
    staleTime: 30_000,
  });
}

export function useCompanyUsers(empresaId: number | undefined, enabled = true) {
  return useQuery({
    queryKey: companyUserKeys.list(empresaId ?? 0),
    queryFn: () => fetchCompanyUsers(empresaId!),
    enabled: enabled && Boolean(empresaId),
    staleTime: 30_000,
  });
}

export function useInvalidateAgents() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: agentsDetailKeys.all });
}
