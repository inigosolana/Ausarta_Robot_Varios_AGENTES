import React, { useState, useEffect } from 'react';
import { Plus, Bot, Edit2, Trash2, Loader2, Search, Mic, Brain, Speaker } from 'lucide-react';
import { supabase } from '../lib/supabase';
import type { AgentConfig, AIConfig } from '../types';
import AgentFormView from './AgentFormView';

const AgentListView: React.FC = () => {
    const [agents, setAgents] = useState<(AgentConfig & { ai_config?: AIConfig })[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [editingAgent, setEditingAgent] = useState<AgentConfig | null>(null);
    const [isCreating, setIsCreating] = useState(false);

    useEffect(() => {
        loadAgents();
    }, []);

    const loadAgents = async () => {
        setLoading(true);
        try {
            const { data: agentsData, error } = await supabase
                .from('agent_config')
                .select('*')
                .order('created_at', { ascending: false });

            if (error) throw error;

            // Load AI configs for each agent
            const agentsWithAI = await Promise.all(
                (agentsData || []).map(async (agent: AgentConfig) => {
                    const { data: aiData } = await supabase
                        .from('ai_config')
                        .select('*')
                        .eq('agent_id', agent.id)
                        .maybeSingle();
                    return { ...agent, ai_config: aiData as AIConfig | undefined };
                })
            );

            setAgents(agentsWithAI);
        } catch (err) {
            console.error('Error loading agents:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async (id: number) => {
        if (!confirm('¿Estás seguro de que quieres eliminar este agente? Esta acción no se puede deshacer.')) return;
        try {
            await supabase.from('ai_config').delete().eq('agent_id', id);
            await supabase.from('agent_config').delete().eq('id', id);
            setAgents(prev => prev.filter(a => a.id !== id));
        } catch (err) {
            alert('Error al eliminar el agente');
        }
    };

    const handleSaveAgent = async () => {
        setEditingAgent(null);
        setIsCreating(false);
        await loadAgents();
    };

    // Show agent form if creating or editing
    if (isCreating || editingAgent) {
        return (
            <AgentFormView
                agent={editingAgent || undefined}
                onSave={handleSaveAgent}
                onCancel={() => { setEditingAgent(null); setIsCreating(false); }}
            />
        );
    }

    const filtered = agents.filter(a =>
        a.name.toLowerCase().includes(search.toLowerCase()) ||
        (a.use_case || '').toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Crear Agentes</h1>
                    <p className="text-gray-500 text-sm">Gestiona tus agentes de voz con IA</p>
                </div>
                <button
                    onClick={() => setIsCreating(true)}
                    className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl hover:from-blue-500 hover:to-blue-400 transition-all shadow-lg shadow-blue-500/20 font-medium text-sm"
                >
                    <Plus size={18} />
                    Crear Nuevo Agente
                </button>
            </div>

            {/* Search */}
            <div className="relative">
                <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                    type="text"
                    placeholder="Buscar agentes..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 outline-none transition-all text-sm"
                />
            </div>

            {/* Loading */}
            {loading ? (
                <div className="flex items-center justify-center py-20">
                    <Loader2 className="animate-spin text-gray-400" size={32} />
                </div>
            ) : filtered.length === 0 ? (
                /* Empty State */
                <div className="text-center py-20 bg-white rounded-2xl border border-gray-100">
                    <Bot size={48} className="mx-auto text-gray-300 mb-4" />
                    <h3 className="text-lg font-semibold text-gray-700 mb-2">
                        {search ? 'No se encontraron agentes' : 'No hay agentes aún'}
                    </h3>
                    <p className="text-gray-400 text-sm mb-6">
                        {search ? 'Prueba con otro término de búsqueda' : 'Crea tu primer agente para empezar'}
                    </p>
                    {!search && (
                        <button
                            onClick={() => setIsCreating(true)}
                            className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white rounded-xl hover:bg-blue-500 transition-colors font-medium text-sm"
                        >
                            <Plus size={18} />
                            Crear Primer Agente
                        </button>
                    )}
                </div>
            ) : (
                /* Agents Grid */
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filtered.map((agent) => (
                        <div
                            key={agent.id}
                            onClick={() => setEditingAgent(agent)}
                            className="group bg-white rounded-xl border border-gray-100 hover:border-blue-200 hover:shadow-lg hover:shadow-blue-500/5 transition-all cursor-pointer overflow-hidden"
                        >
                            {/* Card Header */}
                            <div className="p-5 pb-3">
                                <div className="flex items-start justify-between">
                                    <div className="flex items-center gap-3">
                                        <div className="p-2.5 rounded-xl bg-gradient-to-br from-blue-50 to-blue-100 text-blue-600 group-hover:from-blue-100 group-hover:to-blue-200 transition-colors">
                                            <Bot size={20} />
                                        </div>
                                        <div>
                                            <h3 className="font-semibold text-gray-900 group-hover:text-blue-600 transition-colors">{agent.name}</h3>
                                            <p className="text-xs text-gray-400">{agent.use_case || 'Sin caso de uso'}</p>
                                        </div>
                                    </div>
                                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                        <button
                                            onClick={(e) => { e.stopPropagation(); setEditingAgent(agent); }}
                                            className="p-1.5 rounded-lg hover:bg-blue-50 text-gray-400 hover:text-blue-600 transition-colors"
                                        >
                                            <Edit2 size={14} />
                                        </button>
                                        <button
                                            onClick={(e) => { e.stopPropagation(); handleDelete(agent.id!); }}
                                            className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-600 transition-colors"
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    </div>
                                </div>
                            </div>

                            {/* Description */}
                            <div className="px-5 pb-3">
                                <p className="text-sm text-gray-500 line-clamp-2">{agent.description || 'Sin descripción'}</p>
                            </div>

                            {/* AI Config Tags */}
                            <div className="px-5 pb-4 flex flex-wrap gap-1.5">
                                {agent.ai_config && (
                                    <>
                                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 bg-purple-50 text-purple-600 rounded-full font-medium">
                                            <Brain size={10} />
                                            {agent.ai_config.llm_provider}
                                        </span>
                                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 bg-green-50 text-green-600 rounded-full font-medium">
                                            <Speaker size={10} />
                                            {agent.ai_config.tts_provider}
                                        </span>
                                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 bg-orange-50 text-orange-600 rounded-full font-medium">
                                            <Mic size={10} />
                                            {agent.ai_config.stt_provider}
                                        </span>
                                    </>
                                )}
                            </div>

                            {/* Card Footer */}
                            <div className="px-5 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
                                <span className="text-[10px] text-gray-400">
                                    {agent.updated_at ? `Editado: ${new Date(agent.updated_at).toLocaleDateString('es-ES')}` : 'Recién creado'}
                                </span>
                                <span className="text-[10px] text-blue-500 font-medium group-hover:underline">Editar →</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default AgentListView;
