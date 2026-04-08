
export type ViewState =
  | 'overview'
  | 'create-agents'
  | 'empresas'
  | 'agents'
  | 'test-call'
  | 'campaigns'
  | 'automation'
  | 'models'
  | 'telephony'
  | 'tools'
  | 'files'
  | 'developers'
  | 'usage'
  | 'results'
  | 'admin'
  | 'assistant'
  | 'profile';

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
  /** Call credits balance. Each completed call deducts 1 credit. 0 = campaigns paused. */
  creditos_llamadas?: number | null;
  created_at?: string;
  updated_at?: string;
}

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
  company_context?: string;
  enthusiasm_level?: 'Bajo' | 'Normal' | 'Alto' | 'Extremo' | string;
  voice_id?: string;
  speaking_speed?: number;
  created_at?: string;
  updated_at?: string;
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

export interface VoiceAgent {
  id: string;
  name: string;
  callType: 'Inbound' | 'Outbound';
  useCase: string;
  description: string;
}

export interface TelephonyConfig {
  provider: string;
  fromNumbers: string;
}

export interface ModelConfig {
  llmProvider: string;
  voiceProvider: string;
  transcriberProvider: string;
  embeddingProvider: string;
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
  { key: 'ai_prompt_generator', label: 'Generador de Agentes AI (Extra)' },
  { key: 'premium_voice', label: 'Voz Ausarta (Acceso Premium)' },
];

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
  datos_extra?: Record<string, any> | null;
  customer_name?: string | null;
  empresa_name?: string | null;
  recording_url?: string | null;
}

// Mapeo canónico de disposición para gráficos
export type CallDisposition = 'completed' | 'incomplete' | 'rejected' | 'failed' | 'pending';

export function getCallDisposition(status: string | null): CallDisposition {
  if (!status) return 'pending';
  const s = status.toLowerCase();
  if (s === 'completada' || s === 'completed') return 'completed';
  if (s === 'parcial' || s === 'incomplete') return 'incomplete';
  if (s === 'rechazada' || s === 'rejected_opt_out' || s === 'rejected') return 'rejected';
  if (s === 'fallida' || s === 'failed' || s === 'no_contesta' || s === 'unreached') return 'failed';
  return 'pending';
}

