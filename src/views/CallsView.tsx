import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Phone, Radio, RefreshCw, Eye, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';
import { fetchCalls, formatCallDuration, type CallRow } from '../lib/callsApi';
import { LiveCallPanel } from '../components/LiveCallPanel';
import { getTipoResultadosLabel } from '../lib/agentVoiceOptions';

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  calling: 'bg-blue-100 text-blue-700',
  in_progress: 'bg-cyan-100 text-cyan-700',
  initiated: 'bg-amber-100 text-amber-700',
};

function statusBadgeClass(status: string, isLive: boolean): string {
  if (isLive) return 'bg-emerald-100 text-emerald-700 animate-pulse';
  return STATUS_COLORS[status] || 'bg-gray-100 text-gray-600';
}

const CallsView: React.FC = () => {
  const { t } = useTranslation();
  const { profile, isPlatformOwner } = useAuth();
  const [liveOnly, setLiveOnly] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [monitorRoom, setMonitorRoom] = useState<string | null>(null);

  const empresaId = isPlatformOwner ? undefined : profile?.empresa_id ?? undefined;

  const queryKey = ['calls', empresaId, liveOnly, statusFilter] as const;

  const { data, isLoading, isFetching, refetch, error } = useQuery({
    queryKey,
    queryFn: () =>
      fetchCalls({
        empresaId: empresaId ?? 'all',
        liveOnly,
        status: statusFilter || undefined,
        limit: 100,
      }),
    refetchInterval: 5000,
  });

  const calls = data?.calls ?? [];
  const liveCount = data?.live_count ?? calls.filter((c) => c.is_live).length;

  const groupedLive = useMemo(
    () => calls.filter((c) => c.is_live),
    [calls],
  );

  const openMonitor = (call: CallRow) => {
    if (call.room_name) setMonitorRoom(call.room_name);
  };

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Phone className="text-cyan-500" size={24} />
            {t('Live Calls', 'Llamadas en tiempo real')}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {liveCount} activa(s) · {data?.total ?? 0} en listado · actualización cada 5s
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 cursor-pointer">
            <input
              type="checkbox"
              checked={liveOnly}
              onChange={(e) => setLiveOnly(e.target.checked)}
              className="rounded border-gray-300"
            />
            {t('Live only', 'Solo en curso')}
          </label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-sm border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 bg-white dark:bg-gray-900"
          >
            <option value="">{t('All statuses', 'Todos los estados')}</option>
            <option value="calling">calling</option>
            <option value="in_progress">in_progress</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
          </select>
          <button
            type="button"
            onClick={() => refetch()}
            className="inline-flex items-center gap-1 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
            {t('Refresh', 'Actualizar')}
          </button>
        </div>
      </div>

      {groupedLive.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {groupedLive.map((call) => (
            <button
              key={call.id}
              type="button"
              onClick={() => openMonitor(call)}
              className="text-left p-4 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/20 hover:shadow-md transition-shadow"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="flex items-center gap-1 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                  <Radio size={12} className="animate-pulse" />
                  EN VIVO
                </span>
                <span className="text-xs text-gray-500">{formatCallDuration(call.duration_seconds)}</span>
              </div>
              <p className="font-semibold text-gray-900 dark:text-white">{call.phone}</p>
              <p className="text-xs text-gray-500 truncate">{call.agent_name || '—'}</p>
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="p-4 rounded-lg bg-red-50 text-red-700 text-sm">
          {(error as Error).message}
        </div>
      )}

      <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden bg-white dark:bg-gray-900/50">
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader2 className="animate-spin mr-2" size={20} />
            Cargando llamadas…
          </div>
        ) : calls.length === 0 ? (
          <p className="text-center py-16 text-gray-400 text-sm">
            {t('No calls found', 'No hay llamadas')}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-800/80 text-left text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">{t('Phone', 'Teléfono')}</th>
                  <th className="px-4 py-3">{t('Status', 'Estado')}</th>
                  <th className="px-4 py-3">{t('Duration', 'Duración')}</th>
                  <th className="px-4 py-3">{t('Agent', 'Agente')}</th>
                  <th className="px-4 py-3">{t('Campaign', 'Campaña')}</th>
                  {isPlatformOwner && <th className="px-4 py-3">{t('Company', 'Empresa')}</th>}
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {calls.map((call) => (
                  <tr key={call.id} className="hover:bg-gray-50/80 dark:hover:bg-gray-800/40">
                    <td className="px-4 py-3 font-mono text-xs">{call.id}</td>
                    <td className="px-4 py-3">
                      <div className="font-medium">{call.phone}</div>
                      {call.customer_name && (
                        <div className="text-xs text-gray-500">{call.customer_name}</div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${statusBadgeClass(call.status, call.is_live)}`}
                      >
                        {call.is_live ? 'live' : call.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {formatCallDuration(call.duration_seconds)}
                    </td>
                    <td className="px-4 py-3">
                      <div>{call.agent_name || '—'}</div>
                      <div className="text-xs text-gray-500">
                        {getTipoResultadosLabel(call.agent_type)}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400 max-w-[140px] truncate">
                      {call.campaign_name || (call.campaign_id ? `#${call.campaign_id}` : '—')}
                    </td>
                    {isPlatformOwner && (
                      <td className="px-4 py-3 text-xs">{call.empresa_name}</td>
                    )}
                    <td className="px-4 py-3">
                      {call.is_live && call.room_name && (
                        <button
                          type="button"
                          onClick={() => openMonitor(call)}
                          className="inline-flex items-center gap-1 text-xs text-cyan-600 hover:text-cyan-700 font-medium"
                        >
                          <Eye size={14} />
                          Monitor
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {monitorRoom && (
        <LiveCallPanel roomName={monitorRoom} onClose={() => setMonitorRoom(null)} />
      )}
    </div>
  );
};

export default CallsView;
