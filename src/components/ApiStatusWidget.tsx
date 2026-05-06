import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Server, Activity, Database, Zap } from 'lucide-react';
import { apiFetch } from '../lib/apiFetch';

export const ApiStatusWidget: React.FC = () => {
    const { t } = useTranslation();

    const { data: status, isLoading, isError } = useQuery({
        queryKey: ['api-status'],
        queryFn: async () => {
            const res = await apiFetch('/api/dashboard/api-status');
            if (!res.ok) throw new Error('Error fetching API status');
            return res.json();
        },
        refetchInterval: 30000, // Refrescar cada 30 segundos
    });

    const services = [
        { key: 'openai', name: 'OpenAI (LLM)', icon: Zap },
        { key: 'livekit', name: 'LiveKit (WebRTC)', icon: Activity },
        { key: 'supabase', name: 'Supabase (DB)', icon: Database },
    ];

    if (isLoading) {
        return (
            <div className="bg-white dark:bg-slate-900/40 backdrop-blur-xl p-6 rounded-2xl shadow-sm border border-gray-100 dark:border-cyan-900/30 animate-pulse">
                <div className="h-6 w-32 bg-gray-200 dark:bg-slate-700 rounded mb-4"></div>
                <div className="space-y-3">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="h-10 w-full bg-gray-100 dark:bg-slate-800 rounded-xl"></div>
                    ))}
                </div>
            </div>
        );
    }

    if (isError) {
        return (
            <div className="bg-white dark:bg-slate-900/40 backdrop-blur-xl p-6 rounded-2xl shadow-sm border border-red-100 dark:border-red-900/30">
                <h3 className="text-lg font-bold text-red-600 dark:text-red-400 mb-2">{t('Error de Monitoreo')}</h3>
                <p className="text-sm text-red-500 dark:text-red-400/80">{t('No se pudo cargar el estado de las APIs.')}</p>
            </div>
        );
    }

    return (
        <div className="bg-white dark:bg-slate-900/40 backdrop-blur-xl p-6 rounded-2xl shadow-[0_0_15px_rgba(0,240,255,0.05)] border border-gray-100 dark:border-cyan-900/30 hover:border-cyan-500/50 transition-all duration-300 group">
            <div className="flex items-center gap-3 mb-5">
                <div className="p-2 rounded-lg bg-cyan-50 dark:bg-cyan-900/20 text-cyan-600 dark:text-cyan-400">
                    <Server size={20} />
                </div>
                <h3 className="text-lg font-bold text-gray-900 dark:text-cyan-50">{t('Estado de Servicios API')}</h3>
            </div>

            <div className="space-y-3">
                {services.map(({ key, name, icon: Icon }) => {
                    const isActive = status?.[key] === 'active';
                    return (
                        <div key={key} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-slate-800/50 rounded-xl border border-gray-100 dark:border-slate-700/50 group-hover:bg-slate-800/80 transition-colors">
                            <div className="flex items-center gap-3">
                                <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${isActive ? 'text-emerald-500 bg-emerald-500/10' : 'text-red-500 bg-red-500/10'}`}>
                                    <Icon size={16} />
                                </div>
                                <span className="text-sm font-bold text-gray-800 dark:text-gray-200">{name}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className="relative flex h-2.5 w-2.5">
                                    {isActive && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>}
                                    <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${isActive ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
                                </span>
                                <span className={`text-[10px] font-bold tracking-wider uppercase ${isActive ? 'text-emerald-500' : 'text-red-500'}`}>
                                    {isActive ? 'Operativo' : 'Caído'}
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>
            {status?.last_checked && (
                <div className="mt-4 text-[10px] text-gray-400 dark:text-gray-500 text-right uppercase tracking-wider">
                    {t('Última comprobación:')} {new Date(status.last_checked).toLocaleTimeString()}
                </div>
            )}
        </div>
    );
};
