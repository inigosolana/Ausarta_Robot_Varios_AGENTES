import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
    Wallet,
    ExternalLink,
    AlertTriangle,
    CheckCircle2,
    RefreshCw,
    KeyRound,
    Info,
} from 'lucide-react';
import { apiFetch } from '../lib/apiFetch';
import { useAuth } from '../contexts/AuthContext';

interface ApiCreditEntry {
    provider: string;
    key_configured: boolean;
    supported: boolean;
    status: 'ok' | 'no_key' | 'no_api' | 'auth_error' | 'no_data' | 'error';
    balance: number | null;
    balance_unit: string | null;
    usage_amount: number | null;
    usage_limit: number | null;
    usage_unit: string | null;
    period: string | null;
    note: string | null;
    dashboard_url: string | null;
}

interface ApiCreditsResponse {
    last_checked: string;
    providers: ApiCreditEntry[];
}

const formatNumber = (value: number, unit?: string | null) => {
    const isMoney = unit && /usd|eur|gbp|\$|€/i.test(unit);
    if (isMoney) {
        return new Intl.NumberFormat('es-ES', {
            style: 'currency',
            currency: (unit || 'USD').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3) || 'USD',
            maximumFractionDigits: 2,
        }).format(value);
    }
    return `${new Intl.NumberFormat('es-ES').format(value)}${unit ? ' ' + unit : ''}`;
};

const StatusPill: React.FC<{ entry: ApiCreditEntry }> = ({ entry }) => {
    if (!entry.key_configured) {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-gray-100 text-gray-500 dark:bg-slate-800 dark:text-gray-400">
                <KeyRound size={10} /> Sin clave
            </span>
        );
    }
    if (entry.status === 'auth_error') {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-red-50 text-red-600 dark:bg-red-900/30 dark:text-red-300">
                <AlertTriangle size={10} /> Clave inválida
            </span>
        );
    }
    if (entry.status === 'error') {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-300">
                <AlertTriangle size={10} /> Error
            </span>
        );
    }
    if (!entry.supported) {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                <Info size={10} /> Sin API saldo
            </span>
        );
    }
    return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-300">
            <CheckCircle2 size={10} /> Conectado
        </span>
    );
};

const PrimaryValue: React.FC<{ entry: ApiCreditEntry }> = ({ entry }) => {
    if (entry.balance !== null && entry.balance !== undefined) {
        return (
            <div className="text-right">
                <div className="text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider">Saldo</div>
                <div className="text-lg font-bold tabular-nums text-cyan-700 dark:text-cyan-300">
                    {formatNumber(entry.balance, entry.balance_unit)}
                </div>
            </div>
        );
    }
    if (entry.usage_amount !== null && entry.usage_amount !== undefined) {
        const pct =
            entry.usage_limit && entry.usage_limit > 0
                ? Math.min(100, Math.round((entry.usage_amount / entry.usage_limit) * 100))
                : null;
        return (
            <div className="text-right min-w-[140px]">
                <div className="text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                    {entry.period ? 'Consumo' : 'Uso'}
                </div>
                <div className="text-lg font-bold tabular-nums text-violet-700 dark:text-violet-300">
                    {formatNumber(entry.usage_amount, entry.usage_unit)}
                </div>
                {entry.usage_limit ? (
                    <>
                        <div className="text-[10px] text-gray-400 mt-0.5">
                            / {formatNumber(entry.usage_limit, entry.usage_unit)}
                        </div>
                        {pct !== null && (
                            <div className="mt-1 h-1.5 w-32 ml-auto bg-gray-100 dark:bg-slate-800 rounded-full overflow-hidden">
                                <div
                                    className={`h-full rounded-full ${
                                        pct >= 90
                                            ? 'bg-red-500'
                                            : pct >= 70
                                            ? 'bg-amber-500'
                                            : 'bg-emerald-500'
                                    }`}
                                    style={{ width: `${pct}%` }}
                                />
                            </div>
                        )}
                    </>
                ) : null}
            </div>
        );
    }
    return (
        <div className="text-right text-[11px] text-gray-400 dark:text-gray-500 italic max-w-[180px]">
            {entry.dashboard_url ? 'Ver en el panel del proveedor →' : '—'}
        </div>
    );
};

