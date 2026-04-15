/**
 * TestCallModal — Simulador de llamada en tiempo real con sandbox visual.
 *
 * Flujo:
 *  1. El usuario introduce su número y pulsa "Llamar ahora".
 *  2. POST /api/calls/outbound → { callId }.
 *  3. Suscripción Supabase Realtime a la fila de encuesta.
 *  4. Conexión LiveKit como supervisor para mostrar:
 *     - Estado del agente (Escuchando / Pensando / Hablando)
 *     - Transcripción en tiempo real de ambas partes.
 *  5. Cuando el estado pasa a terminal se desconecta LiveKit y muestra resultados.
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
    Phone, PhoneOff, X, Loader2, CheckCircle2, AlertTriangle,
    FlaskConical, Mic, Brain, Volume2, Bot, User, WifiOff, Radio
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
    Room, RoomEvent, RemoteParticipant, RemoteTrack,
    Track, TranscriptionSegment, ConnectionState
} from 'livekit-client';
import { supabase } from '../lib/supabase';
import { SurveyResult } from '../types';
import { CallResultModal } from './CallResultModal';
import { apiFetch } from '../lib/apiFetch';

interface Props {
    agentId: number;
    agentName: string;
    onClose: () => void;
}

type Phase = 'idle' | 'calling' | 'done' | 'error';
type AgentState = 'connecting' | 'listening' | 'thinking' | 'speaking';

interface TranscriptEntry {
    id: string;
    speaker: 'agent' | 'client' | 'system';
    label: string;
    text: string;
    ts: number;
    isFinal: boolean;
}

const TERMINAL_STATUSES = new Set([
    'completed', 'completada',
    'failed', 'fallida',
    'unreached', 'no_contesta',
    'incomplete', 'parcial',
    'rejected_opt_out', 'rechazada', 'rejected',
]);

const PHASE_TIMEOUT_MS = 5 * 60 * 1000;
const API_URL = import.meta.env.VITE_API_URL || '';
const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL || 'wss://ausarta-robot-m7e6v2y5.livekit.cloud';

function classifySpeaker(identity: string): { role: 'agent' | 'client'; label: string } {
    const lower = (identity || '').toLowerCase();
    if (lower.startsWith('agent') || lower.includes('agent')) return { role: 'agent', label: 'Agente IA' };
    return { role: 'client', label: 'Cliente' };
}

const AGENT_STATE_CONFIG: Record<AgentState, { icon: typeof Mic; color: string; bg: string; text: string; pulse: boolean }> = {
    connecting: { icon: Radio,   color: 'text-yellow-500', bg: 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800', text: 'Conectando…',  pulse: true },
    listening:  { icon: Mic,     color: 'text-emerald-500', bg: 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800', text: 'Escuchando…',  pulse: true },
    thinking:   { icon: Brain,   color: 'text-amber-500', bg: 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800', text: 'Pensando…',    pulse: true },
    speaking:   { icon: Volume2, color: 'text-blue-500', bg: 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800', text: 'Hablando…',    pulse: false },
};

export const TestCallModal: React.FC<Props> = ({ agentId, agentName, onClose }) => {
    const { t } = useTranslation();

    const [phone, setPhone] = useState('');
    const [phase, setPhase] = useState<Phase>('idle');
    const [errorMsg, setErrorMsg] = useState('');
    const [callId, setCallId] = useState<number | null>(null);
    const [result, setResult] = useState<SurveyResult | null>(null);
    const [showResult, setShowResult] = useState(false);
    const [elapsedSecs, setElapsedSecs] = useState(0);

    // LiveKit sandbox state
    const [agentState, setAgentState] = useState<AgentState>('connecting');
    const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);
    const [lkConnected, setLkConnected] = useState(false);

    const channelRef = useRef<ReturnType<typeof supabase.channel> | null>(null);
    const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const roomRef = useRef<Room | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const thinkingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const transcriptsEndRef = useRef<HTMLDivElement>(null);
    const entryCounter = useRef(0);

    const cleanup = useCallback(() => {
        if (channelRef.current) { supabase.removeChannel(channelRef.current); channelRef.current = null; }
        if (timerRef.current) clearInterval(timerRef.current);
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        if (thinkingTimerRef.current) { clearTimeout(thinkingTimerRef.current); thinkingTimerRef.current = null; }
        if (roomRef.current) {
            try { roomRef.current.disconnect(); } catch { /* ignore */ }
            roomRef.current = null;
        }
        setLkConnected(false);
    }, []);

    useEffect(() => () => cleanup(), [cleanup]);

    // Elapsed-seconds ticker
    useEffect(() => {
        if (phase === 'calling') {
            setElapsedSecs(0);
            timerRef.current = setInterval(() => setElapsedSecs(s => s + 1), 1000);
        } else {
            if (timerRef.current) clearInterval(timerRef.current);
        }
    }, [phase]);

    // Auto-scroll transcripts
    useEffect(() => {
        transcriptsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [transcripts]);

    const nextId = () => { entryCounter.current++; return `te-${entryCounter.current}-${Date.now()}`; };

    const addSystemMsg = useCallback((text: string) => {
        setTranscripts(prev => [...prev, { id: `sys-${Date.now()}`, speaker: 'system', label: 'Sistema', text, ts: Date.now(), isFinal: true }].slice(-80));
    }, []);

    // --- Transition to "thinking" after client speaks, cleared when agent speaks ---
    const scheduleThinking = useCallback(() => {
        if (thinkingTimerRef.current) clearTimeout(thinkingTimerRef.current);
        thinkingTimerRef.current = setTimeout(() => setAgentState('thinking'), 800);
    }, []);

    // --- LiveKit connection: poll live-sessions, then connect ---
    const connectLiveKit = useCallback(async (surveyId: number) => {
        setAgentState('connecting');

        const findRoom = async (): Promise<string | null> => {
            try {
                const res = await fetch(`${API_URL}/api/dashboard/live-sessions`);
                if (!res.ok) return null;
                const sessions: { name: string }[] = await res.json();
                const match = sessions.find(s => s.name.includes(`encuesta_${surveyId}`) || s.name.includes(`_${surveyId}`));
                return match?.name ?? null;
            } catch { return null; }
        };

        // Try immediately, then poll every 3s
        let roomName = await findRoom();
        if (!roomName) {
            await new Promise<void>((resolve) => {
                pollRef.current = setInterval(async () => {
                    roomName = await findRoom();
                    if (roomName && pollRef.current) {
                        clearInterval(pollRef.current);
                        pollRef.current = null;
                        resolve();
                    }
                }, 3000);

                // Stop polling after 60s
                setTimeout(() => {
                    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                    resolve();
                }, 60_000);
            });
        }

        if (!roomName) {
            addSystemMsg(t('No se pudo encontrar la sala de LiveKit. Transcripción no disponible.'));
            return;
        }

        try {
            const tokenRes = await fetch(`${API_URL}/api/dashboard/token?room_name=${encodeURIComponent(roomName)}`);
            if (!tokenRes.ok) throw new Error(`HTTP ${tokenRes.status}`);
            const { token } = await tokenRes.json();

            const room = new Room({ adaptiveStream: true, dynacast: true });
            roomRef.current = room;

            room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
                if (state === ConnectionState.Connected) {
                    setLkConnected(true);
                    setAgentState('listening');
                    addSystemMsg(t('Conectado a la sala. Transcripción en vivo activa.'));
                } else if (state === ConnectionState.Disconnected) {
                    setLkConnected(false);
                }
            });

            room.on(RoomEvent.TranscriptionReceived, (segments: TranscriptionSegment[], participant?: RemoteParticipant) => {
                const identity = participant?.identity || participant?.name || 'unknown';
                const { role, label } = classifySpeaker(identity);
                const text = segments.map(s => s.text).join(' ').trim();
                if (!text) return;
                const allFinal = segments.every(s => s.final);

                if (role === 'agent') {
                    setAgentState('speaking');
                    if (thinkingTimerRef.current) { clearTimeout(thinkingTimerRef.current); thinkingTimerRef.current = null; }
                } else {
                    setAgentState('listening');
                    if (allFinal) scheduleThinking();
                }

                setTranscripts(prev => {
                    if (prev.length > 0) {
                        const last = prev[prev.length - 1];
                        if (last.speaker === role && !last.isFinal) {
                            const updated = [...prev];
                            updated[updated.length - 1] = { ...last, text, isFinal: allFinal, ts: Date.now() };
                            return updated.slice(-80);
                        }
                    }
                    return [...prev, { id: nextId(), speaker: role, label, text, ts: Date.now(), isFinal: allFinal }].slice(-80);
                });
            });

            room.on(RoomEvent.DataReceived, (payload: Uint8Array, participant?: RemoteParticipant) => {
                try {
                    const data = JSON.parse(new TextDecoder().decode(payload));
                    if (data.text || data.transcription) {
                        const identity = participant?.identity || 'Agent';
                        const { role, label } = classifySpeaker(identity);
                        setTranscripts(prev => [...prev, { id: nextId(), speaker: role, label, text: data.text || data.transcription, ts: Date.now(), isFinal: true }].slice(-80));
                    }
                } catch { /* not JSON or not transcription */ }
            });

            room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
                if (track.kind === Track.Kind.Audio) {
                    const el = track.attach();
                    el.muted = true; // supervisor mode: muted by default
                }
            });

            room.on(RoomEvent.ParticipantDisconnected, (p: RemoteParticipant) => {
                const { label } = classifySpeaker(p.identity);
                addSystemMsg(`${label} se desconectó`);
            });

            await room.connect(LIVEKIT_URL, token);
            setLkConnected(true);
            setAgentState('listening');
        } catch (err: any) {
            console.error('LiveKit sandbox connect error:', err);
            addSystemMsg(t('Error conectando al sandbox LiveKit.'));
        }
    }, [addSystemMsg, scheduleThinking, t]);

    // --- Supabase Realtime subscription ---
    const subscribeToResult = (surveyId: number) => {
        const channel = supabase
            .channel(`test-call-${surveyId}`)
            .on(
                'postgres_changes',
                { event: 'UPDATE', schema: 'public', table: 'encuestas', filter: `id=eq.${surveyId}` },
                async (payload) => {
                    const updated = payload.new as SurveyResult;
                    if (updated.status && TERMINAL_STATUSES.has(updated.status)) {
                        cleanup();
                        const { data } = await supabase.from('encuestas').select('*').eq('id', surveyId).single();
                        const fullResult = (data as SurveyResult) ?? updated;
                        setResult(fullResult);
                        setPhase('done');
                        setShowResult(true);
                    }
                }
            )
            .subscribe();

        channelRef.current = channel;

        timeoutRef.current = setTimeout(async () => {
            cleanup();
            const { data } = await supabase.from('encuestas').select('*').eq('id', surveyId).single();
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
        setTranscripts([]);
        entryCounter.current = 0;

        try {
            const res = await apiFetch('/api/calls/outbound', {
                method: 'POST',
                body: JSON.stringify({ phoneNumber: cleaned, agentId: String(agentId), customerName: 'Test — Simulador', isTestCall: true }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                const d = err.detail;
                const msg = Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg || '').join(' ') : (d || err.error || `HTTP ${res.status}`);
                throw new Error(msg);
            }
            const data = await res.json();
            const surveyId: number = data.callId;
            setCallId(surveyId);
            subscribeToResult(surveyId);
            connectLiveKit(surveyId);
        } catch (e: any) {
            setErrorMsg(e.message || t('Error desconocido'));
            setPhase('error');
        }
    };

    const handleCancel = () => {
        cleanup();
        setPhase('idle');
        setCallId(null);
        setTranscripts([]);
        setAgentState('connecting');
    };

    const fmtSecs = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`;

    if (showResult && result) {
        return <CallResultModal result={result} onClose={() => { setShowResult(false); onClose(); }} />;
    }

    const stCfg = AGENT_STATE_CONFIG[agentState];
    const StateIcon = stCfg.icon;

    return (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
            <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden animate-in fade-in zoom-in duration-200 flex flex-col"
                 style={{ maxHeight: 'min(92vh, 720px)' }}>

                {/* Header */}
                <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-800 flex justify-between items-center bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-gray-800 dark:to-indigo-950/30 shrink-0">
                    <div className="flex items-center gap-3">
                        <div className="bg-blue-100 dark:bg-blue-900/40 p-2 rounded-xl">
                            <FlaskConical size={20} className="text-blue-600 dark:text-blue-400" />
                        </div>
                        <div>
                            <h3 className="text-base font-bold text-gray-900 dark:text-white">{t('Probar Agente', 'Probar Agente')}</h3>
                            <p className="text-xs text-gray-500 dark:text-gray-400">{agentName}</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {phase === 'calling' && (
                            <span className="font-mono text-xs text-gray-400 tabular-nums">{fmtSecs(elapsedSecs)}</span>
                        )}
                        <button
                            onClick={phase === 'calling' ? handleCancel : onClose}
                            className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 dark:hover:text-white bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-full hover:shadow-sm transition-all"
                        >
                            <X size={16} />
                        </button>
                    </div>
                </div>

                {/* Body */}
                <div className="flex-1 flex flex-col overflow-hidden">

                    {/* === IDLE / ERROR === */}
                    {(phase === 'idle' || phase === 'error') && (
                        <div className="p-6 space-y-5">
                            <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">
                                {t(
                                    'Introduce tu número de teléfono. El agente te llamará ahora mismo para que puedas probar cómo funciona en una conversación real.',
                                    'Introduce tu número de teléfono. El agente te llamará ahora mismo para que puedas probar cómo funciona en una conversación real.'
                                )}
                            </p>
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                    {t('Tu número de teléfono', 'Tu número de teléfono')}
                                </label>
                                <input
                                    type="tel"
                                    value={phone}
                                    onChange={e => setPhone(e.target.value)}
                                    onKeyDown={e => e.key === 'Enter' && handleCall()}
                                    placeholder="+34 600 000 000"
                                    className="w-full px-4 py-3 border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 font-mono tracking-wider text-gray-900 dark:text-white"
                                    autoFocus
                                />
                            </div>
                            {phase === 'error' && (
                                <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800 rounded-xl">
                                    <AlertTriangle size={16} className="text-red-500 shrink-0 mt-0.5" />
                                    <p className="text-sm text-red-700 dark:text-red-400">{errorMsg}</p>
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
                            <p className="text-[11px] text-gray-400 text-center leading-relaxed">
                                {t(
                                    'Esta es una llamada de prueba real. El agente ejecutará su guion completo y al finalizar verás los datos que extrajo.',
                                    'Esta es una llamada de prueba real. El agente ejecutará su guion completo y al finalizar verás los datos que extrajo.'
                                )}
                            </p>
                        </div>
                    )}

                    {/* === CALLING — SANDBOX VIEW === */}
                    {phase === 'calling' && (
                        <div className="flex-1 flex flex-col overflow-hidden">

                            {/* Agent State Indicator */}
                            <div className={`mx-4 mt-4 mb-2 flex items-center gap-3 px-4 py-3 rounded-xl border transition-all ${stCfg.bg}`}>
                                <div className="relative">
                                    <StateIcon size={22} className={stCfg.color} />
                                    {stCfg.pulse && (
                                        <span className={`absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full ${stCfg.color.replace('text-', 'bg-')} animate-pulse`} />
                                    )}
                                </div>
                                <div className="flex-1 min-w-0">
                                    <p className={`text-sm font-bold ${stCfg.color}`}>{t(stCfg.text)}</p>
                                    <p className="text-[10px] text-gray-400 dark:text-gray-500 truncate">
                                        {lkConnected
                                            ? t('Sandbox conectado — transcripción en vivo', 'Sandbox conectado — transcripción en vivo')
                                            : t('Conectando al sandbox…', 'Conectando al sandbox…')
                                        }
                                    </p>
                                </div>
                                <span className="font-mono text-xs text-gray-400 tabular-nums shrink-0">{fmtSecs(elapsedSecs)}</span>
                            </div>

                            {/* Live Transcript */}
                            <div className="flex-1 mx-4 mb-2 overflow-y-auto rounded-xl border border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-950/50">
                                {transcripts.length === 0 ? (
                                    <div className="h-full flex flex-col items-center justify-center text-gray-400 py-10 gap-3">
                                        <div className="w-12 h-12 rounded-2xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center animate-pulse">
                                            <Mic size={22} className="text-gray-300 dark:text-gray-600" />
                                        </div>
                                        <p className="text-xs font-medium">{t('Esperando transcripción…', 'Esperando transcripción…')}</p>
                                        <p className="text-[10px] text-gray-300 dark:text-gray-600 px-6 text-center">
                                            {t('La conversación aparecerá aquí en tiempo real', 'La conversación aparecerá aquí en tiempo real')}
                                        </p>
                                    </div>
                                ) : (
                                    <div className="p-3 space-y-1.5">
                                        {transcripts.map(entry => (
                                            <div
                                                key={entry.id}
                                                className={`flex gap-2 items-start py-1 transition-opacity duration-200 ${entry.isFinal ? 'opacity-100' : 'opacity-60'}`}
                                            >
                                                <div className={`shrink-0 w-6 h-6 rounded-lg flex items-center justify-center mt-0.5 ${
                                                    entry.speaker === 'agent'
                                                        ? 'bg-blue-100 dark:bg-blue-900/40'
                                                        : entry.speaker === 'client'
                                                        ? 'bg-emerald-100 dark:bg-emerald-900/40'
                                                        : 'bg-gray-100 dark:bg-gray-700'
                                                }`}>
                                                    {entry.speaker === 'agent'
                                                        ? <Bot size={13} className="text-blue-600 dark:text-blue-400" />
                                                        : entry.speaker === 'client'
                                                        ? <User size={13} className="text-emerald-600 dark:text-emerald-400" />
                                                        : <Radio size={11} className="text-gray-400" />
                                                    }
                                                </div>
                                                <div className="min-w-0 flex-1">
                                                    <div className="flex items-center gap-1.5 mb-0.5">
                                                        <span className={`text-[10px] font-bold uppercase tracking-wider ${
                                                            entry.speaker === 'agent' ? 'text-blue-600 dark:text-blue-400'
                                                            : entry.speaker === 'client' ? 'text-emerald-600 dark:text-emerald-400'
                                                            : 'text-gray-400'
                                                        }`}>{entry.label}</span>
                                                        <span className="text-[9px] text-gray-300 dark:text-gray-600 tabular-nums">
                                                            {new Date(entry.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                                        </span>
                                                        {!entry.isFinal && <span className="text-[8px] text-yellow-500 font-medium animate-pulse">●</span>}
                                                    </div>
                                                    <p className={`text-xs leading-relaxed ${
                                                        entry.speaker === 'system' ? 'text-gray-400 italic' : 'text-gray-700 dark:text-gray-200'
                                                    }`}>{entry.text}</p>
                                                </div>
                                            </div>
                                        ))}
                                        <div ref={transcriptsEndRef} />
                                    </div>
                                )}
                            </div>

                            {/* Cancel button */}
                            <div className="px-4 pb-4 pt-1 shrink-0">
                                <button
                                    onClick={handleCancel}
                                    className="w-full flex items-center justify-center gap-2 py-2.5 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/40 rounded-xl text-sm font-medium transition-colors"
                                >
                                    <PhoneOff size={16} />
                                    {t('Cancelar seguimiento', 'Cancelar seguimiento')}
                                </button>
                            </div>
                        </div>
                    )}

                    {/* === DONE (quick transition) === */}
                    {phase === 'done' && !showResult && (
                        <div className="flex flex-col items-center py-8 gap-4 p-6">
                            <div className="w-16 h-16 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center">
                                <CheckCircle2 size={32} className="text-green-600 dark:text-green-400" />
                            </div>
                            <p className="font-bold text-gray-900 dark:text-white">{t('Llamada finalizada', 'Llamada finalizada')}</p>
                            <button
                                onClick={() => setShowResult(true)}
                                className="px-6 py-2.5 bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-sm font-semibold rounded-xl hover:bg-black dark:hover:bg-gray-100 transition-all"
                            >
                                {t('Ver resultados', 'Ver resultados')}
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
