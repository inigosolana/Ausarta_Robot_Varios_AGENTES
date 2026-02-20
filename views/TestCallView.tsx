import React, { useState, useEffect } from 'react';
import { Phone, Loader2, Bot, PhoneCall } from 'lucide-react';
import { supabase } from '../lib/supabase';
import type { AgentConfig } from '../types';

const API_URL = import.meta.env.VITE_API_URL || window.location.origin + '/api' || 'http://localhost:8001/api';

const TestCallView: React.FC = () => {
    const [agents, setAgents] = useState<AgentConfig[]>([]);
    const [selectedAgentId, setSelectedAgentId] = useState<string>('');
    const [phoneNumber, setPhoneNumber] = useState('+34');
    const [loading, setLoading] = useState(true);
    const [isCalling, setIsCalling] = useState(false);
    const [callResult, setCallResult] = useState<{ success: boolean; message: string } | null>(null);

    useEffect(() => {
        loadAgents();
    }, []);

    const loadAgents = async () => {
        try {
            const { data, error } = await supabase
                .from('agent_config')
                .select('id, name, use_case, description, instructions, greeting')
                .order('name');

            if (error) throw error;
            setAgents(data || []);
            if (data && data.length > 0) {
                setSelectedAgentId(String(data[0].id));
            }
        } catch (err) {
            console.error('Error loading agents:', err);
        } finally {
            setLoading(false);
        }
    };

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
            const selectedAgent = agents.find(a => String(a.id) === selectedAgentId);

            const response = await fetch(`${API_URL}/calls/outbound`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    agentId: selectedAgentId,
                    phoneNumber: phoneNumber,
                    agentName: selectedAgent?.name || 'Agent'
                })
            });

            const data = await response.json();
            if (response.ok) {
                setCallResult({
                    success: true,
                    message: `✅ Llamada iniciada! Sala: ${data.roomName}`
                });
            } else {
                setCallResult({
                    success: false,
                    message: `❌ Error: ${data.detail || 'Error desconocido'}`
                });
            }
        } catch (error) {
            setCallResult({
                success: false,
                message: '❌ Error de conexión con el backend'
            });
        } finally {
            setIsCalling(false);
        }
    };

    const selectedAgent = agents.find(a => String(a.id) === selectedAgentId);

    return (
        <div className="max-w-lg mx-auto mt-8">
            {/* Header */}
            <div className="text-center mb-8">
                <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-green-400 to-green-600 rounded-2xl shadow-lg shadow-green-500/30 mb-4">
                    <PhoneCall size={28} className="text-white" />
                </div>
                <h1 className="text-2xl font-bold text-gray-900">Llamada de Prueba</h1>
                <p className="text-gray-500 text-sm mt-1">Lanza una llamada rápida con un agente configurado</p>
            </div>

            {/* Card */}
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                <div className="p-6 space-y-6">
                    {/* Agent Selector */}
                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-2">
                            Seleccionar Agente
                        </label>
                        {loading ? (
                            <div className="flex items-center gap-2 text-gray-400 text-sm py-2">
                                <Loader2 size={16} className="animate-spin" /> Cargando agentes...
                            </div>
                        ) : agents.length === 0 ? (
                            <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-xl text-yellow-700 text-sm">
                                No hay agentes creados. Ve a <strong>"Crear Agentes"</strong> para crear uno.
                            </div>
                        ) : (
                            <select
                                value={selectedAgentId}
                                onChange={(e) => setSelectedAgentId(e.target.value)}
                                className="w-full px-4 py-3 border border-gray-200 rounded-xl bg-gray-50 focus:ring-2 focus:ring-green-500/20 focus:border-green-400 outline-none transition-all text-sm font-medium"
                            >
                                {agents.map(agent => (
                                    <option key={agent.id} value={String(agent.id)}>
                                        {agent.name} {agent.use_case ? `— ${agent.use_case}` : ''}
                                    </option>
                                ))}
                            </select>
                        )}
                    </div>

                    {/* Agent preview card */}
                    {selectedAgent && (
                        <div className="p-4 bg-blue-50/50 border border-blue-100 rounded-xl">
                            <div className="flex items-center gap-3">
                                <div className="p-2 bg-blue-100 rounded-lg text-blue-600">
                                    <Bot size={18} />
                                </div>
                                <div>
                                    <h4 className="font-semibold text-gray-800 text-sm">{selectedAgent.name}</h4>
                                    <p className="text-xs text-gray-500">{selectedAgent.description || selectedAgent.use_case || 'Sin descripción'}</p>
                                </div>
                            </div>
                            {selectedAgent.greeting && (
                                <p className="mt-2 text-xs text-gray-400 italic border-l-2 border-blue-200 pl-2">
                                    "{selectedAgent.greeting}"
                                </p>
                            )}
                        </div>
                    )}

                    {/* Phone Number */}
                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-2">
                            Número de Teléfono
                        </label>
                        <div className="relative">
                            <Phone size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                            <input
                                type="tel"
                                value={phoneNumber}
                                onChange={(e) => setPhoneNumber(e.target.value)}
                                placeholder="+34600123456"
                                className="w-full pl-10 pr-4 py-3 border border-gray-200 rounded-xl bg-gray-50 focus:ring-2 focus:ring-green-500/20 focus:border-green-400 outline-none transition-all text-sm font-mono"
                                disabled={isCalling}
                            />
                        </div>
                    </div>

                    {/* Call Result */}
                    {callResult && (
                        <div className={`p-4 rounded-xl text-sm font-medium ${callResult.success
                                ? 'bg-green-50 border border-green-200 text-green-700'
                                : 'bg-red-50 border border-red-200 text-red-700'
                            }`}>
                            {callResult.message}
                        </div>
                    )}
                </div>

                {/* Call Button */}
                <div className="p-6 bg-gray-50 border-t border-gray-100">
                    <button
                        onClick={handleCall}
                        disabled={isCalling || !selectedAgentId || agents.length === 0}
                        className="w-full py-3.5 bg-gradient-to-r from-green-500 to-green-600 text-white font-semibold rounded-xl hover:from-green-400 hover:to-green-500 focus:outline-none focus:ring-2 focus:ring-green-500/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 shadow-lg shadow-green-500/25 text-sm"
                    >
                        {isCalling ? (
                            <>
                                <Loader2 size={18} className="animate-spin" />
                                Iniciando llamada...
                            </>
                        ) : (
                            <>
                                <Phone size={18} />
                                Llamar Ahora
                            </>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default TestCallView;