export const ApiCreditsWidget: React.FC = () => {
    const { t } = useTranslation();
    const { profile, loading } = useAuth();
    const isAdmin = !loading && (profile?.role === 'admin' || profile?.role === 'superadmin');

    const { data, isLoading, isError, refetch, isFetching } = useQuery<ApiCreditsResponse>({
        queryKey: ['api-credits'],
        queryFn: async () => {
            const res = await apiFetch('/api/admin/api-credits');
            if (!res.ok) throw new Error('Error fetching API credits');
            return res.json();
        },
        enabled: isAdmin,
        staleTime: 5 * 60 * 1000,
        refetchInterval: 5 * 60 * 1000,
    });

    if (loading) {
        return (
            <div className="bg-white dark:bg-slate-900/40 backdrop-blur-xl p-6 rounded-2xl shadow-[0_0_15px_rgba(0,240,255,0.05)] border border-gray-100 dark:border-cyan-900/30">
                <div className="h-6 w-40 bg-gray-100 dark:bg-slate-800 rounded mb-4 animate-pulse" />
                <div className="h-10 w-full bg-gray-100 dark:bg-slate-800 rounded animate-pulse" />
            </div>
        );
    }

    if (!isAdmin) return null;

    return (
        <div className="bg-white dark:bg-slate-900/40 backdrop-blur-xl p-6 rounded-2xl shadow-[0_0_15px_rgba(0,240,255,0.05)] border border-gray-100 dark:border-cyan-900/30 hover:border-cyan-500/50 transition-all duration-300">
            <div className="flex items-center justify-between gap-3 mb-5">
                <div className="flex items-center gap-3 min-w-0">
                    <div className="p-2 rounded-lg bg-violet-50 dark:bg-violet-900/20 text-violet-600 dark:text-violet-400">
                        <Wallet size={20} />
                    </div>
                    <div className="min-w-0">
                        <h3 className="text-lg font-bold text-gray-900 dark:text-cyan-50 truncate">
                            {t('Créditos de APIs')}
                        </h3>
                        <p className="text-[11px] text-gray-400 dark:text-gray-500">
                            {t('Saldos y consumo de los proveedores externos')}
                        </p>
                    </div>
                </div>
                <button
                    onClick={() => refetch()}
                    className="p-2 border border-gray-200 dark:border-cyan-900/40 rounded-xl hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors shrink-0"
                    title={t('Refrescar')}
                    disabled={isFetching}
                >
                    <RefreshCw
                        size={16}
                        className={isFetching ? 'animate-spin text-gray-500' : 'text-gray-500'}
                    />
                </button>
            </div>

            {isLoading ? (
                <div className="space-y-2">
                    {[1, 2, 3, 4].map((i) => (
                        <div
                            key={i}
                            className="h-14 w-full bg-gray-50 dark:bg-slate-800/40 rounded-xl animate-pulse"
                        />
                    ))}
                </div>
            ) : isError ? (
                <div className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
                    {t('No se pudo cargar la información de créditos.')}
                </div>
            ) : (
                <>
                    <div className="space-y-2">
                        {(data?.providers ?? []).map((entry) => (
                            <div
                                key={entry.provider}
                                className="flex items-center justify-between gap-3 p-3 bg-gray-50 dark:bg-slate-800/50 rounded-xl border border-gray-100 dark:border-slate-700/50"
                            >
                                <div className="min-w-0 flex-1">
                                    <div className="flex items-center gap-2 mb-0.5">
                                        <span className="font-bold text-sm text-gray-800 dark:text-gray-100 truncate">
                                            {entry.provider}
                                        </span>
                                        <StatusPill entry={entry} />
                                    </div>
                                    {entry.note && (
                                        <p className="text-[11px] text-gray-500 dark:text-gray-400 leading-snug">
                                            {entry.note}
                                        </p>
                                    )}
                                    {entry.dashboard_url && (
                                        <a
                                            href={entry.dashboard_url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="inline-flex items-center gap-1 text-[11px] text-cyan-600 dark:text-cyan-400 hover:underline mt-0.5"
                                        >
                                            {t('Abrir panel del proveedor')}
                                            <ExternalLink size={10} />
                                        </a>
                                    )}
                                </div>
                                <PrimaryValue entry={entry} />
                            </div>
                        ))}
                    </div>
                    {data?.last_checked && (
                        <div className="mt-4 text-[10px] text-gray-400 dark:text-gray-500 text-right uppercase tracking-wider">
                            {t('Última comprobación:')}{' '}
                            {new Date(data.last_checked).toLocaleTimeString()}
                        </div>
                    )}
                </>
            )}
        </div>
    );
};
