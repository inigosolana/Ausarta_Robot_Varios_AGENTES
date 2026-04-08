import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
    Activity,
    X,
    Play,
    Square,
    MessageSquare,
    Volume2,
    VolumeX,
    Users,
    Wifi,
    WifiOff,
    RefreshCw,
    Shield,
    Clock,
    Phone,
    PhoneOff,
    Radio,
    Eye,
    ChevronDown,
    AlertCircle,
    User,
    Bot
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
    Room,
    RoomEvent,
    RemoteParticipant,
    RemoteTrack,
    Track,
    TranscriptionSegment,
    ConnectionState
} from 'livekit-client';

const API_URL = import.meta.env.VITE_API_URL || '';

interface LiveSession {
    sid: string;
    name: string;
    num_participants: number;
    created_at: number;
}

interface TranscriptEntry {
    id: string;
    speaker: 'agent' | 'client' | 'system';
    speakerLabel: string;
    text: string;
    timestamp: number;
    isFinal: boolean;
}

type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

// Clasifica participantes por su identidad LiveKit
function classifySpeaker(identity: string): { role: 'agent' | 'client' | 'system'; label: string } {
    const lower = (identity || '').toLowerCase();
    if (lower.startsWith('agent') || lower.includes('agent')) {
        return { role: 'agent', label: 'Agente IA' };
    }
    if (lower.startsWith('sip_') || lower.startsWith('user_') || lower.startsWith('phone_')) {
        return { role: 'client', label: 'Cliente' };
    }
    if (lower.startsWith('supervisor')) {
        return { role: 'system', label: 'Supervisor' };
    }
    return { role: 'client', label: identity || 'Participante' };
}

