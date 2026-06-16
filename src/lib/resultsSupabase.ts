import { supabase } from './supabase';
import type { SurveyResult } from '../types';

export interface ResultsFilters {
  empresaId?: number | 'all';
  agentId?: number;
  campaignId?: number;
  startDate?: string;
  endDate?: string;
}

const RESULT_COLUMNS =
  'id, telefono, fecha, completada, status, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, comentarios, transcription, seconds_used, tipo_resultados, agent_type, agent_results, datos_extra, campaign_name, empresa_id, campaign_id, agent_id';

export async function fetchSurveyResults(filters: ResultsFilters): Promise<SurveyResult[]> {
  let q = supabase.from('encuestas').select(RESULT_COLUMNS).order('fecha', { ascending: false }).limit(5000);

  if (filters.empresaId && filters.empresaId !== 'all') {
    q = q.eq('empresa_id', filters.empresaId);
  }
  if (filters.agentId) q = q.eq('agent_id', filters.agentId);
  if (filters.campaignId) q = q.eq('campaign_id', filters.campaignId);
  if (filters.startDate) q = q.gte('fecha', filters.startDate);
  if (filters.endDate) q = q.lte('fecha', filters.endDate);

  const { data, error } = await q;
  if (error) throw error;
  return (data as SurveyResult[]) || [];
}
