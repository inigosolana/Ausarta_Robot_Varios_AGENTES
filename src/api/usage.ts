import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';

export const usageKeys = {
  all: ['usage'] as const,
  dashboard: (empresaId?: number) => [...usageKeys.all, 'dashboard', empresaId ?? 'all'] as const,
  miConsumo: ['usage', 'mi-consumo'] as const,
  sipLogs: ['usage', 'sip-logs'] as const,
};

export type UsageDashboardData = {
  integrations: unknown[];
  usage: unknown;
  liveLimits: unknown;
  alerts: unknown[];
};

export async function fetchUsageDashboard(empresaId?: number): Promise<UsageDashboardData> {
  const qs = empresaId ? `?empresa_id=${empresaId}` : '';
  const [intRes, usageRes, limitsRes, alertsRes] = await Promise.all([
    apiFetch('/api/dashboard/integrations'),
    apiFetch(`/api/dashboard/usage-stats${qs}`),
    apiFetch('/api/ai/limits'),
    apiFetch(`/api/alerts${qs}`),
  ]);

  return {
    integrations: intRes.ok ? await intRes.json() : [],
    usage: usageRes.ok ? await usageRes.json() : null,
    liveLimits: limitsRes.ok ? await limitsRes.json() : null,
    alerts: alertsRes.ok ? await alertsRes.json() : [],
  };
}

export async function fetchMiConsumo() {
  const res = await apiFetch('/api/usage/mi-consumo');
  if (!res.ok) return null;
  return res.json();
}

export async function fetchSipLogs(): Promise<string[]> {
  const res = await apiFetch('/api/logs/sip');
  if (!res.ok) return [];
  const data = await res.json();
  return data.logs || [];
}

export function useUsageDashboard(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: usageKeys.dashboard(empresaId),
    queryFn: () => fetchUsageDashboard(empresaId),
    enabled,
    staleTime: 30_000,
  });
}

export function useMiConsumo(enabled = true) {
  return useQuery({
    queryKey: usageKeys.miConsumo,
    queryFn: fetchMiConsumo,
    enabled,
    staleTime: 30_000,
  });
}

export function useSipLogs(enabled = true) {
  return useQuery({
    queryKey: usageKeys.sipLogs,
    queryFn: fetchSipLogs,
    enabled,
    staleTime: 15_000,
  });
}
