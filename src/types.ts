
export type UserRole = 'superadmin' | 'admin' | 'user';

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  empresa_id?: number | null;
  empresas?: Empresa | null;
  position?: string;
  created_by: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserPermission {
  id: number;
  user_id: string;
  module: string;
  enabled: boolean;
  granted_by: string | null;
  created_at: string;
}
export interface Empresa {
  id?: number;
  nombre: string;
  responsable: string;
  max_admins?: number;
  enabled_modules?: string[];
  crm_type?: string | null;
  crm_webhook_url?: string | null;
  /** Generic automation webhook (Zapier, Make, custom). Separate from CRM-specific crm_webhook_url. */
  webhook_url?: string | null;
  /** Public URL of the company logo stored in Supabase Storage. */
  logo_url?: string | null;
  created_at?: string;
  updated_at?: string;
  sip_outbound_trunk_id?: string | null;
  sip_inbound_trunk_id?: string | null;
  kb_allow_internet_search?: boolean;
}

// ── Workflow types ──────────────────────────────────────────────────────────

export type AgentMode = 'prompt' | 'workflow' | 'mixed';

export type WorkflowNodeType =
  | 'message'
  | 'question'
  | 'condition'
  | 'llm_free'
  | 'transfer'
  | 'end';

export interface WorkflowNodePosition {
  x: number;
  y: number;
}

export interface WorkflowNode {
  id: string;
  type: WorkflowNodeType;
  label: string;
  content?: string;
  prompt?: string;       // sub-prompt para nodo llm_free en modo mixed
  variable?: string;     // nombre de variable donde guardar respuesta
  options?: string[];    // opciones de respuesta (tipo question)
  position?: WorkflowNodePosition;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  condition?: string | null;  // null / undefined → default
}

export interface WorkflowDefinition {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  start_node: string;
}

// ── AgentConfig ─────────────────────────────────────────────────────────────

export interface AgentConfig {
  id?: number;
  empresa_id?: number | null;
  name: string;
  use_case: string;
  description: string;
  instructions: string;
  critical_rules?: string;
  greeting: string;
  tipo_resultados?: string;
  agent_type?: string;
  company_context?: string;
  /** true = KB agente + KB empresa + internet (si la empresa lo permite) */
  kb_allow_internet_search?: boolean;
  enthusiasm_level?: 'Bajo' | 'Normal' | 'Alto' | 'Extremo' | string;
  voice_id?: string;
  speaking_speed?: number;
  created_at?: string;
  updated_at?: string;
  // Workflow fields
  agent_mode?: AgentMode;
  workflow_definition?: WorkflowDefinition | null;
  workflow_variables?: Record<string, string | null>;
}

export interface AIConfig {
  id?: number;
  agent_id: number;
  llm_provider: string;
  llm_model: string;
  tts_provider: string;
  tts_model: string;
  tts_voice: string;
  stt_provider: string;
  stt_model: string;
  language: string;
}

export interface ExtractionSchemaProperty {
  key: string;
  type: 'boolean' | 'number' | 'text' | 'enum' | string;
  label: string;
  options?: string[];
}

export interface Campaign {
  id: number;
  name: string;
  agent_id: number;
  status: 'pending' | 'running' | 'completed' | 'paused';
  scheduled_time: string | null;
  retries_count: number;
  retry_interval: number;
  created_at: string;
  total_leads?: number;
  called_leads?: number;
  failed_leads?: number;
  pending_leads?: number;
  extraction_schema?: ExtractionSchemaProperty[];
}

// All available modules for permission system
export const ALL_MODULES: { key: string; label: string }[] = [
  { key: 'overview', label: 'Dashboard' },
  { key: 'empresas', label: 'Empresas' },
  { key: 'agents', label: 'Agentes' },
  { key: 'test-call', label: 'Llamada Prueba' },
  { key: 'campaigns', label: 'Campañas' },
  { key: 'models', label: 'AI Models' },
  { key: 'telephony', label: 'Telefonía' },
  { key: 'results', label: 'Resultados' },
  { key: 'usage', label: 'Uso' },
  { key: 'assistant', label: 'Ausarta Copilot' },
  { key: 'admin', label: 'Usuarios' },
  { key: 'crm', label: 'CRM Integration' },
  { key: 'contacts', label: 'Contactos' },
  { key: 'ai_prompt_generator', label: 'Generador de Agentes AI (Extra)' },
  { key: 'premium_voice', label: 'Voz Ausarta (Acceso Premium)' },
];

export type Sentimiento = 'Positivo' | 'Neutral' | 'Negativo';

