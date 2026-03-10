import React, { useState, useEffect } from 'react';
import {
    Phone,
    CheckCircle,
    BarChart2,
    Timer,
    Zap,
    Download,
    RefreshCw,
    Trophy,
    Bot,
    Building2,
    FlaskConical
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
    completed: 'Completadas', completada: 'Completadas',
    rejected_opt_out: 'Rechazadas', rejected: 'Rechazadas', rechazada: 'Rechazadas',
    incomplete: 'Parciales', parcial: 'Parciales',
    unreached: 'No Contestó', no_contesta: 'No Contestó',
    failed: 'Fallidas', fallida: 'Fallidas',
    initiated: 'Iniciadas', calling: 'Llamando',
    pending: 'Pendientes', unknown: 'Otros'
};

const DISPOSITION_COLORS: Record<string, string> = {
    completed: '#10B981', completada: '#10B981',
    incomplete: '#F59E0B', parcial: '#F59E0B',
    rejected_opt_out: '#EF4444', rejected: '#EF4444', rechazada: '#EF4444',
    failed: '#8B5CF6', fallida: '#8B5CF6',
    unreached: '#F97316', no_contesta: '#F97316',
    initiated: '#6B7280', calling: '#3B82F6',
    pending: '#9CA3AF', unknown: '#D1D5DB'
};

const TIPO_LABELS: Record<string, { label: string; cls: string }> = {
    ENCUESTA_NUMERICA: { label: 'Numérica', cls: 'bg-green-50 text-green-700 border-green-200' },
    ENCUESTA_MIXTA: { label: 'Mixta', cls: 'bg-teal-50 text-teal-700 border-teal-200' },
    CUALIFICACION_LEAD: { label: 'Lead', cls: 'bg-orange-50 text-orange-700 border-orange-200' },
    AGENDAMIENTO_CITA: { label: 'Cita', cls: 'bg-purple-50 text-purple-700 border-purple-200' },
    SOPORTE_CLIENTE: { label: 'Soporte', cls: 'bg-blue-50 text-blue-700 border-blue-200' },
    PREGUNTAS_ABIERTAS: { label: 'Abierta', cls: 'bg-gray-50 text-gray-700 border-gray-200' },
};

interface DashboardStats {
    total_calls: number;
    completed_calls: number;
    pending_calls: number;
    avg_scores: { overall: number };
    status_breakdown?: Record<string, number>;
}

interface TopPerformer {
    id: number;
    name: string;
    completed: number;
    total: number;
    rate: number;
}

interface TopPerformers {
    top_campaign: TopPerformer | null;
    top_agent: TopPerformer | null;
}

interface Call {
    id: number;
    phone: string;
    campaign: string;
    campaign_id: number | null;
    date: string;
    status: string;
    llm_model: string;
    empresa_id: number | null;
    empresa_name: string;
    tipo_resultados: string | null;
    agent_name: string | null;
    is_test: boolean;
}

