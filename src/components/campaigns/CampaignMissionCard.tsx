import React from 'react';
import { ChevronRight, Edit2, Trash2 } from 'lucide-react';

export interface MissionCampaign {
  id: number;
  name: string;
  status: string;
  scheduled_time: string | null;
  created_at: string;
  total_leads?: number;
  called_leads?: number;
  failed_leads?: number;
  pending_leads?: number;
  empresas?: { nombre: string };
}

function statusMeta(status: string) {
  const s = status === 'active' ? 'running' : status;
  if (s === 'running') {
    return { key: 'running', badge: 'camp-badge-running', label: 'En curso', stripe: 'bg-cyan-500', icon: 'play_circle' };
  }
  if (s === 'completed') {
    return { key: 'completed', badge: 'camp-badge-completed', label: 'Completada', stripe: 'bg-emerald-500', icon: 'check_circle' };
  }
  if (s === 'paused') {
    return { key: 'paused', badge: 'camp-badge-paused', label: 'Pausada', stripe: 'bg-amber-500', icon: 'pause_circle' };
  }
  return { key: 'pending', badge: 'camp-badge-pending', label: 'Pendiente', stripe: 'bg-indigo-400', icon: 'schedule' };
}

function formatRelative(dateStr: string | null, createdAt: string): string {
  const ref = dateStr ? new Date(dateStr) : new Date(createdAt);
  const diff = Date.now() - ref.getTime();
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 1) return 'Hace unos minutos';
  if (hours < 24) return `Hace ${hours}h`;
  return ref.toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric' });
}

function MaterialIcon({ name, className = '' }: { name: string; className?: string }) {
  return <span className={`material-symbols-outlined text-[18px] ${className}`}>{name}</span>;
}

type Props = {
  campaign: MissionCampaign;
  onOpen: () => void;
  onEdit: (e: React.MouseEvent) => void;
  onDelete: (e: React.MouseEvent) => void;
  showCompany?: boolean;
};

export const CampaignMissionCard: React.FC<Props> = ({
  campaign,
  onOpen,
  onEdit,
  onDelete,
  showCompany,
}) => {
  const meta = statusMeta(campaign.status);
  const total = campaign.total_leads || 0;
  const called = campaign.called_leads || 0;
  const pending = campaign.pending_leads ?? Math.max(0, total - called);
  const failed = campaign.failed_leads || 0;
  const pct = total > 0 ? Math.min(100, Math.round((called / total) * 100)) : 0;
  const successRate = called > 0 ? Math.max(0, ((called - failed) / called) * 100) : 0;
  const isPending = meta.key === 'pending';
  const isCompleted = meta.key === 'completed';
  const dimmed = isCompleted ? 'opacity-80 hover:opacity-100' : isPending ? 'opacity-90 hover:opacity-100' : '';

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={e => e.key === 'Enter' && onOpen()}
      className={`camp-mission-card group relative cursor-pointer overflow-hidden rounded-xl p-5 ${dimmed}`}
    >
      <div className={`absolute left-0 top-0 h-full w-1 ${meta.stripe} ${isCompleted ? 'opacity-50' : ''}`} />

      <div className="flex flex-col justify-between gap-6 md:flex-row md:items-center">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-3">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.badge}`}>
              {meta.key === 'running' && (
                <span className="h-1.5 w-1.5 rounded-full bg-cyan-500 camp-status-pulse dark:bg-cyan-400" />
              )}
              {meta.key !== 'running' && <MaterialIcon name={meta.icon} className="!text-[12px]" />}
              {meta.label}
            </span>
            <span className="camp-mono text-xs tracking-wider text-gray-400 dark:text-gray-500">
              CPG-{String(campaign.id).padStart(4, '0')}
            </span>
          </div>

          <h4 className="mb-1 truncate text-lg font-semibold text-gray-900 dark:text-white">
            {campaign.name}
          </h4>

          <div className="flex flex-wrap items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
            {showCompany && campaign.empresas?.nombre && (
              <span className="flex items-center gap-1">
                <MaterialIcon name="business" className="!text-[14px]" />
                {campaign.empresas.nombre}
              </span>
            )}
            <span className="flex items-center gap-1">
              <MaterialIcon name="schedule" className="!text-[14px]" />
              {campaign.scheduled_time
                ? `Programada: ${new Date(campaign.scheduled_time).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' })}`
                : formatRelative(campaign.scheduled_time, campaign.created_at)}
            </span>
            <span className="flex items-center gap-1">
              <MaterialIcon name="groups" className="!text-[14px]" />
              {total} contactos
            </span>
          </div>
        </div>

        <div className="w-full flex-1 md:max-w-xs">
          {isPending && total === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-3 text-center dark:border-gray-700 dark:bg-gray-800/40">
              <p className="text-sm italic text-gray-500 dark:text-gray-400">Esperando inicio</p>
              <p className="camp-mono mt-1 text-xs text-gray-400">Sin contactos cargados</p>
            </div>
          ) : isPending && total > 0 ? (
            <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-3 text-center dark:border-gray-700 dark:bg-gray-800/40">
              <p className="text-sm italic text-gray-500 dark:text-gray-400">Lista para desplegar</p>
              <p className="camp-mono mt-1 text-xs text-gray-400">{total} contactos objetivo</p>
            </div>
          ) : (
            <>
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-gray-700 dark:text-gray-200">Progreso</span>
                <span className="camp-mono text-xs text-cyan-600 dark:text-cyan-400">
                  {pct}% <span className="font-normal text-gray-400">({called}/{total})</span>
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100 shadow-inner dark:bg-gray-800">
                <div className="camp-progress-gradient relative h-full rounded-full" style={{ width: `${pct}%` }} />
              </div>
              <div className="mt-3 flex justify-between gap-2">
                <div>
                  <span className="mb-0.5 block text-[10px] uppercase tracking-wider text-gray-400">Éxito</span>
                  <span className="text-sm font-semibold text-emerald-600 dark:text-emerald-400">
                    {called > 0 ? `${successRate.toFixed(1)}%` : '—'}
                  </span>
                </div>
                <div>
                  <span className="mb-0.5 block text-[10px] uppercase tracking-wider text-gray-400">Pendientes</span>
                  <span className="text-sm font-semibold text-gray-800 dark:text-white">{pending}</span>
                </div>
                <div>
                  <span className="mb-0.5 block text-[10px] uppercase tracking-wider text-gray-400">Fallidas</span>
                  <span className="text-sm font-semibold text-gray-800 dark:text-white">{failed}</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="hidden items-center gap-1 md:flex">
          <button
            type="button"
            onClick={onEdit}
            className="flex h-8 w-8 items-center justify-center rounded-full border border-transparent text-gray-400 transition-colors hover:border-gray-200 hover:bg-gray-100 hover:text-indigo-600 dark:hover:border-gray-700 dark:hover:bg-gray-800 dark:hover:text-indigo-300"
            title="Editar"
          >
            <Edit2 size={16} />
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="flex h-8 w-8 items-center justify-center rounded-full border border-transparent text-gray-400 transition-colors hover:border-red-200 hover:bg-red-50 hover:text-red-500 dark:hover:border-red-900/40 dark:hover:bg-red-950/30 dark:hover:text-red-400"
            title="Eliminar"
          >
            <Trash2 size={16} />
          </button>
          <button
            type="button"
            onClick={e => { e.stopPropagation(); onOpen(); }}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-100 text-gray-500 transition-colors hover:bg-gray-200 hover:text-gray-800 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-white"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>
    </div>
  );
};
