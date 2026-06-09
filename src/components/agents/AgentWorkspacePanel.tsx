import React, { useState } from 'react';
import { Edit2, Phone, Trash2 } from 'lucide-react';
import type { AgentConfig, AIConfig, Empresa } from '../../types';

type AgentRow = AgentConfig & { ai_config?: AIConfig; empresas?: Empresa };

function MaterialIcon({ name, className = '' }: { name: string; className?: string }) {
  return <span className={`material-symbols-outlined ${className}`}>{name}</span>;
}

type Tab = 'knowledge' | 'personality' | 'voice';

type Props = {
  agent: AgentRow;
  onEdit: () => void;
  onTest: () => void;
  onDelete: () => void;
  t: (key: string, fallback: string) => string;
};

export const AgentWorkspacePanel: React.FC<Props> = ({ agent, onEdit, onTest, onDelete, t }) => {
  const [tab, setTab] = useState<Tab>('knowledge');
  const lang = agent.ai_config?.language || 'es';
  const model = agent.ai_config?.llm_model || 'llama-3.3-70b';

  const tabs: { id: Tab; label: string; icon: string }[] = [
    { id: 'knowledge', label: 'Base de conocimiento', icon: 'psychology' },
    { id: 'personality', label: 'Personalidad', icon: 'tune' },
    { id: 'voice', label: 'Perfil de voz', icon: 'record_voice_over' },
  ];

  return (
    <div className="flex h-full min-h-[560px] flex-col">
      <div className="agent-glass relative flex-shrink-0 overflow-hidden rounded-t-2xl p-6">
        <div className="pointer-events-none absolute inset-0 opacity-20" style={{ background: 'radial-gradient(circle at top right, #06b6d4, transparent 60%)' }} />
        <div className="relative z-10 flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">{agent.name}</h2>
              <span className="flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                Activo
              </span>
            </div>
            <p className="agent-mono text-sm text-gray-500 dark:text-gray-400">
              ID: AGT-{String(agent.id).padStart(4, '0')} · Modelo: {model} · {lang.toUpperCase()}
            </p>
            {agent.empresas?.nombre && (
              <p className="mt-1 text-sm text-indigo-600 dark:text-indigo-300">{agent.empresas.nombre}</p>
            )}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onDelete}
              className="rounded-lg border border-gray-200 bg-white p-2 text-gray-500 transition-colors hover:border-red-300 hover:text-red-500 dark:border-gray-700 dark:bg-gray-900 dark:hover:border-red-800"
              title={t('Delete', 'Eliminar')}
            >
              <Trash2 size={16} />
            </button>
            <button
              type="button"
              onClick={onEdit}
              className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
            >
              <Edit2 size={16} />
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
          </div>
        </div>

        <div className="relative z-10 mt-6 grid grid-cols-3 gap-3">
          {[
            { label: 'Idioma', value: lang.toUpperCase() },
            { label: 'Entusiasmo', value: agent.enthusiasm_level || 'Normal' },
            { label: 'Velocidad', value: `${(agent.speaking_speed ?? 1).toFixed(2)}x` },
          ].map(m => (
            <div key={m.label} className="rounded-lg border border-gray-100 bg-gray-50/80 p-3 dark:border-white/5 dark:bg-gray-900/40">
              <p className="agent-mono mb-1 text-[10px] uppercase text-gray-500">{m.label}</p>
              <p className="text-lg font-semibold text-gray-900 dark:text-white">{m.value}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="agent-glass flex flex-1 flex-col rounded-b-2xl border-t border-gray-100 dark:border-white/10">
        <div className="flex gap-6 border-b border-gray-100 px-6 pt-2 dark:border-white/10">
          {tabs.map(item => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`flex items-center gap-2 px-1 pb-3 text-xs font-medium uppercase tracking-wider transition-colors ${
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
          {tab === 'knowledge' && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <label className="agent-mono text-xs font-bold uppercase tracking-widest text-gray-700 dark:text-gray-300">
                  System Prompt (Directiva)
                </label>
              </div>
              <div className="relative">
                <textarea
                  readOnly
                  value={agent.instructions || agent.description || 'Sin instrucciones configuradas.'}
                  className="agent-mono h-48 w-full resize-none rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm leading-relaxed text-gray-800 dark:border-gray-700 dark:bg-gray-900/60 dark:text-gray-200"
                />
              </div>
              {agent.company_context && (
                <div className="mt-4">
                  <p className="agent-mono mb-2 text-xs font-bold uppercase tracking-widest text-gray-500">Contexto empresa</p>
                  <p className="rounded-lg border border-gray-100 bg-gray-50 p-3 text-sm text-gray-600 line-clamp-4 dark:border-white/5 dark:bg-gray-900/40 dark:text-gray-400">
                    {agent.company_context}
                  </p>
                </div>
              )}
            </div>
          )}

          {tab === 'personality' && (
            <div className="space-y-4 text-sm text-gray-600 dark:text-gray-400">
              <p><strong className="text-gray-800 dark:text-gray-200">Saludo:</strong> {agent.greeting || '—'}</p>
              <p><strong className="text-gray-800 dark:text-gray-200">Reglas críticas:</strong> {agent.critical_rules || '—'}</p>
              <p><strong className="text-gray-800 dark:text-gray-200">Caso de uso:</strong> {agent.use_case || '—'}</p>
              <p><strong className="text-gray-800 dark:text-gray-200">Tipo resultados:</strong> {agent.tipo_resultados || '—'}</p>
            </div>
          )}

          {tab === 'voice' && (
            <div className="space-y-4 text-sm text-gray-600 dark:text-gray-400">
              <p><strong className="text-gray-800 dark:text-gray-200">TTS:</strong> {agent.ai_config?.tts_provider || 'cartesia'} / {agent.ai_config?.tts_model || 'sonic'}</p>
              <p><strong className="text-gray-800 dark:text-gray-200">STT:</strong> {agent.ai_config?.stt_provider || 'deepgram'}</p>
              <p><strong className="text-gray-800 dark:text-gray-200">Voice ID:</strong> <span className="agent-mono text-xs">{agent.voice_id || agent.ai_config?.tts_voice || '—'}</span></p>
            </div>
          )}

          <div className="mt-8 flex justify-end gap-3 border-t border-gray-100 pt-4 dark:border-white/5">
            <button type="button" onClick={onEdit} className="rounded-lg bg-gray-800 px-5 py-2 text-sm font-medium text-white dark:bg-gray-700">
              {t('Edit configuration', 'Editar configuración')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
