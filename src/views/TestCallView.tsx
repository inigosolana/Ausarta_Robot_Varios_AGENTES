import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
    Phone, Loader2, Bot, PhoneCall, PhoneIncoming, PhoneOutgoing,
    Copy, Check, AlertTriangle, ExternalLink,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { apiFetch } from '../lib/apiFetch';
import { getAgentCallDirection, type AgentCallDirection } from '../lib/agentVoiceOptions';
import { LiveCallPanel } from '../components/LiveCallPanel';
import { useInboundPhoneNumbers, useTestCallAgents } from '../api/testCall';

type CallMode = AgentCallDirection;

const MODE_STYLES = {
    outbound: {
        headerIcon: 'from-amber-400 to-amber-600 shadow-amber-500/30',
        tabActive: 'bg-amber-500/15 text-amber-800 dark:text-amber-200 border-amber-500/40',
        tabIdle: 'text-gray-500 hover:bg-amber-500/5',
        preview: 'bg-amber-50/60 dark:bg-amber-950/20 border-amber-100 dark:border-amber-900/40',
        previewIcon: 'bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400',
        focusRing: 'focus:ring-amber-500/20 focus:border-amber-400',
        button: 'from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 shadow-amber-500/25 focus:ring-amber-500/50',
    },
    inbound: {
        headerIcon: 'from-violet-400 to-violet-600 shadow-violet-500/30',
        tabActive: 'bg-violet-500/15 text-violet-800 dark:text-violet-200 border-violet-500/40',
        tabIdle: 'text-gray-500 hover:bg-violet-500/5',
        preview: 'bg-violet-50/60 dark:bg-violet-950/20 border-violet-100 dark:border-violet-900/40',
        previewIcon: 'bg-violet-100 dark:bg-violet-900/40 text-violet-600 dark:text-violet-400',
        focusRing: 'focus:ring-violet-500/20 focus:border-violet-400',
        button: 'from-violet-500 to-violet-600 hover:from-violet-400 hover:to-violet-500 shadow-violet-500/25 focus:ring-violet-500/50',
    },
} as const;

