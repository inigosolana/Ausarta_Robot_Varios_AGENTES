import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
    X,
    Phone,
    PhoneOff,
    UserCheck,
    Clock,
    ChevronDown,
    Bot,
    User,
    AlertTriangle,
    CheckCircle,
    Loader2,
    ArrowRight,
} from 'lucide-react';
import { supabase } from '../lib/supabase';
import { apiFetch } from '../lib/apiFetch';

const API_URL = (import.meta as any).env.VITE_API_URL || '';

interface TranscriptEntry {
    speaker: 'agent' | 'user';
    text: string;
    ts: string;
}

interface ContactInfo {
    nombre: string | null;
    telefono: string;
    datos_extra: Record<string, unknown>;
}

interface Extension {
    id: string;
    extension_number: string;
    extension_name: string | null;
    departamento: string | null;
}

interface CallData {
    room_name: string;
    status: 'active' | 'transferred' | 'ended';
    duration_seconds: number;
    transcript: TranscriptEntry[];
    contact: ContactInfo;
    transfer_briefing: string | null;
    extensions_available: Extension[];
}

interface LiveCallPanelProps {
    roomName: string;
    onClose: () => void;
}

function formatSeconds(s: number): string {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
}

const StatusBadge: React.FC<{ status: CallData['status'] }> = ({ status }) => {
    const cfg = {
        active: { label: 'En llamada', cls: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
        transferred: { label: 'Transfiriendo', cls: 'bg-amber-100 text-amber-700 border-amber-200' },
        ended: { label: 'Finalizada', cls: 'bg-gray-100 text-gray-500 border-gray-200' },
    }[status];
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wider ${cfg.cls}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${status === 'active' ? 'bg-emerald-500 animate-pulse' : status === 'transferred' ? 'bg-amber-500 animate-pulse' : 'bg-gray-400'}`} />
            {cfg.label}
        </span>
    );
};

export const LiveCallPanel: React.FC<LiveCallPanelProps> = ({ roomName, onClose }) => {
    const [data, setData] = useState<CallData | null>(null);
    const [connected, setConnected] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [selectedExt, setSelectedExt] = useState('');
    const [transferring, setTransferring] = useState(false);
    const [hangingUp, setHangingUp] = useState(false);
    const [actionMsg, setActionMsg] = useState<{ ok: boolean; text: string } | null>(null);

    const transcriptEndRef = useRef<HTMLDivElement>(null);
    const transcriptBoxRef = useRef<HTMLDivElement>(null);
    const esRef = useRef<EventSource | null>(null);
    const [autoScroll, setAutoScroll] = useState(true);

    // Pick first extension when data loads
    useEffect(() => {
        if (data?.extensions_available.length && !selectedExt) {
            setSelectedExt(data.extensions_available[0].extension_number);
        }
    }, [data?.extensions_available]);

    // Auto-scroll
    useEffect(() => {
        if (autoScroll && transcriptEndRef.current) {
            transcriptEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [data?.transcript, autoScroll]);

    const handleTranscriptScroll = useCallback(() => {
        const el = transcriptBoxRef.current;
        if (!el) return;
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        setAutoScroll(atBottom);
    }, []);

    const connectSSE = useCallback(async () => {
        if (esRef.current) {
            esRef.current.close();
            esRef.current = null;
        }

        let token: string | null = null;
        try {
            const { data: sd } = await supabase.auth.getSession();
            token = sd.session?.access_token ?? null;
        } catch { /* ignore */ }

        if (!token) {
            setTimeout(connectSSE, 3000);
            return;
        }

        const url = `${API_URL}/api/monitoring/call/${encodeURIComponent(roomName)}/stream?token=${encodeURIComponent(token)}`;
        const es = new EventSource(url);
        esRef.current = es;

        es.onopen = () => setConnected(true);

        es.onmessage = (evt) => {
            try {
                const payload: CallData = JSON.parse(evt.data);
                if ((payload as any).error) {
                    setError(String((payload as any).error));
                    return;
                }
                setData(payload);
                setConnected(true);
                setError(null);
            } catch { /* ignore */ }
        };

        es.onerror = () => {
            setConnected(false);
            es.close();
            esRef.current = null;
            setTimeout(connectSSE, 5000);
        };
    }, [roomName]);

    useEffect(() => {
        connectSSE();
        return () => {
            esRef.current?.close();
            esRef.current = null;
        };
    }, [connectSSE]);

    const handleTransfer = async () => {
        if (!selectedExt || !data) return;
        setTransferring(true);
        setActionMsg(null);
        try {
            const res = await apiFetch('/api/calls/transfer', {
                method: 'POST',
                body: JSON.stringify({
                    room_name: roomName,
                    empresa_id: 0,
                    call_id: roomName,
                    extension: selectedExt,
                }),
            });
            if (res.status === 409) {
                const json = await res.json().catch(() => ({}));
                setActionMsg({ ok: false, text: `Extensión ocupada (${json.status || 'Busy'})` });
            } else if (res.ok) {
                setActionMsg({ ok: true, text: `Transferido a ext. ${selectedExt}` });
            } else {
                const json = await res.json().catch(() => ({}));
                setActionMsg({ ok: false, text: json.detail || `Error HTTP ${res.status}` });
            }
        } catch (err: any) {
            setActionMsg({ ok: false, text: err.message || 'Error de red' });
        } finally {
            setTransferring(false);
        }
    };

    const handleHangUp = async () => {
        setHangingUp(true);
        setActionMsg(null);
        try {
            const res = await apiFetch('/api/calls/hang_up', {
                method: 'POST',
                body: JSON.stringify({ room_name: roomName }),
            });
            if (res.ok) {
                setActionMsg({ ok: true, text: 'Llamada colgada' });
                setTimeout(onClose, 1500);
            } else {
                const json = await res.json().catch(() => ({}));
                setActionMsg({ ok: false, text: json.detail || `Error HTTP ${res.status}` });
            }
        } catch (err: any) {
            setActionMsg({ ok: false, text: err.message || 'Error de red' });
        } finally {
            setHangingUp(false);
        }
    };

    return (
        <div
            className="flex flex-col bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-2xl overflow-hidden"
            style={{ width: 380, height: 600 }}
        >
            {/* ── Header ───────────────────────────────────────────────── */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-700 bg-gradient-to-r from-blue-50/60 to-indigo-50/30 dark:from-blue-900/20 dark:to-indigo-900/10 shrink-0">
                <div className="flex items-center gap-2">
                    <Phone size={15} className="text-blue-600 dark:text-blue-400" />
                    <span className="text-xs font-bold text-gray-700 dark:text-white truncate max-w-[200px]" title={roomName}>
                        Panel de llamada
                    </span>
                    <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500 animate-pulse' : 'bg-gray-300'}`} />
                </div>
                <button
                    onClick={onClose}
                    className="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 transition-colors"
                >
                    <X size={15} />
                </button>
            </div>

            {/* ── Sección 1: Info del cliente ───────────────────────────── */}
            <div className="px-4 py-3 border-b border-gray-50 dark:border-gray-700 shrink-0 space-y-1.5">
                {data ? (
                    <>
                        <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                                <p className="text-sm font-bold text-gray-900 dark:text-white truncate">
                                    {data.contact.nombre || 'Contacto desconocido'}
                                </p>
                                <p className="text-[11px] text-gray-400 font-mono">
                                    {data.contact.telefono || roomName}
                                </p>
                                {Object.keys(data.contact.datos_extra || {}).length > 0 && (
                                    <div className="flex flex-wrap gap-1 mt-1">
                                        {Object.entries(data.contact.datos_extra).slice(0, 3).map(([k, v]) => (
                                            <span key={k} className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-[9px] text-gray-500 dark:text-gray-400">
                                                {k}: {String(v)}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>
                            <div className="shrink-0 text-right space-y-1">
                                <StatusBadge status={data.status} />
                                <div className="flex items-center justify-end gap-1 text-[10px] text-gray-400">
                                    <Clock size={10} />
                                    <span className="tabular-nums font-mono">{formatSeconds(data.duration_seconds)}</span>
                                </div>
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="flex items-center gap-2 text-gray-400 text-xs py-1">
                        <Loader2 size={13} className="animate-spin" /> Conectando…
                    </div>
                )}
            </div>

            {/* ── Sección 2: Transcript ─────────────────────────────────── */}
            <div className="flex-1 flex flex-col min-h-0">
                {/* Briefing banner */}
                {data?.transfer_briefing && data.status === 'transferred' && (
                    <div className="mx-3 mt-2 mb-1 p-2.5 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700 rounded-xl shrink-0">
                        <p className="text-[10px] font-bold text-blue-600 dark:text-blue-400 uppercase tracking-wider mb-1">
                            Briefing para agente humano
                        </p>
                        <p className="text-xs text-blue-800 dark:text-blue-200 leading-relaxed">
                            {data.transfer_briefing}
                        </p>
                    </div>
                )}

                <div
                    ref={transcriptBoxRef}
                    onScroll={handleTranscriptScroll}
                    className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5"
                >
                    {!data || data.transcript.length === 0 ? (
                        <div className="h-full flex flex-col items-center justify-center text-gray-300 dark:text-gray-600 space-y-2">
                            <Bot size={28} />
                            <p className="text-xs text-center">
                                {!connected ? 'Conectando al SSE…' : 'Sin transcripción aún'}
                            </p>
                        </div>
                    ) : (
                        data.transcript.map((entry, i) => {
                            const isAgent = entry.speaker === 'agent';
                            return (
                                <div
                                    key={i}
                                    className={`flex gap-1.5 items-start ${isAgent ? '' : 'flex-row-reverse'}`}
                                >
                                    <div className={`shrink-0 w-5 h-5 rounded-lg flex items-center justify-center mt-0.5 ${isAgent ? 'bg-blue-100 dark:bg-blue-900/40' : 'bg-emerald-100 dark:bg-emerald-900/40'}`}>
                                        {isAgent
                                            ? <Bot size={11} className="text-blue-600 dark:text-blue-400" />
                                            : <User size={11} className="text-emerald-600 dark:text-emerald-400" />
                                        }
                                    </div>
                                    <div className={`max-w-[80%] px-2.5 py-1.5 rounded-2xl text-[11px] leading-relaxed ${
                                        isAgent
                                            ? 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-tl-sm'
                                            : 'bg-blue-600 text-white rounded-tr-sm'
                                    }`}>
                                        {entry.text}
                                    </div>
                                </div>
                            );
                        })
                    )}
                    <div ref={transcriptEndRef} />
                </div>

                {!autoScroll && data && data.transcript.length > 0 && (
                    <button
                        onClick={() => {
                            setAutoScroll(true);
                            transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
                        }}
                        className="mx-3 mb-1 py-1 text-[10px] font-bold text-blue-600 bg-blue-50 dark:bg-blue-900/30 rounded-lg flex items-center justify-center gap-1 shrink-0"
                    >
                        <ChevronDown size={11} /> Nuevos mensajes
                    </button>
                )}
            </div>

            {/* ── Sección 3: Acciones ───────────────────────────────────── */}
            <div className="px-3 py-3 border-t border-gray-100 dark:border-gray-700 shrink-0 space-y-2 bg-gray-50/50 dark:bg-gray-800/50">
                {/* Extension selector */}
                <div className="flex gap-2">
                    <div className="relative flex-1">
                        <select
                            value={selectedExt}
                            onChange={(e) => setSelectedExt(e.target.value)}
                            className="w-full h-8 pl-2.5 pr-7 text-[11px] border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 appearance-none focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400"
                        >
                            {data?.extensions_available.length ? (
                                data.extensions_available.map((ext) => (
                                    <option key={ext.id} value={ext.extension_number}>
                                        ext {ext.extension_number}{ext.extension_name ? ` — ${ext.extension_name}` : ''}{ext.departamento ? ` (${ext.departamento})` : ''}
                                    </option>
                                ))
                            ) : (
                                <option value="">Sin extensiones configuradas</option>
                            )}
                        </select>
                        <ChevronDown size={11} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                    </div>

                    <button
                        onClick={handleTransfer}
                        disabled={transferring || !selectedExt || !data?.extensions_available.length || data?.status === 'ended'}
                        className="h-8 px-3 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-[11px] font-bold flex items-center gap-1 disabled:opacity-50 transition-colors"
                        title="Transferir a extensión seleccionada"
                    >
                        {transferring
                            ? <Loader2 size={12} className="animate-spin" />
                            : <UserCheck size={12} />
                        }
                        <ArrowRight size={11} />
                    </button>
                </div>

                {/* Hang up */}
                <button
                    onClick={handleHangUp}
                    disabled={hangingUp || data?.status === 'ended'}
                    className="w-full h-8 rounded-lg bg-red-500 hover:bg-red-600 text-white text-[11px] font-bold flex items-center justify-center gap-1.5 disabled:opacity-50 transition-colors"
                >
                    {hangingUp
                        ? <Loader2 size={12} className="animate-spin" />
                        : <PhoneOff size={12} />
                    }
                    Colgar llamada
                </button>

                {/* Action feedback */}
                {actionMsg && (
                    <div className={`flex items-center gap-1.5 text-[10px] font-medium px-2 py-1 rounded-lg ${
                        actionMsg.ok
                            ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
                            : 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400'
                    }`}>
                        {actionMsg.ok ? <CheckCircle size={11} /> : <AlertTriangle size={11} />}
                        {actionMsg.text}
                    </div>
                )}

                {error && (
                    <p className="text-[10px] text-red-400 text-center">{error}</p>
                )}
            </div>
        </div>
    );
};

export default LiveCallPanel;
