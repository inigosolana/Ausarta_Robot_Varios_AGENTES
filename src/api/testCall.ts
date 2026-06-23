import { useQuery } from '@tanstack/react-query';
import { apiFetch, extractInboundPhoneNumbers, fetchTrunks } from '../lib/apiFetch';
import { supabase } from '../lib/supabase';
import type { AgentConfig } from '../types';

export const testCallKeys = {
  all: ['test-call'] as const,
  agents: (empresaId?: number) => [...testCallKeys.all, 'agents', empresaId ?? 'all'] as const,
  inboundNumbers: (empresaId: number) => [...testCallKeys.all, 'inbound', empresaId] as const,
};

export async function fetchTestCallAgents(empresaId?: number): Promise<AgentConfig[]> {
  let loadedAgents: AgentConfig[] = [];
  try {
    const qs = empresaId ? `?empresa_id=${empresaId}` : '';
    const res = await apiFetch(`/api/agents${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    loadedAgents = Array.isArray(data) ? data : [];
  } catch {
    loadedAgents = [];
  }

  if (!loadedAgents.length) {
    let query = supabase
      .from('agent_config')
      .select('id, name, use_case, description, instructions, greeting, empresa_id, agent_type, tipo_resultados');
    if (empresaId) query = query.eq('empresa_id', empresaId);
    const { data, error } = await query.order('name');
    if (error) throw error;
    loadedAgents = (data || []) as AgentConfig[];
  }

  return loadedAgents;
}

export function useTestCallAgents(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: testCallKeys.agents(empresaId),
    queryFn: () => fetchTestCallAgents(empresaId),
    enabled,
    staleTime: 30_000,
  });
}

export function useInboundPhoneNumbers(empresaId: number | null, enabled = true) {
  return useQuery({
    queryKey: empresaId ? testCallKeys.inboundNumbers(empresaId) : ['test-call', 'inbound', 'none'],
    queryFn: async () => {
      const data = await fetchTrunks(empresaId!);
      return extractInboundPhoneNumbers(data);
    },
    enabled: enabled && empresaId != null,
    staleTime: 60_000,
  });
}