function formatDuration(startMs: number): string {
    const elapsed = Math.floor((Date.now() - startMs) / 1000);
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatRoomName(name: string): string {
    // llamada_ausarta_empresa_X_campana_Y_contacto_Z_encuesta_W -> Encuesta #W
    const encMatch = name.match(/encuesta_(\d+)/);
    if (encMatch) return `Encuesta #${encMatch[1]}`;
    const callMatch = name.match(/call_(\d+)/);
    if (callMatch) return `Llamada #${callMatch[1]}`;
    // Fallback: últimos 20 chars
    return name.length > 25 ? `…${name.slice(-22)}` : name;
}

export const LiveMonitoring: React.FC = () => {
    const { t } = useTranslation();
    const [sessions, setSessions] = useState<LiveSession[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [selectedRoom, setSelectedRoom] = useState<string | null>(null);
    const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);
    const [isMonitoring, setIsMonitoring] = useState(false);
    const [isMuted, setIsMuted] = useState(true);
    const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected');
    const [monitorStartTime, setMonitorStartTime] = useState<number>(0);
    const [elapsedDisplay, setElapsedDisplay] = useState('0:00');
    const [participantCount, setParticipantCount] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [autoScroll, setAutoScroll] = useState(true);

    const roomRef = useRef<Room | null>(null);
    const transcriptsEndRef = useRef<HTMLDivElement>(null);
    const transcriptsContainerRef = useRef<HTMLDivElement>(null);
    const audioElementsRef = useRef<HTMLAudioElement[]>([]);
    const entryIdCounter = useRef(0);

    // Auto-refresh de sesiones activas
    useEffect(() => {
        loadSessions();
        const interval = setInterval(loadSessions, 15000);
        return () => {
            clearInterval(interval);
            stopMonitoring();
        };
    }, []);

    // Scroll automático en transcripciones
    useEffect(() => {
        if (autoScroll && transcriptsEndRef.current) {
            transcriptsEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [transcripts, autoScroll]);

    // Timer de duración de monitorización
    useEffect(() => {
        if (!isMonitoring || !monitorStartTime) return;
        const timer = setInterval(() => {
            setElapsedDisplay(formatDuration(monitorStartTime));
        }, 1000);
        return () => clearInterval(timer);
    }, [isMonitoring, monitorStartTime]);

    // Detectar scroll manual para desactivar autoscroll
    const handleTranscriptsScroll = useCallback(() => {
        if (!transcriptsContainerRef.current) return;
        const el = transcriptsContainerRef.current;
        const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        setAutoScroll(isAtBottom);
    }, []);

    const loadSessions = async () => {
        try {
            setIsLoading(true);
            const res = await fetch(`${API_URL}/api/dashboard/live-sessions`);
            if (res.ok) {
                const data = await res.json();
                setSessions(data);
            }
        } catch (err) {
            console.error('Error loading live sessions:', err);
        } finally {
            setIsLoading(false);
        }
    };

    const nextEntryId = () => {
        entryIdCounter.current += 1;
        return `t-${entryIdCounter.current}-${Date.now()}`;
    };

    const addSystemMessage = (text: string) => {
        setTranscripts(prev => [
            ...prev,
            {
                id: nextEntryId(),
                speaker: 'system',
                speakerLabel: 'Sistema',
                text,
                timestamp: Date.now(),
                isFinal: true,
            }
        ]);
    };

    const startMonitoring = async (roomName: string) => {
        if (isMonitoring) await stopMonitoring();

        try {
            setSelectedRoom(roomName);
            setTranscripts([]);
            setIsMonitoring(true);
            setConnectionStatus('connecting');
            setError(null);
            setMonitorStartTime(Date.now());
            setAutoScroll(true);
            entryIdCounter.current = 0;

            // 1. Obtener token de supervisor
            const tokenRes = await fetch(`${API_URL}/api/dashboard/token?room_name=${encodeURIComponent(roomName)}`);
            if (!tokenRes.ok) {
                throw new Error(`Error obteniendo token: HTTP ${tokenRes.status}`);
            }
            const { token } = await tokenRes.json();

            // 2. Conectar a LiveKit
            const room = new Room({
                adaptiveStream: true,
                dynacast: true,
            });
            roomRef.current = room;

            // --- Event: Estado de conexión ---
            room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
                if (state === ConnectionState.Connected) {
                    setConnectionStatus('connected');
                    addSystemMessage('Conectado a la sala. Escuchando transcripción…');
                } else if (state === ConnectionState.Reconnecting) {
                    setConnectionStatus('connecting');
                } else if (state === ConnectionState.Disconnected) {
                    setConnectionStatus('disconnected');
                }
            });

            // --- Event: Transcripciones ---
            room.on(RoomEvent.TranscriptionReceived, (segments: TranscriptionSegment[], participant?: RemoteParticipant) => {
                const identity = participant?.identity || participant?.name || 'unknown';
                const { role, label } = classifySpeaker(identity);

                // Concatenar segmentos del mismo turno
                const combinedText = segments.map(s => s.text).join(' ').trim();
                if (!combinedText) return;

                // Determinar si es final (todos los segmentos son finales)
                const allFinal = segments.every(s => s.final);

                setTranscripts(prev => {
                    // Si el último mensaje es del mismo speaker y no era final, lo actualizamos
                    if (prev.length > 0) {
                        const last = prev[prev.length - 1];
                        if (last.speaker === role && !last.isFinal) {
                            const updated = [...prev];
                            updated[updated.length - 1] = {
                                ...last,
                                text: combinedText,
                                isFinal: allFinal,
                                timestamp: Date.now(),
                            };
                            return updated.slice(-100);
                        }
                    }

                    return [
                        ...prev,
                        {
                            id: `t-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
                            speaker: role,
                            speakerLabel: label,
                            text: combinedText,
                            timestamp: Date.now(),
                            isFinal: allFinal,
                        }
                    ].slice(-100);
                });
            });

            // --- Event: Data messages (fallback para transcripciones por data channel) ---
            room.on(RoomEvent.DataReceived, (payload: Uint8Array, participant?: RemoteParticipant) => {
                try {
                    const decoder = new TextDecoder();
                    const data = JSON.parse(decoder.decode(payload));
                    if (data.text || data.transcription) {
                        const identity = participant?.identity || 'Agent';
                        const { role, label } = classifySpeaker(identity);
                        const text = data.text || data.transcription;
                        setTranscripts(prev => [
                            ...prev,
                            {
                                id: nextEntryId(),
                                speaker: role,
                                speakerLabel: label,
                                text,
                                timestamp: Date.now(),
                                isFinal: true,
                            }
                        ].slice(-100));
                    }
                } catch {
                    // No es JSON o no es transcripción
                }
            });

            // --- Event: Audio tracks (supervisor escucha) ---
            room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
                if (track.kind === Track.Kind.Audio) {
                    const audioEl = track.attach();
                    audioEl.muted = isMuted;
                    audioElementsRef.current.push(audioEl);
                }
            });

            // --- Event: Participantes ---
            room.on(RoomEvent.ParticipantConnected, () => {
                setParticipantCount(room.remoteParticipants.size + 1);
            });
            room.on(RoomEvent.ParticipantDisconnected, (p: RemoteParticipant) => {
                setParticipantCount(room.remoteParticipants.size + 1);
                const { label } = classifySpeaker(p.identity);
                addSystemMessage(`${label} se desconectó`);
            });

            // --- Event: Desconexión ---
            room.on(RoomEvent.Disconnected, () => {
                setConnectionStatus('disconnected');
                addSystemMessage('Desconectado de la sala.');
            });

            // 3. Conectar
            const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL || 'wss://ausarta-robot-m7e6v2y5.livekit.cloud';
            await room.connect(LIVEKIT_URL, token);
            setParticipantCount(room.remoteParticipants.size + 1);
            setConnectionStatus('connected');

        } catch (err: any) {
            console.error('Monitoring error:', err);
            setError(err.message || 'Error desconocido');
            setConnectionStatus('error');
            setIsMonitoring(false);
            setSelectedRoom(null);
        }
    };

    const stopMonitoring = async () => {
        // Limpiar elementos de audio
        audioElementsRef.current.forEach(el => {
            el.pause();
            el.srcObject = null;
            el.remove();
        });
        audioElementsRef.current = [];

        if (roomRef.current) {
            try {
                await roomRef.current.disconnect();
            } catch { /* ignore */ }
            roomRef.current = null;
        }
        setIsMonitoring(false);
        setSelectedRoom(null);
        setTranscripts([]);
        setConnectionStatus('disconnected');
        setError(null);
        setParticipantCount(0);
    };

    const toggleAudio = () => {
        const newMuted = !isMuted;
        setIsMuted(newMuted);
        audioElementsRef.current.forEach(el => {
            el.muted = newMuted;
        });
    };

    // --- Indicador de conexión ---
    const ConnectionIndicator: React.FC = () => {
        const statusConfig = {
            disconnected: { color: 'bg-gray-400', text: 'Desconectado', icon: WifiOff },
            connecting: { color: 'bg-yellow-400 animate-pulse', text: 'Conectando…', icon: Wifi },
            connected: { color: 'bg-emerald-500 animate-pulse', text: 'En vivo', icon: Radio },
            error: { color: 'bg-red-500', text: 'Error', icon: AlertCircle },
        };
        const cfg = statusConfig[connectionStatus];
        const Icon = cfg.icon;
        return (
            <div className="flex items-center gap-1.5">
                <div className={`w-2 h-2 rounded-full ${cfg.color}`} />
                <Icon size={12} className="text-gray-400" />
                <span className="text-[10px] text-gray-400 uppercase tracking-wider font-medium">{cfg.text}</span>
            </div>
        );
    };

    return (
        <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-100 dark:border-gray-700 shadow-sm overflow-hidden h-full flex flex-col"
             style={{ animation: 'slideUp 0.3s ease-out' }}>

            {/* Header */}
            <div className="p-4 border-b border-gray-50 dark:border-gray-700 bg-gradient-to-r from-gray-50/80 to-blue-50/30 dark:from-gray-700/30 dark:to-blue-900/10 flex justify-between items-center">
                <div className="flex items-center gap-2">
                    <div className="p-1.5 bg-blue-100 dark:bg-blue-900/40 rounded-lg">
                        <Shield className="text-blue-600 dark:text-blue-400" size={18} />
                    </div>
                    <div>
                        <h3 className="font-bold text-gray-800 dark:text-white text-sm">
                            {t('Live Supervision', 'Supervisión en Vivo')}
                        </h3>
                        {isMonitoring && (
                            <div className="flex items-center gap-2 mt-0.5">
                                <ConnectionIndicator />
                            </div>
                        )}
                    </div>
                </div>
                <div className="flex items-center gap-1">
                    {isMonitoring && (
                        <div className="flex items-center gap-1 px-2 py-1 bg-red-50 dark:bg-red-900/20 rounded-lg mr-1">
                            <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                            <Clock size={11} className="text-red-500" />
                            <span className="text-[10px] font-bold text-red-600 dark:text-red-400 tabular-nums">{elapsedDisplay}</span>
                        </div>
                    )}
                    <button
                        onClick={loadSessions}
                        disabled={isLoading}
                        className="p-1.5 hover:bg-white dark:hover:bg-gray-600 rounded-lg transition-colors disabled:opacity-50"
                        title={t('Refresh', 'Actualizar')}
                    >
                        <RefreshCw size={14} className={`${isLoading ? 'animate-spin text-blue-500' : 'text-gray-400'}`} />
                    </button>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 flex flex-col min-h-[320px]">
                {!isMonitoring ? (
                    /* --- LISTA DE SESIONES --- */
                    <div className="p-4 flex-1 overflow-y-auto">
                        {error && (
                            <div className="mb-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800 rounded-xl flex items-start gap-2">
                                <AlertCircle size={14} className="text-red-500 mt-0.5 shrink-0" />
                                <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
                            </div>
                        )}

                        <div className="space-y-2">
                            {sessions.length === 0 ? (
                                <div className="text-center py-16">
                                    <div className="w-16 h-16 bg-gray-50 dark:bg-gray-700 rounded-2xl flex items-center justify-center mx-auto mb-4"
                                         style={{ animation: 'pulse 3s ease-in-out infinite' }}>
                                        <Phone size={28} className="text-gray-300 dark:text-gray-500" />
                                    </div>
                                    <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
                                        {t('No active calls at the moment', 'No hay llamadas activas')}
                                    </p>
                                    <p className="text-[10px] text-gray-400 mt-1">
                                        {t('Calls will appear here in real-time', 'Las llamadas aparecerán aquí en tiempo real')}
                                    </p>
                                </div>
                            ) : (
                                sessions.map(session => (
                                    <div
                                        key={session.sid}
                                        className="group p-3 border border-gray-100 dark:border-gray-700 rounded-xl hover:border-blue-200 dark:hover:border-blue-700 hover:bg-blue-50/30 dark:hover:bg-blue-900/10 transition-all cursor-pointer"
                                        onClick={() => startMonitoring(session.name)}
                                    >
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-3">
                                                <div className="relative">
                                                    <div className="w-9 h-9 rounded-xl bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center">
                                                        <Phone size={16} className="text-emerald-600 dark:text-emerald-400" />
                                                    </div>
                                                    <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 border-2 border-white dark:border-gray-800 animate-pulse" />
                                                </div>
                                                <div>
                                                    <p className="text-sm font-bold text-gray-800 dark:text-white">
                                                        {formatRoomName(session.name)}
                                                    </p>
                                                    <div className="flex items-center gap-2 mt-0.5">
                                                        <span className="text-[10px] text-gray-400 flex items-center gap-1">
                                                            <Users size={10} /> {session.num_participants}
                                                        </span>
                                                        <span className="text-[10px] text-gray-400 flex items-center gap-1">
                                                            <Clock size={10} /> {formatDuration(session.created_at * 1000)}
                                                        </span>
                                                    </div>
                                                </div>
                                            </div>
                                            <button
                                                onClick={(e) => { e.stopPropagation(); startMonitoring(session.name); }}
                                                className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-lg text-[10px] font-bold opacity-0 group-hover:opacity-100 transition-all hover:scale-105 active:scale-95"
                                            >
                                                <Eye size={12} />
                                                {t('Monitor', 'Monitorear')}
                                            </button>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                ) : (
                    /* --- VISTA DE MONITORIZACIÓN --- */
                    <div className="flex-1 flex flex-col overflow-hidden">
                        {/* Toolbar de monitorización */}
                        <div className="px-3 py-2 border-b border-gray-100 dark:border-gray-700 flex justify-between items-center bg-gray-50/50 dark:bg-gray-800/50">
                            <div className="flex items-center gap-2 min-w-0">
                                <div className="shrink-0 flex items-center gap-1.5">
                                    <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                                    <span className="text-[10px] font-bold text-red-500 uppercase tracking-wider">REC</span>
                                </div>
                                <span className="text-xs font-bold text-gray-700 dark:text-gray-200 truncate" title={selectedRoom || ''}>
                                    {formatRoomName(selectedRoom || '')}
                                </span>
                                <span className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-[9px] text-gray-500 font-medium shrink-0">
                                    <Users size={9} className="inline mr-0.5" />{participantCount}
                                </span>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                                <button
                                    onClick={toggleAudio}
                                    className={`p-1.5 rounded-lg transition-all ${
                                        isMuted
                                            ? 'text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700'
                                            : 'text-blue-500 bg-blue-50 dark:bg-blue-900/30 hover:bg-blue-100'
                                    }`}
                                    title={isMuted ? t('Unmute', 'Activar audio') : t('Mute', 'Silenciar')}
                                >
                                    {isMuted ? <VolumeX size={15} /> : <Volume2 size={15} />}
                                </button>
                                <button
                                    onClick={stopMonitoring}
                                    className="p-1.5 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/40 text-red-500 rounded-lg transition-all hover:scale-105 active:scale-95"
                                    title={t('Stop monitoring', 'Detener monitorización')}
                                >
                                    <PhoneOff size={15} />
                                </button>
                            </div>
                        </div>

                        {/* Transcripciones */}
                        <div
                            ref={transcriptsContainerRef}
                            onScroll={handleTranscriptsScroll}
                            className="flex-1 p-3 overflow-y-auto space-y-1.5 bg-white dark:bg-gray-900"
                        >
                            {transcripts.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-gray-400 space-y-3 py-12">
                                    <div className="w-12 h-12 rounded-2xl bg-gray-50 dark:bg-gray-800 flex items-center justify-center"
                                         style={{ animation: 'pulse 2s ease-in-out infinite' }}>
                                        <MessageSquare size={24} className="text-gray-300" />
                                    </div>
                                    <div className="text-center">
                                        <p className="text-sm font-medium">{t('Waiting for transcription...', 'Esperando transcripción…')}</p>
                                        <p className="text-[10px] text-gray-400 mt-1">
                                            {t('Transcription will appear as the conversation happens', 'La transcripción aparecerá en tiempo real')}
                                        </p>
                                    </div>
                                </div>
                            ) : (
                                transcripts.map((entry) => (
                                    <div
                                        key={entry.id}
                                        className={`flex gap-2 items-start py-1.5 transition-opacity duration-300 ${
                                            entry.isFinal ? 'opacity-100' : 'opacity-60'
                                        }`}
                                        style={{ animation: 'fadeIn 0.2s ease-out' }}
                                    >
                                        {/* Avatar */}
                                        <div className={`shrink-0 w-6 h-6 rounded-lg flex items-center justify-center mt-0.5 ${
                                            entry.speaker === 'agent'
                                                ? 'bg-blue-100 dark:bg-blue-900/40'
                                                : entry.speaker === 'client'
                                                ? 'bg-emerald-100 dark:bg-emerald-900/40'
                                                : 'bg-gray-100 dark:bg-gray-700'
                                        }`}>
                                            {entry.speaker === 'agent' ? (
                                                <Bot size={13} className="text-blue-600 dark:text-blue-400" />
                                            ) : entry.speaker === 'client' ? (
                                                <User size={13} className="text-emerald-600 dark:text-emerald-400" />
                                            ) : (
                                                <Activity size={11} className="text-gray-400" />
                                            )}
                                        </div>

                                        {/* Contenido */}
                                        <div className="min-w-0 flex-1">
                                            <div className="flex items-center gap-1.5 mb-0.5">
                                                <span className={`text-[10px] font-bold uppercase tracking-wider ${
                                                    entry.speaker === 'agent'
                                                        ? 'text-blue-600 dark:text-blue-400'
                                                        : entry.speaker === 'client'
                                                        ? 'text-emerald-600 dark:text-emerald-400'
                                                        : 'text-gray-400'
                                                }`}>
                                                    {entry.speakerLabel}
                                                </span>
                                                <span className="text-[9px] text-gray-300 dark:text-gray-600 tabular-nums">
                                                    {new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                                </span>
                                                {!entry.isFinal && (
                                                    <span className="text-[8px] text-yellow-500 font-medium animate-pulse">●</span>
                                                )}
                                            </div>
                                            <p className={`text-xs leading-relaxed ${
                                                entry.speaker === 'system'
                                                    ? 'text-gray-400 italic'
                                                    : 'text-gray-700 dark:text-gray-200'
                                            }`}>
                                                {entry.text}
                                            </p>
                                        </div>
                                    </div>
                                ))
                            )}
                            <div ref={transcriptsEndRef} />
                        </div>

                        {/* Scroll-to-bottom indicator */}
                        {!autoScroll && transcripts.length > 0 && (
                            <button
                                onClick={() => {
                                    setAutoScroll(true);
                                    transcriptsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
                                }}
                                className="absolute bottom-14 left-1/2 -translate-x-1/2 px-3 py-1.5 bg-gray-900/80 dark:bg-white/80 text-white dark:text-gray-900 text-[10px] font-bold rounded-full shadow-lg flex items-center gap-1 hover:scale-105 transition-transform z-10"
                            >
                                <ChevronDown size={12} />
                                {t('New messages', 'Nuevos mensajes')}
                            </button>
                        )}
                    </div>
                )}
            </div>

            {/* Footer */}
            <div className="p-2.5 bg-gray-50 dark:bg-gray-700/30 text-[10px] text-gray-500 flex items-center justify-between border-t border-gray-100 dark:border-gray-700">
                <span className="flex items-center gap-1">
                    <Wifi size={10} className={sessions.length > 0 ? 'text-emerald-500' : 'text-gray-400'} />
                    LiveKit Cloud
                </span>
                <span className="font-medium">
                    {sessions.length} {t('Active Rooms', sessions.length === 1 ? 'Sala Activa' : 'Salas Activas')}
                </span>
            </div>

            {/* Inline animations (CSS-in-JS fallback para no depender de index.css) */}
            <style>{`
                @keyframes slideUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
                @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
                @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
            `}</style>
        </div>
    );
};
