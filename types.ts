
export type ViewState =
  | 'overview'
  | 'create-agents'
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
  | 'admin';

export type UserRole = 'superadmin' | 'admin' | 'user';

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
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
  greeting: string;
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
  { key: 'create-agents', label: 'Crear Agentes' },
  { key: 'test-call', label: 'Llamada Prueba' },
  { key: 'campaigns', label: 'Campañas' },
  { key: 'models', label: 'AI Models' },
  { key: 'telephony', label: 'Telefonía' },
  { key: 'results', label: 'Resultados' },
  { key: 'usage', label: 'Uso' },
];
