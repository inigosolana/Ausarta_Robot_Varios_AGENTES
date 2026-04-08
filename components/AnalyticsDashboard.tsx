import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
    ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from 'recharts';
import { Database, Hash, ToggleLeft, AlignLeft, List } from 'lucide-react';
import { SurveyResult, getCallDisposition, ExtractionSchemaProperty } from '../types';

interface AnalyticsProps {
    tipoResultados: string;
    results: SurveyResult[];
    schema?: ExtractionSchemaProperty[];
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

const CHART_COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#14B8A6', '#F97316'];

interface InsightItem {
    id: number;
    telefono: string;
    fecha: string;
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

// ─── Widget: Boolean ──────────────────────────────────────────────────────────

interface WidgetProps {
    field: ExtractionSchemaProperty;
    completedResults: SurveyResult[];
}

const BooleanWidget: React.FC<WidgetProps> = ({ field, completedResults }) => {
    const data = useMemo(() => {
        let trueCount = 0, falseCount = 0;
        completedResults.forEach(r => {
            const val = r.datos_extra?.[field.key];
            if (val === true || val === 'true' || val === 'si' || val === 'sí' || val === '1' || val === 1)
                trueCount++;
            else if (val === false || val === 'false' || val === 'no' || val === '0' || val === 0)
                falseCount++;
        });
        if (trueCount === 0 && falseCount === 0) return null;
        return [
            { name: 'Sí', value: trueCount },
            { name: 'No', value: falseCount },
        ];
    }, [completedResults, field.key]);

    if (!data) return null;

    const PIE_COLORS = ['#10B981', '#EF4444'];
    const total = data[0].value + data[1].value;

    return (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <div className="flex items-center gap-2 mb-4">
                <ToggleLeft className="w-4 h-4 text-emerald-500" />
                <h3 className="text-base font-bold text-gray-900">{field.label}</h3>
                <span className="ml-auto text-xs text-gray-400 font-medium">{total} resp.</span>
            </div>
            <div className="flex items-center gap-4">
                <div className="h-36 w-36 flex-shrink-0">
                    <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                            <Pie
                                data={data}
                                cx="50%" cy="50%"
                                innerRadius={40} outerRadius={58}
                                paddingAngle={3}
                                dataKey="value"
                                stroke="none"
                            >
                                {data.map((_, i) => <Cell key={i} fill={PIE_COLORS[i]} />)}
                            </Pie>
                            <RechartsTooltip
                                contentStyle={{ borderRadius: '10px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                            />
                        </PieChart>
                    </ResponsiveContainer>
                </div>
                <div className="flex flex-col gap-3 flex-1">
                    {data.map((d, i) => (
                        <div key={d.name} className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: PIE_COLORS[i] }} />
                                <span className="text-sm text-gray-700 font-medium">{d.name}</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <span className="text-xl font-bold text-gray-900">{d.value}</span>
                                <span className="text-xs text-gray-400">
                                    ({total > 0 ? Math.round((d.value / total) * 100) : 0}%)
                                </span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
};

// ─── Widget: Number ───────────────────────────────────────────────────────────

const NumberWidget: React.FC<WidgetProps> = ({ field, completedResults }) => {
    const { avg, distribution } = useMemo(() => {
        const values: number[] = [];
        completedResults.forEach(r => {
            const val = r.datos_extra?.[field.key];
            const num = typeof val === 'number' ? val : parseFloat(String(val));
            if (!isNaN(num)) values.push(num);
        });
        if (values.length === 0) return { avg: null, distribution: [] };

        const avg = +(values.reduce((s, v) => s + v, 0) / values.length).toFixed(2);

        const uniqueVals = [...new Set(values)].sort((a, b) => a - b);
        let distribution: { name: string; count: number }[];

        if (uniqueVals.length <= 15) {
            const counts: Record<string, number> = {};
            values.forEach(v => { counts[String(v)] = (counts[String(v)] || 0) + 1; });
            distribution = uniqueVals.map(v => ({ name: String(v), count: counts[String(v)] || 0 }));
        } else {
            const min = uniqueVals[0];
            const max = uniqueVals[uniqueVals.length - 1];
            const step = (max - min) / 8;
            const buckets: Record<string, number> = {};
            values.forEach(v => {
                const bi = step > 0 ? Math.min(7, Math.floor((v - min) / step)) : 0;
                const label = step > 0
                    ? `${+(min + bi * step).toFixed(1)}`
                    : String(v);
                buckets[label] = (buckets[label] || 0) + 1;
            });
            distribution = Object.entries(buckets).map(([name, count]) => ({ name, count }));
        }

        return { avg, distribution };
    }, [completedResults, field.key]);

    if (avg === null) return null;

    return (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <div className="flex items-center gap-2 mb-4">
                <Hash className="w-4 h-4 text-blue-500" />
                <h3 className="text-base font-bold text-gray-900">{field.label}</h3>
            </div>
            <div className="flex items-start gap-6">
                <div className="flex flex-col items-center justify-center bg-blue-50 rounded-2xl p-4 min-w-[88px]">
                    <span className="text-3xl font-bold text-blue-700">{avg}</span>
                    <span className="text-[10px] text-blue-500 font-semibold uppercase tracking-wider mt-1">Media</span>
                </div>
                {distribution.length > 1 && (
                    <div className="flex-1 h-28">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={distribution} margin={{ top: 4, right: 4, left: -32, bottom: 0 }}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E5E7EB" />
                                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#9CA3AF', fontSize: 10 }} />
                                <YAxis axisLine={false} tickLine={false} tick={{ fill: '#9CA3AF', fontSize: 10 }} />
                                <RechartsTooltip
                                    contentStyle={{ borderRadius: '10px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                                    formatter={(v: number) => [v, 'Frecuencia']}
                                />
                                <Bar dataKey="count" fill="#3B82F6" radius={[4, 4, 0, 0]} maxBarSize={32} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                )}
            </div>
        </div>
    );
};

// ─── Widget: Enum ─────────────────────────────────────────────────────────────

const EnumWidget: React.FC<WidgetProps> = ({ field, completedResults }) => {
    const data = useMemo(() => {
        const counts: Record<string, number> = {};
        completedResults.forEach(r => {
            const val = r.datos_extra?.[field.key];
            if (val != null && val !== '') {
                const key = String(val).trim();
                counts[key] = (counts[key] || 0) + 1;
            }
        });
        return Object.entries(counts)
            .map(([name, value]) => ({ name, value }))
            .sort((a, b) => b.value - a.value);
    }, [completedResults, field.key]);

    if (data.length === 0) return null;

    const chartHeight = Math.max(160, data.length * 40);

    return (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <div className="flex items-center gap-2 mb-4">
                <List className="w-4 h-4 text-purple-500" />
                <h3 className="text-base font-bold text-gray-900">{field.label}</h3>
                <span className="ml-auto text-xs text-gray-400 font-medium">{data.length} opciones</span>
            </div>
            <div style={{ height: chartHeight }}>
                <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data} layout="vertical" margin={{ top: 0, right: 24, left: 8, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#E5E7EB" />
                        <XAxis
                            type="number"
                            axisLine={false} tickLine={false}
                            tick={{ fill: '#9CA3AF', fontSize: 11 }}
                            allowDecimals={false}
                        />
                        <YAxis
                            type="category" dataKey="name"
                            axisLine={false} tickLine={false}
                            tick={{ fill: '#374151', fontSize: 11 }}
                            width={100}
                        />
                        <RechartsTooltip
                            contentStyle={{ borderRadius: '10px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                            formatter={(v: number) => [v, 'Respuestas']}
                        />
                        <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={28}>
                            {data.map((_, index) => (
                                <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                            ))}
                        </Bar>
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
};

// ─── Widget: Text ─────────────────────────────────────────────────────────────

const TextWidget: React.FC<WidgetProps> = ({ field, completedResults }) => {
    const items = useMemo(() => {
        return completedResults
            .filter(r => {
                const val = r.datos_extra?.[field.key];
                return val != null && val !== '' && String(val).trim().length > 0;
            })
            .slice(0, 12)
            .map(r => ({
                id: r.id,
                telefono: r.telefono,
                fecha: r.fecha,
                text: String(r.datos_extra![field.key]),
            }));
    }, [completedResults, field.key]);

    if (items.length === 0) return null;

    return (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <div className="flex items-center gap-2 mb-4">
                <AlignLeft className="w-4 h-4 text-indigo-500" />
                <h3 className="text-base font-bold text-gray-900">{field.label}</h3>
                <span className="ml-auto text-xs text-gray-400 font-medium">{items.length} respuestas</span>
            </div>
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                {items.map(item => (
                    <div key={item.id} className="p-3 rounded-xl border border-gray-100 bg-gray-50/50">
                        <div className="flex justify-between items-center mb-1">
                            <span className="text-xs font-semibold text-gray-900">{item.telefono}</span>
                            <span className="text-[10px] text-gray-400">{new Date(item.fecha).toLocaleDateString()}</span>
                        </div>
                        <p className="text-xs text-gray-600 italic leading-relaxed">"{item.text}"</p>
                    </div>
                ))}
            </div>
        </div>
    );
};

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export const AnalyticsDashboard: React.FC<AnalyticsProps> = ({ results, schema }) => {
    const { t } = useTranslation();

    const dispositionData = useMemo(() => {
        const counts: Record<string, number> = {};
        results.forEach(r => {
            const disp = getCallDisposition(r.status);
            counts[disp] = (counts[disp] || 0) + 1;
        });
        return Object.entries(counts)
            .map(([key, value]) => ({ name: DISPOSITION_LABELS[key] || key, value, key }))
            .filter(d => d.value > 0)
            .sort((a, b) => b.value - a.value);
    }, [results]);

    const totalCalls = results.length;
    const completedCount = dispositionData.find(d => d.key === 'completed')?.value || 0;
    const completionRate = totalCalls > 0 ? Math.round((completedCount / totalCalls) * 100) : 0;

    const completedResults = useMemo(
        () => results.filter(r => r.status === 'completed' || r.status === 'completada'),
        [results]
    );

    const localInsights = useMemo((): InsightItem[] => {
        return results
            .filter(r => r.datos_extra && typeof r.datos_extra === 'object' && Object.keys(r.datos_extra).length > 0)
            .slice(0, 6)
            .map(r => ({
                id: r.id,
                telefono: r.telefono,
                fecha: r.fecha,
                campaign_name: r.campaign_name,
                keys: Object.keys(r.datos_extra!).slice(0, 4),
                datos_extra: r.datos_extra!,
            }));
    }, [results]);

    const hasSchema = Array.isArray(schema) && schema.length > 0;

    if (results.length === 0) return null;

    return (
        <div className="space-y-6 mb-8">

            {/* ── Universal KPIs ── */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
                    <p className="text-xs text-gray-500 font-medium mb-1">{t('Total Llamadas')}</p>
                    <h3 className="text-2xl font-bold text-gray-900">{totalCalls}</h3>
                </div>
                <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
                    <p className="text-xs text-gray-500 font-medium mb-1">{t('Completadas')}</p>
                    <h3 className="text-2xl font-bold text-green-600">
                        {completedCount}
                        <span className="text-sm text-gray-400 font-normal ml-1">({completionRate}%)</span>
                    </h3>
                </div>
                <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 col-span-2 md:col-span-1">
                    <p className="text-xs text-gray-500 font-medium mb-1">{t('Con Datos Extra')}</p>
                    <h3 className="text-2xl font-bold text-gray-900">{localInsights.length}</h3>
                </div>
            </div>

            {/* ── Disposition Donut ── */}
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                <h3 className="text-base font-bold text-gray-900 mb-4">{t('Estado de Llamadas')}</h3>
                <div className="h-64 w-full relative">
                    <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                            <Pie
                                data={dispositionData}
                                cx="50%" cy="50%"
                                innerRadius={70} outerRadius={95}
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

            {/* ── Dynamic Schema Widgets ── */}
            {hasSchema ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {schema!.map(field => {
                        const isFullWidth = field.type === 'text' || field.type === 'enum';
                        return (
                            <div key={field.key} className={isFullWidth ? 'md:col-span-2' : ''}>
                                {field.type === 'boolean' && (
                                    <BooleanWidget field={field} completedResults={completedResults} />
                                )}
                                {field.type === 'number' && (
                                    <NumberWidget field={field} completedResults={completedResults} />
                                )}
                                {field.type === 'enum' && (
                                    <EnumWidget field={field} completedResults={completedResults} />
                                )}
                                {field.type === 'text' && (
                                    <TextWidget field={field} completedResults={completedResults} />
                                )}
                            </div>
                        );
                    })}
                </div>
            ) : (
                /* ── Legacy Fallback ── */
                localInsights.length > 0 && (
                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                        <div className="flex items-center gap-2 mb-4">
                            <Database className="w-5 h-5 text-indigo-500" />
                            <h3 className="text-base font-bold text-gray-900">{t('Datos Extra Recientes')}</h3>
                            <span className="bg-indigo-100 text-indigo-700 text-[10px] font-bold px-2 py-0.5 rounded-full uppercase">
                                {localInsights.length} últimas
                            </span>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                            {localInsights.map((item) => (
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
                )
            )}
        </div>
    );
};
