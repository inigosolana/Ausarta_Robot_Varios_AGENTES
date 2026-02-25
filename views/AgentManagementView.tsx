import React, { useState, useEffect } from "react";
import { Plus, Bot, Edit2, Trash2, Loader2, Search, Building2, ArrowLeft } from "lucide-react";
import { supabase } from "../lib/supabase";
import { useAuth } from "../contexts/AuthContext";
import type { AgentConfig, AIConfig, Empresa } from "../types";
import AgentFormView from "./AgentFormView";

const AgentManagementView: React.FC = () => {
    const { profile, isRole } = useAuth();
    const [empresas, setEmpresas] = useState<Empresa[]>([]);
    const [agents, setAgents] = useState<(AgentConfig & { ai_config?: AIConfig; empresas?: Empresa })[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState("");
    const [editingAgent, setEditingAgent] = useState<AgentConfig | null>(null);
    const [isCreatingAgent, setIsCreatingAgent] = useState(false);
    const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | "all">("all");

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            // Load empresas
            let empQuery = supabase.from("empresas").select("*").order("nombre");
            if (!isRole('superadmin') && profile?.empresa_id) {
                empQuery = empQuery.eq('id', profile.empresa_id);
            }
            const { data: empData } = await empQuery;
            setEmpresas(empData || []);

            // Load agents - if admin of a company, filter by empresa_id
            let query = supabase.from("agent_config").select("*, empresas(*)").order("created_at", { ascending: false });

            if (isRole('admin') && !isRole('superadmin') && profile?.empresa_id) {
                // Admin can only see their company's agents
                query = query.eq("empresa_id", profile.empresa_id);
            }

            const { data: agentsData } = await query;
            setAgents(agentsData || []);
        } catch (err) {
            console.error("Error loading data:", err);
        } finally {
            setLoading(false);
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

    // Determine which empresa_id to use for new agents
    const getNewAgentEmpresaId = (): number | undefined => {
        if (isRole('admin') && !isRole('superadmin') && profile?.empresa_id) {
            return profile.empresa_id;
        }
        if (selectedEmpresaId !== "all") {
            return selectedEmpresaId as number;
        }
        return undefined;
    };

    // Filter agents by selected empresa and search
    const filteredAgents = agents
        .filter(a => selectedEmpresaId === "all" || a.empresa_id === selectedEmpresaId)
        .filter(a => a.name.toLowerCase().includes(search.toLowerCase()) || (a.use_case || "").toLowerCase().includes(search.toLowerCase()));

    // If creating or editing, show the form
    if (isCreatingAgent || editingAgent) {
        const empresaId = editingAgent?.empresa_id || getNewAgentEmpresaId();
        return (
            <AgentFormView
                agent={editingAgent || { name: "", use_case: "", description: "", instructions: "", critical_rules: "", greeting: "", empresa_id: empresaId }}
                onSave={async () => {
                    setEditingAgent(null);
                    setIsCreatingAgent(false);
                    await loadData();
                }}
                onCancel={() => {
                    setEditingAgent(null);
                    setIsCreatingAgent(false);
                }}
            />
        );
    }

    const isAusartaAdmin = profile?.empresas?.nombre === 'Ausarta' && isRole('admin');
    const isSuperadmin = isRole('superadmin') || isAusartaAdmin;
    const canCreate = isSuperadmin || (isRole('admin') && profile?.empresa_id);

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Gestión de Agentes</h1>
                    <p className="text-gray-500 text-sm">
                        {isSuperadmin
                            ? "Crea y gestiona agentes de todas las empresas"
                            : "Crea y gestiona agentes de tu empresa"
                        }
                    </p>
                </div>
                {canCreate && (
                    <button
                        onClick={() => {
                            if (isSuperadmin && selectedEmpresaId === "all") {
                                alert("Selecciona una empresa antes de crear un agente");
                                return;
                            }
                            setIsCreatingAgent(true);
                        }}
                        className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl hover:from-blue-500 shadow-lg shadow-blue-500/20 font-medium text-sm transition-all hover:scale-105"
                    >
                        <Plus size={18} />
                        Crear Agente
                    </button>
                )}
            </div>

            {/* Filters */}
            <div className="flex flex-col sm:flex-row gap-3">
                {/* Empresa filter (for superadmin and Ausarta admins) */}
                {isSuperadmin && (
                    <select
                        value={selectedEmpresaId}
                        onChange={(e) => setSelectedEmpresaId(e.target.value === "all" ? "all" : Number(e.target.value))}
                        className="px-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:border-blue-400 bg-white text-sm font-medium"
                    >
                        <option value="all">🏢 Todas las empresas</option>
                        {empresas.map(emp => (
                            <option key={emp.id} value={emp.id}>🏢 {emp.nombre}</option>
                        ))}
                    </select>
                )}

                {/* Search */}
                <div className="relative flex-1">
                    <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                    <input
                        type="text"
                        placeholder="Buscar agentes..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:border-blue-400 transition-all"
                    />
                </div>
            </div>

            {/* Agents Grid */}
            {loading ? (
                <div className="flex justify-center py-20"><Loader2 className="animate-spin text-blue-500" size={32} /></div>
            ) : filteredAgents.length === 0 ? (
                <div className="text-center py-20 bg-white rounded-2xl border border-dashed border-gray-200">
                    <Bot size={48} className="mx-auto text-gray-300 mb-4" />
                    <h3 className="text-lg font-semibold text-gray-700">
                        {search ? "No se encontraron agentes" : "Sin agentes aún"}
                    </h3>
                    <p className="text-gray-400 text-sm">
                        {search ? "Prueba con otra búsqueda" : "Crea tu primer agente para empezar"}
                    </p>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
                    {filteredAgents.map((agent) => (
                        <div
                            key={agent.id}
                            onClick={() => setEditingAgent(agent)}
                            className="group bg-white rounded-xl border border-gray-100 hover:border-blue-200 hover:shadow-lg cursor-pointer overflow-hidden p-5 transition-all"
                        >
                            <div className="flex items-start justify-between">
                                <div className="flex items-center gap-3">
                                    <div className="p-2.5 rounded-xl bg-blue-50 text-blue-600 group-hover:bg-blue-600 group-hover:text-white transition-all">
                                        <Bot size={20} />
                                    </div>
                                    <div>
                                        <h3 className="font-semibold text-gray-900 group-hover:text-blue-600">{agent.name}</h3>
                                        <p className="text-xs text-gray-400">{agent.use_case || "Sin caso de uso"}</p>
                                    </div>
                                </div>
                                <button
                                    onClick={(e) => { e.stopPropagation(); handleDeleteAgent(agent.id!); }}
                                    className="p-1.5 opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-400 hover:text-red-500 rounded-lg transition-all"
                                >
                                    <Trash2 size={16} />
                                </button>
                            </div>
                            <p className="text-sm text-gray-500 my-3 line-clamp-2">{agent.description || "Sin descripción"}</p>

                            {/* Company badge */}
                            {agent.empresas && (
                                <div className="flex items-center gap-1.5 mt-2">
                                    <span className="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-50 text-indigo-700 rounded-full text-xs font-medium border border-indigo-100">
                                        <Building2 size={12} /> {agent.empresas.nombre}
                                    </span>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default AgentManagementView;
