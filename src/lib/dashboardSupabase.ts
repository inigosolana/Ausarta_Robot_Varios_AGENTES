/**
 * Lecturas de dashboard directamente desde Supabase (PostgREST).
 * Respeta filtros multi-tenant vía empresa_id.
 */
import { supabase } from './supabase';

export interface DashboardFilters {
  empresaId?: number;
  agentId?: number;
  campaignId?: number;
  startDate?: string;
  endDate?: string;
}

function applyEncuestaFilters<T extends { eq: (c: string, v: unknown) => T; gte: (c: string, v: string) => T; lte: (c: string, v: string) => T }>(
  query: T,
  f: DashboardFilters
): T {
  let q = query;
  if (f.empresaId) q = q.eq('empresa_id', f.empresaId);
  if (f.agentId) q = q.eq('agent_id', f.agentId);
  if (f.campaignId) q = q.eq('campaign_id', f.campaignId);
  if (f.startDate) q = q.gte('fecha', f.startDate);
  if (f.endDate) q = q.lte('fecha', f.endDate);
  return q;
}

export interface DashboardStats {
  total_calls: number;
  completed_calls: number;
  pending_calls: number;
  is_question_based?: boolean;
  status_breakdown: Record<string, number>;
  avg_scores: {
    comercial: number;
    instalador: number;
    rapidez: number;
    overall: number;
  };
}

export async function fetchDashboardStats(filters: DashboardFilters): Promise<DashboardStats> {
  const empty: DashboardStats = {
    total_calls: 0,
    completed_calls: 0,
    pending_calls: 0,
    status_breakdown: {},
    avg_scores: { comercial: 0, instalador: 0, rapidez: 0, overall: 0 },
  };

  let totalQ = supabase.from('encuestas').select('id', { count: 'exact', head: true });
  totalQ = applyEncuestaFilters(totalQ, filters);
  const { count: totalCalls, error: e1 } = await totalQ;
  if (e1) throw e1;

  let completedQ = supabase.from('encuestas').select('id', { count: 'exact', head: true }).eq('completada', 1);
  completedQ = applyEncuestaFilters(completedQ, filters);
  const { count: completedCalls, error: e2 } = await completedQ;
  if (e2) throw e2;

  let pendingCalls = 0;
  if (filters.empresaId) {
    const { data: camps } = await supabase.from('campaigns').select('id').eq('empresa_id', filters.empresaId);
    const campIds = (camps || []).map((c) => c.id);
    if (campIds.length) {
      let pq = supabase.from('campaign_leads').select('id', { count: 'exact', head: true }).in('status', ['pending', 'calling']).in('campaign_id', campIds);
      if (filters.startDate) pq = pq.gte('created_at', filters.startDate);
      if (filters.endDate) pq = pq.lte('created_at', filters.endDate);
      const { count } = await pq;
      pendingCalls = count ?? 0;
    }
  } else {
    let pq = supabase.from('campaign_leads').select('id', { count: 'exact', head: true }).in('status', ['pending', 'calling']);
    if (filters.startDate) pq = pq.gte('created_at', filters.startDate);
    if (filters.endDate) pq = pq.lte('created_at', filters.endDate);
    const { count } = await pq;
    pendingCalls = count ?? 0;
  }

  let scoresQ = supabase.from('encuestas').select('puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez');
  scoresQ = applyEncuestaFilters(scoresQ, filters);
  const { data: scoresData, error: e3 } = await scoresQ;
  if (e3) throw e3;

  let statusQ = supabase.from('encuestas').select('status');
  statusQ = applyEncuestaFilters(statusQ, filters);
  const { data: statusRows, error: e4 } = await statusQ;
  if (e4) throw e4;

  const status_breakdown: Record<string, number> = {};
  (statusRows || []).forEach((r) => {
    const st = r.status || 'unknown';
    status_breakdown[st] = (status_breakdown[st] || 0) + 1;
  });

  const valsCom = (scoresData || []).map((r) => r.puntuacion_comercial).filter((v) => v != null) as number[];
  const valsIns = (scoresData || []).map((r) => r.puntuacion_instalador).filter((v) => v != null) as number[];
  const valsRap = (scoresData || []).map((r) => r.puntuacion_rapidez).filter((v) => v != null) as number[];
  const avg = (arr: number[]) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0);
  const allVals = [...valsCom, ...valsIns, ...valsRap];

  return {
    total_calls: totalCalls ?? 0,
    completed_calls: completedCalls ?? 0,
    pending_calls: pendingCalls,
    status_breakdown,
    avg_scores: {
      comercial: Math.round(avg(valsCom) * 10) / 10,
      instalador: Math.round(avg(valsIns) * 10) / 10,
      rapidez: Math.round(avg(valsRap) * 10) / 10,
      overall: Math.round(avg(allVals) * 10) / 10,
    },
  };
}

export interface RecentCallRow {
  id: number;
  phone: string;
  campaign: string;
  campaign_id: number | null;
  date: string;
  status: string;
  llm_model: string | null;
  empresa_id: number | null;
  empresa_name: string;
  tipo_resultados: string | null;
  agent_name: string | null;
  is_test: boolean;
}

