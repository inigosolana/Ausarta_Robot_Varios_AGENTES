import React, { useState, useEffect } from "react";
import { Bot, Loader2, Search, Building2, ChevronRight, ArrowLeft, Users, Mail, Trash2, Settings } from "lucide-react";
import { supabase } from "../lib/supabase";
import { useAuth } from "../contexts/AuthContext";
import { useTranslation } from "react-i18next";
import type { AgentConfig, AIConfig, Empresa, UserProfile } from "../types";

const SkeletonCard = () => (
    <div className="bg-white rounded-2xl border border-gray-100 p-8 flex flex-col items-center space-y-4 animate-pulse">
        <div className="w-20 h-20 bg-gray-200 rounded-3xl" />
        <div className="space-y-2 w-full flex flex-col items-center">
            <div className="h-5 bg-gray-200 rounded w-2/3" />
            <div className="h-3 bg-gray-100 rounded w-1/2" />
            <div className="h-2 bg-gray-100 rounded w-1/3 mt-1" />
        </div>
        <div className="h-4 bg-gray-100 rounded w-1/4 mt-4" />
    </div>
);

const AgentListView: React.FC = () => {
    const { profile, isRole } = useAuth();
    const { t } = useTranslation();

    const isAusartaAdmin = profile?.empresas?.nombre === 'Ausarta' && isRole('admin');
    const isPlatformOwner = isRole('superadmin') || isAusartaAdmin;

    const [empresas, setEmpresas] = useState<Empresa[]>([]);
    const [agents, setAgents] = useState<(AgentConfig & { ai_config?: AIConfig })[]>([]);
    const [companyUsers, setCompanyUsers] = useState<UserProfile[]>([]);

    // View States
    const [loading, setLoading] = useState(true);
    const [selectedEmpresa, setSelectedEmpresa] = useState<Empresa | null>(null);
    const [activeTab, setActiveTab] = useState<"agents" | "users">("agents");
    const [search, setSearch] = useState("");
    const [selectedResponsable, setSelectedResponsable] = useState<string>("all");

    useEffect(() => {
        loadEmpresas();
    }, []);

    const loadEmpresas = async () => {
        setLoading(true);
        try {
            const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error("Timeout")), 10000));
            // Use cached API endpoint
            const fetchPromise = fetch(`${import.meta.env.VITE_API_URL || ''}/api/empresas`);
            const res = (await Promise.race([fetchPromise, timeoutPromise])) as Response;
            const data = await res.json();

            if (Array.isArray(data)) {
                let filtered = data;
                if (!isPlatformOwner && profile?.empresa_id) {
                    filtered = data.filter(e => e.id === profile.empresa_id);
                }
                setEmpresas(filtered);
            }
        } catch (err) {
            console.error("Error loading empresas:", err);
            // Fallback to direct Supabase
            try {
                const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error("Timeout")), 10000));

                const fetchSupabase = async () => {
                    let query = supabase.from("empresas").select("*").order("created_at", { ascending: true });
                    if (!isPlatformOwner && profile?.empresa_id) {
                        query = query.eq('id', profile.empresa_id);
                    }
                    const { data } = await query;
                    setEmpresas(data || []);
                };
                await Promise.race([fetchSupabase(), timeoutPromise]);
            } catch (e2) {
                console.error("Fallback also failed:", e2);
            }
        } finally {
            setTimeout(() => setLoading(false), 200);
        }
    };

    const loadCompanyData = async (empresaId: number) => {
        setLoading(true);
        try {
            const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error("Timeout")), 10000));
            const fetchData = async () => {
                // Load Agents
                const { data: agentsData } = await supabase
                    .from("agent_config")
                    .select("*")
                    .eq("empresa_id", empresaId)
                    .order("created_at", { ascending: false });

                const agentIds = (agentsData || []).map(a => a.id);
                const { data: aiConfigsData } = await supabase
                    .from("ai_config")
                    .select("*")
                    .in("agent_id", agentIds);

                const agentsWithAI = (agentsData || []).map(agent => ({
                    ...agent,
                    ai_config: (aiConfigsData || []).find(c => c.agent_id === agent.id)
                }));
                setAgents(agentsWithAI);

                // Load Users
                const { data: usersData } = await supabase
                    .from("user_profiles")
                    .select("*")
                    .eq("empresa_id", empresaId);
                setCompanyUsers(usersData || []);
            };

            await Promise.race([fetchData(), timeoutPromise]);
        } catch (err) {
            console.error("Error loading company data:", err);
        } finally {
            setLoading(false);
        }
    };

    const handleCreateEmpresa = async () => {
        const nombre = prompt(t("New Company / Project Name:", "Nombre de la nueva Empresa / Proyecto:"));
        if (!nombre) return;
        const responsable = prompt(t("Manager Name:", "Nombre del Responsable:"));
        if (!responsable) return;

        try {
            const { error } = await supabase.from("empresas").insert({ nombre, responsable });
            if (error) throw error;
            loadEmpresas();
        } catch (err) {
            alert(t("Error creating company", "Error al crear la empresa"));
        }
    };

    const handleEditEmpresa = async (e: React.MouseEvent, emp: Empresa) => {
        e.stopPropagation();
        const nombre = prompt(t("Edit company name:", "Editar nombre de la empresa:"), emp.nombre);
        if (nombre === null) return;
        const responsable = prompt(t("Edit manager:", "Editar responsable:"), emp.responsable);
        if (responsable === null) return;
        const maxAdminsVal = prompt(t("Edit admin limit:", "Editar límite de administradores:"), String(emp.max_admins || 1));
        if (maxAdminsVal === null) return;
        const max_admins = parseInt(maxAdminsVal);

        try {
            const { error } = await supabase.from("empresas")
                .update({ nombre, responsable, max_admins })
                .eq("id", emp.id);
            if (error) throw error;
            loadEmpresas();
        } catch (err) {
            alert(t("Error updating company", "Error al actualizar la empresa"));
        }
    };

    const handleDeleteEmpresa = async (id: number) => {
        if (!confirm(t("Are you sure you want to delete this company and ALL its agents?", "¿Seguro que quieres eliminar esta empresa y TODOS sus agentes?"))) return;
        try {
            await supabase.from("empresas").delete().eq("id", id);
            loadEmpresas();
        } catch (err) {
            alert(t("Error deleting", "Error al eliminar"));
        }
    };

    // ===== COMPANY DETAIL VIEW (Read-only agents) =====
    if (selectedEmpresa) {
        return (
            <div className="space-y-6">
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                    <div className="animate-in fade-in slide-in-from-left-4 duration-500">
                        <button onClick={() => setSelectedEmpresa(null)} className="flex items-center gap-1 text-sm text-gray-500 hover:text-blue-600 mb-2 transition-colors">
                            <ArrowLeft size={16} /> {t("Back to Companies", "Volver a Empresas")}
                        </button>
                        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
                            <Building2 size={24} className="text-blue-500" />
                            {selectedEmpresa.nombre}
                        </h1>
                        <p className="text-gray-500 text-sm">{t("Manager", "Responsable")}: {selectedEmpresa.responsable}</p>
                    </div>
                </div>

                {/* Tabs */}
                <div className="flex gap-1 bg-gray-100 p-1 rounded-xl w-fit">
                    <button
                        onClick={() => setActiveTab("agents")}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === "agents" ? "bg-white text-blue-600 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}
                    >
                        <Bot size={18} /> {t("Agents")} ({agents.length})
                    </button>
                    <button
                        onClick={() => setActiveTab("users")}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === "users" ? "bg-white text-blue-600 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}
                    >
                        <Users size={18} /> {t("Users", "Usuarios")} ({companyUsers.length})
                    </button>
                </div>

                <div className="relative">
                    <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                    <input
                        type="text"
                        placeholder={activeTab === "agents" ? t("Search agents...", "Buscar agentes...") : t("Search users...", "Buscar usuarios...")}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:border-blue-400 transition-all"
                    />
                </div>

                {loading ? (
                    <div className="flex justify-center py-20"><Loader2 className="animate-spin text-blue-500" size={32} /></div>
                ) : activeTab === "agents" ? (
                    <>
                        {agents.length === 0 ? (
                            <div className="text-center py-12 bg-white rounded-2xl border border-dashed border-gray-200">
                                <Bot size={40} className="mx-auto text-gray-300 mb-3" />
                                <p className="text-gray-500 font-medium">{t("This company has no agents yet", "Esta empresa no tiene agentes aún")}</p>
                                <p className="text-gray-400 text-sm mt-1">{t("Go to the 'Agents' tab in the side menu to create one.", "Ve a la pestaña \"Agentes\" del menú lateral para crear uno.")}</p>
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
                                {agents.filter(a => a.name.toLowerCase().includes(search.toLowerCase())).map((agent) => (
                                    <div key={agent.id} className="bg-white rounded-xl border border-gray-100 overflow-hidden p-5 transition-all hover:border-blue-100 hover:shadow-sm">
                                        <div className="flex items-center gap-3">
                                            <div className="p-2.5 rounded-xl bg-blue-50 text-blue-600">
                                                <Bot size={20} />
                                            </div>
                                            <div>
                                                <h3 className="font-semibold text-gray-900">{agent.name}</h3>
                                                <p className="text-xs text-gray-400">{agent.use_case || t("No use case", "Sin caso de uso")}</p>
                                            </div>
                                        </div>
                                        <p className="text-sm text-gray-500 my-4 line-clamp-2">{agent.description || t("No description", "Sin descripción")}</p>
                                        {agent.ai_config && (
                                            <div className="flex flex-wrap gap-1.5 text-[10px]">
                                                <span className="px-2 py-0.5 bg-purple-50 text-purple-600 rounded-full font-medium">
                                                    {agent.ai_config.llm_model}
                                                </span>
                                                <span className="px-2 py-0.5 bg-green-50 text-green-600 rounded-full font-medium">
                                                    {agent.ai_config.stt_provider}
                                                </span>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </>
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

    // ===== MAIN: COMPANY LIST =====
    return (
        <div className="space-y-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">{t("Companies and Clients", "Empresas y Clientes")}</h1>
                    <p className="text-gray-500 text-sm">{t("View and manage multitenant structure", "Visualiza y gestiona la estructura multitenant")}</p>
                </div>
                {isPlatformOwner && (
                    <button
                        onClick={handleCreateEmpresa}
                        className="flex items-center gap-2 px-5 py-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 transition-all font-medium text-sm shadow-lg shadow-gray-200"
                    >
                        <Building2 size={18} />
                        {t("Create New Company", "Crear Nueva Empresa")}
                    </button>
                )}
            </div>

            {/* Filters */}
            <div className="flex flex-col sm:flex-row gap-3">
                {isPlatformOwner && (
                    <select
                        value={selectedResponsable}
                        onChange={(e) => setSelectedResponsable(e.target.value)}
                        className="px-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:border-blue-400 bg-white text-sm font-medium"
                    >
                        <option value="all">👤 {t("All managers", "Todos los responsables")}</option>
                        {Array.from(new Set(empresas.map(e => e.responsable).filter(Boolean))).sort().map(resp => (
                            <option key={resp} value={resp}>👤 {resp}</option>
                        ))}
                    </select>
                )}

                <div className="relative flex-1">
                    <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                    <input
                        type="text"
                        placeholder={t("Search company or manager...", "Buscar empresa o responsable...")}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl outline-none focus:border-blue-400 transition-all bg-white text-sm"
                    />
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-in fade-in duration-700">
                {loading ? (
                    <>{[1, 2, 3, 4, 5, 6].map(i => <SkeletonCard key={i} />)}</>
                ) : empresas.length === 0 ? (
                    <div className="col-span-full text-center py-20 bg-white rounded-2xl border border-dashed border-gray-200">
                        <Building2 size={48} className="mx-auto text-gray-300 mb-4" />
                        <h3 className="text-lg font-semibold text-gray-700">{t("Start by creating a company", "Comienza creando una empresa")}</h3>
                        <p className="text-gray-400 text-sm">{t("You will be able to separate agents and users for each client.", "Podrás separar agentes y usuarios por cada cliente.")}</p>
                    </div>
                ) : (
                    empresas
                        .filter(empresa => selectedResponsable === "all" || empresa.responsable === selectedResponsable)
                        .filter(empresa =>
                            empresa.nombre.toLowerCase().includes(search.toLowerCase()) ||
                            (empresa.responsable && empresa.responsable.toLowerCase().includes(search.toLowerCase()))
                        )
                        .map((empresa) => (
                            <div key={empresa.id} onClick={() => { setSelectedEmpresa(empresa); loadCompanyData(empresa.id!); setSearch(""); }} className="group relative bg-white rounded-2xl border border-gray-100 p-8 flex flex-col items-center text-center space-y-4 hover:border-blue-400 hover:shadow-2xl hover:shadow-blue-500/10 transition-all cursor-pointer">
                                {isPlatformOwner && (
                                    <div className="absolute top-4 right-4 flex gap-2">
                                        <button onClick={(e) => handleEditEmpresa(e, empresa)} className="p-2 opacity-0 group-hover:opacity-100 hover:bg-blue-50 text-gray-300 hover:text-blue-500 rounded-xl transition-all">
                                            <Settings size={18} />
                                        </button>
                                        <button onClick={(e) => { e.stopPropagation(); handleDeleteEmpresa(empresa.id!); }} className="p-2 opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-300 hover:text-red-500 rounded-xl transition-all">
                                            <Trash2 size={18} />
                                        </button>
                                    </div>
                                )}

                                <div className="w-20 h-20 bg-blue-50 rounded-3xl flex items-center justify-center group-hover:bg-blue-600 group-hover:rotate-6 transition-all duration-500 shadow-inner">
                                    <Building2 size={32} className="text-blue-500 group-hover:text-white transition-colors" />
                                </div>

                                <div>
                                    <h3 className="text-xl font-bold text-gray-900 group-hover:text-blue-600 transition-colors uppercase tracking-tight">{empresa.nombre}</h3>
                                    <p className="text-sm text-gray-500 font-medium whitespace-nowrap overflow-hidden text-ellipsis">{t("Manager", "Responsable")}: {empresa.responsable}</p>
                                    <p className="text-[10px] text-gray-400 mt-1 uppercase font-bold tracking-widest">
                                        {t("Admin Limit", "Límite Admins")}: {empresa.nombre === 'Ausarta' ? t('Unlimited', 'Ilimitado') : (empresa.max_admins || 1)}
                                    </p>
                                </div>

                                <div className="pt-4 flex items-center gap-2 text-xs font-bold text-blue-500 opacity-0 group-hover:opacity-100 translate-y-2 group-hover:translate-y-0 transition-all">
                                    {t("VIEW COMPANY", "VER EMPRESA")} <ChevronRight size={14} />
                                </div>
                            </div>
                        ))
                )}
            </div>
        </div>
    );
};

export default AgentListView;
