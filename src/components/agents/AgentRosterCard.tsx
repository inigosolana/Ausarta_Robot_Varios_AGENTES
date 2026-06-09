import React from 'react';
import { ChevronRight } from 'lucide-react';
import type { AgentConfig, AIConfig, Empresa } from '../../types';
import { getAgentCallDirection } from '../../lib/agentVoiceOptions';

type AgentRow = AgentConfig & { ai_config?: AIConfig; empresas?: Empresa };

function MaterialIcon({ name, className = '' }: { name: string; className?: string }) {
  return <span className={`material-symbols-outlined text-lg ${className}`}>{name}</span>;
}

const DIRECTION_STYLES = {
  inbound: {
    card: 'agent-roster-card--inbound',
    glow: 'bg-violet-500/15',
    avatarBorder: 'border-violet-500/35',
    avatarIcon: 'text-violet-600 dark:text-violet-400',
    pulse: 'border-violet-400',
    badge: 'border-violet-500/25 bg-violet-500/10 text-violet-700 dark:text-violet-300',
    icon: 'call_received',
    label: 'Inbound',
  },
  outbound: {
    card: 'agent-roster-card--outbound',
    glow: 'bg-amber-500/15',
    avatarBorder: 'border-amber-500/35',
    avatarIcon: 'text-amber-600 dark:text-amber-400',
    pulse: 'border-amber-400',
    badge: 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300',
    icon: 'call_made',
    label: 'Outbound',
  },
} as const;

type Props = {
  agent: AgentRow;
  selected: boolean;
  onClick: () => void;
};

export const AgentRosterCard: React.FC<Props> = ({ agent, selected, onClick }) => {
  const lang = (agent.ai_config?.language || 'es').toUpperCase();
  const useCase = agent.use_case || agent.tipo_resultados?.replace(/_/g, ' ') || 'General';
  const isActive = true;
  const direction = getAgentCallDirection(agent);
  const dirStyle = direction ? DIRECTION_STYLES[direction] : null;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`agent-roster-card relative w-full overflow-hidden rounded-xl p-4 text-left ${dirStyle?.card ?? ''} ${selected ? 'selected' : ''}`}
    >
      {selected && (
        <div className={`pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full blur-xl ${dirStyle?.glow ?? 'bg-cyan-500/15'}`} />
      )}
      <div className="relative z-10 flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          <div
            className={`relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full border bg-gray-100 dark:bg-gray-900 ${
              dirStyle?.avatarBorder ?? 'border-cyan-500/30'
            }`}
          >
            {selected && isActive && (
              <div className={`absolute inset-0 rounded-full border agent-pulse-ring ${dirStyle?.pulse ?? 'border-cyan-400'}`} />
            )}
            <MaterialIcon
              name={dirStyle?.icon ?? 'face_4'}
              className={dirStyle?.avatarIcon ?? 'text-cyan-500 dark:text-cyan-400'}
            />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-gray-900 dark:text-white">{agent.name}</h3>
            <div className="mt-1 flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${isActive ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]' : 'bg-gray-400'}`} />
              <span className="agent-mono text-[10px] uppercase text-gray-500 dark:text-gray-400">
                {isActive ? 'Online' : 'Idle'} · {useCase}
              </span>
            </div>
          </div>
        </div>
        <ChevronRight size={18} className="shrink-0 text-gray-400 group-hover:text-cyan-500" />
      </div>
      <div className="relative z-10 mt-3 flex flex-wrap gap-2">
        {direction && dirStyle && (
          <span className={`agent-mono rounded border px-2 py-0.5 text-[10px] font-semibold uppercase ${dirStyle.badge}`}>
            {dirStyle.label}
          </span>
        )}
        <span className="agent-mono rounded border border-cyan-500/20 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-700 dark:text-cyan-300">
          {lang}
        </span>
        {agent.empresas?.nombre && (
          <span className="agent-mono rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] text-gray-600 dark:border-white/10 dark:bg-gray-800 dark:text-gray-400">
            {agent.empresas.nombre}
          </span>
        )}
        {agent.enthusiasm_level && (
          <span className="agent-mono rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] text-gray-600 dark:border-white/10 dark:bg-gray-800 dark:text-gray-400">
            {agent.enthusiasm_level}
          </span>
        )}
      </div>
    </button>
  );
};
