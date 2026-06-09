export const AUSARTA_FEMALE_VOICE_ID = 'b5aa8098-49ef-475d-89b0-c9262ecf33fd';

export const TIPO_RESULTADOS_OPTIONS = [
  { value: 'ENCUESTA_NUMERICA', label: 'Encuesta numérica' },
  { value: 'ENCUESTA_MIXTA', label: 'Encuesta mixta' },
  { value: 'CUALIFICACION_LEAD', label: 'Cualificación lead' },
  { value: 'AGENDAMIENTO_CITA', label: 'Agendamiento cita' },
  { value: 'SOPORTE_CLIENTE', label: 'Soporte cliente' },
] as const;

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
