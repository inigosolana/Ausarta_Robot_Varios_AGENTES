import React, { useState } from 'react';
import {
    Phone,
    CheckCircle,
    Clock,
    Star,
    Bot,
    ArrowRight,
    Loader2,
    Calendar,
    User,
    ChevronRight,
    TrendingUp,
    Download,
    RefreshCw
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from 'react-i18next';
import { DateRangePicker, getDatesFromRange, DateRange } from './DateRangePicker';
import { LiveMonitoring } from './LiveMonitoring';

const API_URL = import.meta.env.VITE_API_URL || '';

interface Props {
    empresaId?: number;
}

interface DashboardStats {
    total_calls: number;
    completed_calls: number;
    pending_calls: number;
    avg_scores: {
        overall: number;
    };
}

interface UsageStats {
    total_minutes: number;
}

interface Agent {
    id: string;
    name: string;
    use_case: string;
    is_active?: boolean;
}

interface Call {
    id: number;
    phone: string;
    campaign: string;
    date: string;
    status: string;
}

const KPICard = ({ title, value, subValue, icon: Icon, color }: any) => (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-2xl border border-gray-100 dark:border-gray-700 shadow-sm transition-all hover:shadow-md">
        <div className="flex justify-between items-start mb-4">
            <div className={`p-3 rounded-xl bg-${color}-50 dark:bg-${color}-900/20 text-${color}-600 dark:text-${color}-400`}>
                <Icon size={24} />
            </div>
            {subValue && (
                <span className="text-xs font-bold text-green-600 bg-green-50 dark:bg-green-900/30 px-2 py-1 rounded-full flex items-center gap-1">
                    <TrendingUp size={12} /> {subValue}
                </span>
            )}
        </div>
        <div>
            <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{title}</p>
            <h3 className="text-3xl font-bold text-gray-900 dark:text-white mt-1">{value}</h3>
        </div>
    </div>
);

const ClientDashboard: React.FC<Props> = ({ empresaId }) => {
    const { profile } = useAuth();
    const { t } = useTranslation();
    const [dateRange, setDateRange] = useState<DateRange>('7d');

    const finalEmpresaId = empresaId || profile?.empresa_id;

    const fetchClientData = async () => {
        const params = new URLSearchParams();
        if (finalEmpresaId) params.append('empresa_id', String(finalEmpresaId));
        const dates = getDatesFromRange(dateRange);
        if (dates.start) params.append('start_date', dates.start);
        if (dates.end) params.append('end_date', dates.end);
        const queryStr = params.toString() ? `?${params.toString()}` : '';

        const [statsRes, usageRes, agentsRes, callsRes] = await Promise.all([
            fetch(`${API_URL}/api/dashboard/stats${queryStr}`),
            fetch(`${API_URL}/api/dashboard/usage-stats${queryStr}`),
            fetch(`${API_URL}/api/agents?empresa_id=${finalEmpresaId}`),
            fetch(`${API_URL}/api/dashboard/recent-calls${queryStr}`)
        ]);

        return {
            stats: statsRes.ok ? (await statsRes.json()) as DashboardStats : null,
            usage: usageRes.ok ? (await usageRes.json()) as UsageStats : null,
            agents: agentsRes.ok ? (await agentsRes.json()) as Agent[] : [],
            recentCalls: callsRes.ok ? ((await callsRes.json()) as Call[]).slice(0, 5) : [],
        };
    };

    const { data, isLoading, refetch: loadData } = useQuery({
        queryKey: ['client-dashboard', finalEmpresaId, dateRange],
        queryFn: fetchClientData,
        enabled: !!finalEmpresaId,
        staleTime: 30_000,
    });

    const stats = data?.stats ?? null;
    const usage = data?.usage ?? null;
    const agents = data?.agents ?? [];
    const recentCalls = data?.recentCalls ?? [];

    const exportCSV = () => {
        const headers = [
            t("Teléfono"),
            t("Campaña"),
            t("Fecha"),
            t("Estado")
        ];
        const csvContent = [
            headers.join(","),
            ...recentCalls.map(c => [
                c.phone,
                `"${c.campaign.replace(/"/g, '""')}"`,
                new Date(c.date).toLocaleString(),
                c.status
            ].join(","))
        ].join("\n");

        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement("a");
        const url = URL.createObjectURL(blob);
        link.setAttribute("href", url);
        link.setAttribute("download", `client_activity_${new Date().toISOString().split('T')[0]}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
                <Loader2 className="animate-spin text-blue-500" size={40} />
                <p className="text-gray-500 font-medium">{t('Analyzing business ROI...', 'Analizando el ROI de negocio...')}</p>
            </div>
        );
    }

    const hoursSaved = usage ? Math.round(usage.total_minutes / 60 * 10) / 10 : 0;
    const totalContacts = (stats?.total_calls || 0) + (stats?.pending_calls || 0);
    const connectionRate = stats?.total_calls ? Math.round((stats.completed_calls / stats.total_calls) * 100) : 0;

    return (
        <div className="space-y-8 animate-fade-in pb-10">
            {/* Header / Filter */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-2xl bg-blue-600 flex items-center justify-center shadow-lg shadow-blue-200 text-white">
                        <TrendingUp size={24} />
                    </div>
                    <div>
                        <h2 className="text-3xl font-extrabold text-gray-900 dark:text-white tracking-tight">
                            {t('Welcome back', 'Bienvenido de nuevo')}, <span className="text-blue-600">{profile?.full_name?.split(' ')[0]}</span>
                        </h2>
                        <p className="text-gray-500 dark:text-gray-400 mt-0.5 flex items-center gap-2 text-sm">
                            <Calendar size={14} /> {new Date().toLocaleDateString('es-ES', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
                        </p>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <DateRangePicker value={dateRange} onChange={setDateRange} />
                    <button
                        onClick={loadData}
                        className="p-2.5 border border-gray-200 dark:border-gray-700 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors bg-white dark:bg-gray-800"
                        title={t('Refresh data', 'Refrescar datos')}
                    >
                        <RefreshCw size={18} className={isLoading ? "animate-spin" : "text-gray-500"} />
                    </button>
                </div>
            </div>

            {/* KPI Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
                <KPICard
                    title={t('Calls Made', 'Llamadas Realizadas')}
                    value={stats?.total_calls || 0}
                    icon={Phone}
                    color="blue"
                />
                <KPICard
                    title={t('Leads / Appointments', 'Citas / Leads')}
                    value={stats?.completed_calls || 0}
                    subValue={`${connectionRate}% conv.`}
                    icon={CheckCircle}
                    color="green"
                />
                <KPICard
                    title={t('Human Hours Saved', 'Horas Ahorradas')}
                    value={`${hoursSaved}h`}
                    icon={Clock}
                    color="purple"
                />
                <KPICard
                    title={t('Satisfaction Score', 'Nota Satisfacción')}
                    value={`${stats?.avg_scores?.overall || 0}/10`}
                    icon={Star}
                    color="amber"
                />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Funnel Chart (Business Flow) */}
                <div className="lg:col-span-2 bg-white dark:bg-gray-800 p-8 rounded-3xl border border-gray-100 dark:border-gray-700 shadow-sm">
                    <h3 className="text-xl font-bold text-gray-800 dark:text-white mb-8 flex items-center gap-2">
                        <TrendingUp className="text-blue-600" size={20} />
                        {t('Growth Funnel', 'Embudo de Crecimiento')}
                    </h3>

                    <div className="space-y-10 py-4 max-w-lg mx-auto">
                        {/* Step 1: Uploaded */}
                        <div className="relative">
                            <div className="flex justify-between items-center mb-2">
                                <span className="text-sm font-bold text-gray-400 uppercase tracking-wider">{t('Loaded Contacts', 'Contactos Cargados')}</span>
                                <span className="font-bold text-gray-900 dark:text-white">{totalContacts}</span>
                            </div>
                            <div className="h-10 bg-blue-500/10 dark:bg-blue-500/5 rounded-2xl border border-blue-500/20 overflow-hidden relative">
                                <div className="h-full bg-gradient-to-r from-blue-600 to-blue-400 w-full" />
                                <div className="absolute inset-0 flex items-center justify-center text-xs font-bold text-white uppercase tracking-widest bg-black/5">100% Data Pool</div>
                            </div>
                            <div className="absolute -bottom-8 left-1/2 -translate-x-1/2 text-gray-300">
                                <ChevronRight size={24} className="rotate-90" />
                            </div>
                        </div>

                        {/* Step 2: Connected */}
                        <div className="relative">
                            <div className="flex justify-between items-center mb-2 pt-2">
                                <span className="text-sm font-bold text-gray-400 uppercase tracking-wider">{t('Calls Connected', 'Llamadas Conectadas')}</span>
                                <span className="font-bold text-gray-900 dark:text-white">{stats?.total_calls || 0}</span>
                            </div>
                            <div className="h-10 bg-blue-500/10 dark:bg-blue-500/5 rounded-2xl border border-blue-500/20 overflow-hidden relative flex justify-center">
                                <div
                                    className="h-full bg-gradient-to-r from-indigo-600 to-indigo-400 transition-all duration-1000"
                                    style={{ width: totalContacts ? `${(stats?.total_calls || 0) / totalContacts * 100}%` : '0%' }}
                                />
                                <div className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-gray-500 uppercase tracking-widest">
                                    {totalContacts ? Math.round((stats?.total_calls || 0) / totalContacts * 100) : 0}% Outreach
                                </div>
                            </div>
                            <div className="absolute -bottom-8 left-1/2 -translate-x-1/2 text-gray-300">
                                <ChevronRight size={24} className="rotate-90" />
                            </div>
                        </div>

                        {/* Step 3: Converted */}
                        <div>
                            <div className="flex justify-between items-center mb-2 pt-2">
                                <span className="text-sm font-bold text-green-600 uppercase tracking-wider">{t('Objectives Reached', 'Objetivos Cumplidos')}</span>
                                <span className="font-extrabold text-green-600">{stats?.completed_calls || 0}</span>
                            </div>
                            <div className="h-10 bg-green-500/10 rounded-2xl border border-green-500/20 overflow-hidden relative flex justify-center">
                                <div
                                    className="h-full bg-gradient-to-r from-green-600 to-green-400 transition-all duration-1000"
                                    style={{ width: stats?.total_calls ? `${(stats?.completed_calls || 0) / stats.total_calls * 100}%` : '0%' }}
                                />
                                <div className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-green-700 uppercase tracking-widest">
                                    {connectionRate}% ROI Conversion
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Active Agents (Live status) */}
                <div className="bg-white dark:bg-gray-800 p-8 rounded-3xl border border-gray-100 dark:border-gray-700 shadow-sm flex flex-col">
                    <h3 className="text-xl font-bold text-gray-800 dark:text-white mb-6 flex items-center gap-2">
                        <Bot size={20} className="text-purple-500" />
                        {t('My AI Staff', 'Mis Agentes Activos')}
                    </h3>

                    <div className="space-y-4 flex-1">
                        {agents.length === 0 ? (
                            <div className="text-center py-6">
                                <p className="text-gray-400 text-sm italic">{t('No active agents found', 'No tienes agentes activos todavía.')}</p>
                            </div>
                        ) : (
                            agents.map(agent => (
                                <div key={agent.id} className="p-4 rounded-2xl bg-gray-50 dark:bg-gray-700/30 border border-gray-100 dark:border-gray-600 flex items-center justify-between group transition-all hover:border-purple-200">
                                    <div className="flex items-center gap-3">
                                        <div className="w-10 h-10 rounded-full bg-purple-100 dark:bg-purple-900/40 text-purple-600 dark:text-purple-400 flex items-center justify-center">
                                            <Bot size={20} />
                                        </div>
                                        <div>
                                            <h4 className="font-bold text-gray-900 dark:text-white text-sm">{agent.name}</h4>
                                            <p className="text-xs text-gray-500 dark:text-gray-400 truncate max-w-[120px]">{agent.use_case || t('Intelligent Assistant')}</p>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-1.5">
                                        <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                                        <span className="text-[10px] font-bold text-green-600 uppercase tracking-tighter">Online</span>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>

                    <button className="mt-6 w-full py-3 bg-gray-900 dark:bg-gray-700 text-white text-sm font-bold rounded-xl hover:bg-black transition-colors flex items-center justify-center gap-2 group">
                        {t('Configure Agents', 'Gestionar Agentes')}
                        <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
                    </button>
                </div>
            </div>

            {/* Supervision & Activity */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 pb-10">
                <div className="lg:col-span-1">
                    <LiveMonitoring />
                </div>

                <div className="lg:col-span-2 bg-white dark:bg-gray-800 p-8 rounded-3xl border border-gray-100 dark:border-gray-700 shadow-sm overflow-hidden">

                    <div className="flex justify-between items-center mb-6">
                        <h3 className="text-xl font-bold text-gray-800 dark:text-white">{t('Live Activity Feed', 'Última Actividad Real')}</h3>
                        <div className="flex items-center gap-3">
                            <button
                                onClick={exportCSV}
                                className="flex items-center gap-2 px-3 py-1.5 text-xs font-bold text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-700 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-600 transition-all border border-gray-100 dark:border-gray-600"
                            >
                                <Download size={14} />
                                {t('Export CSV', 'Exportar CSV')}
                            </button>
                            <button className="text-blue-600 dark:text-blue-400 text-sm font-bold hover:underline">{t('View all results', 'Ver todos los resultados')}</button>
                        </div>
                    </div>

                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="text-left border-b border-gray-100 dark:border-gray-700">
                                <tr>
                                    <th className="pb-4 text-xs font-bold text-gray-400 uppercase tracking-widest">{t('Contact', 'Contacto')}</th>
                                    <th className="pb-4 text-xs font-bold text-gray-400 uppercase tracking-widest">{t('Time', 'Hora')}</th>
                                    <th className="pb-4 text-xs font-bold text-gray-400 uppercase tracking-widest text-center">{t('Status', 'Resultado')}</th>
                                    <th className="pb-4"></th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-50 dark:divide-gray-700">
                                {recentCalls.map((call) => (
                                    <tr key={call.id} className="group hover:bg-gray-50/50 dark:hover:bg-gray-700/20 transition-colors">
                                        <td className="py-4">
                                            <div className="flex items-center gap-3">
                                                <div className="w-8 h-8 rounded-full bg-gray-100 dark:bg-gray-700 flex items-center justify-center text-gray-500">
                                                    <User size={14} />
                                                </div>
                                                <div>
                                                    <p className="text-sm font-bold text-gray-900 dark:text-white">{call.phone}</p>
                                                    <p className="text-[10px] text-blue-500 font-bold uppercase tracking-tight">{call.campaign}</p>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="py-4 text-xs text-gray-500 dark:text-gray-400 font-medium">
                                            {new Date(call.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                        </td>
                                        <td className="py-4 text-center">
                                            {(() => {
                                                const status = call.status.toLowerCase();
                                                if (status === 'completada' || status === 'completed')
                                                    return <span className="px-3 py-1 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-[10px] font-extrabold uppercase">{t('Success', 'Éxito')}</span>;
                                                if (status === 'parcial')
                                                    return <span className="px-3 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded-full text-[10px] font-extrabold uppercase">{t('Partial', 'Parcial')}</span>;
                                                if (status === 'rechazada' || status === 'rejected' || status === 'rejected_opt_out')
                                                    return <span className="px-3 py-1 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded-full text-[10px] font-extrabold uppercase">{t('Rejected', 'Rechazada')}</span>;
                                                if (status === 'no_contesta' || status === 'unreached')
                                                    return <span className="px-3 py-1 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 rounded-full text-[10px] font-extrabold uppercase">{t('No Answer', 'No Contesta')}</span>;
                                                if (status === 'fallida' || status === 'failed')
                                                    return <span className="px-3 py-1 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded-full text-[10px] font-extrabold uppercase">{t('Failed', 'Fallida')}</span>;
                                                return <span className="px-3 py-1 bg-gray-100 dark:bg-gray-700 text-gray-500 rounded-full text-[10px] font-extrabold uppercase">{call.status}</span>;
                                            })()}
                                        </td>
                                        <td className="py-4 text-right">
                                            <button className="p-2 text-gray-300 hover:text-blue-600 transition-colors">
                                                <ChevronRight size={18} />
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        {recentCalls.length === 0 && (
                            <div className="text-center py-10">
                                <p className="text-gray-400 text-sm italic">{t('No activity yet today', 'Sin actividad reciente hoy.')}</p>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ClientDashboard;