const TestCallView: React.FC = () => {
    const { profile } = useAuth();
    const agentsEmpresaId =
        profile && profile.role !== 'superadmin' && profile.empresa_id
            ? profile.empresa_id
            : undefined;

    const { data: agents = [], isLoading: loading } = useTestCallAgents(agentsEmpresaId, Boolean(profile));
    const [selectedAgentId, setSelectedAgentId] = useState<string>('');
    const [callMode, setCallMode] = useState<CallMode>('outbound');
    const [modeTouched, setModeTouched] = useState(false);
    const [phoneNumber, setPhoneNumber] = useState('+34');
    const [isCalling, setIsCalling] = useState(false);
    const [callResult, setCallResult] = useState<{ success: boolean; message: string } | null>(null);
    const [activeRoomName, setActiveRoomName] = useState<string | null>(null);
    const [copiedNumber, setCopiedNumber] = useState<string | null>(null);

    useEffect(() => {
        if (!agents.length) {
            setSelectedAgentId('');
            return;
        }
        setSelectedAgentId((prev) =>
            prev && agents.some((a) => String(a.id) === prev)
                ? prev
                : String(agents[0].id),
        );
    }, [agents]);

    const selectedAgent = agents.find((a) => String(a.id) === selectedAgentId);
    const empresaId = selectedAgent?.empresa_id ?? profile?.empresa_id ?? null;
    const detectedDirection = selectedAgent ? getAgentCallDirection(selectedAgent) : null;
    const styles = MODE_STYLES[callMode];

    const {
        data: inboundNumbers = [],
        isLoading: inboundLoading,
        isError: inboundIsError,
        error: inboundQueryError,
    } = useInboundPhoneNumbers(empresaId, callMode === 'inbound' && Boolean(empresaId));
    const inboundError = inboundIsError
        ? (inboundQueryError instanceof Error ? inboundQueryError.message : 'No se pudieron cargar los números entrantes')
        : '';

    useEffect(() => {
        if (!selectedAgent || modeTouched) return;
        const direction = getAgentCallDirection(selectedAgent);
        if (direction) setCallMode(direction);
    }, [selectedAgentId, selectedAgent, modeTouched]);

    const handleModeChange = (mode: CallMode) => {
        setModeTouched(true);
        setCallMode(mode);
        setCallResult(null);
    };

    const copyNumber = useCallback(async (num: string) => {
        try {
            await navigator.clipboard.writeText(num);
            setCopiedNumber(num);
            setTimeout(() => setCopiedNumber(null), 2000);
        } catch {
            /* ignore */
        }
    }, []);

    const handleCall = async () => {
        if (!selectedAgentId) {
            alert('Selecciona un agente');
            return;
        }
        if (!phoneNumber || phoneNumber.length < 5) {
            alert('Introduce un número de teléfono válido');
            return;
        }

        setIsCalling(true);
        setCallResult(null);

        try {
            const response = await apiFetch('/api/calls/outbound', {
                method: 'POST',
                body: JSON.stringify({
                    agentId: selectedAgentId,
                    phoneNumber: phoneNumber,
                    agentName: selectedAgent?.name || 'Agent',
                }),
            });

            const data = await response.json().catch(() => ({}));
            if (response.ok) {
                const roomName = data.roomName || data.room_name || null;
                setActiveRoomName(roomName);
                setCallResult({
                    success: true,
                    message: `Llamada iniciada. Sala: ${roomName || '—'}`,
                });
            } else {
                const detail = data.detail;
                const msg = Array.isArray(detail)
                    ? detail.map((d: unknown) => (typeof d === 'object' && d && 'msg' in d ? (d as { msg: string }).msg : String(d))).join(' ')
                    : (detail || data.error || 'Error desconocido');
                setCallResult({ success: false, message: msg });
            }
        } catch {
            setCallResult({ success: false, message: 'Error de conexión con el backend' });
        } finally {
            setIsCalling(false);
        }
    };

    return (
        <div className={`mx-auto mt-8 flex gap-6 items-start ${activeRoomName ? 'max-w-4xl' : 'max-w-lg'}`}>
            <div className="flex-1 min-w-0">
                <div className="text-center mb-8">
                    <div className={`inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br rounded-2xl shadow-lg mb-4 ${styles.headerIcon}`}>
                        {callMode === 'inbound' ? (
                            <PhoneIncoming size={28} className="text-white" />
                        ) : (
                            <PhoneOutgoing size={28} className="text-white" />
                        )}
                    </div>
                    <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Llamada de Prueba</h1>
                    <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
                        {callMode === 'inbound'
                            ? 'Llama al número entrante de la empresa para probar el agente'
                            : 'Lanza una llamada saliente al número que quieras'}
                    </p>
                </div>

                <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm overflow-hidden">
                    <div className="p-6 space-y-6">
                        {/* Mode toggle */}
                        <div className="grid grid-cols-2 gap-2 p-1 rounded-xl bg-gray-50 dark:bg-gray-800/60 border border-gray-100 dark:border-gray-800">
                            <button
                                type="button"
                                onClick={() => handleModeChange('outbound')}
                                className={`flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-semibold border transition-all ${
                                    callMode === 'outbound' ? MODE_STYLES.outbound.tabActive : `border-transparent ${MODE_STYLES.outbound.tabIdle}`
                                }`}
                            >
                                <PhoneOutgoing size={16} />
                                Saliente
                            </button>
                            <button
                                type="button"
                                onClick={() => handleModeChange('inbound')}
                                className={`flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-semibold border transition-all ${
                                    callMode === 'inbound' ? MODE_STYLES.inbound.tabActive : `border-transparent ${MODE_STYLES.inbound.tabIdle}`
                                }`}
                            >
                                <PhoneIncoming size={16} />
                                Entrante
                            </button>
                        </div>

                        {/* Agent selector */}
                        <div>
                            <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                                Seleccionar Agente
                            </label>
                            {loading ? (
                                <div className="flex items-center gap-2 text-gray-400 text-sm py-2">
                                    <Loader2 size={16} className="animate-spin" /> Cargando agentes...
                                </div>
                            ) : agents.length === 0 ? (
                                <div className="p-4 bg-yellow-50 dark:bg-yellow-950/30 border border-yellow-200 dark:border-yellow-900/40 rounded-xl text-yellow-700 dark:text-yellow-300 text-sm">
                                    No hay agentes creados. Ve a <strong>Crear Agentes</strong> para crear uno.
                                </div>
                            ) : (
                                <select
                                    value={selectedAgentId}
                                    onChange={(e) => {
                                        setSelectedAgentId(e.target.value);
                                        setModeTouched(false);
                                        setCallResult(null);
                                    }}
                                    className={`w-full px-4 py-3 border border-gray-200 dark:border-gray-700 rounded-xl bg-gray-50 dark:bg-gray-800 focus:ring-2 outline-none transition-all text-sm font-medium text-gray-900 dark:text-gray-100 ${styles.focusRing}`}
                                >
                                    {agents.map((agent) => (
                                        <option key={agent.id} value={String(agent.id)}>
                                            {agent.name} {agent.use_case ? `— ${agent.use_case}` : ''}
                                        </option>
                                    ))}
                                </select>
                            )}
                        </div>

                        {selectedAgent && (
                            <div className={`p-4 border rounded-xl ${styles.preview}`}>
                                <div className="flex items-center gap-3">
                                    <div className={`p-2 rounded-lg ${styles.previewIcon}`}>
                                        <Bot size={18} />
                                    </div>
                                    <div className="min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <h4 className="font-semibold text-gray-800 dark:text-gray-100 text-sm">{selectedAgent.name}</h4>
                                            {detectedDirection && (
                                                <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full border ${
                                                    detectedDirection === 'inbound'
                                                        ? 'border-violet-500/25 bg-violet-500/10 text-violet-700 dark:text-violet-300'
                                                        : 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300'
                                                }`}>
                                                    {detectedDirection === 'inbound' ? 'Inbound' : 'Outbound'}
                                                </span>
                                            )}
                                        </div>
                                        <p className="text-xs text-gray-500 dark:text-gray-400">
                                            {selectedAgent.description || selectedAgent.use_case || 'Sin descripción'}
                                        </p>
                                    </div>
                                </div>
                                {selectedAgent.greeting && (
                                    <p className="mt-2 text-xs text-gray-400 dark:text-gray-500 italic border-l-2 border-gray-200 dark:border-gray-700 pl-2">
                                        &ldquo;{selectedAgent.greeting}&rdquo;
                                    </p>
                                )}
                            </div>
                        )}

                        {callMode === 'outbound' ? (
                            <div>
                                <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                                    Número de Teléfono
                                </label>
                                <div className="relative">
                                    <Phone size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                                    <input
                                        type="tel"
                                        value={phoneNumber}
                                        onChange={(e) => setPhoneNumber(e.target.value)}
                                        placeholder="+34600123456"
                                        className={`w-full pl-10 pr-4 py-3 border border-gray-200 dark:border-gray-700 rounded-xl bg-gray-50 dark:bg-gray-800 focus:ring-2 outline-none transition-all text-sm font-mono text-gray-900 dark:text-gray-100 ${styles.focusRing}`}
                                        disabled={isCalling}
                                    />
                                </div>
                                <p className="mt-2 text-xs text-gray-400">
                                    El sistema llamará a este número con el agente seleccionado.
                                </p>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300">
                                    Número que debes llamar
                                </label>
                                <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 px-4 py-3.5 min-h-[56px]">
                                    {inboundLoading ? (
                                        <span className="inline-flex items-center gap-2 text-sm text-gray-500">
                                            <Loader2 size={16} className="animate-spin" />
                                            Cargando número entrante...
                                        </span>
                                    ) : inboundNumbers.length ? (
                                        <div className="space-y-2">
                                            {inboundNumbers.map((num) => (
                                                <div key={num} className="flex items-center justify-between gap-3">
                                                    <span className="font-mono text-lg font-semibold text-gray-900 dark:text-gray-100">{num}</span>
                                                    <button
                                                        type="button"
                                                        onClick={() => copyNumber(num)}
                                                        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-white dark:hover:bg-gray-700 transition-colors"
                                                    >
                                                        {copiedNumber === num ? (
                                                            <><Check size={14} className="text-emerald-500" /> Copiado</>
                                                        ) : (
                                                            <><Copy size={14} /> Copiar</>
                                                        )}
                                                    </button>
                                                </div>
                                            ))}
                                        </div>
                                    ) : (
                                        <span className="text-sm text-gray-500">
                                            No hay número entrante sincronizado para esta empresa.
                                        </span>
                                    )}
                                </div>

                                {(inboundError || !empresaId) && (
                                    <div className="flex items-start gap-2 p-3 bg-amber-50 dark:bg-amber-950/30 border border-amber-100 dark:border-amber-900/40 rounded-xl">
                                        <AlertTriangle size={16} className="text-amber-500 shrink-0 mt-0.5" />
                                        <p className="text-sm text-amber-700 dark:text-amber-300">
                                            {inboundError || 'El agente no tiene empresa asociada.'}
                                        </p>
                                    </div>
                                )}

                                <div className="rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900/50 p-4 text-sm text-gray-600 dark:text-gray-400 space-y-2">
                                    <p>
                                        Llama desde tu móvil o fijo al DDI mostrado. La PBX enruta la llamada a LiveKit y se abre la sala con el agente entrante de la empresa.
                                    </p>
                                    {!inboundNumbers.length && empresaId && (
                                        <Link
                                            to="/trunks"
                                            className="inline-flex items-center gap-1.5 text-violet-600 dark:text-violet-400 font-medium hover:underline"
                                        >
                                            Configurar troncales SIP
                                            <ExternalLink size={14} />
                                        </Link>
                                    )}
                                </div>
                            </div>
                        )}

                        {callResult && callMode === 'outbound' && (
                            <div className={`p-4 rounded-xl text-sm font-medium ${
                                callResult.success
                                    ? 'bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-900/40 text-green-700 dark:text-green-300'
                                    : 'bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/40 text-red-700 dark:text-red-300'
                            }`}>
                                {callResult.message}
                            </div>
                        )}
                    </div>

                    {callMode === 'outbound' && (
                        <div className="p-6 bg-gray-50 dark:bg-gray-800/40 border-t border-gray-100 dark:border-gray-800">
                            <button
                                onClick={handleCall}
                                disabled={isCalling || !selectedAgentId || agents.length === 0}
                                className={`w-full py-3.5 bg-gradient-to-r text-white font-semibold rounded-xl focus:outline-none focus:ring-2 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 shadow-lg text-sm ${styles.button}`}
                            >
                                {isCalling ? (
                                    <>
                                        <Loader2 size={18} className="animate-spin" />
                                        Iniciando llamada...
                                    </>
                                ) : (
                                    <>
                                        <PhoneCall size={18} />
                                        Llamar Ahora
                                    </>
                                )}
                            </button>
                        </div>
                    )}
                </div>
            </div>

            {activeRoomName && (
                <div className="shrink-0 sticky top-6 self-start">
                    <LiveCallPanel
                        roomName={activeRoomName}
                        onClose={() => setActiveRoomName(null)}
                    />
                </div>
            )}
        </div>
    );
};

export default TestCallView;