/** Campos comunes presentes en datos_extra tras el post-procesamiento de llamada. */
export interface DatosExtraBase {
  sentimiento_cliente?: Sentimiento | string;
  idioma?: string;
  resumen_narrativo?: string;
  telefono?: string;
  /** Campos dinámicos del extraction_schema o del analizador LLM. */
  [key: string]: unknown;
}

/** Campos específicos del agente SOPORTE_CLIENTE. */
export interface DatosExtraSoporte extends DatosExtraBase {
  motivo_llamada?: string;
  resolucion?: string;
  puntos_clave?: string[];
}

/** Campos específicos del agente CUALIFICACION_LEAD. */
export interface DatosExtraCualificacion extends DatosExtraBase {
  lead_cualificado?: boolean;
  interes?: 'alto' | 'medio' | 'bajo' | string;
  motivo_rechazo?: string | null;
}

/** Campos específicos del agente AGENDAMIENTO_CITA. */
export interface DatosExtraAgendamiento extends DatosExtraBase {
  cita_agendada?: boolean;
  fecha_cita?: string | null;
  disponibilidad?: string | null;
}

export type DatosExtra =
  | DatosExtraBase
  | DatosExtraSoporte
  | DatosExtraCualificacion
  | DatosExtraAgendamiento;

export interface AgentCallResults {
  schema_version?: number;
  agent_type?: string;
  scores?: Record<string, number | null>;
  notes?: Record<string, unknown>;
  extracted?: Record<string, unknown>;
  analysis?: Record<string, unknown>;
}

export interface SurveyResult {
  id: number;
  telefono: string;
  campaign_name?: string;
  fecha: string;
  completada: number;
  status: string | null;
  puntuacion_comercial: number | null;
  puntuacion_instalador: number | null;
  puntuacion_rapidez: number | null;
  comentarios: string | null;
  transcription: string | null;
  llm_model: string | null;
  seconds_used?: number | null;
  tipo_resultados?: string | null;
  agent_type?: string | null;
  agent_results?: AgentCallResults | null;
  datos_extra?: DatosExtra | null;
  customer_name?: string | null;
  empresa_name?: string | null;
  recording_url?: string | null;
  ai_analysis_done?: boolean | null;
  comentarios_ai?: string | null;
}

export function getSentimiento(r: SurveyResult): Sentimiento {
  const val = r.datos_extra?.sentimiento_cliente;
  if (val === 'Positivo' || val === 'Neutral' || val === 'Negativo') return val;
  return 'Neutral';
}

export function getIdioma(r: SurveyResult): string | null {
  return r.datos_extra?.idioma ?? null;
}

/** Puntuación de ira del cliente (1–10) desde agent_results o datos_extra. */
export function getCustomerAngerScore(r: SurveyResult): number | null {
  const fromAnalysis = r.agent_results?.analysis?.customer_anger_score;
  if (typeof fromAnalysis === 'number' && !Number.isNaN(fromAnalysis)) return fromAnalysis;
  const fromExtra = r.datos_extra?.customer_anger_score;
  if (typeof fromExtra === 'number' && !Number.isNaN(fromExtra)) return fromExtra;
  return null;
}

/** Alerta roja B2B: cliente requiere atención humana urgente. */
export function requiresUrgentHumanAttention(r: SurveyResult): boolean {
  const fromAnalysis = r.agent_results?.analysis?.requires_urgent_human_attention;
  if (typeof fromAnalysis === 'boolean') return fromAnalysis;
  return Boolean(r.datos_extra?.requires_urgent_human_attention);
}

// Mapeo canónico de disposición para gráficos (usa los nombres del backend)
export type CallDisposition = 'completed' | 'incomplete' | 'rejected_opt_out' | 'failed' | 'unreached' | 'pending';

/** Sala LiveKit activa (métricas admin). */
export interface LiveCallRoomMetric {
  sid: string;
  name: string;
  num_participants: number;
  created_at: number;
  created_at_iso?: string | null;
}

export interface LiveCallsMetricsResponse {
  total: number;
  rooms: LiveCallRoomMetric[];
}

/** Métricas Redis para el panel de administración. */
export interface RedisMetricsResponse {
  memory_used: string;
  memory_peak: string;
  connected_clients: number;
  ops_per_second: number;
  uptime_days: number;
}

export function getCallDisposition(status: string | null): CallDisposition {
  if (!status) return 'pending';
  const s = status.toLowerCase();
  if (s === 'completada' || s === 'completed') return 'completed';
  if (s === 'parcial' || s === 'incomplete') return 'incomplete';
  if (s === 'rechazada' || s === 'rejected' || s === 'rejected_opt_out') return 'rejected_opt_out';
  if (s === 'unreached' || s === 'no_contesta') return 'unreached';
  if (s === 'fallida' || s === 'failed') return 'failed';
  return 'pending';
}

