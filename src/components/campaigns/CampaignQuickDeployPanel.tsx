import React from 'react';
import { Loader2 } from 'lucide-react';

type Agent = { id: string; name: string };

type Props = {
  agents: Agent[];
  selectedAgent: string;
  onAgentChange: (id: string) => void;
  empresaName?: string | null;
  csvFile: File | null;
  onCsvSelect: (file: File) => void;
  onLaunch: () => void;
  canLaunch: boolean;
  launching?: boolean;
};

function MaterialIcon({ name, className = '' }: { name: string; className?: string }) {
  return <span className={`material-symbols-outlined text-[18px] ${className}`}>{name}</span>;
}

export const CampaignQuickDeployPanel: React.FC<Props> = ({
  agents,
  selectedAgent,
  onAgentChange,
  empresaName,
  csvFile,
  onCsvSelect,
  onLaunch,
  canLaunch,
  launching,
}) => {
  const step2Done = Boolean(csvFile);

  return (
    <div className="camp-glass relative overflow-hidden rounded-xl p-6">
      <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-indigo-500/10 blur-[40px]" />

      <div className="relative z-10 mb-6 flex items-center gap-2 border-b border-gray-200 pb-4 dark:border-gray-700/60">
        <MaterialIcon name="rocket_launch" className="text-indigo-500 dark:text-indigo-300" />
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Despliegue rápido</h3>
      </div>

      <div className="relative z-10 space-y-5">
        <div className="flex gap-4">
          <div className="flex flex-col items-center">
            <div className="flex h-7 w-7 items-center justify-center rounded-full border border-indigo-400/50 bg-indigo-600 text-xs font-medium text-white shadow-md shadow-indigo-500/20">
              1
            </div>
            <div className="mt-1 h-12 w-px bg-gray-200 dark:bg-gray-700" />
          </div>
          <div className="flex-1 pb-2">
            <p className="mb-2 text-sm font-medium text-gray-900 dark:text-white">Perfil del agente</p>
            <select
              value={selectedAgent}
              onChange={e => onAgentChange(e.target.value)}
              className="w-full appearance-none rounded-lg border border-gray-200 bg-white p-2.5 text-sm text-gray-700 shadow-sm transition-all hover:border-gray-300 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-700 dark:bg-gray-900/60 dark:text-gray-200"
            >
              {agents.length === 0 ? (
                <option value="">Sin agentes disponibles</option>
              ) : (
                agents.map(a => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))
              )}
            </select>
            {empresaName && (
              <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">Empresa: {empresaName}</p>
            )}
          </div>
        </div>

        <div className="flex gap-4">
          <div className="flex flex-col items-center">
            <div className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-medium ${
              step2Done
                ? 'border-cyan-500/50 bg-cyan-600 text-white'
                : 'border-gray-200 bg-gray-100 text-gray-400 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-500'
            }`}>
              2
            </div>
            <div className="mt-1 h-12 w-px bg-gray-200 dark:bg-gray-700" />
          </div>
          <div className="flex-1 pb-2">
            <p className="mb-2 text-sm font-medium text-gray-900 dark:text-white">Fuente de contactos</p>
            <label className="group flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-center transition-colors hover:border-cyan-400/50 hover:bg-cyan-50/30 dark:border-gray-700 dark:bg-gray-900/30 dark:hover:bg-gray-800/50">
              <input
                type="file"
                accept=".csv"
                className="hidden"
                onChange={e => {
                  const f = e.target.files?.[0];
                  if (f) onCsvSelect(f);
                }}
              />
              <MaterialIcon name="cloud_upload" className="text-gray-400 transition-colors group-hover:text-cyan-500" />
              <p className="text-xs text-gray-500 transition-colors group-hover:text-gray-700 dark:text-gray-400 dark:group-hover:text-gray-200">
                {csvFile ? csvFile.name : 'Subir CSV o arrastrar aquí'}
              </p>
            </label>
          </div>
        </div>

        <div className={`flex gap-4 ${!step2Done ? 'opacity-50' : ''}`}>
          <div className="flex flex-col items-center">
            <div className="flex h-7 w-7 items-center justify-center rounded-full border border-gray-200 bg-gray-100 text-xs font-medium text-gray-400 dark:border-gray-700 dark:bg-gray-800">
              3
            </div>
          </div>
          <div className="flex-1">
            <p className="mb-1 text-sm font-medium text-gray-900 dark:text-white">Parámetros</p>
            <p className="text-xs text-gray-500 dark:text-gray-500">
              {step2Done ? 'Abre el asistente completo para programar y lanzar.' : 'Esperando archivo CSV…'}
            </p>
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={onLaunch}
        disabled={!canLaunch || launching}
        className={`relative z-10 mt-6 flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-medium transition-colors ${
          canLaunch
            ? 'bg-indigo-600 text-white hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400'
            : 'cursor-not-allowed border border-gray-200 bg-gray-100 text-gray-400 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-500'
        }`}
      >
        {launching ? <Loader2 size={18} className="animate-spin" /> : <MaterialIcon name="rocket_launch" />}
        {launching ? 'Iniciando…' : 'Abrir asistente de campaña'}
      </button>
    </div>
  );
};

export const CampaignTelemetryPanel: React.FC<{
  running: number;
  pending: number;
  completed: number;
  totalLeads: number;
}> = ({ running, pending, completed, totalLeads }) => {
  const loadPct = totalLeads > 0 ? Math.min(100, Math.round((running / Math.max(1, running + pending + completed)) * 100)) : 0;

  return (
    <div className="camp-glass rounded-xl p-5">
      <h3 className="mb-4 flex items-center justify-between text-sm font-medium text-gray-900 dark:text-white">
        <span className="flex items-center gap-2">
          <span className="material-symbols-outlined text-[18px] text-gray-400">dns</span>
          Telemetría
        </span>
        <span className="flex h-4 items-center gap-1">
          {[1, 2, 3, 4, 5].map(n => (
            <span key={n} className="camp-wave-bar" />
          ))}
        </span>
      </h3>
      <div className="space-y-4">
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <span className="camp-mono text-xs text-gray-500 dark:text-gray-400">Campañas activas</span>
            <span className="camp-mono text-xs font-medium text-gray-800 dark:text-white">{running}</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
            <div
              className="h-full rounded-full bg-cyan-500 shadow-[0_0_8px_rgba(6,182,212,0.4)] dark:bg-cyan-400"
              style={{ width: `${Math.max(8, loadPct)}%` }}
            />
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-gray-100 py-2 dark:border-gray-800">
          <span className="camp-mono text-xs text-gray-500 dark:text-gray-400">Pendientes</span>
          <span className="camp-mono rounded border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-600 dark:text-amber-300">
            {pending}
          </span>
        </div>
        <div className="flex items-center justify-between border-t border-gray-100 py-2 dark:border-gray-800">
          <span className="camp-mono text-xs text-gray-500 dark:text-gray-400">Contactos en cola</span>
          <span className="camp-mono flex items-center gap-1.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_5px_rgba(16,185,129,0.6)]" />
            {totalLeads.toLocaleString('es-ES')}
          </span>
        </div>
        <div className="flex items-center justify-between border-t border-gray-100 py-2 dark:border-gray-800">
          <span className="camp-mono text-xs text-gray-500 dark:text-gray-400">Completadas</span>
          <span className="camp-mono text-xs font-medium text-gray-700 dark:text-gray-300">{completed}</span>
        </div>
      </div>
    </div>
  );
};
