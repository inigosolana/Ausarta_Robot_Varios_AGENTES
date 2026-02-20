import React, { useState, useEffect } from "react";
import { Plus, Bot, Edit2, Trash2, Loader2, Search, Mic, Brain, Speaker, Building2, ChevronRight, ArrowLeft } from "lucide-react";
import { supabase } from "../lib/supabase";
import type { AgentConfig, AIConfig, Empresa } from "../types";
import AgentFormView from "./AgentFormView";

const AgentListView: React.FC = () => {
    const [empresas, setEmpresas] = useState<Empresa[]>([]);
    const [agents, setAgents] = useState<(AgentConfig & { ai_config?: AIConfig })[]>([]);
    
    // View States
    const [loading, setLoading] = useState(true);
    const [selectedEmpresa, setSelectedEmpresa] = useState<Empresa | null>(null);
    const [isCreatingEmpresa, setIsCreatingEmpresa] = useState(false);
    
    const [search, setSearch] = useState("");
    const [editingAgent, setEditingAgent] = useState<AgentConfig | null>(null);
    const [isCreatingAgent, setIsCreatingAgent] = useState(false);

    useEffect(() => {
        loadEmpresas();
    }, []);

    const loadEmpresas = async () => {
        setLoading(true);
        try {
            const { data, error } = await supabase
                .from("empresas")
                .select("*")
                .order("created_at", { ascending: true });
            if (error) throw error;
            setEmpresas(data || []);
        } catch (err) {
            console.error("Error loading empresas:", err);
        } finally {
            setLoading(false);
        }
    };

    const loadAgentsForEmpresa = async (empresaId: number) => {
        setLoading(true);
        try {
            const { data: agentsData, error } = await supabase
                .from("agent_config")
                .select("*")
                .eq("empresa_id", empresaId)
                .order("created_at", { ascending: false });

            if (error) throw error;

            const agentsWithAI = await Promise.all(
                (agentsData || []).map(async (agent: AgentConfig) => {
                    const { data: aiData } = await supabase
                        .from("ai_config")
                        .select("*")
                        .eq("agent_id", agent.id)
                        .maybeSingle();
                    return { ...agent, ai_config: aiData as AIConfig | undefined };
                })
            );

            setAgents(agentsWithAI);
        } catch (err) {
            console.error("Error loading agents:", err);
        } finally {
            setLoading(false);
        }
    };

    const handleCreateEmpresa = async () => {
        const nombre = prompt("Nombre de la nueva Empresa / Proyecto:");
        if (!nombre) return;
        const responsable = prompt("Nombre del Responsable:");
        if (!responsable) return;

        try {
            const { error } = await supabase.from("empresas").insert({ nombre, responsable });
            if (error) throw error;
            alert("Empresa creada con éxito");
            loadEmpresas();
        } catch (err) {
            alert("Error al crear la empresa");
        }
    };

    const handleDeleteEmpresa = async (id: number) => {
        if (!confirm("¿Seguro que quieres eliminar esta empresa y TODOS sus agentes?")) return;
        try {
            await supabase.from("empresas").delete().eq("id", id);
            loadEmpresas();
        } catch (err) {
            alert("Error al eliminar");
        }
    };

    const handleDeleteAgent = async (id: number) => {
        if (!confirm("¿Estás seguro de que quieres eliminar este agente?")) return;
        try {
            await supabase.from("ai_config").delete().eq("agent_id", id);
            await supabase.from("agent_config").delete().eq("id", id);
            setAgents(prev => prev.filter(a => a.id !== id));
        } catch (err) {
            alert("Error al eliminar el agente");
        }
    };

    // If editing or creating an agent
    if (isCreatingAgent || editingAgent) {
        return (
            <AgentFormView
                agent={editingAgent || { name: "", use_case: "", description: "", instructions: "", greeting: "", empresa_id: selectedEmpresa?.id }}
                onSave={async () => {
                    setEditingAgent(null);
                    setIsCreatingAgent(false);
                    if (selectedEmpresa) await loadAgentsForEmpresa(selectedEmpresa.id!);
                }}
                onCancel={() => { 
                    setEditingAgent(null); 
                    setIsCreatingAgent(false); 
                }}
            />
        );
    }

    // 1. Mostrar Lista de Agentes si hay una Empresa seleccionada
    if (selectedEmpresa) {
        const filteredAgents = agents.filter(a =>
            a.name.toLowerCase().includes(search.toLowerCase()) ||
            (a.use_case || "").toLowerCase().includes(search.toLowerCase())
        );

        return (
            <div className="space-y-6">
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                    <div>
                        <button onClick={() => setSelectedEmpresa(null)} className="flex items-center gap-1 text-sm text-gray-500 hover:text-blue-600 mb-2 transition-colors">
                            <ArrowLeft size={16} /> Volver a Empresas
                        </button>
                        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
                            <Building2 size={24} className="text-blue-500" />
                            {selectedEmpresa.nombre}
                        </h1>
                        <p className="text-gray-500 text-sm">Responsable: {selectedEmpresa.responsable} · Lista de Agentes</p>
                    </div>
                    <button
                        onClick={() => setIsCreatingAgent(true)}
                        className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl hover:from-blue-500 shadow-lg shadow-blue-500/20 font-medium text-sm"
                    >
                        <Plus size={18} />
                        Crear Agente
                    </button>
                </div>

                <div className="relative">
                    <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                    <input
                        type="text"
                        placeholder="Buscar agentes..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:border-blue-400"
                    />
                </div>

                {loading ? (
                    <div className="flex justify-center py-20"><Loader2 className="animate-spin text-gray-400" size={32} /></div>
                ) : filteredAgents.length === 0 ? (
                    <div className="text-center py-20 bg-white rounded-2xl border border-gray-100">
                        <Bot size={48} className="mx-auto text-gray-300 mb-4" />
                        <h3 className="text-lg font-semibold text-gray-700">No hay agentes en esta empresa</h3>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {filteredAgents.map((agent) => (
                            <div key={agent.id} onClick={() => setEditingAgent(agent)} className="group bg-white rounded-xl border border-gray-100 hover:border-blue-200 hover:shadow-lg cursor-pointer overflow-hidden p-5">
                                <div className="flex items-start justify-between">
                                    <div className="flex items-center gap-3">
                                        <div className="p-2.5 rounded-xl bg-blue-50 text-blue-600">
                                            <Bot size={20} />
                                        </div>
                                        <div>
                                            <h3 className="font-semibold text-gray-900 group-hover:text-blue-600">{agent.name}</h3>
                                            <p className="text-xs text-gray-400">{agent.use_case || "Sin caso de uso"}</p>
                                        </div>
                                    </div>
                                    <button onClick={(e) => { e.stopPropagation(); handleDeleteAgent(agent.id!); }} className="p-1.5 opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-400 hover:text-red-500 rounded-lg">
                                        <Trash2 size={16} />
                                    </button>
                                </div>
                                <p className="text-sm text-gray-500 my-4 line-clamp-2">{agent.description}</p>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        );
    }

    // 2. Mostrar Lista de Empresas por Defecto
    const filteredEmpresas = empresas.filter(e => e.nombre.toLowerCase().includes(search.toLowerCase()));

    return (
        <div className="space-y-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Listado de Empresas</h1>
                    <p className="text-gray-500 text-sm">Gestiona clientes, departamentos o empresas y sus agentes</p>
                </div>
                <button
                    onClick={handleCreateEmpresa}
                    className="flex items-center gap-2 px-5 py-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 transition-all font-medium text-sm"
                >
                    <Building2 size={18} />
                    Crear Nueva Empresa
                </button>
            </div>

            <div className="relative">
                <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                    type="text"
                    placeholder="Buscar empresas..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:border-blue-400"
                />
            </div>

            {loading ? (
                <div className="flex justify-center py-20"><Loader2 className="animate-spin text-gray-400" size={32} /></div>
            ) : filteredEmpresas.length === 0 ? (
                <div className="text-center py-20 bg-white rounded-2xl border border-gray-100">
                    <Building2 size={48} className="mx-auto text-gray-300 mb-4" />
                    <h3 className="text-lg font-semibold text-gray-700">No hay empresas creadas.</h3>
                    <p className="text-gray-400 text-sm mb-6">Crea la primera empresa para empezar a gestionar agentes separadamente.</p>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filteredEmpresas.map((empresa) => (
                        <div key={empresa.id} onClick={() => { setSelectedEmpresa(empresa); loadAgentsForEmpresa(empresa.id!); setSearch(""); }} className="group bg-white rounded-xl border border-gray-100 hover:border-blue-200 hover:shadow-lg cursor-pointer p-6 transition-all flex flex-col items-center justify-center text-center space-y-3 relative">
                            <button onClick={(e) => { e.stopPropagation(); handleDeleteEmpresa(empresa.id!); }} className="absolute top-3 right-3 p-1.5 opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-300 hover:text-red-500 rounded-lg transition-all">
                                <Trash2 size={16} />
                            </button>
                            <div className="w-16 h-16 bg-gray-50 rounded-full border-2 border-dashed border-gray-200 flex items-center justify-center group-hover:border-blue-300 group-hover:bg-blue-50 transition-all">
                                <Building2 size={24} className="text-gray-400 group-hover:text-blue-500" />
                            </div>
                            <div>
                                <h3 className="font-semibold text-gray-900 group-hover:text-blue-600 text-lg">{empresa.nombre}</h3>
                                <p className="text-sm text-gray-500">Resp: {empresa.responsable}</p>
                            </div>
                            <span className="text-xs font-medium text-blue-500 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all translate-y-2 group-hover:translate-y-0">
                                Ver sus Agentes <ChevronRight size={14} />
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default AgentListView;