interface Integration {
    name: string;
    provider: string;
    active: boolean;
    status?: string | number;
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
        <div className="bg-white p-5 rounded-xl border border-gray-100 shadow-sm">
            <div className="flex items-center justify-between mb-3">
                <div className={`p-2.5 rounded-lg ${colors[color]}`}><Icon size={22} /></div>
            </div>
            <h3 className="text-sm font-medium text-gray-500">{title}</h3>
            <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
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
    const [topPerformers, setTopPerformers] = useState<TopPerformers>({ top_campaign: null, top_agent: null });
    const [integrations, setIntegrations] = useState<Integration[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [dateRange, setDateRange] = useState<DateRange>('7d');

    // Determinar si la vista es "global" (Ausarta ve todas las empresas)
    const isGlobalView = isPlatformOwner && !empresaId;

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

            const [statsRes, callsRes, topRes, intRes] = await Promise.all([
                fetch(`${API_URL}/api/dashboard/stats${queryStr}`),
                fetch(`${API_URL}/api/dashboard/recent-calls${queryStr}`),
                fetch(`${API_URL}/api/dashboard/top-performers${queryStr}`),
                hideIntegrations ? Promise.resolve({ ok: true, json: () => [] }) : fetch(`${API_URL}/api/dashboard/integrations`)
            ]);

            if (statsRes.ok) setStats(await statsRes.json());
            if (callsRes.ok) setRecentCalls(await callsRes.json());
            if (topRes.ok) setTopPerformers(await topRes.json());
            if (intRes.ok && !hideIntegrations) setIntegrations(await intRes.json());
        } catch (error) {
            console.error('Error loading dashboard data:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const exportCSV = () => {
        const headers = [t("ID"), t("Teléfono"), t("Campaña"), t("Empresa"), t("Tipo"), t("Fecha"), t("Estado"), t("Modelo")];
        const csvContent = [
            headers.join(","),
            ...recentCalls.map(c => [
                c.id,
                c.phone,
                `"${(c.campaign || '').replace(/"/g, '""')}"`,
                `"${c.empresa_name}"`,
                c.tipo_resultados || '',
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

    const donutData = stats?.status_breakdown
        ? Object.entries(stats.status_breakdown)
            .map(([key, value]) => ({ name: STATUS_LABELS[key] || key, value, key }))
            .filter(d => d.value > 0)
            .sort((a, b) => b.value - a.value)
        : [];

    const completionRate = stats?.total_calls ? Math.round((stats.completed_calls / stats.total_calls) * 100) : 0;

    if (isLoading && !stats) return <div className="p-8 text-center text-gray-500">{t('Cargando dashboard...')}</div>;

    return (
        <div className="space-y-6 animate-fade-in">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                {!title ? (
                    <div className="flex items-center gap-3">
                        <img src="/ausarta.png" alt="Logo" className="h-10 w-auto object-contain" />
                        <div>
                            <h2 className="text-3xl font-bold text-gray-900">{t('Panel de Administración')}</h2>
                            <p className="text-gray-500 text-sm">{t('Salud del sistema y estadísticas globales')}</p>
                        </div>
                    </div>
                ) : (
                    <div>
                        <h2 className="text-2xl font-bold text-gray-900">{title}</h2>
                        <p className="text-gray-500 mt-1 text-sm">{t('Resumen de actividad')}</p>
                    </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <DateRangePicker value={dateRange} onChange={setDateRange} />
                    <button onClick={loadData} className="p-2 border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors" title={t('Refrescar')}>
                        <RefreshCw size={18} className={isLoading ? "animate-spin" : "text-gray-500"} />
                    </button>
                </div>
            </div>

            {/* KPI Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard title={t('Llamadas Globales')} value={stats?.total_calls || 0} icon={Phone} color="blue" />
                <StatCard title={t('Completadas')} value={stats?.completed_calls || 0} icon={CheckCircle} color="green" />
                <StatCard title={t('Tasa Completadas')} value={`${completionRate}%`} icon={BarChart2} color="purple" />
                <StatCard title={t('En Curso')} value={stats?.pending_calls || 0} icon={Timer} color="orange" />
            </div>

            {/* Donut + Top Performers */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Donut Chart */}
                {donutData.length > 0 && (
                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                        <h3 className="text-base font-bold text-gray-900 mb-4">{t('Estado de Llamadas')}</h3>
                        <div className="h-64 w-full relative">
                            <ResponsiveContainer width="100%" height="100%">
                                <PieChart>
                                    <Pie data={donutData} cx="50%" cy="50%" innerRadius={68} outerRadius={92} paddingAngle={3} dataKey="value" stroke="none">
                                        {donutData.map((entry) => (
                                            <Cell key={entry.key} fill={DISPOSITION_COLORS[entry.key] || '#9CA3AF'} />
                                        ))}
                                    </Pie>
                                    <RechartsTooltip contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} formatter={(value: number) => [`${value} llamadas`, '']} />
                                    <Legend verticalAlign="bottom" height={36} />
                                </PieChart>
                            </ResponsiveContainer>
                            <div className="absolute inset-0 flex items-center justify-center flex-col pointer-events-none pb-8">
                                <span className="text-3xl font-bold text-gray-900">{stats?.total_calls || 0}</span>
                                <span className="text-[10px] text-gray-500 font-medium uppercase tracking-wider">Total</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* Top Performers: Campaña y Agente */}
                <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 flex flex-col justify-between">
                    <h3 className="text-base font-bold text-gray-900 mb-5">{t('Top Performers')}</h3>
                    <div className="space-y-4 flex-1">
                        {/* Top Campaña */}
                        <div className="p-4 rounded-xl bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-100">
                            <div className="flex items-center gap-2 mb-2">
                                <Trophy size={18} className="text-amber-600" />
                                <span className="text-xs font-bold text-amber-700 uppercase tracking-wider">{t('Campaña Más Exitosa')}</span>
                            </div>
                            {topPerformers.top_campaign ? (
                                <div>
                                    <p className="font-bold text-gray-900 text-lg truncate">{topPerformers.top_campaign.name}</p>
                                    <div className="flex items-center gap-3 mt-2">
                                        <span className="text-2xl font-extrabold text-amber-600">{topPerformers.top_campaign.rate}%</span>
                                        <span className="text-xs text-gray-500">{topPerformers.top_campaign.completed}/{topPerformers.top_campaign.total} completadas</span>
                                    </div>
                                    <div className="mt-2 h-2 bg-amber-100 rounded-full overflow-hidden">
                                        <div className="h-full bg-amber-500 rounded-full transition-all duration-1000" style={{ width: `${topPerformers.top_campaign.rate}%` }} />
                                    </div>
                                </div>
                            ) : (
                                <p className="text-sm text-gray-400 italic mt-2">{t('Sin datos suficientes')}</p>
                            )}
                        </div>

                        {/* Top Agente */}
                        <div className="p-4 rounded-xl bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-100">
                            <div className="flex items-center gap-2 mb-2">
                                <Bot size={18} className="text-indigo-600" />
                                <span className="text-xs font-bold text-indigo-700 uppercase tracking-wider">{t('Agente Más Exitoso')}</span>
                            </div>
                            {topPerformers.top_agent ? (
                                <div>
                                    <p className="font-bold text-gray-900 text-lg truncate">{topPerformers.top_agent.name}</p>
                                    <div className="flex items-center gap-3 mt-2">
                                        <span className="text-2xl font-extrabold text-indigo-600">{topPerformers.top_agent.rate}%</span>
                                        <span className="text-xs text-gray-500">{topPerformers.top_agent.completed}/{topPerformers.top_agent.total} completadas</span>
                                    </div>
                                    <div className="mt-2 h-2 bg-indigo-100 rounded-full overflow-hidden">
                                        <div className="h-full bg-indigo-500 rounded-full transition-all duration-1000" style={{ width: `${topPerformers.top_agent.rate}%` }} />
                                    </div>
                                </div>
                            ) : (
                                <p className="text-sm text-gray-400 italic mt-2">{t('Sin datos suficientes')}</p>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Main Content Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Supervision & Integrations */}
                <div className="lg:col-span-1 space-y-6">
                    <LiveMonitoring />
                    {!hideIntegrations && integrations.length > 0 && (
                        <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm">
                            <h3 className="text-lg font-bold text-gray-800 mb-4">{t('Integraciones')}</h3>
                            <div className="space-y-3">
                                {integrations.map((int, i) => (
                                    <div key={i} className="flex items-center justify-between p-3 bg-gray-50 rounded-xl border border-gray-100">
                                        <div className="flex items-center gap-3">
                                            <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${int.active ? 'bg-green-100 text-green-600' : 'bg-red-100 text-red-600'}`}>
                                                <Zap size={18} />
                                            </div>
                                            <div>
                                                <h4 className="text-sm font-bold text-gray-800">{int.name}</h4>
                                                <p className="text-[10px] text-gray-500 uppercase">{int.provider}</p>
                                            </div>
                                        </div>
                                        <span className={`text-[10px] font-bold px-2 py-1 rounded-full ${int.active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                                            {int.active ? 'ONLINE' : 'OFFLINE'}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* Recent Activity - ENRICHED */}
                <div className="lg:col-span-2">
                    <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                        <div className="flex justify-between items-center mb-5">
                            <h3 className="text-lg font-bold text-gray-800">{t('Última Actividad Global')}</h3>
                            <button onClick={exportCSV} className="flex items-center gap-2 px-3 py-1.5 text-xs font-bold text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100 transition-all border border-blue-100">
                                <Download size={14} /> {t('Exportar CSV')}
                            </button>
                        </div>
                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-sm">
                                <thead className="text-xs uppercase text-gray-400 border-b border-gray-100">
                                    <tr>
                                        <th className="pb-3 font-semibold">{t('Teléfono')}</th>
                                        {isGlobalView && <th className="pb-3 font-semibold">{t('Empresa')}</th>}
                                        <th className="pb-3 font-semibold">{t('Campaña / Tipo')}</th>
                                        <th className="pb-3 font-semibold">{t('Fecha')}</th>
                                        <th className="pb-3 font-semibold text-center">{t('Estado')}</th>
                                        <th className="pb-3 font-semibold">{t('Modelo')}</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-50">
                                    {recentCalls.map((call) => {
                                        const tipoInfo = TIPO_LABELS[call.tipo_resultados || ''] || { label: call.tipo_resultados || '—', cls: 'bg-gray-50 text-gray-600 border-gray-200' };
                                        return (
                                            <tr key={call.id} className="group hover:bg-gray-50/50 transition-colors">
                                                <td className="py-3">
                                                    <div className="font-bold text-gray-800">{call.phone}</div>
                                                </td>
                                                {isGlobalView && (
                                                    <td className="py-3">
                                                        <div className="flex items-center gap-1.5">
                                                            <Building2 size={12} className="text-gray-400" />
                                                            <span className="text-xs text-gray-600 font-medium truncate max-w-[100px]">{call.empresa_name}</span>
                                                        </div>
                                                    </td>
                                                )}
                                                <td className="py-3">
                                                    <div className="flex flex-col gap-1">
                                                        <div className="flex items-center gap-1.5">
                                                            {call.is_test ? (
                                                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold bg-yellow-50 text-yellow-700 border border-yellow-200">
                                                                    <FlaskConical size={9} /> PRUEBA
                                                                </span>
                                                            ) : (
                                                                <span className="text-xs text-gray-700 font-medium truncate max-w-[120px]">{call.campaign || '—'}</span>
                                                            )}
                                                        </div>
                                                        <span className={`inline-flex self-start items-center px-1.5 py-0.5 rounded text-[9px] font-bold border ${tipoInfo.cls}`}>
                                                            {tipoInfo.label}
                                                        </span>
                                                    </div>
                                                </td>
                                                <td className="py-3 text-gray-500 text-xs whitespace-nowrap">
                                                    {new Date(call.date).toLocaleDateString()} <span className="text-gray-400">{new Date(call.date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                                                </td>
                                                <td className="py-3 text-center">
                                                    {(() => {
                                                        const s = (call.status || '').toLowerCase();
                                                        const cls = (s === 'completada' || s === 'completed') ? 'bg-green-100 text-green-700'
                                                            : (s === 'parcial' || s === 'incomplete') ? 'bg-orange-100 text-orange-700'
                                                            : (s === 'rechazada' || s === 'rejected' || s === 'rejected_opt_out') ? 'bg-red-100 text-red-700'
                                                            : (s === 'no_contesta' || s === 'unreached') ? 'bg-amber-100 text-amber-700'
                                                            : (s === 'fallida' || s === 'failed') ? 'bg-purple-100 text-purple-700'
                                                            : 'bg-gray-100 text-gray-600';
                                                        const label = (s === 'completada' || s === 'completed') ? 'Completada'
                                                            : (s === 'parcial' || s === 'incomplete') ? 'Parcial'
                                                            : (s === 'rechazada' || s === 'rejected' || s === 'rejected_opt_out') ? 'Rechazada'
                                                            : (s === 'no_contesta' || s === 'unreached') ? 'No Contesta'
                                                            : (s === 'fallida' || s === 'failed') ? 'Fallida'
                                                            : (call.status || 'Pendiente');
                                                        return <span className={`px-2 py-1 rounded-full text-[10px] font-bold uppercase ${cls}`}>{label}</span>;
                                                    })()}
                                                </td>
                                                <td className="py-3">
                                                    <span className="text-[10px] text-gray-400 flex items-center gap-1"><Zap size={10} /> {call.llm_model || 'GPT-4o'}</span>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                            {recentCalls.length === 0 && (
                                <div className="text-center py-12 text-gray-400 italic">{t('Sin actividad reciente')}</div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default AdminDashboard;
