import React, { useMemo, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer,
    PieChart, Pie, Cell
} from 'recharts';
import { Target, MessageCircle, Star, Clock, UserCheck, Database, Zap } from 'lucide-react';
import { SurveyResult, getCallDisposition } from '../types';

interface AnalyticsProps {
    tipoResultados: string;
    results: SurveyResult[];
}

const DISPOSITION_COLORS: Record<string, string> = {
    completed: '#10B981',
    incomplete: '#F59E0B',
    rejected: '#EF4444',
    failed: '#8B5CF6',
    pending: '#9CA3AF',
};

const DISPOSITION_LABELS: Record<string, string> = {
    completed: 'Completada',
    incomplete: 'Parcial',
    rejected: 'Rechazada',
    failed: 'Fallida / No Contesta',
    pending: 'Pendiente',
};

interface InsightItem {
    id: number;
    telefono: string;
    fecha: string;
    status: string;
    campaign_name?: string;
    keys: string[];
    datos_extra: Record<string, any>;
}

function prettifyKey(raw: string): string {
    return raw
        .replace(/_/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (c) => c.toUpperCase());
}

export const AnalyticsDashboard: React.FC<AnalyticsProps> = ({ tipoResultados, results }) => {
    const { t } = useTranslation();
    const [insights, setInsights] = useState<InsightItem[]>([]);

    // Gráfico 1: Distribución por disposición (usa TODOS los resultados)
    const dispositionData = useMemo(() => {
        const counts: Record<string, number> = {};
        results.forEach(r => {
            const disp = getCallDisposition(r.status);
            counts[disp] = (counts[disp] || 0) + 1;
        });
        return Object.entries(counts)
            .map(([key, value]) => ({
                name: DISPOSITION_LABELS[key] || key,
                value,
                key,
            }))
            .filter(d => d.value > 0)
            .sort((a, b) => b.value - a.value);
    }, [results]);

    const totalCalls = results.length;

    // Gráfico 2: Medias numéricas (solo filas con valores reales)
    const scoreData = useMemo(() => {
        let comSum = 0, insSum = 0, rapSum = 0;
        let comCount = 0, insCount = 0, rapCount = 0;

        results.forEach(r => {
            if (r.puntuacion_comercial != null && r.puntuacion_comercial > 0) {
                comSum += r.puntuacion_comercial;
                comCount++;
            }
            if (r.puntuacion_instalador != null && r.puntuacion_instalador > 0) {
                insSum += r.puntuacion_instalador;
                insCount++;
            }
            if (r.puntuacion_rapidez != null && r.puntuacion_rapidez > 0) {
                rapSum += r.puntuacion_rapidez;
                rapCount++;
            }
        });

        return {
            avgCom: comCount > 0 ? +(comSum / comCount).toFixed(1) : null,
            avgIns: insCount > 0 ? +(insSum / insCount).toFixed(1) : null,
            avgRap: rapCount > 0 ? +(rapSum / rapCount).toFixed(1) : null,
            countCom: comCount,
            countIns: insCount,
            countRap: rapCount,
        };
    }, [results]);

    const hasNumericData = scoreData.avgCom !== null || scoreData.avgIns !== null || scoreData.avgRap !== null;

    // Evolución temporal de puntuaciones (solo para numéricas/mixtas)
    const chartData = useMemo(() => {
        if (!hasNumericData) return [];

        const chartDataMap: Record<string, { name: string, comercial: number, instalador: number, rapidez: number, cCom: number, cIns: number, cRap: number }> = {};
        results.forEach(r => {
            const date = new Date(r.fecha);
            const key = `${date.getDate()}/${date.getMonth() + 1}`;
            if (!chartDataMap[key]) {
                chartDataMap[key] = { name: key, comercial: 0, instalador: 0, rapidez: 0, cCom: 0, cIns: 0, cRap: 0 };
            }
            if (r.puntuacion_comercial != null && r.puntuacion_comercial > 0) {
                chartDataMap[key].comercial += r.puntuacion_comercial;
                chartDataMap[key].cCom++;
            }
            if (r.puntuacion_instalador != null && r.puntuacion_instalador > 0) {
                chartDataMap[key].instalador += r.puntuacion_instalador;
                chartDataMap[key].cIns++;
            }
            if (r.puntuacion_rapidez != null && r.puntuacion_rapidez > 0) {
                chartDataMap[key].rapidez += r.puntuacion_rapidez;
                chartDataMap[key].cRap++;
            }
        });

        return Object.values(chartDataMap).map(d => ({
            name: d.name,
            comercial: d.cCom ? +(d.comercial / d.cCom).toFixed(1) : 0,
            instalador: d.cIns ? +(d.instalador / d.cIns).toFixed(1) : 0,
            rapidez: d.cRap ? +(d.rapidez / d.cRap).toFixed(1) : 0,
        })).slice(-10);
    }, [results, hasNumericData]);

    // Cualificación de leads
    const leadData = useMemo(() => {
        if (tipoResultados !== 'CUALIFICACION_LEAD') return null;
        let hot = 0, cold = 0;
        results.forEach(r => {
            if (r.status !== 'completed' && r.status !== 'completada') return;
            const data = r.datos_extra || {};
            if (data.lead_cualificado === true) hot++;
            else if (data.lead_cualificado === false) cold++;
        });
        if (hot === 0 && cold === 0) return null;
        return { hot, cold, rate: Math.round((hot / (hot + cold)) * 100) };
    }, [results, tipoResultados]);

    // Insights recientes (datos extra) - computados localmente de los resultados ya cargados
    const localInsights = useMemo(() => {
        return results
            .filter(r => r.datos_extra && typeof r.datos_extra === 'object' && Object.keys(r.datos_extra).length > 0)
            .slice(0, 5)
            .map(r => ({
                id: r.id,
                telefono: r.telefono,
                fecha: r.fecha,
                status: r.status || 'pending',
                campaign_name: r.campaign_name,
                keys: Object.keys(r.datos_extra!).slice(0, 4),
                datos_extra: r.datos_extra!,
            }));
    }, [results]);

    const displayInsights = localInsights.length > 0 ? localInsights : insights;

    // Preguntas abiertas relevantes
    const relevantComments = useMemo(() => {
        if (tipoResultados !== 'PREGUNTAS_ABIERTAS' && tipoResultados !== 'SOPORTE_CLIENTE') return [];
        return [...results]
            .filter(r => r.comentarios && r.comentarios !== "Sin comentarios" && (r.status === 'completed' || r.status === 'completada'))
            .sort((a, b) => (b.comentarios?.length || 0) - (a.comentarios?.length || 0))
            .slice(0, 4);
    }, [results, tipoResultados]);

    if (results.length === 0) return null;

    return (
        <div className="space-y-6 mb-8">
            {/* Fila de KPIs rápidos */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
                    <p className="text-xs text-gray-500 font-medium mb-1">{t('Total Llamadas')}</p>
                    <h3 className="text-2xl font-bold text-gray-900">{totalCalls}</h3>
                </div>
                <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
                    <p className="text-xs text-gray-500 font-medium mb-1">{t('Completadas')}</p>
                    <h3 className="text-2xl font-bold text-green-600">
                        {dispositionData.find(d => d.key === 'completed')?.value || 0}
                        <span className="text-sm text-gray-400 font-normal ml-1">
                            ({totalCalls > 0 ? Math.round(((dispositionData.find(d => d.key === 'completed')?.value || 0) / totalCalls) * 100) : 0}%)
                        </span>
                    </h3>
                </div>
                {hasNumericData && scoreData.avgCom !== null && (
                    <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 flex items-center gap-3">
                        <div className="bg-blue-50 p-2.5 rounded-xl">
                            <Star className="text-blue-500 w-5 h-5" />
                        </div>
                        <div>
                            <p className="text-xs text-gray-500 font-medium">{t('Media Comercial')}</p>
                            <h3 className="text-xl font-bold text-gray-900">{scoreData.avgCom} <span className="text-sm text-gray-400">/10</span></h3>
                        </div>
                    </div>
                )}
                {hasNumericData && scoreData.avgRap !== null && (
                    <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 flex items-center gap-3">
                        <div className="bg-purple-50 p-2.5 rounded-xl">
                            <Zap className="text-purple-500 w-5 h-5" />
                        </div>
                        <div>
                            <p className="text-xs text-gray-500 font-medium">{t('Media Rapidez')}</p>
                            <h3 className="text-xl font-bold text-gray-900">{scoreData.avgRap} <span className="text-sm text-gray-400">/10</span></h3>
                        </div>
                    </div>
                )}
                {!hasNumericData && leadData && (
                    <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 flex items-center gap-3">
                        <div className="bg-green-50 p-2.5 rounded-xl">
                            <Target className="text-green-500 w-5 h-5" />
                        </div>
                        <div>
                            <p className="text-xs text-gray-500 font-medium">{t('Leads Hot')}</p>
                            <h3 className="text-xl font-bold text-green-600">{leadData.hot}</h3>
                        </div>
                    </div>
                )}
                {!hasNumericData && !leadData && (
                    <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 flex items-center gap-3">
                        <div className="bg-indigo-50 p-2.5 rounded-xl">
                            <Database className="text-indigo-500 w-5 h-5" />
                        </div>
                        <div>
                            <p className="text-xs text-gray-500 font-medium">{t('Con Datos Extra')}</p>
                            <h3 className="text-xl font-bold text-gray-900">{displayInsights.length}</h3>
                        </div>
                    </div>
                )}
            </div>

            {/* Fila principal: Donut + Barras/Cualificación */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Gráfico 1: Donut de Disposición */}
                <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                    <h3 className="text-base font-bold text-gray-900 mb-4">{t('Estado de Llamadas')}</h3>
                    <div className="h-64 w-full relative">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={dispositionData}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={70}
                                    outerRadius={95}
                                    paddingAngle={3}
                                    dataKey="value"
                                    stroke="none"
                                >
                                    {dispositionData.map((entry) => (
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
                            <span className="text-3xl font-bold text-gray-900">{totalCalls}</span>
                            <span className="text-[10px] text-gray-500 font-medium uppercase tracking-wider">{t('Total')}</span>
                        </div>
                    </div>
                </div>

                {/* Gráfico 2: Barras numéricas O Cualificación O Comentarios */}
                {hasNumericData && chartData.length > 0 ? (
                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                        <h3 className="text-base font-bold text-gray-900 mb-4">{t('Satisfacción Media')}</h3>
                        <div className="h-64 w-full">
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E5E7EB" />
                                    <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#6B7280', fontSize: 12 }} dy={10} />
                                    <YAxis axisLine={false} tickLine={false} tick={{ fill: '#6B7280', fontSize: 12 }} domain={[0, 10]} />
                                    <RechartsTooltip cursor={{ fill: '#F3F4F6' }} contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} />
                                    <Legend wrapperStyle={{ paddingTop: '12px' }} />
                                    {scoreData.avgCom !== null && <Bar dataKey="comercial" name="Comercial" fill="#3B82F6" radius={[4, 4, 0, 0]} maxBarSize={40} />}
                                    {scoreData.avgIns !== null && <Bar dataKey="instalador" name="Instalador" fill="#10B981" radius={[4, 4, 0, 0]} maxBarSize={40} />}
                                    {scoreData.avgRap !== null && <Bar dataKey="rapidez" name="Rapidez" fill="#8B5CF6" radius={[4, 4, 0, 0]} maxBarSize={40} />}
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    </div>
                ) : leadData ? (
                    <div className="bg-gradient-to-br from-gray-900 to-black rounded-2xl p-8 shadow-md text-white flex flex-col justify-center relative overflow-hidden">
                        <div className="absolute top-0 right-0 -mt-4 -mr-4 bg-emerald-500 w-32 h-32 rounded-full blur-3xl opacity-20"></div>
                        <Target className="w-10 h-10 text-emerald-400 mb-4" />
                        <h4 className="text-xl font-bold mb-2">{t('Ratio Cualificación')}</h4>
                        <p className="text-gray-400 mb-6 text-sm">
                            <strong className="text-white">{leadData.hot} leads calientes</strong> ({leadData.rate}% tasa) de {leadData.hot + leadData.cold} evaluados.
                        </p>
                        <div className="grid grid-cols-2 gap-3">
                            <div className="bg-white/10 p-4 rounded-xl backdrop-blur-sm border border-white/5">
                                <p className="text-gray-400 text-xs mb-1">Hot</p>
                                <p className="text-2xl font-bold text-emerald-400">{leadData.hot}</p>
                            </div>
                            <div className="bg-white/10 p-4 rounded-xl backdrop-blur-sm border border-white/5">
                                <p className="text-gray-400 text-xs mb-1">Descartados</p>
                                <p className="text-2xl font-bold text-rose-400">{leadData.cold}</p>
                            </div>
                        </div>
                    </div>
                ) : relevantComments.length > 0 ? (
                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 overflow-hidden">
                        <div className="flex items-center gap-2 mb-4">
                            <MessageCircle className="w-5 h-5 text-blue-500" />
                            <h3 className="text-base font-bold text-gray-900">{t('Comentarios Relevantes')}</h3>
                        </div>
                        <div className="space-y-3 max-h-56 overflow-y-auto pr-1">
                            {relevantComments.map((r) => (
                                <div key={r.id} className="p-3 rounded-xl border border-gray-100 bg-gray-50/50">
                                    <div className="flex justify-between items-center mb-1.5">
                                        <span className="text-xs font-medium text-gray-900">{r.telefono}</span>
                                        <span className="text-[10px] text-gray-400">{new Date(r.fecha).toLocaleDateString()}</span>
                                    </div>
                                    <p className="text-xs text-gray-600 italic leading-relaxed line-clamp-2">"{r.comentarios}"</p>
                                </div>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 flex flex-col items-center justify-center text-center">
                        <Database className="w-10 h-10 text-gray-300 mb-3" />
                        <p className="text-sm text-gray-500 font-medium">{t('Los datos detallados se mostrarán aquí cuando haya más llamadas.')}</p>
                    </div>
                )}
            </div>

            {/* Sección de Insights Recientes (datos_extra) */}
            {displayInsights.length > 0 && (
                <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                    <div className="flex items-center gap-2 mb-4">
                        <Database className="w-5 h-5 text-indigo-500" />
                        <h3 className="text-base font-bold text-gray-900">{t('Datos Extra Recientes')}</h3>
                        <span className="bg-indigo-100 text-indigo-700 text-[10px] font-bold px-2 py-0.5 rounded-full uppercase">{displayInsights.length} últimas</span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {displayInsights.map((item) => (
                            <div key={item.id} className="p-4 rounded-xl border border-gray-100 bg-gray-50/50 hover:bg-gray-50 transition-colors">
                                <div className="flex justify-between items-start mb-2">
                                    <div>
                                        <span className="text-sm font-semibold text-gray-900">{item.telefono}</span>
                                        {item.campaign_name && (
                                            <span className="text-[10px] text-blue-600 font-bold uppercase ml-2">{item.campaign_name}</span>
                                        )}
                                    </div>
                                    <span className="text-[10px] text-gray-400">{new Date(item.fecha).toLocaleDateString()}</span>
                                </div>
                                <div className="flex flex-wrap gap-1.5">
                                    {item.keys.map((key) => (
                                        <span
                                            key={key}
                                            className="inline-flex items-center px-2 py-0.5 rounded-md bg-indigo-50 border border-indigo-100 text-[10px] text-indigo-700 font-medium"
                                            title={`${prettifyKey(key)}: ${JSON.stringify(item.datos_extra[key])}`}
                                        >
                                            {prettifyKey(key)}
                                        </span>
                                    ))}
                                    {Object.keys(item.datos_extra).length > 4 && (
                                        <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-gray-100 text-[10px] text-gray-500 font-medium">
                                            +{Object.keys(item.datos_extra).length - 4} más
                                        </span>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};
