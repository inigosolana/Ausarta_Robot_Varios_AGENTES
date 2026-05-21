import React, { useState, useEffect } from "react";
import { Plus, Bot, Edit2, Trash2, Loader2, Search, Building2, ArrowLeft, Phone, Languages, Sparkles } from "lucide-react";
import { TestCallModal } from "../components/TestCallModal";
import { supabase } from "../lib/supabase";
import { useAuth } from "../contexts/AuthContext";
import { useTranslation } from "react-i18next";
import type { AgentConfig, AIConfig, Empresa } from "../types";
import AgentFormView from "./AgentFormView";
import { AgentTemplateGallery } from "../components/AgentTemplateGallery";
import type { AgentTemplate } from "../components/AgentTemplateGallery";

const AgentManagementView: React.FC = () => {
    const { profile, isRole, isPlatformOwner } = useAuth();
    const { t } = useTranslation();

    const [empresas, setEmpresas] = useState<Empresa[]>([]);
    const [agents, setAgents] = useState<(AgentConfig & { ai_config?: AIConfig; empresas?: Empresa })[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState("");
    const [editingAgent, setEditingAgent] = useState<AgentConfig | null>(null);
    const [isCreatingAgent, setIsCreatingAgent] = useState(false);
    const [showTemplateGallery, setShowTemplateGallery] = useState(false);
    const [selectedEmpresaId, setSelectedEmpresaId] = useState<number | "all">("all");
    const [templatePreload, setTemplatePreload] = useState<Partial<AgentConfig> | null>(null);
    const [testCallAgent, setTestCallAgent] = useState<AgentConfig | null>(null);

    useEffect(() => {
        loadData();
    }, []);


    const loadData = async () => {
        setLoading(true);
        try {
            const API_URL = (import.meta as any).env.VITE_API_URL || '';

            // Load Empresas
            const empRes = await fetch(`${API_URL}/api/empresas`);
            const empData = await empRes.json();
            if (Array.isArray(empData)) {
                setEmpresas(empData);
            }

            // Load Agents
            const res = await fetch(`${API_URL}/api/agents${selectedEmpresaId !== 'all' ? `?empresa_id=${selectedEmpresaId}` : ''}`);
            const data = await res.json();

            if (Array.isArray(data)) {
                setAgents(data);
            } else {
                setAgents([]);
            }
        } catch (err) {
            console.error("Error loading data:", err);
        } finally {
            setLoading(false);
        }
    };

    const [agentToDelete, setAgentToDelete] = useState<number | null>(null);

    const executeDelete = async () => {
        if (!agentToDelete) return;
        try {
            setLoading(true);
            const API_URL = (import.meta as any).env.VITE_API_URL || '';
            const res = await fetch(`${API_URL}/api/agents/${agentToDelete}`, {
                method: 'DELETE'
            });
            const result = await res.json();

            if (!res.ok) {
                throw new Error(result.error || "Error deleting agent");
            }

            setAgents(prev => prev.filter(a => a.id !== agentToDelete));
            setAgentToDelete(null);
        } catch (err: any) {
            console.error("Error deleting agent:", err);
            alert(`${t("Error deleting agent", "Error al eliminar el agente")}: ${err.message || "Unknown error"}`);
        } finally {
            setLoading(false);
        }
    };

    // Determine which empresa_id to use for new agents
    const getNewAgentEmpresaId = (): number | undefined => {
        if (isRole('admin') && !isPlatformOwner && profile?.empresa_id) {
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

    const handleTemplateSelected = (config: AgentTemplate['config']) => {
        setTemplatePreload(config as Partial<AgentConfig>);
        setShowTemplateGallery(false);
        setIsCreatingAgent(true);
    };

    const handleNewAgentClick = () => {
        if (isSuperadmin && selectedEmpresaId === "all") {
            alert(t("Select a company before creating an agent", "Selecciona una empresa antes de crear un agente"));
            return;
        }
        setShowTemplateGallery(true);
    };

    // If creating or editing, show the form
    if (isCreatingAgent || editingAgent) {
        const empresaId = editingAgent?.empresa_id || getNewAgentEmpresaId();
        const baseAgent = editingAgent || {
            name: "",
            use_case: "",
            description: "",
            instructions: "",
            critical_rules: "",
            greeting: "",
            empresa_id: empresaId,
            ...(templatePreload || {}),
        };
        return (
            <AgentFormView
                agent={baseAgent as AgentConfig}
                onSave={async () => {
                    setEditingAgent(null);
                    setIsCreatingAgent(false);
                    setTemplatePreload(null);
                    await loadData();
                }}
                onCancel={() => {
                    setEditingAgent(null);
                    setIsCreatingAgent(false);
                    setTemplatePreload(null);
                }}
            />
        );
    }

    const isSuperadmin = isPlatformOwner;
    const canCreate = isSuperadmin || (isRole('admin') && profile?.empresa_id);

    return (
        <div className="space-y-6 relative">
            {/* Template Gallery Modal */}
            {testCallAgent && (
                <TestCallModal
                    agentId={testCallAgent.id!}
                    agentName={testCallAgent.name}
                    onClose={() => setTestCallAgent(null)}
                />
            )}

            {showTemplateGallery && (
                <AgentTemplateGallery
                    onSelectTemplate={handleTemplateSelected}
                    onClose={() => setShowTemplateGallery(false)}
                />
            )}

            {/* Custom Delete Modal */}
            {agentToDelete && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-300">
                    <div className="bg-white rounded-3xl shadow-2xl max-w-md w-full p-8 animate-in zoom-in-95 duration-300">
                        <div className="w-16 h-16 bg-red-50 text-red-500 rounded-2xl flex items-center justify-center mb-6 mx-auto">
                            <Trash2 size={32} />
                        </div>
                        <h2 className="text-2xl font-bold text-gray-900 text-center mb-2">
                            {t("Delete Agent?", "¿Eliminar Agente?")}
                        </h2>
                        <p className="text-gray-500 text-center mb-8 leading-relaxed">
                            {t(
                                "This will permanently delete the agent and ACCOMPANIED DATA: all associated campaigns, leads, call records, and configurations. This action cannot be undone.",
                                "Esto eliminará permanentemente al agente y TODOS sus datos: campañas, leads, registros de llamadas y configuraciones asociadas. Esta acción no se puede deshacer."
                            )}
                        </p>
                        <div className="flex gap-3">
                            <button
                                onClick={() => setAgentToDelete(null)}
                                className="flex-1 px-6 py-3 border border-gray-200 text-gray-600 rounded-xl font-semibold hover:bg-gray-50 transition-all"
                            >
                                {t("Cancel", "Cancelar")}
                            </button>
                            <button
                                onClick={executeDelete}
                                className="flex-1 px-6 py-3 bg-red-500 text-white rounded-xl font-semibold hover:bg-red-600 shadow-lg shadow-red-500/30 transition-all active:scale-95"
                            >
                                {t("Delete Everything", "Borrar Todo")}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Header */}
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">{t("Agent Management", "Gestión de Agentes")}</h1>
                    <p className="text-gray-500 text-sm">
                        {isSuperadmin
                            ? t("Create and manage agents from all companies", "Crea y gestiona agentes de todas las empresas")
                            : t("Create and manage agents from your company", "Crea y gestiona agentes de tu empresa")
                        }
                    </p>
                </div>
                <div className="flex items-center gap-3">

                    {canCreate && (
                        <button
                            onClick={handleNewAgentClick}
                            className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl hover:from-blue-500 shadow-lg shadow-blue-500/20 font-medium text-sm transition-all hover:scale-105"
                        >
                            <Plus size={18} />
                            {t("Create Agent", "Crear Agente")}
                        </button>
                    )}
                </div>
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
                        <option value="all">🏢 {t("All companies", "Todas las empresas")}</option>
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
                        placeholder={t("Search agents...", "Buscar agentes...")}
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
                        {search ? t("No agents found", "No se encontraron agentes") : t("No agents yet", "Sin agentes aún")}
                    </h3>
                    <p className="text-gray-400 text-sm">
                        {search ? t("Try another search", "Prueba con otra búsqueda") : t("Create your first agent to start", "Crea tu primer agente para empezar")}
                    </p>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 animate-in fade-in slide-in-from-bottom-4 duration-500">
                    {filteredAgents.map((agent) => {
                        const lang = agent.ai_config?.language || 'es';
                        const langColors: Record<string, string> = {
                            es: 'bg-blue-50 text-blue-700 border-blue-100',
                            en: 'bg-violet-50 text-violet-700 border-violet-100',
                            eu: 'bg-amber-50 text-amber-800 border-amber-100',
                        };
                        const langBadge = langColors[lang.slice(0, 2).toLowerCase()] || 'bg-slate-50 text-slate-700 border-slate-100';
                        const initials = agent.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
                        return (
                        <div
                            key={agent.id}
                            className="group relative bg-white rounded-xl border border-slate-100 hover:border-indigo-200 hover:shadow-lg shadow-sm overflow-hidden transition-all duration-300 flex flex-col"
                        >
                            <div className="h-1 w-full bg-gradient-to-r from-indigo-500 via-violet-500 to-indigo-400 opacity-0 group-hover:opacity-100 transition-opacity" />
                            <div className="p-6 flex flex-col flex-1">
                            <div className="flex items-start justify-between gap-3">
                                <div className="flex items-center gap-4 min-w-0">
                                    <div className="relative shrink-0">
                                        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white font-bold text-lg shadow-md shadow-indigo-500/25">
                                            {initials}
                                        </div>
                                        <span className="absolute -bottom-1 -right-1 w-6 h-6 rounded-lg bg-white border border-slate-100 flex items-center justify-center shadow-sm">
                                            <Bot size={12} className="text-indigo-600" />
                                        </span>
                                    </div>
                                    <div className="min-w-0">
                                        <h3 className="font-semibold text-slate-900 text-lg tracking-tight truncate">{agent.name}</h3>
                                        <span className={`inline-flex items-center gap-1 mt-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold border ${langBadge}`}>
                                            <Languages size={11} />
                                            {lang.toUpperCase()}
                                        </span>
                                    </div>
                                </div>
                                <button
                                    onClick={() => setAgentToDelete(agent.id!)}
                                    className="p-2 opacity-0 group-hover:opacity-100 hover:bg-red-50 text-slate-400 hover:text-red-500 rounded-lg transition-all shrink-0"
                                    title={t("Delete", "Eliminar")}
                                >
                                    <Trash2 size={16} />
                                </button>
                            </div>
                            <p className="text-sm text-slate-500 my-4 line-clamp-2 flex-1 leading-relaxed">{agent.description || agent.use_case || t("No description", "Sin descripción")}</p>

                            <button
                                type="button"
                                onClick={() => setTestCallAgent(agent)}
                                className="w-full flex items-center justify-center gap-2 py-3.5 bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-xl shadow-md shadow-slate-900/20 transition-all active:scale-[0.98] group/btn"
                            >
                                <Sparkles size={16} className="text-amber-300 group-hover/btn:animate-pulse" />
                                <Phone size={18} />
                                {t("Test agent now", "Probar Agente ahora")}
                            </button>

                            <button
                                type="button"
                                onClick={() => setEditingAgent(agent)}
                                className="w-full mt-2 py-2.5 text-sm font-medium text-slate-600 border border-slate-200 rounded-xl hover:bg-slate-50 transition-colors"
                            >
                                {t("Edit agent", "Editar agente")}
                            </button>

                            <div className="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-slate-50">
                                {agent.empresas && (
                                    <span className="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-50 text-indigo-700 rounded-full text-[11px] font-medium border border-indigo-100">
                                        <Building2 size={12} /> {agent.empresas.nombre}
                                    </span>
                                )}
                                {agent.tipo_resultados && (
                                    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border ${agent.tipo_resultados === 'ENCUESTA_NUMERICA' ? 'bg-green-50 text-green-700 border-green-200' :
                                        agent.tipo_resultados === 'ENCUESTA_MIXTA' ? 'bg-teal-50 text-teal-700 border-teal-200' :
                                        agent.tipo_resultados === 'CUALIFICACION_LEAD' ? 'bg-orange-50 text-orange-700 border-orange-200' :
                                            agent.tipo_resultados === 'AGENDAMIENTO_CITA' ? 'bg-purple-50 text-purple-700 border-purple-200' :
                                                agent.tipo_resultados === 'SOPORTE_CLIENTE' ? 'bg-blue-50 text-blue-700 border-blue-200' :
                                                    'bg-gray-50 text-gray-700 border-gray-200'
                                        }`}>
                                        {agent.tipo_resultados.replace('_', ' ')}
                                    </span>
                                )}
                            </div>
                            </div>
                        </div>
                    );})}
                </div>
            )}
        </div>
    );
};

export default AgentManagementView;
