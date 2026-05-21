import { supabase } from './supabase';

export interface CampaignRow {
  id: number;
  name: string;
  status: string;
  scheduled_time: string | null;
  created_at: string;
  empresa_id: number | null;
  total_leads?: number;
  called_leads?: number;
  empresas?: { nombre: string };
  [key: string]: unknown;
}

/** Lista campañas con conteos de leads; filtra por empresa (multi-tenant). */
export async function fetchCampaignsList(empresaId?: number): Promise<CampaignRow[]> {
  let q = supabase.from('campaigns').select('*, empresas:empresa_id(nombre)').order('created_at', { ascending: false }).limit(100);
  if (empresaId) q = q.eq('empresa_id', empresaId);

  const { data: campaigns, error } = await q;
  if (error) throw error;
  if (!campaigns?.length) return [];

  const enriched = await Promise.all(
    campaigns.map(async (c) => {
      const [totalRes, pendingRes] = await Promise.all([
        supabase.from('campaign_leads').select('id', { count: 'exact', head: true }).eq('campaign_id', c.id),
        supabase
          .from('campaign_leads')
          .select('id', { count: 'exact', head: true })
          .eq('campaign_id', c.id)
          .in('status', ['pending', 'calling']),
      ]);
      const total = totalRes.count ?? 0;
      const pending = pendingRes.count ?? 0;
      return {
        ...c,
        total_leads: total,
        called_leads: Math.max(0, total - pending),
      } as CampaignRow;
    })
  );

  return enriched;
}

export async function fetchEmpresasList(empresaId?: number) {
  let q = supabase.from('empresas').select('*').order('nombre');
  if (empresaId) q = q.eq('id', empresaId);
  const { data, error } = await q;
  if (error) throw error;
  return data || [];
}

export async function fetchAgentsList(empresaId?: number) {
  let q = supabase.from('agent_config').select('id, name, empresa_id').order('name');
  if (empresaId) q = q.eq('empresa_id', empresaId);
  const { data, error } = await q;
  if (error) throw error;
  return (data || []).map((a) => ({ id: String(a.id), name: a.name }));
}
