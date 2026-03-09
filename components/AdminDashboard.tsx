import React, { useState, useEffect } from 'react';
import {
    Phone,
    CheckCircle,
    BarChart2,
    Timer,
    User,
    Zap,
    Download,
    Calendar,
    RefreshCw
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from 'react-i18next';
import { DateRangePicker, getDatesFromRange, DateRange } from './DateRangePicker';
import { LiveMonitoring } from './LiveMonitoring';

// API URL - Consistent with other views
const API_URL = import.meta.env.VITE_API_URL || '';

interface DashboardStats {
    total_calls: number;
    completed_calls: number;
    pending_calls: number;
    avg_scores: {
        comercial: number;
        instalador: number;
        rapidez: number;
        overall: number;
    };
    is_question_based?: boolean;
}

interface Call {
    id: number;
    phone: string;
    campaign: string;
    date: string;
    status: string;
    llm_model: string;
    scores?: {
        comercial: number | null;
        instalador: number | null;
        rapidez: number | null;
    };
}

interface Integration {
    name: string;
    provider: string;
    active: boolean;
    status?: string | number;
    url?: string;
    icon?: React.ElementType;
}

interface StatCardProps {
    title: string;
    value: string | number;
    icon: React.ElementType;
    color: 'blue' | 'green' | 'purple' | 'orange';
}

const StatCard: React.FC<StatCardProps> = ({ title, value, icon: Icon, color }) => {
    const colors = {
        blue: 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400',
        green: 'bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400',
        purple: 'bg-purple-50 text-purple-600 dark:bg-purple-900/20 dark:text-purple-400',
        orange: 'bg-orange-50 text-orange-600 dark:bg-orange-900/20 dark:text-orange-400',
    };

    return (
        <div className="bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-100 dark:border-gray-700 shadow-sm animate-slide-up">
            <div className="flex items-center justify-between mb-4">
                <div className={`p-3 rounded-lg ${colors[color]}`}>
                    <Icon size={24} />
                </div>
            </div>
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400">{title}</h3>
            <p className="text-2xl font-bold text-gray-900 dark:text-white mt-1">{value}</p>
        </div>
    );
};

const IntegrationCard: React.FC<Integration> = ({ name, provider, active, status, url }) => {
    return (
        <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl border border-gray-100 dark:border-gray-700 transition-all hover:bg-white dark:hover:bg-gray-700 hover:shadow-sm">
            <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${active ? 'bg-green-100 text-green-600 dark:bg-green-900/30' : 'bg-red-100 text-red-600 dark:bg-red-900/30'}`}>
                    <Zap size={20} />
                </div>
                <div>
                    <h4 className="text-sm font-bold text-gray-800 dark:text-white">{name}</h4>
                    <p className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">{provider}</p>
                </div>
            </div>
            <div className="text-right">
                <span className={`text-[10px] font-bold px-2 py-1 rounded-full ${active ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'}`}>
                    {active ? 'ONLINE' : 'OFFLINE'}
                </span>
                {status && <p className="text-[10px] text-gray-400 mt-1">{status}</p>}
            </div>
        </div>
    );
};

interface AdminDashboardProps {
    title?: string;
    empresaId?: number;
    agentId?: number;
    campaignId?: number;
    hideIntegrations?: boolean;
}

const AdminDashboard: React.FC<AdminDashboardProps> = ({
    title,
    empresaId,
    agentId,
    campaignId,
    hideIntegrations = false
}) => {
    const { profile, isPlatformOwner } = useAuth();
    const { t } = useTranslation();
    const [stats, setStats] = useState<DashboardStats | null>(null);
    const [recentCalls, setRecentCalls] = useState<Call[]>([]);
    const [integrations, setIntegrations] = useState<Integration[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [dateRange, setDateRange] = useState<DateRange>('7d');

    useEffect(() => {
        loadData();
    }, [profile, dateRange]);

    const loadData = async () => {
        try {
            setIsLoading(true);
            const params = new URLSearchParams();

            const finalEmpresaId = empresaId || (isPlatformOwner ? undefined : profile?.empresa_id);
            if (finalEmpresaId) params.append('empresa_id', String(finalEmpresaId));
            if (agentId) params.append('agent_id', String(agentId));
            if (campaignId) params.append('campaign_id', String(campaignId));

            // Date filtering
            const dates = getDatesFromRange(dateRange);
            if (dates.start) params.append('start_date', dates.start);
            if (dates.end) params.append('end_date', dates.end);

            const queryStr = params.toString() ? `?${params.toString()}` : '';

            const [statsRes, callsRes, intRes] = await Promise.all([
                fetch(`${API_URL}/api/dashboard/stats${queryStr}`),
                fetch(`${API_URL}/api/dashboard/recent-calls${queryStr}`),
                hideIntegrations ? Promise.resolve({ ok: true, json: () => [] }) : fetch(`${API_URL}/api/dashboard/integrations`)
            ]);

            if (statsRes.ok) setStats(await statsRes.json());
            if (callsRes.ok) setRecentCalls(await callsRes.json());
            if (intRes.ok && !hideIntegrations) setIntegrations(await intRes.json());

        } catch (error) {
            console.error('Error loading dashboard data:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const exportCSV = () => {
        const headers = [
            t("ID"),
            t("Teléfono / Campaña", "Phone / Campaign"),
            t("Fecha", "Date"),
            t("Estado", "Status"),
            t("Modelo AI", "AI Model"),
            t("C / I / R")
        ];
        const csvContent = [
            headers.join(","),
            ...recentCalls.map(c => [
                c.id,
                `"${c.phone} - ${c.campaign.replace(/"/g, '""')}"`,
                new Date(c.date).toLocaleString(),
                c.status,
                c.llm_model || "Standard",
                `${c.scores?.comercial ?? '-'} / ${c.scores?.instalador ?? '-'} / ${c.scores?.rapidez ?? '-'}`
            ].join(","))
        ].join("\n");

        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement("a");
        const url = URL.createObjectURL(blob);
        link.setAttribute("href", url);
        link.setAttribute("download", `dashboard_activity_${new Date().toISOString().split('T')[0]}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    if (isLoading && !stats) return <div className="p-8 text-center text-gray-500">{t('Loading dashboard...', 'Cargando dashboard...')}</div>;

    return (
        <div className="space-y-8 animate-fade-in">
            {/* Header / Filter */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                {!title && (
                    <div className="flex items-center gap-3">
                        <img src="/ausarta.png" alt="Logo" className="h-10 w-auto object-contain dark:invert" />
                        <div>
                            <h2 className="text-3xl font-bold text-gray-900 dark:text-white">{t('Admin Dashboard', 'Panel de Administración')}</h2>
                            <p className="text-gray-500 dark:text-gray-400 text-sm">{t('System health and global stats', 'Salud del sistema y estadísticas globales')}</p>
                        </div>
                    </div>
                )}
                {title && (
                    <div>
                        <h2 className="text-2xl font-bold text-gray-900 dark:text-white">{title}</h2>
                        <p className="text-gray-500 dark:text-gray-400 mt-1 text-sm">{t('Activity summary', 'Resumen de actividad')}</p>
                    </div>
                )}

                <div className="flex flex-wrap items-center gap-2">
                    <DateRangePicker value={dateRange} onChange={setDateRange} />
                    <button
                        onClick={loadData}
                        className="p-2 border border-gray-200 dark:border-gray-700 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                        title={t('Refresh data', 'Refrescar datos')}
                    >
                        <RefreshCw size={18} className={isLoading ? "animate-spin" : "text-gray-500"} />
                    </button>
                </div>
            </div>

            {/* KPI Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                <StatCard
                    title={t('Total Global Calls', 'Llamadas Globales')}
                    value={stats?.total_calls || 0}
                    icon={Phone}
                    color="blue"
                />
                <StatCard
                    title={t('Completed', 'Completadas')}
                    value={stats?.completed_calls || 0}
                    icon={CheckCircle}
                    color="green"
                />
                {!stats?.is_question_based ? (
                    <StatCard
                        title={t('Average Score', 'Nota Media')}
                        value={stats?.avg_scores?.overall || 0}
                        icon={BarChart2}
                        color="purple"
                    />
                ) : (
                    <StatCard
                        title={t('Open Survey', 'Encuesta Abierta')}
                        value={t('Unlimited', 'Ilimitada')}
                        icon={BarChart2}
                        color="purple"
                    />
                )}
                <StatCard
                    title={t('Pending Calls', 'Llamadas en Curso')}
                    value={stats?.pending_calls || 0}
                    icon={Timer}
                    color="orange"
                />
            </div>

            {/* Main Content Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Integration Status & Supervision */}
                <div className="lg:col-span-1 space-y-8">
                    <LiveMonitoring />

                    {!hideIntegrations && (
                        <div className="bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-100 dark:border-gray-700 shadow-sm animate-slide-up">
                            <h3 className="text-lg font-bold text-gray-800 dark:text-white mb-4">{t('Core Integrations', 'Integraciones Principales')}</h3>
                            <div className="space-y-4">
                                {integrations.map((int, i) => (
                                    <IntegrationCard key={i} {...int} />
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* Recent Activity */}
                <div className="lg:col-span-2 space-y-8">
                    <div className="bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-100 dark:border-gray-700 shadow-sm overflow-hidden animate-slide-up">
                        <div className="flex justify-between items-center mb-6">
                            <h3 className="text-lg font-bold text-gray-800 dark:text-white">{t('Latest Global Activity', 'Última Actividad Global')}</h3>
                            <button
                                onClick={exportCSV}
                                className="flex items-center gap-2 px-3 py-1.5 text-xs font-bold text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 rounded-lg hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-all border border-blue-100 dark:border-blue-800"
                            >
                                <Download size={14} />
                                {t('Export CSV', 'Exportar CSV')}
                            </button>
                        </div>

                        <div className="overflow-x-auto">
                            <table className="w-full text-left">
                                <thead className="text-xs uppercase text-gray-400 border-b border-gray-50 dark:border-gray-700">
                                    <tr>
                                        <th className="pb-3 font-semibold">{t('Phone/Campaign')}</th>
                                        <th className="pb-3 font-semibold">{t('Date')}</th>
                                        <th className="pb-3 font-semibold">{t('Status')}</th>
                                        {!stats?.is_question_based && <th className="pb-3 font-semibold">{t('CIR')}</th>}
                                        <th className="pb-3 font-semibold">{t('Model', 'Modelo')}</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-50 dark:divide-gray-700">
                                    {recentCalls.map((call) => (
                                        <tr key={call.id} className="text-sm group hover:bg-gray-50 dark:hover:bg-gray-700/50">
                                            <td className="py-4">
                                                <div className="font-bold text-gray-800 dark:text-white">{call.phone}</div>
                                                <div className="text-xs text-gray-400">{call.campaign}</div>
                                            </td>
                                            <td className="py-4 text-gray-500 dark:text-gray-400">
                                                {new Date(call.date).toLocaleString()}
                                            </td>
                                            <td className="py-4">
                                                {(() => {
                                                    const s = (call.status || '').toLowerCase();
                                                    const isCompleted = s === 'completada' || s === 'completed';
                                                    const isPartial = s === 'parcial' || s === 'incomplete';
                                                    const isRejected = s === 'rechazada' || s === 'rejected' || s === 'rejected_opt_out';
                                                    const isNoAnswer = s === 'no_contesta' || s === 'unreached';
                                                    const isFailed = s === 'fallida' || s === 'failed';

                                                    const cls = isCompleted
                                                        ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                                                        : isPartial
                                                            ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300'
                                                            : isRejected
                                                                ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                                                                : isNoAnswer
                                                                    ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
                                                                    : isFailed
                                                                        ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300'
                                                                        : 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300';

                                                    const label = isCompleted
                                                        ? t('Completed', 'Completada')
                                                        : isPartial
                                                            ? t('Partial', 'Parcial')
                                                            : isRejected
                                                                ? t('Rejected', 'Rechazada')
                                                                : isNoAnswer
                                                                    ? t('No Answer', 'No Contesta')
                                                                    : isFailed
                                                                        ? t('Failed', 'Fallida')
                                                                        : t('Pending', 'Pendiente');

                                                    return <span className={`px-2 py-1 rounded-full text-[10px] font-bold uppercase ${cls}`}>{label}</span>;
                                                })()}
                                            </td>
                                            {!stats?.is_question_based && (
                                                <td className="py-4">
                                                    <div className="flex gap-1 text-[10px] font-bold">
                                                        <span className="text-blue-500">{call.scores?.comercial ?? '-'}</span>
                                                        <span className="text-gray-300">/</span>
                                                        <span className="text-green-500">{call.scores?.instalador ?? '-'}</span>
                                                        <span className="text-gray-300">/</span>
                                                        <span className="text-purple-500">{call.scores?.rapidez ?? '-'}</span>
                                                    </div>
                                                </td>
                                            )}
                                            <td className="py-4">
                                                <div className="flex items-center gap-1 text-[10px] text-gray-400">
                                                    <Zap size={10} /> {call.llm_model || 'GPT-4o'}
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            {recentCalls.length === 0 && (
                                <div className="text-center py-12 text-gray-400 italic">
                                    {t('No recent activity', 'Sin actividad reciente')}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default AdminDashboard;
