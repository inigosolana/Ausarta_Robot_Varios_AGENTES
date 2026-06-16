import { apiFetch } from './apiFetch';

export interface CallRow {
  id: number;
  phone: string;
  customer_name: string;
  status: string;
  is_live: boolean;
  room_name?: string | null;
  participants?: number | null;
  duration_seconds?: number | null;
  empresa_id?: number | null;
  empresa_name?: string | null;
  agent_id?: number | null;
  agent_name?: string | null;
  agent_type?: string | null;
  campaign_id?: number | null;
  campaign_name?: string | null;
  started_at?: string | null;
  call_direction?: string | null;
  completada?: boolean;
}

export interface CallsListResponse {
  calls: CallRow[];
  live_count: number;
  total: number;
  limit: number;
  offset: number;
}

export interface CallsFilters {
  empresaId?: number | 'all';
  agentId?: number;
  campaignId?: number;
  status?: string;
  liveOnly?: boolean;
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}

export async function fetchCalls(filters: CallsFilters = {}): Promise<CallsListResponse> {
  const params = new URLSearchParams();
  if (filters.empresaId && filters.empresaId !== 'all') {
    params.set('empresa_id', String(filters.empresaId));
  }
  if (filters.agentId) params.set('agent_id', String(filters.agentId));
  if (filters.campaignId) params.set('campaign_id', String(filters.campaignId));
  if (filters.status) params.set('status', filters.status);
  if (filters.liveOnly) params.set('live_only', 'true');
  if (filters.startDate) params.set('start_date', filters.startDate);
  if (filters.endDate) params.set('end_date', filters.endDate);
  if (filters.limit) params.set('limit', String(filters.limit));
  if (filters.offset) params.set('offset', String(filters.offset));

  const qs = params.toString();
  const res = await apiFetch(`/api/calls${qs ? `?${qs}` : ''}`);
  if (!res.ok) {
    throw new Error(`No se pudieron cargar las llamadas (${res.status})`);
  }
  return res.json();
}

export function formatCallDuration(seconds?: number | null): string {
  const s = Math.max(0, Number(seconds || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, '0')}`;
}
