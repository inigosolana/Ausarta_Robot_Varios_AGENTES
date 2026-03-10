import React, { useState, useEffect } from 'react';
import {
    Phone,
    CheckCircle,
    BarChart2,
    Timer,
    Zap,
    Download,
    RefreshCw
} from 'lucide-react';
import {
    PieChart, Pie, Cell, ResponsiveContainer, Tooltip as RechartsTooltip, Legend
} from 'recharts';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from 'react-i18next';
import { DateRangePicker, getDatesFromRange, DateRange } from './DateRangePicker';
import { LiveMonitoring } from './LiveMonitoring';

const API_URL = import.meta.env.VITE_API_URL || '';

const STATUS_LABELS: Record<string, string> = {
    completed: 'Completadas',
    completada: 'Completadas',
    rejected_opt_out: 'Rechazadas',
    rejected: 'Rechazadas',
    rechazada: 'Rechazadas',
    incomplete: 'Parciales',
    parcial: 'Parciales',
    unreached: 'No Contestó',
    no_contesta: 'No Contestó',
    failed: 'Fallidas',
    fallida: 'Fallidas',
    initiated: 'Iniciadas',
    calling: 'Llamando',
    pending: 'Pendientes',
    unknown: 'Otros'
};

// Colores canónicos para el donut
const DISPOSITION_COLORS: Record<string, string> = {
    completed: '#10B981', completada: '#10B981',
    incomplete: '#F59E0B', parcial: '#F59E0B',
    rejected_opt_out: '#EF4444', rejected: '#EF4444', rechazada: '#EF4444',
    failed: '#8B5CF6', fallida: '#8B5CF6',
    unreached: '#F97316', no_contesta: '#F97316',
    initiated: '#6B7280', calling: '#3B82F6',
    pending: '#9CA3AF', unknown: '#D1D5DB'
};

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
    status_breakdown?: Record<string, number>;
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
        blue: 'bg-blue-50 text-blue-600',
        green: 'bg-green-50 text-green-600',
        purple: 'bg-purple-50 text-purple-600',
        orange: 'bg-orange-50 text-orange-600',
    };
    return (
        <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm">
            <div className="flex items-center justify-between mb-4">
                <div className={`p-3 rounded-lg ${colors[color]}`}>
                    <Icon size={24} />
                </div>
            </div>
            <h3 className="text-sm font-medium text-gray-500">{title}</h3>
            <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
        </div>
    );
};

