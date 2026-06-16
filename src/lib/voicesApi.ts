import { apiFetch } from './apiFetch';

export interface VoiceOption {
  id: string;
  name: string;
  label: string;
  language: string;
  group: string;
  gender?: string | null;
  recommended_tts_model?: string | null;
  recommended_speaking_speed?: number | null;
  source?: string;
}

export interface VoicesResponse {
  voices: VoiceOption[];
  source: string;
  default_voice_id: string;
  count: number;
}

export async function fetchVoices(language?: string): Promise<VoicesResponse> {
  const params = language ? `?language=${encodeURIComponent(language)}` : '';
  const res = await apiFetch(`/api/voices${params}`);
  if (!res.ok) {
    throw new Error(`No se pudieron cargar las voces (${res.status})`);
  }
  return res.json();
}

export function groupVoicesByGroup(voices: VoiceOption[]): Record<string, VoiceOption[]> {
  return voices.reduce<Record<string, VoiceOption[]>>((acc, voice) => {
    const group = voice.group || 'Otros';
    if (!acc[group]) acc[group] = [];
    acc[group].push(voice);
    return acc;
  }, {});
}

export function getVoiceMeta(voices: VoiceOption[], voiceId: string): VoiceOption | undefined {
  return voices.find((v) => v.id === voiceId);
}
