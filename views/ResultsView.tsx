import React, { useEffect, useState, useMemo } from 'react';
import { Download, Search, RefreshCw, FileText, Target, ThumbsDown, Clock, Calendar, Bot, User, Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import { AnalyticsDashboard } from '../components/AnalyticsDashboard';
import { DateRangePicker, getDatesFromRange, DateRange } from '../components/DateRangePicker';
import { CallResultModal } from '../components/CallResultModal';
import { SurveyResult } from '../types';

interface Props {
    empresaId?: number;
    agentId?: number;
    campaignId?: number;
    title?: string;
    hideHeader?: boolean;
}

const ResultsView: React.FC<Props> = ({ empresaId, agentId, campaignId, title, hideHeader }) => {
    const { profile, isRole, isPlatformOwner } = useAuth();
    const { t } = useTranslation();

    const [results, setResults] = useState<SurveyResult[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [viewingTranscript, setViewingTranscript] = useState<SurveyResult | null>(null);
    const [empresas, setEmpresas] = useState<any[]>([]);
    const [agents, setAgents] = useState<any[]>([]);
    const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | 'all'>(empresaId || 'all');

    // Para usuarios no-platformOwner, forzar siempre su empresa_id
    const effectiveEmpresaId = !isPlatformOwner && profile?.empresa_id
        ? profile.empresa_id
        : selectedEmpresaId;
    const [selectedAgentId, setSelectedAgentId] = useState<number | 'all'>('all');
    const [selectedTipo, setSelectedTipo] = useState<string | 'all'>('all');
    const [dateRange, setDateRange] = useState<DateRange>('all');

    const loadResults = async () => {
        setLoading(true);
        try {
            const BASE_URL = import.meta.env.VITE_API_URL || '';
            const params = new URLSearchParams();

            if (effectiveEmpresaId !== 'all') params.append('empresa_id', String(effectiveEmpresaId));
            if (selectedAgentId !== 'all') params.append('agent_id', String(selectedAgentId));
            if (agentId) params.append('agent_id', String(agentId));
            if (campaignId) params.append('campaign_id', String(campaignId));

            // Date filtering
            const dates = getDatesFromRange(dateRange);
            if (dates.start) params.append('start_date', dates.start);
            if (dates.end) params.append('end_date', dates.end);

            const queryStr = params.toString() ? `?${params.toString()}` : '';
            const res = await fetch(`${BASE_URL}/api/results${queryStr}`);
            if (res.ok) {
                const data = await res.json();
                setResults(data);
            }
        } catch (e) {
            console.error("Error loading results", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        const fetchEmpresas = async () => {
            if (isPlatformOwner) {
                const { data } = await supabase.from('empresas').select('*').order('nombre');
                setEmpresas(data || []);
            }
        };
        fetchEmpresas();
    }, []);

    useEffect(() => {
        const fetchAgents = async () => {
            const BASE_URL = import.meta.env.VITE_API_URL || window.location.origin;
            const url = effectiveEmpresaId !== 'all' ? `${BASE_URL}/api/agents?empresa_id=${effectiveEmpresaId}` : `${BASE_URL}/api/agents`;
            const res = await fetch(url);
            if (res.ok) setAgents(await res.json());
        };
        fetchAgents();
    }, [effectiveEmpresaId]);

    useEffect(() => {
        loadResults();

        // 1. Canal para actualizaciones en la tabla 'encuestas' (Resultados detallados)
        const filterStrEncuestas = campaignId
            ? `campaign_id=eq.${campaignId}`
            : (effectiveEmpresaId !== 'all' ? `empresa_id=eq.${effectiveEmpresaId}` : undefined);

        const channelEncuestas = supabase
            .channel('results-live-updates-encuestas')
            .on(
                'postgres_changes',
                {
                    event: '*',
                    schema: 'public',
                    table: 'encuestas',
                    filter: filterStrEncuestas
                },
                (payload) => {
                    if (payload.eventType === 'INSERT') {
                        const newRes = payload.new as SurveyResult;
                        setResults(prev => {
                            if (prev.some(r => r.id === newRes.id)) return prev;
                            return [newRes, ...prev];
                        });
                    } else if (payload.eventType === 'UPDATE') {
                        const updatedRes = payload.new as SurveyResult;
                        setResults(prev => prev.map(r =>
                            r.id === updatedRes.id ? { ...r, ...updatedRes } : r
                        ));
                    }
                }
            )
            .subscribe();

        // 2. Canal para actualizaciones en la tabla 'campaign_leads' (Progreso de la campaña)
        // Esto es útil para ver cuando un lead cambia a 'calling' o 'failed' incluso antes de que haya encuesta
        const channelLeads = supabase
            .channel('leads-live-updates')
            .on(
                'postgres_changes',
                {
                    event: 'UPDATE',
                    schema: 'public',
                    table: 'campaign_leads',
                    filter: campaignId ? `campaign_id=eq.${campaignId}` : undefined
                },
                (payload) => {
                    const updatedLead = payload.new as any;
                    if (updatedLead.call_id) {
                        // Si el lead ya tiene call_id, intentamos actualizar el resultado correspondiente
                        setResults(prev => prev.map(r =>
                            r.id === updatedLead.call_id
                                ? { ...r, status: updatedLead.status, transcription: updatedLead.transcription || r.transcription }
                                : r
                        ));
                    }
                }
            )
            .subscribe();

        return () => {
            supabase.removeChannel(channelEncuestas);
            supabase.removeChannel(channelLeads);
        };
    }, [profile, effectiveEmpresaId, selectedAgentId, agentId, campaignId, dateRange]);

    const filteredResults = results.filter(r => {
        const matchesSearch = r.telefono.includes(searchTerm) ||
            (r.campaign_name && r.campaign_name.toLowerCase().includes(searchTerm.toLowerCase())) ||
            (r.comentarios && r.comentarios.toLowerCase().includes(searchTerm.toLowerCase())) ||
            (r.transcription && r.transcription.toLowerCase().includes(searchTerm.toLowerCase()));

        const matchesTipo = selectedTipo === 'all' || r.tipo_resultados === selectedTipo;

        return matchesSearch && matchesTipo;
    });

    const activeAgentType = useMemo(() => {
        if (selectedTipo !== 'all') return selectedTipo;
        if (filteredResults.length > 0 && (selectedAgentId !== 'all' || campaignId)) {
            return filteredResults[0].tipo_resultados || 'PREGUNTAS_ABIERTAS';
        }
        return null;
    }, [filteredResults, selectedTipo, selectedAgentId, campaignId]);

    const exportCSV = () => {
        const headers = [
            t("ID"),
            t("Teléfono", "Phone"),
            t("Fecha", "Date"),
            t("Completada", "Completed"),
            t("Modelo LLM", "LLM Model"),
            t("P. Comercial", "Sales Score"),
            t("P. Instalador", "Installer Score"),
            t("P. Rapidez", "Speed Score"),
            t("Comentarios", "Comments"),
            t("Transcripción", "Transcription")
        ];
        const csvContent = [
            headers.join(","),
            ...results.map(r => [
                r.id,
                r.telefono,
                new Date(r.fecha).toLocaleString(),
                r.completada ? t("Sí", "Yes") : t("No"),
                r.llm_model || "Groq",
                r.puntuacion_comercial || "",
                r.puntuacion_instalador || "",
                r.puntuacion_rapidez || "",
                `"${(r.comentarios || "").replace(/"/g, '""')}"`,
                `"${(r.transcription || "").replace(/"/g, '""')}"`
            ].join(","))
        ].join("\n");

        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement("a");
        const url = URL.createObjectURL(blob);
        link.setAttribute("href", url);
        link.setAttribute("download", "encuestas_ausarta.csv");
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    const handleRetry = (phone: string) => {
        const API_URL = import.meta.env.VITE_API_URL || window.location.origin;
        fetch(`${API_URL}/api/calls/outbound`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phoneNumber: phone })
        })
            .then(res => {
                if (res.ok) alert(t("Retrying call to {{phone}}...", { phone, defaultValue: `Reintentando llamada a ${phone}...` }));
                else alert(t("Error retrying", "Error al reintentar"));
            })
            .catch(e => console.error(e));
    };

    const openTranscript = async (row: SurveyResult) => {
        // Siempre cargamos la transcripción fresca desde la API para mostrar incluso
        // las parciales (llamadas incompletas, cortes, etc.)
        let freshTranscription = row.transcription ?? null;
        try {
            const API_URL = import.meta.env.VITE_API_URL || window.location.origin;
            const res = await fetch(`${API_URL}/api/results/${row.id}/transcription`);
            if (res.ok) {
                const data = await res.json();
                if (data.transcription) {
                    freshTranscription = data.transcription;
                    // Actualizar en el estado global para que no se pierda al reabrir
                    setResults(prev => prev.map(r => r.id === row.id ? { ...r, transcription: freshTranscription } : r));
                }
            }
        } catch (e) {
            console.error("Error fetching transcript", e);
        }
        setViewingTranscript({ ...row, transcription: freshTranscription });
    };

    return (
        <div className="space-y-6">
            {!hideHeader && (
                <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div className="space-y-1">
                        <h1 className="text-xl md:text-2xl font-bold text-gray-900">{title || t('Survey Results')}</h1>
                        <p className="text-gray-500 text-xs md:text-sm">{t('Detailed view of all agent interactions')}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <button
                            onClick={loadResults}
                            className="p-2 bg-white border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
                        >
                            <RefreshCw size={18} className={loading ? "animate-spin" : ""} />
                        </button>
                        <button
                            onClick={exportCSV}
                            className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors"
                        >
                            <Download size={16} />
                            {t('Export CSV')}
                        </button>
                    </div>
                </header>
            )}

            {/* Filters */}
            <div className="flex flex-col sm:flex-row gap-4">
                {isPlatformOwner && !empresaId && (
                    <select
                        value={selectedEmpresaId}
                        onChange={(e) => setSelectedEmpresaId(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                        className="px-4 py-2 border border-gray-200 rounded-lg text-sm bg-white"
                    >
                        <option value="all">{t('Todas las empresas')}</option>
                        {empresas.map(emp => (
                            <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                        ))}
                    </select>
                )}
                <select
                    value={selectedAgentId}
                    onChange={(e) => setSelectedAgentId(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                    className="px-4 py-2 border border-gray-200 rounded-lg text-sm bg-white min-w-[150px]"
                >
                    <option value="all">{t('Todos los agentes')}</option>
                    {agents.map(agent => (
                        <option key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                </select>

                <select
                    value={selectedTipo}
                    onChange={(e) => setSelectedTipo(e.target.value)}
                    className="px-4 py-2 border border-gray-200 rounded-lg text-sm bg-white min-w-[150px]"
                >
                    <option value="all">{t('Todos los tipos')}</option>
                    <option value="ENCUESTA_NUMERICA">{t('Numérica')}</option>
                    <option value="PREGUNTAS_ABIERTAS">{t('Preguntas Abiertas')}</option>
                    <option value="CUALIFICACION_LEAD">{t('Cualificación Lead')}</option>
                    <option value="AGENDAMIENTO_CITA">{t('Cita / Reunión')}</option>
                    <option value="SOPORTE_CLIENTE">{t('Soporte')}</option>
                </select>

                <div className="relative flex-1 max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
                    <input
                        type="text"
                        placeholder={t('Search by phone, comments or transcript...')}
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-black/5 focus:border-black/20"
                    />
                </div>

                <DateRangePicker value={dateRange} onChange={setDateRange} />
            </div>

            {/* Dashboard Section */}
            {
                activeAgentType && filteredResults.length > 0 && (
                    <div className="mb-6">
                        <AnalyticsDashboard
                            tipoResultados={activeAgentType}
                            results={filteredResults}
                        />
                    </div>
                )
            }

            {/* Mobile / Tablet cards */}
            <div className="lg:hidden space-y-3">
                {filteredResults.length === 0 ? (
                    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-8 text-center text-gray-400 text-sm">
                        {t('No results found')}
                    </div>
                ) : filteredResults.map((row) => (
                    <div key={row.id} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-3">
                        <div className="flex items-start justify-between gap-3">
                            <div>
                                <div className="text-xs text-gray-400 font-mono">#{row.id}</div>
                                <div className="font-semibold text-gray-900">{row.telefono}</div>
                                <div className="text-[11px] text-blue-600 font-bold uppercase tracking-tight">{row.campaign_name}</div>
                            </div>
                            <span className="text-xs text-gray-500 text-right">
                                {new Date(row.fecha).toLocaleDateString()}<br />
                                {new Date(row.fecha).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                        </div>

                        <div className="flex items-center justify-between gap-2">
                            <span className={`inline-flex items-center px-2 py-1 rounded-full text-[10px] font-bold uppercase shadow-sm ${
                                row.status === 'completada' || row.status === 'completed' ? 'bg-green-500 text-white' :
                                row.status === 'parcial' || row.status === 'incomplete' ? 'bg-orange-400 text-white' :
                                row.status === 'rechazada' || row.status === 'rejected_opt_out' || row.status === 'rejected' ? 'bg-red-700 text-white' :
                                row.status === 'fallida' || row.status === 'failed' ? 'bg-purple-500 text-white' :
                                row.status === 'no_contesta' || row.status === 'unreached' ? 'bg-amber-400 text-white' :
                                'bg-gray-400 text-white'
                            }`}>
                                {(row.status || 'pendiente').replace('_', ' ')}
                            </span>
                            <span className="text-xs text-gray-500">
                                {row.llm_model?.replace('Google ', '').replace('Groq ', '') || 'Llama 3.3'}
                            </span>
                        </div>

                        <div className="flex flex-col sm:flex-row gap-2">
                            {(row.status === 'failed' || row.status === 'incomplete') && (
                                <button
                                    onClick={() => handleRetry(row.telefono)}
                                    className="flex-1 flex items-center justify-center gap-2 px-3 py-2 border border-orange-200 text-orange-700 bg-orange-50 rounded-lg text-sm font-medium"
                                >
                                    <RefreshCw size={16} /> {t('Retry')}
                                </button>
                            )}
                            <button
                                onClick={() => openTranscript(row)}
                                className="flex-1 flex items-center justify-center gap-2 px-3 py-2 border border-blue-200 text-blue-700 bg-blue-50 rounded-lg text-sm font-semibold"
                            >
                                <FileText size={16} /> {t('Transcript')}
                            </button>
                        </div>
                    </div>
                ))}
            </div>

            {/* Desktop table */}
            <div className="hidden lg:block bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full min-w-[1100px] text-sm text-left text-gray-700">
                        <thead className="bg-gray-50 text-gray-500 font-medium border-b border-gray-100">
                            <tr>
                                <th className="px-6 py-3 w-16">{t('ID')}</th>
                                <th className="px-6 py-3">{t('Phone / Campaign')}</th>
                                <th className="px-6 py-3">{t('Date')}</th>
                                <th className="px-6 py-3 text-center">{t('Status')}</th>
                                <th className="px-6 py-3 text-center">{t('Results / Scores')}</th>
                                <th className="px-6 py-3">{t('Model')}</th>
                                <th className="px-6 py-3">{t('Comments')}</th>
                                <th className="px-6 py-3 text-right sticky right-0 bg-gray-50">{t('More')}</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {filteredResults.length === 0 ? (
                                <tr>
                                    <td colSpan={8} className="px-6 py-12 text-center text-gray-400">
                                        {t('No results found')}
                                    </td>
                                </tr>
                            ) : filteredResults.map((row) => (
                                <tr key={row.id} className="hover:bg-gray-50/50 transition-colors">
                                    <td className="px-6 py-4 font-mono text-xs text-gray-400">#{row.id}</td>
                                    <td className="px-6 py-4">
                                        <div className="flex flex-col">
                                            <span className="font-medium text-gray-900">{row.telefono}</span>
                                            <span className="text-[10px] text-blue-600 font-bold uppercase tracking-tighter">{row.campaign_name}</span>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4 text-gray-500">
                                        {new Date(row.fecha).toLocaleDateString()} <span className="text-xs text-gray-400">{new Date(row.fecha).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                                    </td>
                                    <td className="px-6 py-4 text-center">
                                        {(() => {
                                            if (row.status === 'completada' || row.status === 'completed') {
                                                return <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-bold bg-green-500 text-white uppercase shadow-sm">{t('Completada')}</span>;
                                            } else if (row.status === 'parcial' || row.status === 'incomplete') {
                                                return <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-bold bg-orange-400 text-white uppercase shadow-sm">{t('Parcial')}</span>;
                                            } else if (row.status === 'rechazada' || row.status === 'rejected_opt_out' || row.status === 'rejected') {
                                                return <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-bold bg-red-700 text-white uppercase shadow-sm" title="No reintentar">{t('Rechazada')}</span>;
                                            } else if (row.status === 'fallida' || row.status === 'failed') {
                                                return <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-bold bg-purple-500 text-white uppercase shadow-sm">{t('Fallida')}</span>;
                                            } else if (row.status === 'no_contesta' || row.status === 'unreached') {
                                                return <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-bold bg-amber-400 text-white uppercase shadow-sm">{t('No Contesta')}</span>;
                                            } else {
                                                return <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-bold bg-gray-400 text-white uppercase shadow-sm">{t('Pendiente')}</span>;
                                            }
                                        })()}
                                    </td>
                                    <td className="px-6 py-4 text-center">
                                        {(() => {
                                            const type = row.tipo_resultados;
                                            const badgeClass = type === 'ENCUESTA_NUMERICA' ? 'bg-green-50 text-green-700 border-green-200' :
                                                type === 'CUALIFICACION_LEAD' ? 'bg-orange-50 text-orange-700 border-orange-200' :
                                                    type === 'AGENDAMIENTO_CITA' ? 'bg-purple-50 text-purple-700 border-purple-200' :
                                                        type === 'SOPORTE_CLIENTE' ? 'bg-blue-50 text-blue-700 border-blue-200' :
                                                            'bg-gray-50 text-gray-700 border-gray-200';

                                            const Badge = () => (
                                                <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border ${badgeClass} mb-2`}>
                                                    {(type || 'PREGUNTAS ABIERTAS').replace('_', ' ')}
                                                </span>
                                            );

                                            if (type === 'ENCUESTA_NUMERICA') {
                                                return (
                                                    <div className="flex flex-col items-center">
                                                        <Badge />
                                                        <div className="flex items-center justify-center gap-2">
                                                            {[
                                                                { label: 'COM', val: row.puntuacion_comercial },
                                                                { label: 'INS', val: row.puntuacion_instalador },
                                                                { label: 'RAP', val: row.puntuacion_rapidez }
                                                            ].map((s, idx) => (
                                                                <div key={idx} className="flex flex-col items-center">
                                                                    <span className="text-[10px] text-gray-400 mb-0.5">{s.label}</span>
                                                                    <span className={`w-8 h-8 flex items-center justify-center rounded-lg text-sm font-bold shadow-sm ${getScoreColor(s.val)}`}>
                                                                        {s.val ?? '-'}
                                                                    </span>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                );
                                            } else if (type === 'CUALIFICACION_LEAD') {
                                                const isLead = row.datos_extra?.lead_cualificado;
                                                return (
                                                    <div className="flex flex-col items-center">
                                                        <Badge />
                                                        {isLead === true ? (
                                                            <span className="flex items-center gap-1 bg-green-100 text-green-700 text-xs px-2 py-1 rounded-md font-bold shadow-sm">
                                                                <Target size={14} /> HOT LEAD
                                                            </span>
                                                        ) : isLead === false ? (
                                                            <span className="flex items-center gap-1 bg-red-100 text-red-700 text-xs px-2 py-1 rounded-md font-bold shadow-sm">
                                                                <ThumbsDown size={14} /> DESCARTADO
                                                            </span>
                                                        ) : (
                                                            <span className="text-gray-400 text-xs">-</span>
                                                        )}
                                                    </div>
                                                );
                                            } else if (type === 'AGENDAMIENTO_CITA') {
                                                const hasCita = row.datos_extra?.cita_agendada;
                                                const fecha = row.datos_extra?.fecha_cita;
                                                return (
                                                    <div className="flex flex-col items-center">
                                                        <Badge />
                                                        {hasCita ? (
                                                            <div className="bg-purple-100 text-purple-800 text-xs px-3 py-1.5 rounded-lg border border-purple-200 text-center font-medium shadow-sm">
                                                                <Clock size={14} className="inline mr-1" />
                                                                {fecha || 'Cita Agendada'}
                                                            </div>
                                                        ) : (
                                                            <span className="text-gray-400 text-xs">Sin fecha</span>
                                                        )}
                                                    </div>
                                                );
                                            } else {
                                                return (
                                                    <div className="flex justify-center items-center">
                                                        <Badge />
                                                    </div>
                                                );
                                            }
                                        })()}
                                    </td>
                                    <td className="px-6 py-4">
                                        <div className="flex flex-col">
                                            <span className="text-[10px] text-blue-600 font-mono font-bold tracking-tighter uppercase whitespace-nowrap">
                                                {row.llm_model?.split(' ')[0] || 'Primary'}
                                            </span>
                                            <span className="text-xs font-bold text-gray-900">
                                                {row.llm_model?.replace('Google ', '').replace('Groq ', '') || 'Llama 3.3'}
                                            </span>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4">
                                        {row.comentarios && row.comentarios !== "Sin comentarios" ? (
                                            <div className="bg-yellow-50 border border-yellow-100 p-2 rounded-lg text-xs text-gray-800 italic max-w-xs truncate">
                                                "{row.comentarios}"
                                            </div>
                                        ) : (
                                            <span className="text-gray-300 italic text-xs">{t('None')}</span>
                                        )}
                                    </td>
                                    <td className="px-6 py-4 text-right sticky right-0 bg-white">
                                        <div className="flex justify-end items-center gap-2">
                                            {(row.status === 'failed' || row.status === 'incomplete') && (
                                                <button
                                                    onClick={() => handleRetry(row.telefono)}
                                                    className="px-3 py-2 text-orange-700 bg-orange-50 border border-orange-200 hover:bg-orange-100 rounded-lg transition-colors flex items-center gap-1 text-xs font-medium whitespace-nowrap"
                                                    title="Reintentar llamada ahora"
                                                >
                                                    <RefreshCw size={16} /> {t('Retry')}
                                                </button>
                                            )}
                                            <button
                                                onClick={() => openTranscript(row)}
                                                className="px-3 py-2 text-blue-700 bg-blue-50 border border-blue-200 hover:bg-blue-100 rounded-lg transition-colors flex items-center gap-1 text-xs font-semibold whitespace-nowrap"
                                            >
                                                <FileText size={16} /> {t('Transcript')}
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Transcript Modal */}
            <CallResultModal
                result={viewingTranscript}
                onClose={() => setViewingTranscript(null)}
            />
        </div>
    );
};

function getScoreColor(score: number | null): string {
    if (score === null) return 'bg-gray-50 text-gray-400 border border-gray-100';
    if (score >= 9) return 'bg-green-100 text-green-700 border border-green-200';
    if (score >= 7) return 'bg-blue-100 text-blue-700 border border-blue-200';
    if (score >= 5) return 'bg-yellow-100 text-yellow-700 border border-yellow-200';
    return 'bg-red-100 text-red-700 border border-red-200';
}

export default ResultsView;
