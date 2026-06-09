export const AUSARTA_FEMALE_VOICE_ID = 'b5aa8098-49ef-475d-89b0-c9262ecf33fd';

/** Debe coincidir con ALLOWED_AGENT_TYPES en backend/routers/agents.py */
export const TIPO_RESULTADOS_OPTIONS = [
  { value: 'ENCUESTA_NUMERICA', label: 'Encuesta numérica', group: 'Encuestas' },
  { value: 'ENCUESTA_MIXTA', label: 'Encuesta mixta', group: 'Encuestas' },
  { value: 'PREGUNTAS_ABIERTAS', label: 'Preguntas abiertas', group: 'Encuestas' },
  { value: 'CUALIFICACION_LEAD', label: 'Cualificación lead', group: 'Comercial' },
  { value: 'AGENDAMIENTO_CITA', label: 'Agendamiento cita', group: 'Comercial' },
  { value: 'SOPORTE_CLIENTE', label: 'Soporte cliente', group: 'Atención' },
] as const;

export type TipoResultadosValue = (typeof TIPO_RESULTADOS_OPTIONS)[number]['value'];

export const TIPO_RESULTADOS_GROUPS = ['Encuestas', 'Comercial', 'Atención'] as const;

export function getTipoResultadosLabel(value?: string | null): string {
  if (!value) return '—';
  const found = TIPO_RESULTADOS_OPTIONS.find(o => o.value === value);
  return found?.label ?? value.replace(/_/g, ' ');
}

export const ENTHUSIASM_LEVELS = ['Bajo', 'Normal', 'Alto', 'Extremo'] as const;

export type AgentCallDirection = 'inbound' | 'outbound';

export function getAgentCallDirection(agent: {
  name?: string;
  use_case?: string;
  description?: string;
  agent_type?: string;
  tipo_resultados?: string;
}): AgentCallDirection | null {
  const tipo = String(agent.agent_type || agent.tipo_resultados || '').toUpperCase();
  if (tipo === 'SOPORTE_CLIENTE') return 'inbound';

  const haystack = [agent.name, agent.use_case, agent.description, agent.agent_type, agent.tipo_resultados]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  if (/\binbound\b/.test(haystack) || /\bentrante/.test(haystack) || /\brecepcion/.test(haystack)) {
    return 'inbound';
  }
  if (/\boutbound\b/.test(haystack) || /\bsaliente/.test(haystack)) return 'outbound';
  return null;
}