export async function fetchRecentCalls(filters: DashboardFilters, limit = 50): Promise<RecentCallRow[]> {
  const cols = 'id, telefono, campaign_name, campaign_id, nombre_cliente, fecha, status, llm_model, empresa_id, agent_id';
  let q = supabase.from('encuestas').select(cols);
  q = applyEncuestaFilters(q, filters);
  const { data: rows, error } = await q.order('fecha', { ascending: false }).limit(limit);
  if (error) throw error;

  const [{ data: empresas }, { data: agents }] = await Promise.all([
    supabase.from('empresas').select('id, nombre'),
    supabase.from('agent_config').select('id, tipo_resultados, name'),
  ]);

  const empMap = Object.fromEntries((empresas || []).map((e) => [e.id, e.nombre]));
  const agentMap = Object.fromEntries((agents || []).map((a) => [String(a.id), { tipo: a.tipo_resultados, name: a.name }]));

  return (rows || []).map((r) => {
    const aid = String(r.agent_id || '');
    const campId = r.campaign_id;
    const empId = r.empresa_id;
    const agentInfo = agentMap[aid] || {};
    return {
      id: r.id,
      phone: r.telefono || '',
      campaign: r.campaign_name || r.nombre_cliente || '—',
      campaign_id: campId,
      date: r.fecha || '',
      status: r.status || 'pending',
      llm_model: r.llm_model,
      empresa_id: empId,
      empresa_name: empId ? (empMap[empId] || '—') : '—',
      tipo_resultados: agentInfo.tipo ?? null,
      agent_name: agentInfo.name ?? null,
      is_test: !campId || campId === 0,
    };
  });
}

export interface TopPerformers {
  top_campaign: { id: number; name: string; completed: number; total: number; rate: number } | null;
  top_agent: { id: number; name: string; completed: number; total: number; rate: number } | null;
}

export async function fetchTopPerformers(filters: DashboardFilters): Promise<TopPerformers> {
  let q = supabase.from('encuestas').select('campaign_id, campaign_name, agent_id, status');
  if (filters.empresaId) q = q.eq('empresa_id', filters.empresaId);
  if (filters.startDate) q = q.gte('fecha', filters.startDate);
  if (filters.endDate) q = q.lte('fecha', filters.endDate);
  const { data: rows, error } = await q.not('campaign_id', 'is', null);
  if (error) throw error;
  if (!rows?.length) return { top_campaign: null, top_agent: null };

  const campStats: Record<number, { total: number; completed: number; name: string }> = {};
  const agentStats: Record<number, { total: number; completed: number }> = {};

  rows.forEach((r) => {
    const st = (r.status || '').toLowerCase();
    const done = st === 'completada' || st === 'completed' ? 1 : 0;
    const cid = r.campaign_id;
    const aid = r.agent_id;
    if (cid) {
      if (!campStats[cid]) campStats[cid] = { total: 0, completed: 0, name: r.campaign_name || '' };
      campStats[cid].total += 1;
      campStats[cid].completed += done;
    }
    if (aid) {
      if (!agentStats[aid]) agentStats[aid] = { total: 0, completed: 0 };
      agentStats[aid].total += 1;
      agentStats[aid].completed += done;
    }
  });

  let top_campaign: TopPerformers['top_campaign'] = null;
  let bestRate = -1;
  Object.entries(campStats).forEach(([id, s]) => {
    if (s.total >= 2) {
      const rate = s.completed / s.total;
      if (rate > bestRate) {
        bestRate = rate;
        top_campaign = { id: Number(id), name: s.name, completed: s.completed, total: s.total, rate: Math.round(rate * 1000) / 10 };
      }
    }
  });

  const { data: agentRows } = await supabase.from('agent_config').select('id, name');
  const agentNames = Object.fromEntries((agentRows || []).map((a) => [a.id, a.name]));

  let top_agent: TopPerformers['top_agent'] = null;
  let bestAgentRate = -1;
  Object.entries(agentStats).forEach(([id, s]) => {
    if (s.total >= 2) {
      const rate = s.completed / s.total;
      if (rate > bestAgentRate) {
        bestAgentRate = rate;
        top_agent = {
          id: Number(id),
          name: agentNames[Number(id)] || `Agente #${id}`,
          completed: s.completed,
          total: s.total,
          rate: Math.round(rate * 1000) / 10,
        };
      }
    }
  });

  return { top_campaign, top_agent };
}

export interface UsageStats {
  total_tokens: number;
  total_minutes: number;
  per_model_stats: { llm_model: string; calls: number; tokens: number; seconds: number }[];
}

export async function fetchUsageStats(filters: DashboardFilters): Promise<UsageStats> {
  let q = supabase.from('encuestas').select('llm_model, seconds_used, status');
  if (filters.empresaId) q = q.eq('empresa_id', filters.empresaId);
  if (filters.startDate) q = q.gte('fecha', filters.startDate);
  if (filters.endDate) q = q.lte('fecha', filters.endDate);
  const { data: rows, error } = await q;
  if (error) throw error;

  const totalSeconds = (rows || []).reduce((s, r) => s + (r.seconds_used || 0), 0);
  const modelStats: Record<string, { llm_model: string; calls: number; tokens: number; seconds: number }> = {};
  (rows || []).forEach((r) => {
    const model = r.llm_model || 'Standard';
    if (!modelStats[model]) modelStats[model] = { llm_model: model, calls: 0, tokens: 0, seconds: 0 };
    modelStats[model].calls += 1;
    modelStats[model].seconds += r.seconds_used || 0;
    modelStats[model].tokens += (r.seconds_used || 0) * 15;
  });

  const per = Object.values(modelStats);
  return {
    total_tokens: per.reduce((s, m) => s + m.tokens, 0),
    total_minutes: Math.round((totalSeconds / 60) * 10) / 10,
    per_model_stats: per,
  };
}

export async function fetchAgentsForEmpresa(empresaId: number) {
  const { data, error } = await supabase
    .from('agent_config')
    .select('id, name, use_case, empresa_id')
    .eq('empresa_id', empresaId)
    .order('name');
  if (error) throw error;
  return data || [];
}
