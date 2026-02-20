import React, { useState, useEffect } from "react";
import { Plus, Bot, Edit2, Trash2, Loader2, Search, Mic, Brain, Speaker, Building2, ChevronRight, ArrowLeft, Users, Mail } from "lucide-react";
import { supabase } from "../lib/supabase";
import type { AgentConfig, AIConfig, Empresa, UserProfile } from "../types";
import AgentFormView from "./AgentFormView";

const AgentListView: React.FC = () => {
    const [empresas, setEmpresas] = useState<Empresa[]>([]);
    const [agents, setAgents] = useState<(AgentConfig & { ai_config?: AIConfig })[]>([]);
    const [companyUsers, setCompanyUsers] = useState<UserProfile[]>([]);
    
    // View States
    const [loading, setLoading] = useState(true);
    const [selectedEmpresa, setSelectedEmpresa] = useState<Empresa | null>(null);
    const [activeTab, setActiveTab] = useState<"agents" | "users">("agents");
    
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

    const loadCompanyData = async (empresaId: number) => {
        setLoading(true);
        try {
            // Load Agents
            const { data: agentsData } = await supabase
                .from("agent_config")
                .select("*")
                .eq("empresa_id", empresaId)
                .order("created_at", { ascending: false });

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

            // Load Users
            const { data: usersData } = await supabase
                .from("user_profiles")
                .select("*")
                .eq("empresa_id", empresaId);
            setCompanyUsers(usersData || []);

        } catch (err) {
            console.error("Error loading company data:", err);
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

    if (isCreatingAgent || editingAgent) {
        return (
            <AgentFormView
                agent={editingAgent || { name: "", use_case: "", description: "", instructions: "", greeting: "", empresa_id: selectedEmpresa?.id }}
                onSave={async () => {
                    setEditingAgent(null);
                    setIsCreatingAgent(false);
                    if (selectedEmpresa) await loadCompanyData(selectedEmpresa.id!);
                }}
                onCancel={() => { 
                    setEditingAgent(null); 
                    setIsCreatingAgent(false); 
                }}
            />
        );
    }

    if (selectedEmpresa) {
        return (
            <div className="space-y-6">
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                    <div className="animate-in fade-in slide-in-from-left-4 duration-500">
                        <button onClick={() => setSelectedEmpresa(null)} className="flex items-center gap-1 text-sm text-gray-500 hover:text-blue-600 mb-2 transition-colors">
                            <ArrowLeft size={16} /> Volver a Empresas
                        </button>
                        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
                            <Building2 size={24} className="text-blue-500" />
                            {selectedEmpresa.nombre}
                        </h1>
                        <p className="text-gray-500 text-sm">Responsable: {selectedEmpresa.responsable}</p>
                    </div>
                    {activeTab === "agents" && (
                        <button
                            onClick={() => setIsCreatingAgent(true)}
                            className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl hover:from-blue-500 shadow-lg shadow-blue-500/20 font-medium text-sm transition-all hover:scale-105"
                        >
                            <Plus size={18} />
                            Crear Agente
                        </button>
                    )}
                </div>

                {/* Tabs */}
                <div className="flex gap-1 bg-gray-100 p-1 rounded-xl w-fit">
                    <button 
                        onClick={() => setActiveTab("agents")}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === "agents" ? "bg-white text-blue-600 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}
                    >
                        <Bot size={18} /> Agentes ({agents.length})
                    </button>
                    <button 
                        onClick={() => setActiveTab("users")}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === "users" ? "bg-white text-blue-600 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}
                    >
                        <Users size={18} /> Usuarios ({companyUsers.length})
                    </button>
                </div>

                <div className="relative">
                    <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                    <input
                        type="text"
                        placeholder={activeTab === "agents" ? "Buscar agentes..." : "Buscar usuarios..."}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:border-blue-400 transition-all"
                    />
                </div>

                {loading ? (
                    <div className="flex justify-center py-20"><Loader2 className="animate-spin text-blue-500" size={32} /></div>
                ) : activeTab === "agents" ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
                        {agents.filter(a => a.name.toLowerCase().includes(search.toLowerCase())).map((agent) => (
                            <div key={agent.id} onClick={() => setEditingAgent(agent)} className="group bg-white rounded-xl border border-gray-100 hover:border-blue-200 hover:shadow-lg cursor-pointer overflow-hidden p-5 transition-all">
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
                                    <button onClick={(e) => { e.stopPropagation(); handleDeleteAgent(agent.id!); }} className="p-1.5 opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-400 hover:text-red-500 rounded-lg transition-all">
                                        <Trash2 size={16} />
                                    </button>
                                </div>
                                <p className="text-sm text-gray-500 my-4 line-clamp-2">{agent.description}</p>
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
                        {companyUsers.filter(u => u.email.toLowerCase().includes(search.toLowerCase()) || u.full_name.toLowerCase().includes(search.toLowerCase())).map((user) => (
                            <div key={user.id} className="bg-white rounded-xl border border-gray-100 p-5 flex items-center gap-4 hover:border-indigo-100 hover:shadow-md transition-all">
                                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center text-white font-bold text-lg shadow-sm">
                                    {(user.full_name || user.email).charAt(0).toUpperCase()}
                                </div>
                                <div className="overflow-hidden">
                                    <h3 className="font-semibold text-gray-900 truncate">{user.full_name}</h3>
                                    <div className="flex items-center gap-1 text-xs text-gray-400 mt-0.5">
                                        <Mail size={12} />
                                        <span className="truncate">{user.email}</span>
                                    </div>
                                    <span className={`inline-block mt-2 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${user.role === "admin" ? "bg-blue-50 text-blue-600" : "bg-gray-50 text-gray-600"}`}>
                                        {user.role}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        );
    }

    // LISTADO DE EMPRESAS
    return (
        <div className="space-y-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Empresas y Clientes</h1>
                    <p className="text-gray-500 text-sm">Gestiona la estructura multitenant y sus usuarios/agentes</p>
                </div>
                <button
                    onClick={handleCreateEmpresa}
                    className="flex items-center gap-2 px-5 py-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 transition-all font-medium text-sm shadow-lg shadow-gray-200"
                >
                    <Building2 size={18} />
                    Crear Nueva Empresa
                </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-in fade-in duration-700">
                {loading ? (
                    <div className="col-span-full flex justify-center py-20"><Loader2 className="animate-spin text-blue-500" size={32} /></div>
                ) : empresas.length === 0 ? (
                    <div className="col-span-full text-center py-20 bg-white rounded-2xl border border-dashed border-gray-200">
                        <Building2 size={48} className="mx-auto text-gray-300 mb-4" />
                        <h3 className="text-lg font-semibold text-gray-700">Comienza creando una empresa</h3>
                        <p className="text-gray-400 text-sm">Podrás separar agentes y usuarios por cada cliente.</p>
                    </div>
                ) : (
                    empresas.map((empresa) => (
                        <div key={empresa.id} onClick={() => { setSelectedEmpresa(empresa); loadCompanyData(empresa.id!); setSearch(""); }} className="group relative bg-white rounded-2xl border border-gray-100 p-8 flex flex-col items-center text-center space-y-4 hover:border-blue-400 hover:shadow-2xl hover:shadow-blue-500/10 transition-all cursor-pointer">
                            <button onClick={(e) => { e.stopPropagation(); handleDeleteEmpresa(empresa.id!); }} className="absolute top-4 right-4 p-2 opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-300 hover:text-red-500 rounded-xl transition-all">
                                <Trash2 size={18} />
                            </button>
                            
                            <div className="w-20 h-20 bg-blue-50 rounded-3xl flex items-center justify-center group-hover:bg-blue-600 group-hover:rotate-6 transition-all duration-500 shadow-inner">
                                <Building2 size={32} className="text-blue-500 group-hover:text-white transition-colors" />
                            </div>

                            <div>
                                <h3 className="text-xl font-bold text-gray-900 group-hover:text-blue-600 transition-colors uppercase tracking-tight">{empresa.nombre}</h3>
                                <p className="text-sm text-gray-500 font-medium">Responsable: {empresa.responsable}</p>
                            </div>

                            <div className="pt-4 flex items-center gap-2 text-xs font-bold text-blue-500 opacity-0 group-hover:opacity-100 translate-y-2 group-hover:translate-y-0 transition-all">
                                GESTIONAR EMPRESA <ChevronRight size={14} />
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

export default AgentListView;

