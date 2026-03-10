import React from 'react';
import { FileText, Target, ThumbsDown, Calendar, Sparkles, X, Database } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { SurveyResult } from '../types';

interface CallResultModalProps {
    result: SurveyResult | null;
    onClose: () => void;
}

function prettifyKey(raw: string): string {
    return raw
        .replace(/_/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(value: any): string {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'boolean') return value ? 'Sí' : 'No';
    if (typeof value === 'number') return String(value);
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(v => formatValue(v)).join(', ');
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
}

function getValueStyle(value: any): string {
    if (typeof value === 'boolean') {
        return value
            ? 'bg-green-50 text-green-700 border-green-200'
            : 'bg-red-50 text-red-700 border-red-200';
    }
    if (typeof value === 'number') return 'bg-blue-50 text-blue-700 border-blue-200';
    return 'bg-gray-50 text-gray-700 border-gray-200';
}

export function CallResultModal({ result, onClose }: CallResultModalProps) {
    const { t } = useTranslation();

    if (!result) return null;

    const TimeStr = ({ basetime, offset }: { basetime: string; offset: number }) => {
        try {
            const d = new Date(basetime);
            if (isNaN(d.getTime())) return null;
            d.setSeconds(d.getSeconds() + offset * 15);
            return (
                <span className="text-[10px] text-gray-400 mt-1 block font-mono">
                    {d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
            );
        } catch (e) {
            return null;
        }
    };

    const parseTranscriptLine = (rawLine: string): { speaker: 'agent' | 'customer'; text: string } => {
        const line = rawLine.trim();
        const lower = line.toLowerCase();
        const agentPrefixes = ['agente:', 'assistant:', 'ai:', 'bot:', 'ausarta robot:'];
        const customerPrefixes = ['cliente:', 'customer:', 'user:', 'you:', 'usuario:'];

        const aPrefix = agentPrefixes.find((p) => lower.startsWith(p));
        if (aPrefix) return { speaker: 'agent', text: line.slice(aPrefix.length).trim() };

        const cPrefix = customerPrefixes.find((p) => lower.startsWith(p));
        if (cPrefix) return { speaker: 'customer', text: line.slice(cPrefix.length).trim() };

        return { speaker: 'customer', text: line };
    };

    // Notas numéricas que existen
    const numericScores = [
        { label: 'Comercial', value: result.puntuacion_comercial },
        { label: 'Instalador', value: result.puntuacion_instalador },
        { label: 'Rapidez', value: result.puntuacion_rapidez },
    ].filter(s => s.value != null && s.value > 0);

    // datos_extra como key-value pairs (filtramos arrays/objetos complejos para mostrar aparte)
    const datosExtra = result.datos_extra && typeof result.datos_extra === 'object' ? result.datos_extra : null;
    const extraEntries = datosExtra ? Object.entries(datosExtra).filter(([_, v]) => v !== null && v !== undefined && v !== '') : [];
    const simpleEntries = extraEntries.filter(([_, v]) => typeof v !== 'object' || typeof v === 'boolean');
    const complexEntries = extraEntries.filter(([_, v]) => typeof v === 'object' && v !== null && typeof v !== 'boolean');

    // Detectar estado de interés para header
    const interes = datosExtra?.interes?.toString().toLowerCase();
    const headerBg = interes === 'alto' ? 'bg-green-50 border-green-100' :
                     interes === 'bajo' ? 'bg-red-50 border-red-100' :
                     'bg-gray-50/50 border-gray-100';

    return (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
            <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in duration-200">
                {/* Header */}
                <div className={`px-6 py-4 border-b flex justify-between items-center ${headerBg}`}>
                    <div>
                        <div className="flex items-center gap-3">
                            <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                                <FileText size={18} className={interes === 'alto' ? 'text-green-600' : 'text-blue-600'} />
                                {t("Detalle Llamada", "Detalle Llamada")} #{result.id}
                            </h3>
                            {interes === 'alto' && <span className="bg-green-100 text-green-700 px-2 py-0.5 rounded-full text-xs font-bold shadow-sm">🔥 Interés Alto</span>}
                            {interes === 'bajo' && <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full text-xs font-bold shadow-sm">Interés Bajo</span>}
                        </div>
                        <p className="text-xs text-gray-500 mt-0.5">
                            {result.customer_name ? `${result.customer_name} · ` : ''}
                            {result.telefono} • {new Date(result.fecha).toLocaleString()}
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 bg-white border border-gray-200 rounded-full hover:shadow-sm transition-all"
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Panel de Datos Estructurados */}
                <div className="px-6 py-4 border-b border-gray-100 bg-indigo-50/30 shrink-0 space-y-4">
                    {/* Notas numéricas (solo si existen) */}
                    {numericScores.length > 0 && (
                        <div>
                            <div className="flex items-center gap-2 mb-2">
                                <Sparkles size={14} className="text-blue-500" />
                                <h4 className="font-bold text-gray-800 text-xs uppercase tracking-wider">{t('Puntuaciones')}</h4>
                            </div>
                            <div className="flex gap-3">
                                {numericScores.map((s) => (
                                    <div key={s.label} className="flex flex-col items-center">
                                        <span className="text-[10px] text-gray-500 mb-1">{s.label}</span>
                                        <span className={`w-10 h-10 flex items-center justify-center rounded-xl text-sm font-bold shadow-sm border ${
                                            s.value! >= 8 ? 'bg-green-100 text-green-700 border-green-200' :
                                            s.value! >= 5 ? 'bg-blue-100 text-blue-700 border-blue-200' :
                                            'bg-red-100 text-red-700 border-red-200'
                                        }`}>
                                            {s.value}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Secciones específicas por tipo */}
                    {result.tipo_resultados === 'CUALIFICACION_LEAD' && datosExtra && (
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center gap-2">
                                <span className="text-xs font-semibold text-gray-600">{t('Estado:')}</span>
                                {datosExtra.lead_cualificado ? (
                                    <span className="bg-green-100 text-green-700 text-xs px-2 py-1 rounded-md font-bold flex items-center gap-1"><Target size={12} /> Cualificado</span>
                                ) : (
                                    <span className="bg-red-100 text-red-700 text-xs px-2 py-1 rounded-md font-bold flex items-center gap-1"><ThumbsDown size={12} /> No Cualificado</span>
                                )}
                            </div>
                            {datosExtra.motivo_rechazo && (
                                <p className="text-sm text-gray-700 bg-white p-2 rounded-lg border border-gray-100">
                                    <span className="font-semibold text-xs text-gray-500 block mb-1">{t('Motivo:')}</span>
                                    {datosExtra.motivo_rechazo}
                                </p>
                            )}
                        </div>
                    )}

                    {result.tipo_resultados === 'AGENDAMIENTO_CITA' && datosExtra?.fecha_cita && (
                        <div className="bg-white border border-purple-100 p-3 rounded-lg flex items-center gap-3">
                            <div className="bg-purple-100 p-2 rounded-full"><Calendar size={16} className="text-purple-700" /></div>
                            <div>
                                <p className="text-xs font-semibold text-gray-500">{t('Fecha de Cita')}</p>
                                <p className="font-bold text-purple-900 text-sm">{datosExtra.fecha_cita}</p>
                            </div>
                        </div>
                    )}

                    {/* Key-Value elegante para datos_extra */}
                    {simpleEntries.length > 0 && (
                        <div>
                            <div className="flex items-center gap-2 mb-2">
                                <Database size={14} className="text-indigo-500" />
                                <h4 className="font-bold text-gray-800 text-xs uppercase tracking-wider">{t('Datos Recopilados')}</h4>
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {simpleEntries.map(([key, value]) => (
                                    <div key={key} className="flex items-start gap-2 bg-white p-2.5 rounded-lg border border-gray-100">
                                        <span className="text-[11px] font-semibold text-gray-500 min-w-[100px] shrink-0 pt-0.5">
                                            {prettifyKey(key)}
                                        </span>
                                        <span className={`px-2 py-0.5 rounded-md text-xs font-medium border ${getValueStyle(value)}`}>
                                            {formatValue(value)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Datos complejos (arrays, objetos anidados) */}
                    {complexEntries.length > 0 && (
                        <div className="space-y-2">
                            {complexEntries.map(([key, value]) => (
                                <div key={key} className="bg-white p-3 rounded-lg border border-gray-100">
                                    <span className="text-[11px] font-semibold text-gray-500 block mb-1">{prettifyKey(key)}</span>
                                    {Array.isArray(value) ? (
                                        <div className="flex flex-wrap gap-1.5">
                                            {value.map((item, idx) => (
                                                <span key={idx} className="px-2 py-0.5 rounded-md bg-indigo-50 border border-indigo-100 text-[10px] text-indigo-700 font-medium">
                                                    {typeof item === 'object' ? JSON.stringify(item) : String(item)}
                                                </span>
                                            ))}
                                        </div>
                                    ) : (
                                        <pre className="text-xs font-mono text-gray-600 whitespace-pre-wrap overflow-hidden bg-gray-50 p-2 rounded">
                                            {JSON.stringify(value, null, 2)}
                                        </pre>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Comentarios */}
                    {result.comentarios && result.comentarios !== "Sin comentarios" && (
                        <div className="bg-yellow-50 border border-yellow-100 p-3 rounded-lg">
                            <span className="text-[10px] text-yellow-800 font-bold uppercase tracking-wider block mb-1">{t('Comentarios')}</span>
                            <p className="text-sm text-gray-800 italic">"{result.comentarios}"</p>
                        </div>
                    )}

                    {/* Sin datos */}
                    {numericScores.length === 0 && simpleEntries.length === 0 && complexEntries.length === 0 && !result.comentarios && (
                        <p className="text-sm text-gray-400 italic">{t('No se recopilaron datos estructurados en esta llamada.')}</p>
                    )}
                </div>

                {/* Transcripción */}
                <div className="p-6 overflow-y-auto space-y-6 bg-gray-50/20 flex-1">
                    {result.transcription ? (
                        result.transcription.split('\n').filter(l => l.trim()).map((line, i) => {
                            const parsed = parseTranscriptLine(line);
                            const isAgente = parsed.speaker === 'agent';
                            return (
                                <div key={i} className={`flex ${isAgente ? 'justify-start' : 'justify-end'}`}>
                                    <div className="flex gap-3 max-w-[85%]">
                                        {isAgente && (
                                            <div className="w-8 h-8 rounded-full bg-[#004a99] flex items-center justify-center shrink-0 shadow-sm">
                                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-white"><path d="M12 8V4H8" /><rect width="16" height="12" x="4" y="8" rx="2" /><path d="M2 14h2" /><path d="M20 14h2" /><path d="M15 13v2" /><path d="M9 13v2" /></svg>
                                            </div>
                                        )}
                                        <div className={`rounded-2xl px-4 py-3 text-sm shadow-sm border ${isAgente
                                            ? 'bg-[#004a99] text-white border-[#003d82] rounded-tl-none'
                                            : 'bg-white text-gray-800 border-gray-200 rounded-tr-none'
                                            }`}>
                                            <p className={`font-semibold text-[10px] uppercase tracking-wider mb-1 ${isAgente ? 'text-blue-200' : 'text-gray-400'}`}>
                                                {isAgente ? 'Ausarta Robot' : t('Customer', 'Cliente')}
                                            </p>
                                            <p className="leading-relaxed whitespace-pre-wrap">
                                                {parsed.text}
                                            </p>
                                            <TimeStr basetime={result.fecha || new Date().toISOString()} offset={i} />
                                        </div>
                                        {!isAgente && (
                                            <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center shrink-0 shadow-sm border border-gray-300">
                                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gray-600"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })
                    ) : (
                        <div className="text-center py-12">
                            <div className="bg-gray-100 w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-3">
                                <FileText className="text-gray-400" />
                            </div>
                            <p className="text-gray-500 font-medium">{t('No transcription available', 'No hay transcripción disponible')}</p>
                            <p className="text-xs text-gray-400 mt-1">{t('The call may have been too short or no speech was detected.', 'La llamada pudo ser muy corta o no se detectó voz.')}</p>
                        </div>
                    )}
                </div>

                <div className="px-6 py-4 border-t border-gray-100 bg-gray-50/50 flex justify-end shrink-0">
                    <button
                        onClick={onClose}
                        className="px-6 py-2 bg-gray-900 text-white text-sm font-semibold rounded-xl hover:bg-black transition-all shadow-md hover:shadow-lg"
                    >
                        {t('Close', 'Cerrar')}
                    </button>
                </div>
            </div>
        </div>
    );
}