const IntegrationCard: React.FC<Integration> = ({ name, provider, active, status }) => (
    <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl border border-gray-100 transition-all hover:bg-white hover:shadow-sm">
        <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${active ? 'bg-green-100 text-green-600' : 'bg-red-100 text-red-600'}`}>
                <Zap size={20} />
            </div>
            <div>
                <h4 className="text-sm font-bold text-gray-800">{name}</h4>
                <p className="text-[10px] text-gray-500 uppercase tracking-wider">{provider}</p>
            </div>
        </div>
        <div className="text-right">
            <span className={`text-[10px] font-bold px-2 py-1 rounded-full ${active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                {active ? 'ONLINE' : 'OFFLINE'}
            </span>
            {status && <p className="text-[10px] text-gray-400 mt-1">{status}</p>}
        </div>
    </div>
);

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

    useEffect(() => { loadData(); }, [profile, dateRange]);

    const loadData = async () => {
        try {
            setIsLoading(true);
            const params = new URLSearchParams();
            const finalEmpresaId = empresaId || (isPlatformOwner ? undefined : profile?.empresa_id);
            if (finalEmpresaId) params.append('empresa_id', String(finalEmpresaId));
            if (agentId) params.append('agent_id', String(agentId));
            if (campaignId) params.append('campaign_id', String(campaignId));
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
        const headers = [t("ID"), t("Teléfono / Campaña"), t("Fecha"), t("Estado"), t("Modelo AI")];
        const csvContent = [
            headers.join(","),
            ...recentCalls.map(c => [
                c.id,
                `"${c.phone} - ${c.campaign.replace(/"/g, '""')}"`,
                new Date(c.date).toLocaleString(),
                c.status,
                c.llm_model || "Standard"
            ].join(","))
        ].join("\n");
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement("a");
        link.setAttribute("href", URL.createObjectURL(blob));
        link.setAttribute("download", `dashboard_activity_${new Date().toISOString().split('T')[0]}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    // Datos para el donut chart desde status_breakdown
    const donutData = stats?.status_breakdown
        ? Object.entries(stats.status_breakdown)
            .map(([key, value]) => ({
                name: STATUS_LABELS[key] || key,
                value,
                key,
            }))
            .filter(d => d.value > 0)
            .sort((a, b) => b.value - a.value)
        : [];

    // Solo mostrar scores numéricos si hay datos reales (no ceros de una encuesta abierta)
    const hasNumericScores = stats?.avg_scores &&
        (stats.avg_scores.comercial > 0 || stats.avg_scores.instalador > 0 || stats.avg_scores.rapidez > 0);

    if (isLoading && !stats) return <div className="p-8 text-center text-gray-500">{t('Loading dashboard...', 'Cargando dashboard...')}</div>;

    return (
        <div className="space-y-8 animate-fade-in">
            {/* Header / Filter */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                {!title && (
                    <div className="flex items-center gap-3">
                        <img src="/ausarta.png" alt="Logo" className="h-10 w-auto object-contain dark:invert" />
                        <div>
                            <h2 className="text-3xl font-bold text-gray-900">{t('Admin Dashboard', 'Panel de Administración')}</h2>
                            <p className="text-gray-500 text-sm">{t('System health and global stats', 'Salud del sistema y estadísticas globales')}</p>
                        </div>
                    </div>
                )}
                {title && (
                    <div>
                        <h2 className="text-2xl font-bold text-gray-900">{title}</h2>
                        <p className="text-gray-500 mt-1 text-sm">{t('Activity summary', 'Resumen de actividad')}</p>
                    </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <DateRangePicker value={dateRange} onChange={setDateRange} />
                    <button
                        onClick={loadData}
                        className="p-2 border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
                        title={t('Refresh data', 'Refrescar datos')}
                    >
                        <RefreshCw size={18} className={isLoading ? "animate-spin" : "text-gray-500"} />
                    </button>
                </div>
            </div>

            {/* KPI Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
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
                {hasNumericScores ? (
                    <StatCard
                        title={t('Average Score', 'Nota Media')}
                        value={stats?.avg_scores?.overall || 0}
                        icon={BarChart2}
                        color="purple"
                    />
                ) : (
                    <StatCard
                        title={t('Completion Rate', 'Tasa Completadas')}
                        value={`${stats?.total_calls ? Math.round((stats.completed_calls / stats.total_calls) * 100) : 0}%`}
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

            {/* Charts Row: Donut + Scores / Rate */}
            {donutData.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Donut: Disposición de Llamadas */}
                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                        <h3 className="text-base font-bold text-gray-900 mb-4">{t('Estado de Llamadas')}</h3>
                        <div className="h-64 w-full relative">
                            <ResponsiveContainer width="100%" height="100%">
                                <PieChart>
                                    <Pie
                                        data={donutData}
                                        cx="50%"
                                        cy="50%"
                                        innerRadius={70}
                                        outerRadius={95}
                                        paddingAngle={3}
                                        dataKey="value"
                                        stroke="none"
                                    >
                                        {donutData.map((entry) => (
                                            <Cell key={entry.key} fill={DISPOSITION_COLORS[entry.key] || '#9CA3AF'} />
                                        ))}
                                    </Pie>
                                    <RechartsTooltip
                                        contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                                        formatter={(value: number) => [`${value} llamadas`, '']}
                                    />
                                    <Legend verticalAlign="bottom" height={36} />
                                </PieChart>
                            </ResponsiveContainer>
                            <div className="absolute inset-0 flex items-center justify-center flex-col pointer-events-none pb-8">
                                <span className="text-3xl font-bold text-gray-900">{stats?.total_calls || 0}</span>
                                <span className="text-[10px] text-gray-500 font-medium uppercase tracking-wider">{t('Total')}</span>
                            </div>
                        </div>
                    </div>

                    {/* Panel derecho: Scores numéricos SI existen, sino resumen de tasas */}
                    {hasNumericScores ? (
                        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                            <h3 className="text-base font-bold text-gray-900 mb-6">{t('Puntuaciones Medias')}</h3>
                            <div className="space-y-5">
                                {[
                                    { label: 'Comercial', value: stats!.avg_scores.comercial, color: 'blue' },
                                    { label: 'Instalador', value: stats!.avg_scores.instalador, color: 'green' },
                                    { label: 'Rapidez', value: stats!.avg_scores.rapidez, color: 'purple' },
                                ].filter(s => s.value > 0).map((s) => (
                                    <div key={s.label}>
                                        <div className="flex justify-between items-center mb-2">
                                            <span className="text-sm font-semibold text-gray-700">{s.label}</span>
                                            <span className="text-lg font-bold text-gray-900">{s.value}<span className="text-sm text-gray-400">/10</span></span>
                                        </div>
                                        <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
                                            <div
                                                className={`h-full rounded-full transition-all duration-1000 ${
                                                    s.color === 'blue' ? 'bg-blue-500' :
                                                    s.color === 'green' ? 'bg-green-500' : 'bg-purple-500'
                                                }`}
                                                style={{ width: `${(s.value / 10) * 100}%` }}
                                            />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ) : (
                        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 flex flex-col justify-center">
                            <h3 className="text-base font-bold text-gray-900 mb-6">{t('Resumen Operativo')}</h3>
                            <div className="grid grid-cols-2 gap-4">
                                {donutData.slice(0, 4).map((d) => (
                                    <div key={d.key} className="bg-gray-50 rounded-xl p-4 text-center border border-gray-100">
                                        <p className="text-2xl font-bold text-gray-900">{d.value}</p>
                                        <p className="text-xs text-gray-500 font-medium mt-1">{d.name}</p>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Main Content Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Integration Status & Supervision */}
                <div className="lg:col-span-1 space-y-8">
                    <LiveMonitoring />

                    {!hideIntegrations && (
                        <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm">
                            <h3 className="text-lg font-bold text-gray-800 mb-4">{t('Core Integrations', 'Integraciones Principales')}</h3>
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
                    <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                        <div className="flex justify-between items-center mb-6">
                            <h3 className="text-lg font-bold text-gray-800">{t('Latest Global Activity', 'Última Actividad Global')}</h3>
                            <button
                                onClick={exportCSV}
                                className="flex items-center gap-2 px-3 py-1.5 text-xs font-bold text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100 transition-all border border-blue-100"
                            >
                                <Download size={14} />
                                {t('Export CSV', 'Exportar CSV')}
                            </button>
                        </div>

                        <div className="overflow-x-auto">
                            <table className="w-full text-left">
                                <thead className="text-xs uppercase text-gray-400 border-b border-gray-50">
                                    <tr>
                                        <th className="pb-3 font-semibold">{t('Phone/Campaign')}</th>
                                        <th className="pb-3 font-semibold">{t('Date')}</th>
                                        <th className="pb-3 font-semibold">{t('Status')}</th>
                                        <th className="pb-3 font-semibold">{t('Model', 'Modelo')}</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-50">
                                    {recentCalls.map((call) => (
                                        <tr key={call.id} className="text-sm group hover:bg-gray-50">
                                            <td className="py-4">
                                                <div className="font-bold text-gray-800">{call.phone}</div>
                                                <div className="text-xs text-gray-400">{call.campaign}</div>
                                            </td>
                                            <td className="py-4 text-gray-500">
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

                                                    const cls = isCompleted ? 'bg-green-100 text-green-700'
                                                        : isPartial ? 'bg-orange-100 text-orange-700'
                                                        : isRejected ? 'bg-red-100 text-red-700'
                                                        : isNoAnswer ? 'bg-amber-100 text-amber-700'
                                                        : isFailed ? 'bg-purple-100 text-purple-700'
                                                        : 'bg-blue-100 text-blue-700';

                                                    const label = isCompleted ? t('Completada')
                                                        : isPartial ? t('Parcial')
                                                        : isRejected ? t('Rechazada')
                                                        : isNoAnswer ? t('No Contesta')
                                                        : isFailed ? t('Fallida')
                                                        : t('Pendiente');

                                                    return <span className={`px-2 py-1 rounded-full text-[10px] font-bold uppercase ${cls}`}>{label}</span>;
                                                })()}
                                            </td>
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
