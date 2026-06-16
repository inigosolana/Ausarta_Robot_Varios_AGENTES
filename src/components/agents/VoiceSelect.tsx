import React, { useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { fetchVoices, getVoiceMeta, groupVoicesByGroup, type VoiceOption } from '../../lib/voicesApi';
import { AUSARTA_FEMALE_VOICE_ID } from '../../lib/agentVoiceOptions';

type VoiceChangeMeta = {
  tts_model?: string;
  speaking_speed?: number;
};

type Props = {
  value: string;
  onChange: (voiceId: string, meta?: VoiceChangeMeta) => void;
  languageFilter?: string;
  className?: string;
  disabled?: boolean;
};

export const VoiceSelect: React.FC<Props> = ({
  value,
  onChange,
  languageFilter,
  className = '',
  disabled = false,
}) => {
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchVoices(languageFilter)
      .then((data) => {
        if (!cancelled) {
          setVoices(data.voices);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Error cargando voces');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [languageFilter]);

  const grouped = useMemo(() => groupVoicesByGroup(voices), [voices]);

  const handleChange = (voiceId: string) => {
    const meta = getVoiceMeta(voices, voiceId);
    onChange(voiceId, {
      tts_model: meta?.recommended_tts_model || undefined,
      speaking_speed: meta?.recommended_speaking_speed ?? undefined,
    });
  };

  if (loading) {
    return (
      <div className={`flex items-center gap-2 text-sm text-gray-500 ${className}`}>
        <Loader2 className="h-4 w-4 animate-spin" />
        Cargando voces…
      </div>
    );
  }

  if (error && voices.length === 0) {
    return (
      <select
        value={value || AUSARTA_FEMALE_VOICE_ID}
        onChange={(e) => onChange(e.target.value)}
        className={className}
        disabled={disabled}
      >
        <option value={AUSARTA_FEMALE_VOICE_ID}>Inés (fallback)</option>
      </select>
    );
  }

  return (
    <select
      value={value}
      onChange={(e) => handleChange(e.target.value)}
      className={className}
      disabled={disabled}
    >
      {Object.entries(grouped).map(([group, items]) => (
        <optgroup key={group} label={group}>
          {items.map((voice) => (
            <option key={voice.id} value={voice.id}>
              {voice.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
};

export function getVoiceLabel(voices: VoiceOption[], voiceId?: string | null): string {
  if (!voiceId) return '—';
  const found = voices.find((v) => v.id === voiceId);
  return found?.label || voiceId;
}
