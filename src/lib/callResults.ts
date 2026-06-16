import type { SurveyResult } from '../types';

export type CallResultItemType = 'number' | 'text' | 'choice';

export interface CallResultItem {
  label: string;
  value: unknown;
  type: CallResultItemType;
}

function prettifyKey(raw: string): string {
  return raw
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function isLikelyChoice(value: unknown): boolean {
  if (typeof value !== 'string') return false;
  const v = value.trim().toLowerCase();
  const choices = [
    'comercial', 'tecnico', 'técnico', 'calidad-precio', 'calidad precio',
    'servicio', 'servicio general', 'si', 'sí', 'no',
  ];
  return choices.includes(v);
}

function inferType(value: unknown): CallResultItemType {
  if (typeof value === 'number') return 'number';
  if (isLikelyChoice(value)) return 'choice';
  return 'text';
}

/** Extrae ítems legibles desde agent_results JSON (prioridad sobre columnas legacy). */
export function extractCallResultItems(row: SurveyResult): CallResultItem[] {
  const items: CallResultItem[] = [];
  const seen = new Set<string>();

  const add = (label: string, value: unknown, type?: CallResultItemType) => {
    const key = `${label}:${String(value)}`;
    if (value === null || value === undefined || value === '' || seen.has(key)) return;
    seen.add(key);
    items.push({ label, value, type: type ?? inferType(value) });
  };

  const ar = row.agent_results;
  if (ar && typeof ar === 'object') {
    const scores = ar.scores && typeof ar.scores === 'object' ? ar.scores : {};
    const notes = ar.notes && typeof ar.notes === 'object' ? ar.notes : {};
    const extracted = ar.extracted && typeof ar.extracted === 'object' ? ar.extracted : {};
    const analysis = ar.analysis && typeof ar.analysis === 'object' ? ar.analysis : {};

    if (scores.comercial != null) add('Comercial', scores.comercial, 'number');
    if (scores.instalador != null) add('Instalador', scores.instalador, 'number');
    if (scores.rapidez != null) add('Rapidez', scores.rapidez, 'number');

    Object.entries(notes).forEach(([k, v]) => add(prettifyKey(k), v));
    Object.entries(extracted).forEach(([k, v]) => {
      if (Array.isArray(v) || (v && typeof v === 'object')) return;
      add(prettifyKey(k), v);
    });
    if (analysis.sentimiento) add('Sentimiento', analysis.sentimiento, 'choice');
    if (analysis.idioma) add('Idioma', analysis.idioma, 'text');

    if (items.length > 0) return items;
  }

  const extra: Record<string, unknown> =
    row.datos_extra && typeof row.datos_extra === 'object' ? row.datos_extra : {};

  add('Comercial', row.puntuacion_comercial ?? extra.nota_comercial, 'number');
  add('Instalador', row.puntuacion_instalador ?? extra.nota_instalador, 'number');
  add('Rapidez', row.puntuacion_rapidez ?? extra.nota_rapidez, 'number');
  if (row.comentarios) add('Comentarios', row.comentarios, 'text');

  return items;
}

export function getCallAgentType(row: SurveyResult): string | null {
  return row.agent_type || row.tipo_resultados || row.agent_results?.agent_type || null;
}
