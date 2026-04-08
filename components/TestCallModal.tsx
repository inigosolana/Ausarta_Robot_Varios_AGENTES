/**
 * TestCallModal — Simulador de llamada en tiempo real.
 *
 * Flujo:
 *  1. El usuario introduce su número y pulsa "Llamar ahora".
 *  2. Se llama a POST /api/calls/outbound con el agentId actual.
 *  3. El backend crea la encuesta y devuelve { callId }.
 *  4. Nos suscribimos al canal Supabase Realtime de esa encuesta concreta.
 *  5. Cuando el estado pasa a terminal (completed / failed / etc.),
 *     mostramos el modal de resultados con datos_extra, transcripción y
 *     el reproductor de audio si hay recording_url.
 *  6. El usuario puede cancelar en cualquier momento.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Phone, PhoneOff, X, Loader2, CheckCircle2, AlertTriangle, FlaskConical } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { supabase } from '../lib/supabase';
import { SurveyResult } from '../types';
import { CallResultModal } from './CallResultModal';

interface Props {
    agentId: number;
    agentName: string;
    onClose: () => void;
}

type Phase =
    | 'idle'       // Esperando que el usuario introduzca el número
    | 'calling'    // Llamada en curso (esperando respuesta)
    | 'done'       // Llamada terminada — mostramos resultados
    | 'error';     // Error al lanzar la llamada

const TERMINAL_STATUSES = new Set([
    'completed', 'completada',
    'failed', 'fallida',
    'unreached', 'no_contesta',
    'incomplete', 'parcial',
    'rejected_opt_out', 'rechazada', 'rejected',
]);

const PHASE_TIMEOUT_MS = 5 * 60 * 1000; // 5 min máximo esperando

export const TestCallModal: React.FC<Props> = ({ agentId, agentName, onClose }) => {
    const { t } = useTranslation();
    const [phone, setPhone] = useState('');
    const [phase, setPhase] = useState<Phase>('idle');
    const [errorMsg, setErrorMsg] = useState('');
    const [callId, setCallId] = useState<number | null>(null);
    const [result, setResult] = useState<SurveyResult | null>(null);
    const [showResult, setShowResult] = useState(false);
    const [elapsedSecs, setElapsedSecs] = useState(0);

    // refs para limpiar suscripción y timer
    const channelRef = useRef<ReturnType<typeof supabase.channel> | null>(null);
    const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const cleanup = () => {
        if (channelRef.current) {
            supabase.removeChannel(channelRef.current);
            channelRef.current = null;
        }
        if (timerRef.current) clearInterval(timerRef.current);
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };

    useEffect(() => () => cleanup(), []);

    // Ticker de segundos transcurridos mientras "calling"
    useEffect(() => {
        if (phase === 'calling') {
            setElapsedSecs(0);
            timerRef.current = setInterval(() => setElapsedSecs(s => s + 1), 1000);
        } else {
            if (timerRef.current) clearInterval(timerRef.current);
        }
    }, [phase]);

    const subscribeToResult = (surveyId: number) => {
        // Suscripción Supabase Realtime a la fila concreta de encuestas
        const channel = supabase
            .channel(`test-call-${surveyId}`)
            .on(
                'postgres_changes',
                {
                    event: 'UPDATE',
                    schema: 'public',
                    table: 'encuestas',
                    filter: `id=eq.${surveyId}`,
                },
                async (payload) => {
                    const updated = payload.new as SurveyResult;
                    if (updated.status && TERMINAL_STATUSES.has(updated.status)) {
                        cleanup();
                        // Fetch completo para asegurarnos de tener todos los campos
                        const { data } = await supabase
                            .from('encuestas')
                            .select('*')
                            .eq('id', surveyId)
                            .single();
                        const fullResult = (data as SurveyResult) ?? updated;
                        setResult(fullResult);
                        setPhase('done');
                        setShowResult(true);
                    }
                }
            )
            .subscribe();

        channelRef.current = channel;

        // Timeout de seguridad: si en 5 min no termina, mostramos lo que hay
        timeoutRef.current = setTimeout(async () => {
            cleanup();
            const { data } = await supabase
                .from('encuestas')
                .select('*')
                .eq('id', surveyId)
                .single();
            setResult((data as SurveyResult) ?? null);
            setPhase('done');
            setShowResult(true);
        }, PHASE_TIMEOUT_MS);
    };

    const handleCall = async () => {
        const cleaned = phone.trim().replace(/\s/g, '');
        if (!cleaned) return;

        setPhase('calling');
        setErrorMsg('');

        try {
            const API_URL = import.meta.env.VITE_API_URL || '';
            const res = await fetch(`${API_URL}/api/calls/outbound`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    phoneNumber: cleaned,
                    agentId: String(agentId),
                    customerName: 'Test — Simulador',
                    isTestCall: true,
                }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || `HTTP ${res.status}`);
            }

            const data = await res.json();
            const surveyId: number = data.callId;
            setCallId(surveyId);
            subscribeToResult(surveyId);
        } catch (e: any) {
            setErrorMsg(e.message || t('Error desconocido'));
            setPhase('error');
        }
    };

    const handleCancel = () => {
        cleanup();
        setPhase('idle');
        setCallId(null);
    };

    const formatSecs = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`;

    // Si la llamada terminó y el usuario quiere ver los resultados
    if (showResult && result) {
        return (
            <CallResultModal
                result={result}
                onClose={() => {
                    setShowResult(false);
                    onClose();
                }}
            />
        );
    }

    return (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in duration-200">

                {/* Header */}
                <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center bg-gradient-to-r from-blue-50 to-indigo-50">
                    <div className="flex items-center gap-3">
                        <div className="bg-blue-100 p-2 rounded-xl">
                            <FlaskConical size={20} className="text-blue-600" />
                        </div>
                        <div>
                            <h3 className="text-base font-bold text-gray-900">{t('Probar Agente', 'Probar Agente')}</h3>
                            <p className="text-xs text-gray-500">{agentName}</p>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        disabled={phase === 'calling'}
                        className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 bg-white border border-gray-200 rounded-full hover:shadow-sm transition-all disabled:opacity-40"
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Body */}
                <div className="p-6 space-y-5">

                    {/* Fase: idle o error */}
                    {(phase === 'idle' || phase === 'error') && (
                        <>
                            <p className="text-sm text-gray-600 leading-relaxed">
                                {t(
                                    'Introduce tu número de teléfono. El agente te llamará ahora mismo para que puedas probar cómo funciona en una conversación real.',
                                    'Introduce tu número de teléfono. El agente te llamará ahora mismo para que puedas probar cómo funciona en una conversación real.'
                                )}
                            </p>

                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider">
                                    {t('Tu número de teléfono', 'Tu número de teléfono')}
                                </label>
                                <div className="flex gap-2">
                                    <input
                                        type="tel"
                                        value={phone}
                                        onChange={e => setPhone(e.target.value)}
                                        onKeyDown={e => e.key === 'Enter' && handleCall()}
                                        placeholder="+34 600 000 000"
                                        className="flex-1 px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 font-mono tracking-wider"
                                        autoFocus
                                    />
                                </div>
                            </div>

                            {phase === 'error' && (
                                <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-100 rounded-xl">
                                    <AlertTriangle size={16} className="text-red-500 shrink-0 mt-0.5" />
                                    <p className="text-sm text-red-700">{errorMsg}</p>
                                </div>
                            )}

                            <button
                                onClick={handleCall}
                                disabled={!phone.trim()}
                                className="w-full flex items-center justify-center gap-2 py-3 bg-gradient-to-r from-green-600 to-emerald-500 text-white font-semibold rounded-xl hover:from-green-500 hover:to-emerald-400 transition-all shadow-lg shadow-green-500/20 disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                <Phone size={18} />
                                {t('Llamarme ahora', 'Llamarme ahora')}
                            </button>
                        </>
                    )}

                    {/* Fase: calling */}
                    {phase === 'calling' && (
                        <div className="flex flex-col items-center py-6 gap-6">
                            {/* Indicador animado */}
                            <div className="relative">
                                <div className="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center">
                                    <Phone size={32} className="text-green-600" />
                                </div>
                                <span className="absolute inset-0 rounded-full border-4 border-green-400 animate-ping opacity-30" />
                            </div>

                            <div className="text-center space-y-1">
                                <p className="font-bold text-gray-900 text-base">
                                    {t('Llamando a', 'Llamando a')} <span className="font-mono text-blue-600">{phone}</span>
                                </p>
                                <p className="text-sm text-gray-500">
                                    {t('El agente se pondrá en contacto contigo en unos segundos...', 'El agente se pondrá en contacto contigo en unos segundos...')}
                                </p>
                                <p className="font-mono text-xs text-gray-400 mt-2">{formatSecs(elapsedSecs)}</p>
                            </div>

                            <div className="w-full space-y-2">
                                <div className="flex items-center gap-3 p-3 bg-blue-50 rounded-xl border border-blue-100 text-sm text-blue-700">
                                    <Loader2 size={16} className="animate-spin shrink-0" />
                                    <span>{t('Esperando que finalice la llamada para mostrarte los resultados...', 'Esperando que finalice la llamada para mostrarte los resultados...')}</span>
                                </div>

                                <button
                                    onClick={handleCancel}
                                    className="w-full flex items-center justify-center gap-2 py-2.5 border border-red-200 text-red-600 bg-red-50 hover:bg-red-100 rounded-xl text-sm font-medium transition-colors"
                                >
                                    <PhoneOff size={16} />
                                    {t('Cancelar seguimiento', 'Cancelar seguimiento')}
                                </button>
                            </div>
                        </div>
                    )}

                    {/* Fase: done (sin mostrar resultados aún — transición rápida) */}
                    {phase === 'done' && !showResult && (
                        <div className="flex flex-col items-center py-8 gap-4">
                            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
                                <CheckCircle2 size={32} className="text-green-600" />
                            </div>
                            <p className="font-bold text-gray-900">{t('Llamada finalizada', 'Llamada finalizada')}</p>
                            <button
                                onClick={() => setShowResult(true)}
                                className="px-6 py-2.5 bg-gray-900 text-white text-sm font-semibold rounded-xl hover:bg-black transition-all"
                            >
                                {t('Ver resultados', 'Ver resultados')}
                            </button>
                        </div>
                    )}
                </div>

                {/* Footer info */}
                {phase === 'idle' && (
                    <div className="px-6 pb-5">
                        <p className="text-[11px] text-gray-400 text-center leading-relaxed">
                            {t(
                                'Esta es una llamada de prueba real. El agente ejecutará su guion completo y al finalizar verás los datos que extrajo.',
                                'Esta es una llamada de prueba real. El agente ejecutará su guion completo y al finalizar verás los datos que extrajo.'
                            )}
                        </p>
                    </div>
                )}
            </div>
        </div>
    );
};
