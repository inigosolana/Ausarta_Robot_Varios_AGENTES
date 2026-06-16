import { useEffect, useMemo, useState } from 'react';
import { supabase } from '../lib/supabase';
import { SurveyResult } from '../types';

const COMPLETED_STATUSES = new Set(['completed', 'completada']);
const COST_PER_SECOND = Number((import.meta as any).env.VITE_COST_PER_SECOND_EUR) || 0.002;

export interface DailyCallPoint {
  date: string;
  label: string;
  calls: number;
}

export interface AnalyticsMetrics {
  totalCalls: number;
  totalMinutes: number;
  successRate: number;
  estimatedCostEur: number;
  dailySeries: DailyCallPoint[];
  rows: SurveyResult[];
}

function formatDayLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' });
}

function buildDailySeries(rows: SurveyResult[]): DailyCallPoint[] {
  const days: DailyCallPoint[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  for (let i = 6; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    days.push({ date: key, label: formatDayLabel(d.toISOString()), calls: 0 });
  }

  const index = new Map(days.map((d, i) => [d.date, i]));
  rows.forEach((r) => {
    if (!r.fecha) return;
    const key = new Date(r.fecha).toISOString().slice(0, 10);
    const idx = index.get(key);
    if (idx !== undefined) days[idx].calls += 1;
  });

  return days;
}

export function useAnalyticsFromSupabase(filters: {
  empresaId?: number | 'all';
  agentId?: number;
  campaignId?: number;
  enabled?: boolean;
}) {
  const [rows, setRows] = useState<SurveyResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const enabled = filters.enabled !== false;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        let query = supabase
          .from('encuestas')
          .select(
            'id, telefono, fecha, completada, status, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, comentarios, transcription, seconds_used, tipo_resultados, agent_type, agent_results, datos_extra, campaign_name, empresa_id, campaign_id, agent_id'
          )
          .order('fecha', { ascending: false })
          .limit(5000);

        if (filters.campaignId) query = query.eq('campaign_id', filters.campaignId);
        if (filters.agentId) query = query.eq('agent_id', filters.agentId);
        if (filters.empresaId && filters.empresaId !== 'all') {
          query = query.eq('empresa_id', filters.empresaId);
        }

        const { data, error: sbError } = await query;
        if (sbError) throw sbError;
        if (!cancelled) setRows((data as SurveyResult[]) || []);
      } catch (e: unknown) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Error loading analytics');
          setRows([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => { cancelled = true; };
  }, [enabled, filters.empresaId, filters.agentId, filters.campaignId]);

  const metrics: AnalyticsMetrics = useMemo(() => {
    const totalCalls = rows.length;
    const completed = rows.filter((r) => COMPLETED_STATUSES.has((r.status || '').toLowerCase())).length;
    const totalSeconds = rows.reduce((s, r) => s + (r.seconds_used || 0), 0);
    const totalMinutes = Math.round(totalSeconds / 60);
    const successRate = totalCalls > 0 ? Math.round((completed / totalCalls) * 100) : 0;
    const estimatedCostEur = Math.round(totalSeconds * COST_PER_SECOND * 100) / 100;

    return {
      totalCalls,
      totalMinutes,
      successRate,
      estimatedCostEur,
      dailySeries: buildDailySeries(rows),
      rows,
    };
  }, [rows]);

  return { metrics, loading, error, rows };
}
