import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';

export interface YeastarConfig {
  empresa_id?: number;
  yeastar_pbx_url: string;
  yeastar_api_mode: 'pseries' | 'cloud_pbx';
  yeastar_client_id: string;
  yeastar_client_secret?: string;
  enabled_capabilities?: string[];
  ddi?: string;
}

export interface YeastarCapability {
  id: string;
  group: string;
  label: string;
  description: string;
  permission: string;
  endpoints: string[];
  status: 'implemented' | 'available' | 'planned' | string;
}

export interface YeastarHealthStatus {
  empresa_id?: number;
  configured?: boolean;
  health_status?: 'ok' | 'down' | 'unknown' | string;
  last_health_check_at?: string | null;
  consecutive_failures?: number;
  failure_threshold?: number;
  campaigns_paused_count?: number;
  campaigns_paused_by_health?: Array<{ id: number; name?: string; paused_reason?: string }>;
}

export interface TelephonyPlatformInfo {
  ausarta_public_ip?: string;
  yeastar_webhook_url?: string;
}

export const telephonyKeys = {
  all: ['telephony'] as const,
  platformInfo: ['telephony', 'platform-info'] as const,
  capabilities: ['telephony', 'capabilities'] as const,
  config: (empresaId: number) => ['telephony', 'config', empresaId] as const,
  health: (empresaId: number) => ['telephony', 'health', empresaId] as const,
};

export async function fetchTelephonyPlatformInfo(): Promise<TelephonyPlatformInfo> {
  try {
    const res = await apiFetch('/api/telephony/platform-info');
    if (!res.ok) return {};
    return await res.json();
  } catch {
    return {};
  }
}

export async function fetchYeastarCapabilities(): Promise<YeastarCapability[]> {
  try {
    const res = await apiFetch('/api/telephony/yeastar/capabilities');
    if (!res.ok) return [];
    const data = await res.json();
    return data.capabilities || [];
  } catch {
    return [];
  }
}

export async function fetchYeastarConfig(empresaId: number): Promise<YeastarConfig | null> {
  const res = await apiFetch(`/api/telephony/yeastar?empresa_id=${empresaId}`);
  if (res.status === 204 || res.status === 404) return null;
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

export async function fetchYeastarHealth(empresaId: number): Promise<YeastarHealthStatus | null> {
  try {
    const res = await apiFetch(`/api/empresas/${empresaId}/yeastar/health`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export function useTelephonyPlatformInfo(enabled = true) {
  return useQuery({
    queryKey: telephonyKeys.platformInfo,
    queryFn: fetchTelephonyPlatformInfo,
    enabled,
    staleTime: 300_000,
  });
}

export function useYeastarCapabilities(enabled = true) {
  return useQuery({
    queryKey: telephonyKeys.capabilities,
    queryFn: fetchYeastarCapabilities,
    enabled,
    staleTime: 300_000,
  });
}

export function useYeastarConfig(empresaId: number | null, enabled = true) {
  return useQuery({
    queryKey: empresaId ? telephonyKeys.config(empresaId) : ['telephony', 'config', 'none'],
    queryFn: () => fetchYeastarConfig(empresaId!),
    enabled: enabled && empresaId != null,
    staleTime: 30_000,
  });
}

export function useYeastarHealth(empresaId: number | null, enabled = true) {
  return useQuery({
    queryKey: empresaId ? telephonyKeys.health(empresaId) : ['telephony', 'health', 'none'],
    queryFn: () => fetchYeastarHealth(empresaId!),
    enabled: enabled && empresaId != null,
    staleTime: 30_000,
  });
}

export function useInvalidateTelephony() {
  const queryClient = useQueryClient();
  return {
    invalidateConfig: (empresaId: number) =>
      queryClient.invalidateQueries({ queryKey: telephonyKeys.config(empresaId) }),
    invalidateHealth: (empresaId: number) =>
      queryClient.invalidateQueries({ queryKey: telephonyKeys.health(empresaId) }),
  };
}
