import React, { useState, useEffect, useCallback } from 'react';
import { Phone, Trash2, Loader2, Save, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../contexts/AuthContext';
import type { AgentConfig, AIConfig, Empresa } from '../../types';
import {
  AUSARTA_FEMALE_VOICE_ID,
  TIPO_RESULTADOS_GROUPS,
  TIPO_RESULTADOS_OPTIONS,
  getTipoResultadosLabel,
  ENTHUSIASM_LEVELS,
  getAgentCallDirection,
} from '../../lib/agentVoiceOptions';
import { AgentKnowledgeDocs } from './AgentKnowledgeDocs';

type AgentRow = AgentConfig & { ai_config?: AIConfig; empresas?: Empresa };

const defaultAIConfig: AIConfig = {
  agent_id: 0,
  llm_provider: 'groq',
  llm_model: 'llama-3.3-70b-versatile',
  tts_provider: 'cartesia',
  tts_model: 'sonic-multilingual',
  tts_voice: AUSARTA_FEMALE_VOICE_ID,
  stt_provider: 'deepgram',
  stt_model: 'nova-2',
  language: 'es',
};

function MaterialIcon({ name, className = '' }: { name: string; className?: string }) {
  return <span className={`material-symbols-outlined ${className}`}>{name}</span>;
}

type Tab = 'knowledge' | 'personality' | 'voice';

type Props = {
  agent: AgentRow;
  onTest: () => void;
  onDelete: () => void;
  onSaved: () => void;
};

function agentToForm(agent: AgentRow): AgentConfig {
  return {
    name: agent.name || '',
    use_case: agent.use_case || '',
    description: agent.description || '',
    instructions: agent.instructions || '',
    critical_rules: agent.critical_rules || '',
    greeting: agent.greeting || '',
    enthusiasm_level: agent.enthusiasm_level || 'Normal',
    voice_id: agent.voice_id || agent.ai_config?.tts_voice || '',
    speaking_speed: agent.speaking_speed ?? 1.0,
    empresa_id: agent.empresa_id ?? null,
    tipo_resultados: agent.tipo_resultados,
    agent_mode: agent.agent_mode,
    workflow_definition: agent.workflow_definition,
  };
}

export const AgentWorkspacePanel: React.FC<Props> = ({ agent, onTest, onDelete, onSaved }) => {
  const { t } = useTranslation();
  const { isPlatformOwner } = useAuth();

  const [tab, setTab] = useState<Tab>('knowledge');
  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState<AgentConfig>(() => agentToForm(agent));
  const [aiConfig, setAiConfig] = useState<AIConfig>({ ...defaultAIConfig, ...(agent.ai_config || {}) });
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingConfig, setIsLoadingConfig] = useState(false);

  const resetForm = useCallback(() => {
    setFormData(agentToForm(agent));
    setAiConfig({ ...defaultAIConfig, ...(agent.ai_config || {}) });
    setIsEditing(false);
  }, [agent]);

  useEffect(() => {
    resetForm();
    setTab('knowledge');
  }, [agent.id, resetForm]);

  useEffect(() => {
    if (!agent.id) return;
    let cancelled = false;
    (async () => {
      setIsLoadingConfig(true);
      try {
        const API_URL = (import.meta as any).env.VITE_API_URL || '';
        const qs = agent.empresa_id ? `?empresa_id=${agent.empresa_id}` : '';
        const resp = await fetch(`${API_URL}/api/agent_config_by_agent/${agent.id}${qs}`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (cancelled) return;
        const loadedAi: AIConfig = {
          ...defaultAIConfig,
          agent_id: Number(agent.id),
          llm_model: data.llm_model || defaultAIConfig.llm_model,
          tts_voice: data.voice_id || defaultAIConfig.tts_voice,
          tts_model: data.tts_model || defaultAIConfig.tts_model,
          stt_provider: data.stt_provider || defaultAIConfig.stt_provider,
          stt_model: data.stt_model || defaultAIConfig.stt_model,
          language: data.language || defaultAIConfig.language,
        };
        setAiConfig(loadedAi);
        setFormData(prev => ({
          ...prev,
          voice_id: prev.voice_id || data.voice_id || '',
          greeting: data.greeting ?? prev.greeting,
          instructions: data.instructions ?? prev.instructions,
          critical_rules: data.critical_rules ?? prev.critical_rules,
          enthusiasm_level: data.enthusiasm_level ?? prev.enthusiasm_level,
          speaking_speed: data.speaking_speed ?? prev.speaking_speed,
        }));
      } catch (err) {
        console.error('Error loading AI config:', err);
      } finally {
        if (!cancelled) setIsLoadingConfig(false);
      }
    })();
    return () => { cancelled = true; };
  }, [agent.id, agent.empresa_id]);

  const lang = aiConfig.language || agent.ai_config?.language || 'es';
  const model = aiConfig.llm_model || agent.ai_config?.llm_model || 'llama-3.3-70b';

  const tabs: { id: Tab; label: string; icon: string }[] = [
    { id: 'knowledge', label: 'Base de conocimiento', icon: 'psychology' },
    { id: 'personality', label: 'Personalidad', icon: 'tune' },
    { id: 'voice', label: 'Perfil de voz', icon: 'record_voice_over' },
  ];

  const inputCls =
    'w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-900 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500/30 dark:border-gray-700 dark:bg-gray-900/60 dark:text-gray-100';
  const textareaCls = `${inputCls} agent-mono resize-none leading-relaxed`;
  const labelCls = 'agent-mono mb-1.5 block text-xs font-bold uppercase tracking-widest text-gray-500 dark:text-gray-400';

  const handleSave = async () => {
    if (!formData.name?.trim()) {
      alert(t('Agent name is mandatory', 'El nombre del agente es obligatorio'));
      return;
    }
    setIsSaving(true);
    try {
      const API_URL = (import.meta as any).env.VITE_API_URL || '';
      const res = await fetch(`${API_URL}/api/agents/${agent.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...formData,
          ...aiConfig,
          voice_id: formData.voice_id || aiConfig.tts_voice,
          speaking_speed: formData.speaking_speed ?? 1.0,
          tts_voice: formData.voice_id || aiConfig.tts_voice,
          agent_mode: agent.agent_mode || 'prompt',
          workflow_definition: agent.workflow_definition ?? null,
          company_context: undefined,
        }),
      });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.error || 'Error saving agent');
      }
      setIsEditing(false);
      onSaved();
    } catch (err: any) {
      alert(`${t('Error saving', 'Error al guardar')}: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const displayName = isEditing ? formData.name : agent.name;
  const displayLang = lang.toUpperCase();
  const displayEnthusiasm = isEditing ? formData.enthusiasm_level : agent.enthusiasm_level || 'Normal';
  const displaySpeed = isEditing ? formData.speaking_speed : agent.speaking_speed;
  const direction = getAgentCallDirection(agent);
  const headerGlow =
    direction === 'inbound'
      ? 'radial-gradient(circle at top right, #8b5cf6, transparent 60%)'
      : direction === 'outbound'
        ? 'radial-gradient(circle at top right, #f59e0b, transparent 60%)'
        : 'radial-gradient(circle at top right, #06b6d4, transparent 60%)';

  return (
    <div className="flex h-full min-h-[560px] flex-col">
      <div className="agent-glass relative flex-shrink-0 overflow-hidden rounded-t-2xl p-6">
        <div className="pointer-events-none absolute inset-0 opacity-20" style={{ background: headerGlow }} />
        <div className="relative z-10 flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              {isEditing ? (
                <input
                  type="text"
                  value={formData.name}
                  onChange={e => setFormData({ ...formData, name: e.target.value })}
                  className="max-w-xs rounded-lg border border-cyan-500/40 bg-white px-3 py-1.5 text-2xl font-bold text-gray-900 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 dark:bg-gray-900 dark:text-white"
                />
              ) : (
                <h2 className="text-2xl font-bold text-gray-900 dark:text-white">{displayName}</h2>
              )}
              <span className="flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                Activo
              </span>
              {direction === 'inbound' && (
                <span className="rounded-full border border-violet-500/30 bg-violet-500/15 px-2 py-0.5 text-xs font-semibold uppercase text-violet-600 dark:text-violet-400">
                  Inbound
                </span>
              )}
              {direction === 'outbound' && (
                <span className="rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-xs font-semibold uppercase text-amber-600 dark:text-amber-400">
                  Outbound
                </span>
              )}
              {isEditing && (
                <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-xs font-medium text-cyan-600 dark:text-cyan-400">
                  {t('Editing', 'Editando')}
                </span>
              )}
            </div>
            <p className="agent-mono text-sm text-gray-500 dark:text-gray-400">
              ID: AGT-{String(agent.id).padStart(4, '0')} · Modelo: {model} · {displayLang}
            </p>
            {agent.empresas?.nombre && (
              <p className="mt-1 text-sm text-indigo-600 dark:text-indigo-300">{agent.empresas.nombre}</p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {isEditing ? (
              <>
                <button
                  type="button"
                  onClick={resetForm}
                  disabled={isSaving}
                  className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300"
                >
                  <X size={16} />
                  {t('Discard Changes', 'Descartar')}
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={isSaving}
                  className="flex items-center gap-2 rounded-lg bg-cyan-600 px-5 py-2 text-sm font-bold text-white shadow-lg transition-all hover:brightness-110 disabled:opacity-50 dark:bg-cyan-500"
                >
                  {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                  {t('Save Configuration', 'Guardar configuración')}
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={onDelete}
                  className="rounded-lg border border-gray-200 bg-white p-2 text-gray-500 transition-colors hover:border-red-300 hover:text-red-500 dark:border-gray-700 dark:bg-gray-900"
                  title={t('Delete', 'Eliminar')}
                >
                  <Trash2 size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => setIsEditing(true)}
                  className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                >
                  <MaterialIcon name="edit" className="!text-[18px]" />
                  {t('Edit', 'Editar')}
                </button>
                <button
                  type="button"
                  onClick={onTest}
                  className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-bold text-white shadow-lg shadow-indigo-500/25 transition-all hover:brightness-110 dark:bg-indigo-500"
                >
                  <Phone size={16} />
                  {t('Test Agent', 'Probar agente')}
                </button>
              </>
            )}
          </div>
        </div>

        <div className="relative z-10 mt-6 grid grid-cols-3 gap-3">
          {[
            { label: 'Idioma', value: displayLang },
            { label: 'Entusiasmo', value: displayEnthusiasm || 'Normal' },
            { label: 'Velocidad', value: `${(displaySpeed ?? 1).toFixed(2)}x` },
          ].map(m => (
            <div key={m.label} className="rounded-lg border border-gray-100 bg-gray-50/80 p-3 dark:border-white/5 dark:bg-gray-900/40">
              <p className="agent-mono mb-1 text-[10px] uppercase text-gray-500">{m.label}</p>
              <p className="text-lg font-semibold text-gray-900 dark:text-white">{m.value}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="agent-glass flex flex-1 flex-col rounded-b-2xl border-t border-gray-100 dark:border-white/10">
        <div className="flex gap-4 overflow-x-auto border-b border-gray-100 px-4 pt-2 sm:gap-6 sm:px-6 dark:border-white/10">
          {tabs.map(item => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`flex shrink-0 items-center gap-2 px-1 pb-3 text-xs font-medium uppercase tracking-wider transition-colors ${
                tab === item.id
                  ? 'border-b-2 border-cyan-500 text-cyan-600 dark:text-cyan-400'
                  : 'text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'
              }`}
            >
              <MaterialIcon name={item.icon} className="!text-[18px]" />
              {item.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {isLoadingConfig && (
            <div className="mb-4 flex items-center gap-2 text-xs text-gray-400">
              <Loader2 size={14} className="animate-spin" />
              {t('Loading configuration...', 'Cargando configuración...')}
            </div>
          )}

          {tab === 'knowledge' && (
            <div className="space-y-4">
              <div>
                <label className={labelCls}>System Prompt (Directiva)</label>
                <textarea
                  readOnly={!isEditing}
                  value={formData.instructions || ''}
                  onChange={e => setFormData({ ...formData, instructions: e.target.value })}
                  rows={12}
                  placeholder={t('Define the agent instructions...', 'Define las instrucciones del agente...')}
                  className={`${textareaCls} h-64 ${!isEditing ? 'cursor-default opacity-90' : ''}`}
                />
              </div>
              {agent.id && (
                <AgentKnowledgeDocs
                  agentId={Number(agent.id)}
                  empresaId={agent.empresa_id}
                  isEditing={isEditing}
                />
              )}
            </div>
          )}

          {tab === 'personality' && (
            <div className="space-y-4">
              {[
                { key: 'greeting' as const, label: 'Saludo', rows: 2 },
                { key: 'critical_rules' as const, label: 'Reglas críticas', rows: 4 },
                { key: 'use_case' as const, label: 'Caso de uso', rows: 2 },
              ].map(field => (
                <div key={field.key}>
                  <label className={labelCls}>{field.label}</label>
                  {isEditing ? (
                    <textarea
                      value={(formData[field.key] as string) || ''}
                      onChange={e => setFormData({ ...formData, [field.key]: e.target.value })}
                      rows={field.rows}
                      className={textareaCls}
                    />
                  ) : (
                    <p className="text-sm text-gray-600 dark:text-gray-400">{agent[field.key] || '—'}</p>
                  )}
                </div>
              ))}
              <div>
                <label className={labelCls}>Tipo de agente / resultados</label>
                {isEditing ? (
                  <select
                    value={formData.tipo_resultados || ''}
                    onChange={e => setFormData({ ...formData, tipo_resultados: e.target.value || undefined })}
                    className={inputCls}
                  >
                    <option value="">— Selecciona tipo —</option>
                    {TIPO_RESULTADOS_GROUPS.map(group => (
                      <optgroup key={group} label={group}>
                        {TIPO_RESULTADOS_OPTIONS.filter(o => o.group === group).map(opt => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                ) : (
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    {getTipoResultadosLabel(agent.tipo_resultados || agent.agent_type)}
                  </p>
                )}
              </div>
              {isEditing && (
                <div className="grid gap-4 rounded-xl border border-gray-100 bg-gray-50/80 p-4 dark:border-white/5 dark:bg-gray-900/30 sm:grid-cols-2">
                  <div>
                    <div className="mb-2 flex justify-between text-xs text-gray-600 dark:text-gray-400">
                      <span>{t('Enthusiasm', 'Entusiasmo')}</span>
                      <span className="font-bold text-cyan-600">{formData.enthusiasm_level}</span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={3}
                      step={1}
                      value={Math.max(0, ENTHUSIASM_LEVELS.indexOf((formData.enthusiasm_level || 'Normal') as typeof ENTHUSIASM_LEVELS[number]))}
                      onChange={e => setFormData({ ...formData, enthusiasm_level: ENTHUSIASM_LEVELS[Number(e.target.value)] })}
                      className="w-full accent-cyan-500"
                    />
                  </div>
                  <div>
                    <div className="mb-2 flex justify-between text-xs text-gray-600 dark:text-gray-400">
                      <span>{t('Speed', 'Velocidad')}</span>
                      <span className="font-bold text-cyan-600">{(formData.speaking_speed ?? 1).toFixed(2)}x</span>
                    </div>
                    <input
                      type="range"
                      min={0.7}
                      max={1.3}
                      step={0.05}
                      value={formData.speaking_speed ?? 1}
                      onChange={e => setFormData({ ...formData, speaking_speed: Number(e.target.value) })}
                      className="w-full accent-cyan-500"
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'voice' && (
            <div className="space-y-4">
              {isPlatformOwner && (
                <div>
                  <label className={labelCls}>{t('Language', 'Idioma')}</label>
                  {isEditing ? (
                    <select
                      value={aiConfig.language || 'es'}
                      onChange={e => setAiConfig({ ...aiConfig, language: e.target.value })}
                      className={inputCls}
                    >
                      <option value="es">Español</option>
                      <option value="en">English</option>
                      <option value="eu">Euskera</option>
                      <option value="gl">Gallego</option>
                    </select>
                  ) : (
                    <p className="text-sm text-gray-600 dark:text-gray-400">{displayLang}</p>
                  )}
                </div>
              )}
              <div>
                <label className={labelCls}>{t('Select Voice', 'Seleccionar voz')}</label>
                {isEditing ? (
                  <select
                    value={formData.voice_id || aiConfig.tts_voice}
                    onChange={e => {
                      const selectedVoice = e.target.value;
                      const isVozBuena = selectedVoice === 'd4db5fb9-f44b-4bd1-85fa-192e0f0d75f9';
                      setAiConfig({
                        ...aiConfig,
                        tts_voice: selectedVoice,
                        tts_model: isVozBuena ? 'sonic-3' : 'sonic-multilingual',
                      });
                      setFormData({
                        ...formData,
                        voice_id: selectedVoice,
                        speaking_speed: isVozBuena ? 1.15 : formData.speaking_speed,
                      });
                    }}
                    className={inputCls}
                  >
                    <optgroup label="Español">
                      <option value={AUSARTA_FEMALE_VOICE_ID}>Inés (España - Natural)</option>
                      <option value="cefcb124-080b-4655-b31f-932f3ee743de">Raquel (España - Suave)</option>
                      <option value="a2f12ebd-80df-4de7-83f3-809599135b1d">Marta (España - Corporativa)</option>
                      <option value="50074b01-9420-4bf5-905e-3a992665e717">Alba (España - Narrativa)</option>
                      <option value="692cd5ac-7140-49e5-950c-35cd0ebebc12">Javier (España - Hombre)</option>
                      <option value="79a125e3-4d2a-4645-83e3-a618400030f0">Carlos (España - Hombre serio)</option>
                      <option value="d4db5fb9-f44b-4bd1-85fa-192e0f0d75f9">VOZ BUENA</option>
                    </optgroup>
                    <optgroup label="Euskera">
                      <option value="99543693-cf6e-4e1d-9259-2e5cc9a0f76b">Ane (Chica Euskera)</option>
                      <option value="a62209c3-9f0a-4474-9b51-84b191593f49">Ion (Chico Euskera)</option>
                    </optgroup>
                    <optgroup label="Gallego">
                      <option value="96eade6e-d863-4f9a-8b08-5d7b74d1643b">Sabela (Chica Gallega)</option>
                      <option value="4679c1e3-1fd5-45c0-a3a6-7f6e21ef82e2">Brais (Chico Gallego)</option>
                    </optgroup>
                    <optgroup label="Inglés">
                      <option value="62ae83ad-4f6a-430b-af41-a9bede9286ca">Sarah (Chica Inglés)</option>
                      <option value="0ad65e7f-006c-47cf-bd31-52279d487913">Mark (Chico Inglés)</option>
                    </optgroup>
                  </select>
                ) : (
                  <p className="agent-mono text-xs text-gray-600 dark:text-gray-400">
                    {agent.voice_id || agent.ai_config?.tts_voice || '—'}
                  </p>
                )}
              </div>
              {!isEditing && (
                <div className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                  <p><strong className="text-gray-800 dark:text-gray-200">TTS:</strong> {agent.ai_config?.tts_provider || 'cartesia'} / {agent.ai_config?.tts_model || 'sonic'}</p>
                  <p><strong className="text-gray-800 dark:text-gray-200">STT:</strong> {agent.ai_config?.stt_provider || 'deepgram'}</p>
                </div>
              )}
            </div>
          )}

          {!isEditing && (
            <div className="mt-8 flex justify-end border-t border-gray-100 pt-4 dark:border-white/5">
              <button
                type="button"
                onClick={() => setIsEditing(true)}
                className="rounded-lg bg-gray-800 px-5 py-2 text-sm font-medium text-white dark:bg-gray-700"
              >
                {t('Edit configuration', 'Editar configuración')}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
