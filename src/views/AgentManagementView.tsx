import React, { useState, useEffect, useMemo } from "react";
import { Plus, Bot, Loader2, Building2 } from "lucide-react";
import { TestCallModal } from "../components/TestCallModal";
import { useAuth } from "../contexts/AuthContext";
import { useTranslation } from "react-i18next";
import type { AgentConfig, AIConfig, Empresa } from "../types";
import AgentFormView from "./AgentFormView";
import { AgentTemplateGallery } from "../components/AgentTemplateGallery";
import type { AgentTemplate } from "../components/AgentTemplateGallery";
import { AgentRosterCard } from "../components/agents/AgentRosterCard";
import { AgentWorkspacePanel } from "../components/agents/AgentWorkspacePanel";
import "./agents.css";

const AgentManagementView: React.FC = () => {
    const { profile, isRole, isPlatformOwner } = useAuth();
    const { t } = useTranslation();
    const isSuperadmin = isPlatformOwner;

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
    const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
    const [agentToDelete, setAgentToDelete] = useState<number | null>(null);

    useEffect(() => {
        loadData();
    }, [selectedEmpresaId]);

    useEffect(() => {
        if (!isSuperadmin && profile?.empresa_id) {
            setSelectedEmpresaId(profile.empresa_id);
        }
    }, [isSuperadmin, profile?.empresa_id]);

    useEffect(() => {
        if (isSuperadmin && empresas.length > 0 && selectedEmpresaId === "all") {
            setSelectedEmpresaId(empresas[0].id);
        }
    }, [empresas, isSuperadmin]);

    const loadData = async () => {
        setLoading(true);
        try {
            const API_URL = (import.meta as any).env.VITE_API_URL || '';

            const empRes = await fetch(`${API_URL}/api/empresas`);
            const empData = await empRes.json();
            if (Array.isArray(empData)) {
                setEmpresas(empData);
            }

            const empresaFilter = selectedEmpresaId !== "all" ? `?empresa_id=${selectedEmpresaId}` : "";
            const res = await fetch(`${API_URL}/api/agents${empresaFilter}`);
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
            if (selectedAgentId === agentToDelete) {
                setSelectedAgentId(null);
            }
            setAgentToDelete(null);
        } catch (err: any) {
            console.error("Error deleting agent:", err);
            alert(`${t("Error deleting agent", "Error al eliminar el agente")}: ${err.message || "Unknown error"}`);
        } finally {
            setLoading(false);
        }
    };

    const getNewAgentEmpresaId = (): number | undefined => {
        if (isRole('admin') && !isPlatformOwner && profile?.empresa_id) {
            return profile.empresa_id;
        }
        if (selectedEmpresaId !== "all") {
            return selectedEmpresaId as number;
        }
        return undefined;
    };

    const filteredAgents = useMemo(() => {
        return agents
            .filter(a => selectedEmpresaId === "all" || a.empresa_id === selectedEmpresaId)
            .filter(a =>
                a.name.toLowerCase().includes(search.toLowerCase()) ||
                (a.use_case || "").toLowerCase().includes(search.toLowerCase())
            );
    }, [agents, selectedEmpresaId, search]);

    const selectedAgent = useMemo(
        () => filteredAgents.find(a => a.id === selectedAgentId) ?? null,
        [filteredAgents, selectedAgentId]
    );

    useEffect(() => {
        if (filteredAgents.length === 0) {
            setSelectedAgentId(null);
            return;
        }
        if (!selectedAgentId || !filteredAgents.some(a => a.id === selectedAgentId)) {
            setSelectedAgentId(filteredAgents[0].id ?? null);
        }
    }, [filteredAgents, selectedAgentId]);

    const selectedEmpresaName = useMemo(() => {
        if (selectedEmpresaId === "all") return null;
        return empresas.find(e => e.id === selectedEmpresaId)?.nombre
            ?? profile?.empresas?.nombre
            ?? null;
    }, [selectedEmpresaId, empresas, profile?.empresas?.nombre]);

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
                empresaName={selectedEmpresaName ?? undefined}
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

    const canCreate = isSuperadmin || (isRole('admin') && profile?.empresa_id);

    return (
        <div className="agent-page relative min-h-full">
            <div className="pointer-events-none absolute right-0 top-0 h-[280px] w-[280px] rounded-full bg-indigo-500/10 blur-[100px]" />
            <div className="pointer-events-none absolute bottom-0 left-0 h-[320px] w-[320px] rounded-full bg-cyan-500/5 blur-[90px]" />

            {testCallAgent && (
                <TestCallModal
                    agentId={testCallAgent.id!}
                    agentName={testCallAgent.name}
                    agentType={testCallAgent.agent_type || testCallAgent.tipo_resultados}
                    empresaId={testCallAgent.empresa_id}
                    empresaName={(testCallAgent as any).empresas?.nombre}
                    onClose={() => setTestCallAgent(null)}
                />
            )}

            {showTemplateGallery && (
                <AgentTemplateGallery
                    onSelectTemplate={handleTemplateSelected}
                    onClose={() => setShowTemplateGallery(false)}
                />
            )}

            {agentToDelete && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
                    <div className="agent-glass w-full max-w-md rounded-2xl p-8 shadow-2xl">
                        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-red-500/10 text-red-500">
                            <span className="material-symbols-outlined text-3xl">delete_forever</span>
                        </div>
                        <h2 className="mb-2 text-center text-2xl font-bold text-gray-900 dark:text-white">
                            {t("Delete Agent?", "¿Eliminar Agente?")}
                        </h2>
                        <p className="mb-8 text-center text-sm leading-relaxed text-gray-500 dark:text-gray-400">
                            {t(
                                "This will permanently delete the agent and ACCOMPANIED DATA: all associated campaigns, leads, call records, and configurations. This action cannot be undone.",
                                "Esto eliminará permanentemente al agente y TODOS sus datos: campañas, leads, registros de llamadas y configuraciones asociadas. Esta acción no se puede deshacer."
                            )}
                        </p>
                        <div className="flex gap-3">
                            <button
                                onClick={() => setAgentToDelete(null)}
                                className="flex-1 rounded-xl border border-gray-200 px-6 py-3 font-semibold text-gray-600 transition-all hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                            >
                                {t("Cancel", "Cancelar")}
                            </button>
                            <button
                                onClick={executeDelete}
                                className="flex-1 rounded-xl bg-red-500 px-6 py-3 font-semibold text-white shadow-lg shadow-red-500/30 transition-all hover:bg-red-600 active:scale-95"
                            >
                                {t("Delete Everything", "Borrar Todo")}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <div className="relative z-10 mx-auto max-w-7xl space-y-6">
                {/* Empresa selector — prominent */}
                <div className="agent-empresa-bar flex flex-col gap-3 rounded-xl px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-500/15 text-indigo-600 dark:text-indigo-300">
                            <Building2 size={20} />
                        </div>
                        <div>
                            <p className="agent-mono text-[10px] font-medium uppercase tracking-widest text-gray-500 dark:text-gray-400">
                                {t("Active tenant", "Empresa activa")}
                            </p>
                            {isSuperadmin ? (
                                <p className="text-sm text-gray-600 dark:text-gray-300">
                                    {t("Select the company to manage its voice agents", "Selecciona la empresa para gestionar sus agentes de voz")}
                                </p>
                            ) : (
                                <p className="text-sm font-semibold text-gray-900 dark:text-white">
                                    {selectedEmpresaName || profile?.empresas?.nombre || t("Your company", "Tu empresa")}
                                </p>
                            )}
                        </div>
                    </div>
                    {isSuperadmin && (
                        <select
                            value={selectedEmpresaId === "all" ? "" : selectedEmpresaId}
                            onChange={e => setSelectedEmpresaId(Number(e.target.value))}
                            className="min-w-[220px] rounded-lg border border-indigo-500/30 bg-white px-4 py-2.5 text-sm font-semibold text-gray-800 shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500 dark:border-indigo-400/30 dark:bg-gray-900/80 dark:text-gray-100"
                        >
                            {empresas.map(emp => (
                                <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                            ))}
                        </select>
                    )}
                </div>

                {/* Page header */}
                <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                    <div>
                        <div className="mb-2 flex items-center gap-2 text-cyan-600 dark:text-cyan-400">
                            <span className="material-symbols-outlined text-sm">memory</span>
                            <span className="agent-mono text-xs font-bold uppercase tracking-widest">Entity Matrix</span>
                        </div>
                        <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-white">
                            {t("Voice Agents", "Agentes de voz")}
                        </h1>
                        <p className="mt-1 max-w-xl text-sm text-gray-500 dark:text-gray-400">
                            {t(
                                "Manage, configure, and monitor your active digital operative identities.",
                                "Gestiona, configura y monitoriza las identidades operativas digitales activas."
                            )}
                        </p>
                    </div>
                    <div className="flex gap-3">
                        {canCreate && (
                            <button
                                onClick={handleNewAgentClick}
                                className="flex items-center gap-2 rounded-lg bg-cyan-600 px-5 py-2 text-sm font-bold text-white shadow-[0_0_20px_rgba(6,182,212,0.35)] transition-all hover:brightness-110 active:scale-95 dark:bg-cyan-500"
                            >
                                <Plus size={18} />
                                {t("New Agent", "Nuevo agente")}
                            </button>
                        )}
                    </div>
                </div>

                {loading ? (
                    <div className="flex justify-center py-20">
                        <Loader2 className="h-10 w-10 animate-spin text-cyan-500" />
                    </div>
                ) : (
                    <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
                        {/* Left: roster */}
                        <div className="flex flex-col gap-4 lg:col-span-4">
                            <div className="relative w-full">
                                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-sm text-gray-400">search</span>
                                <input
                                    type="text"
                                    placeholder={t("Locate entity...", "Buscar agente...")}
                                    value={search}
                                    onChange={e => setSearch(e.target.value)}
                                    className="agent-mono w-full rounded-lg border border-gray-200 bg-white py-2 pl-9 pr-4 text-sm text-gray-800 placeholder:text-gray-400 focus:border-cyan-500 focus:outline-none dark:border-gray-700 dark:bg-gray-900/60 dark:text-gray-100"
                                />
                            </div>

                            {filteredAgents.length === 0 ? (
                                <div className="agent-glass flex flex-col items-center gap-4 rounded-xl border border-dashed border-cyan-500/25 p-10 text-center">
                                    <Bot size={40} className="text-gray-300 dark:text-gray-600" />
                                    <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                        {search ? t("No agents found", "No se encontraron agentes") : t("No agents yet", "Sin agentes aún")}
                                    </p>
                                    {canCreate && !search && (
                                        <button
                                            onClick={handleNewAgentClick}
                                            className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-4 py-2 text-xs font-bold uppercase tracking-widest text-cyan-600 dark:text-cyan-400"
                                        >
                                            {t("Create Agent", "Crear agente")}
                                        </button>
                                    )}
                                </div>
                            ) : (
                                <div className="flex flex-col gap-3">
                                    {filteredAgents.map(agent => (
                                        <AgentRosterCard
                                            key={agent.id}
                                            agent={agent}
                                            selected={agent.id === selectedAgentId}
                                            onClick={() => setSelectedAgentId(agent.id!)}
                                        />
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Right: workspace */}
                        <div className="lg:col-span-8">
                            {selectedAgent ? (
                                <AgentWorkspacePanel
                                    agent={selectedAgent}
                                    onEdit={() => setEditingAgent(selectedAgent)}
                                    onTest={() => setTestCallAgent(selectedAgent)}
                                    onDelete={() => setAgentToDelete(selectedAgent.id!)}
                                    t={t}
                                />
                            ) : (
                                <div className="agent-glass flex min-h-[560px] flex-col items-center justify-center rounded-2xl p-12 text-center">
                                    <span className="material-symbols-outlined mb-4 text-5xl text-gray-300 dark:text-gray-600">settings_voice</span>
                                    <p className="text-lg font-semibold text-gray-700 dark:text-gray-300">
                                        {t("Select an agent", "Selecciona un agente")}
                                    </p>
                                    <p className="mt-1 max-w-sm text-sm text-gray-500 dark:text-gray-400">
                                        {t("Choose an entity from the roster to view and configure it.", "Elige un agente del listado para ver y configurar su perfil.")}
                                    </p>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default AgentManagementView;
