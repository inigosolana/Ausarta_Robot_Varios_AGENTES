import React, { useState, useEffect } from 'react';
import { Save, ArrowLeft, Loader2, Bot, Mic, Speaker, Brain, Sparkles, X, FlaskConical, GitBranch, Eye } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import type { AgentConfig, AIConfig, Empresa, AgentMode, WorkflowDefinition } from '../types';
import DashboardView from './DashboardView';
import ResultsView from './ResultsView';
import { TestCallModal } from '../components/TestCallModal';
import WorkflowEditor from '../components/WorkflowEditor';
import { AgentKnowledgeDocs } from '../components/agents/AgentKnowledgeDocs';
import { Link } from 'react-router-dom';
import './agents.css';

const AUSARTA_FEMALE_VOICE_ID = 'b5aa8098-49ef-475d-89b0-c9262ecf33fd';  // Chica castellano Cartesia

interface Props {
    agent?: AgentConfig;
    empresaName?: string;
    onSave: () => void;
    onCancel: () => void;
}

const defaultAIConfig: AIConfig = {
    agent_id: 0,
    llm_provider: 'groq',
    llm_model: 'llama-3.3-70b-versatile',
    tts_provider: 'cartesia',
    tts_model: 'sonic-multilingual',
    tts_voice: AUSARTA_FEMALE_VOICE_ID,
    stt_provider: 'deepgram',
    stt_model: 'nova-2',
    language: 'es'
};

const AgentFormView: React.FC<Props> = ({ agent, empresaName, onSave, onCancel }) => {
    const { isRole, hasPermission, profile, isPlatformOwner } = useAuth();
    const { t } = useTranslation();

    const isRegularUser = isRole('user');

    const isEditing = !!agent?.id;
    const [empresas, setEmpresas] = useState<Empresa[]>([]);

    const [formData, setFormData] = useState<AgentConfig>({
        name: agent?.name || '',
        use_case: agent?.use_case || '',
        description: agent?.description || '',
        instructions: agent?.instructions || '',
        critical_rules: agent?.critical_rules || '',
        greeting: agent?.greeting || '',
        company_context: agent?.company_context || '',
        enthusiasm_level: agent?.enthusiasm_level || 'Normal',
        voice_id: agent?.voice_id || '',
        speaking_speed: agent?.speaking_speed ?? 1.0,
        empresa_id: agent?.empresa_id || null,
        tipo_resultados: agent?.tipo_resultados || undefined,
    });

    const [aiConfig, setAiConfig] = useState<AIConfig>({ ...defaultAIConfig });
    const [isSaving, setIsSaving] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [isLoadingEmpresas, setIsLoadingEmpresas] = useState(false);
    const [templates, setTemplates] = useState<{ id: number; name: string; content: string }[]>([]);
    const [activeTab, setActiveTab] = useState<'config' | 'overview' | 'results'>('config');

    // AI Prompt Generation State
    const [showAiPromptModal, setShowAiPromptModal] = useState(false);
    const [aiPromptRequest, setAiPromptRequest] = useState('');
    const [isGeneratingPrompt, setIsGeneratingPrompt] = useState(false);

    // Test Call (Simulator) State
    const [showTestCallModal, setShowTestCallModal] = useState(false);

    // Workflow mode state
    const [agentMode, setAgentMode] = useState<AgentMode>(agent?.agent_mode || 'prompt');
    const [workflowDefinition, setWorkflowDefinition] = useState<WorkflowDefinition | null>(
        agent?.workflow_definition || null
    );
    const [showWorkflowPreview, setShowWorkflowPreview] = useState(false);
    const [workflowPreviewData, setWorkflowPreviewData] = useState<{
        compiled_prompt: string;
        steps: any[];
        warnings: string[];
    } | null>(null);
    const [isPreviewLoading, setIsPreviewLoading] = useState(false);


    useEffect(() => {
        if (isEditing && agent?.id) {
            loadAIConfig(Number(agent.id));
        }
    }, [isEditing, agent?.id]);

    useEffect(() => {
        loadTemplates();
    }, []);

    useEffect(() => {
        if (isPlatformOwner) {
            loadEmpresas();
        }
    }, [isPlatformOwner]);

    const loadEmpresas = async () => {
        setIsLoadingEmpresas(true);
        try {
            const API_URL = (import.meta as any).env.VITE_API_URL || '';
            const resp = await fetch(`${API_URL}/api/empresas`);
            if (!resp.ok) throw new Error('No se pudo cargar empresas');
            const data = await resp.json();
            setEmpresas(Array.isArray(data) ? data : []);
        } catch (err) {
            console.error('Error loading empresas:', err);
            setEmpresas([]);
        } finally {
            setIsLoadingEmpresas(false);
        }
    };

    const loadAIConfig = async (agentId: number) => {
        setIsLoading(true);
        try {
            const result = await Promise.race([
                supabase
                    .from('ai_config')
                    .select('*')
                    .eq('agent_id', agentId)
                    .maybeSingle(),
                new Promise<never>((_, reject) =>
                    setTimeout(() => reject(new Error('Timeout loading AI config')), 10000)
                ),
            ]) as { data: AIConfig | null };
            if (result?.data) setAiConfig(result.data as AIConfig);
        } catch (err) {
            console.error('Error loading AI config:', err);
        } finally {
            setIsLoading(false);
        }
    };

    const loadTemplates = async () => {
        const { data } = await supabase.from('prompt_templates').select('id, name, content');
        if (data) setTemplates(data);
    };

    const handleSave = async () => {
        if (!formData.name.trim()) {
            alert(t('Agent name is mandatory', 'El nombre del agente es obligatorio'));
            return;
        }

        setIsSaving(true);
        try {
            const API_URL = (import.meta as any).env.VITE_API_URL || '';
            const method = isEditing ? 'PUT' : 'POST';
            const url = isEditing ? `${API_URL}/api/agents/${agent!.id}` : `${API_URL}/api/agents`;

            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...formData,
                    ...aiConfig,
                    use_case: formData.use_case,
                    voice_id: formData.voice_id || aiConfig.tts_voice,
                    speaking_speed: formData.speaking_speed ?? 1.0,
                    tts_voice: formData.voice_id || aiConfig.tts_voice,
                    // Workflow fields
                    agent_mode: agentMode,
                    workflow_definition: agentMode !== 'prompt' ? workflowDefinition : null,
                    workflow_variables: agentMode !== 'prompt' && workflowDefinition
                        ? Object.fromEntries(
                            (workflowDefinition.nodes || [])
                                .filter(n => n.variable)
                                .map(n => [n.variable!, null])
                          )
                        : {},
                })
            });

            if (!res.ok) {
                const errorData = await res.json();
                throw new Error(errorData.error || 'Error saving agent');
            }

            // Also upsert AI config directly via Supabase for fields not in the simple agents API
            // (The backend API handles LLM and Voice, but STT/TTS Providers might need separate direct upsert if not handled by API)
            // For now, let's keep the backend API as the primary source and only add direct Supabase for missed fields if necessary.

            // Wait, the backend API currently only maps some fields.
            // Let's refine the backend API shortly to handle ALL AI Config fields if we want total isolation.
            // But for now, this ensures cache clearing and classification.

            onSave();
        } catch (err: any) {
            console.error('Error saving agent:', err);
            alert(`${t('Error saving', 'Error al guardar')}: ${err.message}`);
        } finally {
            setIsSaving(false);
        }
    };

    const handlePreviewWorkflow = async () => {
        if (!workflowDefinition || !agent?.id) return;
        setIsPreviewLoading(true);
        try {
            const API_URL = (import.meta as any).env.VITE_API_URL || '';
            const resp = await fetch(`${API_URL}/api/agents/${agent.id}/workflow/validate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    workflow_definition: workflowDefinition,
                    agent_mode: agentMode,
                    base_instructions: formData.instructions || '',
                }),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            setWorkflowPreviewData(data);
            setShowWorkflowPreview(true);
        } catch (err: any) {
            alert(`Error al previsualizar el workflow: ${err.message}`);
        } finally {
            setIsPreviewLoading(false);
        }
    };

    const handleGenerateAIPrompt = async () => {
        if (!aiPromptRequest.trim()) return;
        setIsGeneratingPrompt(true);
        try {
            const API_URL = (import.meta as any).env.VITE_API_URL || window.location.origin;
            const payload = {
                user_request: aiPromptRequest,
                empresa_id: formData.empresa_id || profile?.empresa_id || null,
                current_name: formData.name,
                current_use_case: formData.use_case,
                current_greeting: formData.greeting,
                current_description: formData.description,
                current_instructions: formData.instructions,
                current_critical_rules: formData.critical_rules
            };

            const response = await fetch(`${API_URL}/api/ai/generate-prompt`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (result.success && result.data) {
                const aiData = result.data;
                setFormData(prev => ({
                    ...prev,
                    name: aiData.name || prev.name,
                    use_case: aiData.use_case || prev.use_case,
                    greeting: aiData.greeting || prev.greeting,
                    description: aiData.description || prev.description,
                    instructions: aiData.instructions || prev.instructions,
                    critical_rules: Array.isArray(aiData.critical_rules) ? aiData.critical_rules.join('\n') : (aiData.critical_rules || prev.critical_rules),
                    tipo_resultados: aiData.tipo_resultados || prev.tipo_resultados
                }));
                setShowAiPromptModal(false);
                setAiPromptRequest('');
            } else {
                alert(`${t('Error generating prompt', 'Error al generar prompt')}: ${result.error || t('Unknown error', 'Error desconocido')}`);
            }
        } catch (err) {
            console.error(err);
            alert(t('Error contacting AI generator', 'Error al contactar con el generador de IA'));
        } finally {
            setIsGeneratingPrompt(false);
        }
    };

    const activeEmpresaLabel = empresaName
        || empresas.find(e => Number(e.id) === Number(formData.empresa_id))?.nombre
        || profile?.empresas?.nombre;

    return (
        <div className="agent-page relative mx-auto max-w-7xl space-y-6 pb-20">
            <div className="pointer-events-none absolute right-0 top-0 h-[200px] w-[200px] rounded-full bg-indigo-500/10 blur-[80px]" />
            {/* Test Call Simulator Modal */}
            {showTestCallModal && agent?.id && (
                <TestCallModal
                    agentId={Number(agent.id)}
                    agentName={agent.name || formData.name}
                    onClose={() => setShowTestCallModal(false)}
                />
            )}

            {isLoading && (
                <div className="text-center text-xs text-gray-500">
                    {t('Loading configuration...', 'Cargando configuración...')}
                </div>
            )}
            {/* Empresa bar */}
            {(isPlatformOwner || activeEmpresaLabel) && (
                <div className="agent-empresa-bar relative z-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-4">
                        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-600 dark:text-indigo-300">
                            <span className="material-symbols-outlined text-3xl">apartment</span>
                        </div>
                        <div>
                            <p className="agent-mono agent-empresa-bar__label text-indigo-600/80 dark:text-indigo-300/90">
                                {t('Active tenant', 'Empresa activa')}
                            </p>
                            <p className="agent-empresa-bar__name text-gray-900 dark:text-white">
                                {activeEmpresaLabel || t('Select company...', 'Seleccionar empresa...')}
                            </p>
                            {isPlatformOwner && (
                                <p className="agent-empresa-bar__hint mt-1 text-gray-500 dark:text-gray-400">
                                    {t('Agent will belong to this company', 'El agente pertenecerá a esta empresa')}
                                </p>
                            )}
                        </div>
                    </div>
                    {isPlatformOwner && (
                        <select
                            value={formData.empresa_id || ''}
                            onChange={e => setFormData({ ...formData, empresa_id: e.target.value ? Number(e.target.value) : null })}
                            disabled={isLoadingEmpresas}
                            className="agent-empresa-bar__select border border-cyan-500/40 bg-white text-gray-900 shadow-md focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 dark:border-cyan-400/40 dark:bg-gray-900/90 dark:text-white"
                        >
                            <option value="">{t('Select company...', 'Seleccionar empresa...')}</option>
                            {empresas.map(emp => (
                                <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                            ))}
                        </select>
                    )}
                </div>
            )}

            {/* Header */}
            <header className="agent-glass relative z-10 flex flex-col justify-between gap-4 rounded-xl p-6 sm:flex-row sm:items-center">
                <div className="flex items-center gap-4">
                    <button
                        onClick={onCancel}
                        className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                    >
                        <ArrowLeft size={20} />
                    </button>
                    <div>
                        <div className="mb-1 flex items-center gap-2 text-cyan-600 dark:text-cyan-400">
                            <span className="material-symbols-outlined text-sm">settings_voice</span>
                            <span className="agent-mono text-[10px] font-bold uppercase tracking-widest">Voice Agent</span>
                        </div>
                        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                            {isEditing ? `${t('Edit', 'Editar')}: ${agent?.name}` : t('Create New Agent', 'Crear Nuevo Agente')}
                        </h1>
                        <p className="text-sm text-gray-500 dark:text-gray-400">{t('Agent and AI Models Configuration', 'Configuración del Agente y Modelos AI')}</p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    {isEditing && agent?.id && (
                        <button
                            onClick={() => setShowTestCallModal(true)}
                            className="flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 font-medium text-white shadow-lg shadow-emerald-500/20 transition-all hover:brightness-110"
                        >
                            <FlaskConical size={17} />
                            {t('Probar Agente', 'Probar Agente')}
                        </button>
                    )}
                    <button
                        onClick={handleSave}
                        disabled={isSaving}
                        className="flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 font-medium text-white shadow-lg shadow-indigo-500/25 transition-all hover:brightness-110 disabled:opacity-50 dark:bg-indigo-500"
                    >
                        {isSaving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />}
                        {isEditing ? t('Save Changes', 'Guardar Cambios') : t('Create Agent', 'Crear Agente')}
                    </button>
                </div>
            </header>

            {/* Tabs (Only if editing) */}
            {isEditing && (
                <div className="agent-glass relative z-10 flex gap-1 overflow-hidden rounded-xl p-1">
                    {(['config', 'overview', 'results'] as const).map(tab => (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={`flex-1 rounded-lg py-2 text-sm font-semibold transition-all ${
                                activeTab === tab
                                    ? 'bg-cyan-600 text-white shadow-md dark:bg-cyan-500'
                                    : 'text-gray-500 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800'
                            }`}
                        >
                            {tab === 'config' ? t('Configuration', 'Configuración') : tab === 'overview' ? t('Overview') : t('Results', 'Resultados')}
                        </button>
                    ))}
                </div>
            )}

            {activeTab === 'overview' && isEditing && agent?.id && (
                <DashboardView
                    agentId={agent.id}
                    title={`Dashboard: ${agent.name}`}
                    hideIntegrations={true}
                />
            )}

            {activeTab === 'results' && isEditing && agent?.id && (
                <ResultsView
                    agentId={agent.id}
                    title={`${t('Results', 'Resultados')}: ${agent.name}`}
                    hideHeader={true}
                />
            )}

            {activeTab === 'config' && (
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 animate-fade-in">
                    {/* Column 1: Identity & Voice */}
                    <div className="space-y-6">
                        <section className="agent-form-section space-y-4">
                            <div className="flex items-center gap-2 mb-2">
                                <Bot size={20} className="text-blue-500" />
                                <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500">{t('Identity', 'Identidad')}</h2>
                            </div>
                            
                            <div className="flex flex-col items-center p-6 bg-gray-50 rounded-xl border border-gray-100 mb-4">
                                <div className="relative group">
                                    <div className="w-24 h-24 rounded-full bg-gradient-to-br from-blue-100 to-blue-50 flex items-center justify-center border-4 border-white shadow-sm">
                                        <Bot size={40} className="text-blue-500" />
                                    </div>
                                </div>
                            </div>

                            <div className="space-y-3">
                                <div>
                                    <label className="block text-xs font-medium text-gray-500 mb-1 ml-1">{t('Agent Name', 'Nombre del Agente')} *</label>
                                    <input
                                        type="text"
                                        value={formData.name}
                                        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                        placeholder="Support Pro"
                                        className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 outline-none transition-all"
                                    />
                                </div>

                                {!isPlatformOwner && (
                                    <div>
                                        <label className="block text-xs font-medium text-gray-500 mb-1 ml-1">{t('Language', 'Idioma')}</label>
                                        <select
                                            value={aiConfig.language || 'es'}
                                            onChange={(e) => setAiConfig({ ...aiConfig, language: e.target.value })}
                                            className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 outline-none"
                                        >
                                            <option value="es">🇪🇸 {t('Spanish', 'Español')}</option>
                                            <option value="en">🇺🇸 {t('English', 'Inglés')}</option>
                                            <option value="eu">🏴 {t('Basque', 'Euskera')}</option>
                                            <option value="gl">🏴 {t('Galician', 'Gallego')}</option>
                                        </select>
                                    </div>
                                )}

                            </div>
                        </section>

                        {/* Voice Section moved to Column 1 */}
                        <section className="agent-form-section space-y-4">
                            <div className="flex items-center gap-2 mb-2">
                                <Speaker size={20} className="text-purple-500" />
                                <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500">{t('Voice', 'Voz')}</h2>
                            </div>
                            
                            <div className="p-4 bg-purple-50/50 border border-purple-100 rounded-lg flex items-center justify-between cursor-pointer hover:bg-purple-50 transition-colors">
                                <div className="flex items-center gap-3 w-full">
                                    <div className="p-2 bg-white rounded-full shadow-sm">
                                        <Speaker size={18} className="text-purple-500" />
                                    </div>
                                    <div className="flex-1">
                                        <label className="block text-xs font-medium text-purple-700 mb-1">{t('Select Voice', 'Seleccionar Voz')}</label>
                                        <select
                                            value={formData.voice_id || aiConfig.tts_voice}
                                            onChange={(e) => {
                                                const selectedVoice = e.target.value;
                                                const isVozBuena = selectedVoice === 'd4db5fb9-f44b-4bd1-85fa-192e0f0d75f9';
                                                
                                                setAiConfig({ 
                                                    ...aiConfig, 
                                                    tts_voice: selectedVoice,
                                                    tts_model: isVozBuena ? 'sonic-3' : 'sonic-multilingual'
                                                });
                                                
                                                setFormData({ 
                                                    ...formData, 
                                                    voice_id: selectedVoice,
                                                    speaking_speed: isVozBuena ? 1.15 : formData.speaking_speed
                                                });
                                            }}
                                            className="w-full bg-transparent border-none p-0 text-sm font-bold text-gray-800 focus:ring-0 cursor-pointer"
                                        >
                                            <optgroup label={t('Spanish', 'Español')}>
                                                <option value={AUSARTA_FEMALE_VOICE_ID}>{t('Inés (España - Natural)', 'Inés (España - Natural)')}</option>
                                                <option value="cefcb124-080b-4655-b31f-932f3ee743de">{t('Raquel (España - Suave)', 'Raquel (España - Suave)')}</option>
                                                <option value="a2f12ebd-80df-4de7-83f3-809599135b1d">{t('Marta (España - Corporativa)', 'Marta (España - Corporativa)')}</option>
                                                <option value="50074b01-9420-4bf5-905e-3a992665e717">{t('Alba (España - Narrativa)', 'Alba (España - Narrativa)')}</option>
                                                <option value="692cd5ac-7140-49e5-950c-35cd0ebebc12">{t('Javier (España - Hombre)', 'Javier (España - Hombre)')}</option>
                                                <option value="79a125e3-4d2a-4645-83e3-a618400030f0">{t('Carlos (España - Hombre serio)', 'Carlos (España - Hombre serio)')}</option>
                                                <option value="d4db5fb9-f44b-4bd1-85fa-192e0f0d75f9">{t('VOZ BUENA', 'VOZ BUENA')}</option>
                                            </optgroup>
                                            <optgroup label={t('Basque', 'Euskera')}>
                                                <option value="99543693-cf6e-4e1d-9259-2e5cc9a0f76b">{t('Ane (Basque Female)', 'Ane (Chica Euskera)')}</option>
                                                <option value="a62209c3-9f0a-4474-9b51-84b191593f49">{t('Ion (Basque Male)', 'Ion (Chico Euskera)')}</option>
                                            </optgroup>
                                            <optgroup label={t('Galician', 'Gallego')}>
                                                <option value="96eade6e-d863-4f9a-8b08-5d7b74d1643b">{t('Sabela (Galician Female)', 'Sabela (Chica Gallega)')}</option>
                                                <option value="4679c1e3-1fd5-45c0-a3a6-7f6e21ef82e2">{t('Brais (Galician Male)', 'Brais (Chico Gallego)')}</option>
                                            </optgroup>
                                            <optgroup label={t('English', 'Inglés')}>
                                                <option value="62ae83ad-4f6a-430b-af41-a9bede9286ca">{t('Sarah (English Female)', 'Sarah (Chica Inglés)')}</option>
                                                <option value="0ad65e7f-006c-47cf-bd31-52279d487913">{t('Mark (English Male)', 'Mark (Chico Inglés)')}</option>
                                            </optgroup>
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </section>
                    </div>

                    {/* Column 2: Personality & Context */}
                    <div className="space-y-6">
                        <section className="agent-form-section space-y-4">
                            <div className="flex items-center gap-2 mb-2">
                                <Brain size={20} className="text-indigo-500" />
                                <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500">{t('Personality', 'Personalidad')}</h2>
                            </div>

                            <div className="space-y-6 p-4 bg-gray-50 rounded-xl border border-gray-100">
                                <div>
                                    <div className="flex justify-between items-center mb-2">
                                        <span className="text-xs font-medium text-gray-600">{t('Enthusiasm', 'Entusiasmo')}</span>
                                        <span className="text-xs font-bold text-indigo-600">{formData.enthusiasm_level || 'Normal'}</span>
                                    </div>
                                    <input 
                                        type="range" 
                                        min="0" 
                                        max="3" 
                                        step="1"
                                        value={['Bajo', 'Normal', 'Alto', 'Extremo'].indexOf(formData.enthusiasm_level || 'Normal')}
                                        onChange={(e) => {
                                            const levels = ['Bajo', 'Normal', 'Alto', 'Extremo'];
                                            setFormData({ ...formData, enthusiasm_level: levels[Number(e.target.value)] });
                                        }}
                                        className="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                                    />
                                    <div className="flex justify-between mt-1 px-1">
                                        <span className="text-[10px] text-gray-400">{t('Low', 'Bajo')}</span>
                                        <span className="text-[10px] text-gray-400">{t('Extreme', 'Extremo')}</span>
                                    </div>
                                </div>

                                <div>
                                    <div className="flex justify-between items-center mb-2">
                                        <span className="text-xs font-medium text-gray-600">{t('Speed', 'Velocidad')}</span>
                                        <span className="text-xs font-bold text-indigo-600">{(formData.speaking_speed ?? 1.0).toFixed(2)}x</span>
                                    </div>
                                    <input 
                                        type="range" 
                                        min="0.7" 
                                        max="1.3" 
                                        step="0.05"
                                        value={formData.speaking_speed ?? 1.0}
                                        onChange={(e) => setFormData({ ...formData, speaking_speed: Number(e.target.value) })}
                                        className="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                                    />
                                    <div className="flex justify-between mt-1 px-1">
                                        <span className="text-[10px] text-gray-400">0.7x</span>
                                        <span className="text-[10px] text-gray-400">1.3x</span>
                                    </div>
                                </div>
                            </div>
                        </section>

                        <section className="agent-form-section space-y-4">
                            <div className="flex items-center gap-2 mb-2">
                                <Brain size={20} className="text-green-500" />
                                <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500">{t('Agent Knowledge', 'Conocimiento del agente')}</h2>
                            </div>
                            {isEditing && agent?.id ? (
                                <AgentKnowledgeDocs
                                    agentId={Number(agent.id)}
                                    empresaId={formData.empresa_id || agent.empresa_id}
                                    isEditing
                                />
                            ) : (
                                <p className="text-sm text-gray-500">
                                    {t('Save the agent first to attach agent-specific documents.', 'Guarda el agente primero para adjuntar documentos propios.')}{' '}
                                    <Link to="/knowledge" className="text-cyan-600 hover:underline">
                                        {t('Company knowledge is managed here', 'El conocimiento de empresa se gestiona aquí')}
                                    </Link>
                                    .
                                </p>
                            )}
                        </section>
                    </div>

                    {/* Column 3: Agent Mode + System Prompt / Workflow Editor */}
                    <div className="space-y-6">
                        {/* Mode selector */}
                        <section className="agent-form-section p-4">
                            <div className="flex items-center gap-2 mb-3">
                                <GitBranch size={18} className="text-violet-500" />
                                <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500">{t('Agent Mode', 'Modo de Agente')}</h2>
                            </div>
                            <div className="grid grid-cols-3 gap-2">
                                {([
                                    {
                                        id: 'prompt' as AgentMode,
                                        label: t('Prompt', 'Prompt'),
                                        desc: t('Free text instructions', 'Instrucciones en texto libre'),
                                        color: 'border-blue-300 bg-blue-50 text-blue-700',
                                        inactive: 'border-gray-200 bg-gray-50 text-gray-500 hover:bg-gray-100',
                                    },
                                    {
                                        id: 'workflow' as AgentMode,
                                        label: t('Workflow', 'Workflow'),
                                        desc: t('Structured script', 'Guion estructurado'),
                                        color: 'border-violet-300 bg-violet-50 text-violet-700',
                                        inactive: 'border-gray-200 bg-gray-50 text-gray-500 hover:bg-gray-100',
                                    },
                                    {
                                        id: 'mixed' as AgentMode,
                                        label: t('Mixed', 'Mixto'),
                                        desc: t('Script + free nodes', 'Guion + nodos libres'),
                                        color: 'border-emerald-300 bg-emerald-50 text-emerald-700',
                                        inactive: 'border-gray-200 bg-gray-50 text-gray-500 hover:bg-gray-100',
                                    },
                                ] as const).map(m => (
                                    <button
                                        key={m.id}
                                        type="button"
                                        onClick={() => setAgentMode(m.id)}
                                        className={`p-3 rounded-lg border-2 text-left transition-all ${agentMode === m.id ? m.color : m.inactive}`}
                                    >
                                        <div className="font-bold text-xs">{m.label}</div>
                                        <div className="text-[10px] mt-0.5 opacity-70">{m.desc}</div>
                                    </button>
                                ))}
                            </div>
                        </section>

                        {/* Prompt editor (modo prompt) */}
                        {agentMode === 'prompt' && (
                            <section className="agent-form-section flex flex-col space-y-4">
                                <div className="flex justify-between items-center mb-2">
                                    <div className="flex items-center gap-2">
                                        <Sparkles size={20} className="text-amber-500" />
                                        <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500">{t('System Prompt', 'Prompt del Sistema')}</h2>
                                    </div>
                                    <button
                                        onClick={() => setShowAiPromptModal(true)}
                                        className="text-xs bg-amber-50 text-amber-600 px-2 py-1 rounded-md font-bold hover:bg-amber-100 transition-colors"
                                    >
                                        ✨ {t('AI Wizard', 'Mago IA')}
                                    </button>
                                </div>
                                <div className="flex-1 relative bg-gray-50 border border-gray-200 rounded-xl overflow-hidden flex flex-col shadow-inner" style={{ minHeight: 320 }}>
                                    <div className="flex items-center justify-between px-4 py-2 bg-gray-100 border-b border-gray-200">
                                        <div className="flex gap-1.5">
                                            <div className="w-2.5 h-2.5 rounded-full bg-red-400/80"></div>
                                            <div className="w-2.5 h-2.5 rounded-full bg-amber-400/80"></div>
                                            <div className="w-2.5 h-2.5 rounded-full bg-emerald-400/80"></div>
                                        </div>
                                        <span className="text-[10px] font-mono text-gray-500">instructions.prompt</span>
                                    </div>
                                    <textarea
                                        value={formData.instructions}
                                        onChange={(e) => setFormData({ ...formData, instructions: e.target.value })}
                                        placeholder={t('Define the agent\'s personality, mission, and rules here...', 'Define aquí la personalidad, misión y reglas del agente...')}
                                        className="flex-1 w-full p-4 bg-transparent text-gray-800 font-mono text-xs focus:ring-0 border-0 resize-none leading-relaxed outline-none"
                                        style={{ minHeight: 280 }}
                                        spellCheck={false}
                                    />
                                </div>
                                <div className="mt-2 flex gap-2">
                                    <select
                                        className="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-gray-50"
                                        onChange={(e) => {
                                            const template = templates.find(t => t.id === Number(e.target.value));
                                            if (template && confirm(t('Replace instructions?', '¿Reemplazar instrucciones?'))) {
                                                setFormData({ ...formData, instructions: template.content });
                                            }
                                        }}
                                        value=""
                                    >
                                        <option value="" disabled>📂 {t('Load Template...', 'Cargar Plantilla...')}</option>
                                        {templates.map(tmpl => (
                                            <option key={tmpl.id} value={tmpl.id}>{tmpl.name}</option>
                                        ))}
                                    </select>
                                </div>
                            </section>
                        )}

                        {/* Workflow editor (modos workflow y mixed) */}
                        {(agentMode === 'workflow' || agentMode === 'mixed') && (
                            <section className="agent-form-section overflow-hidden p-0">
                                <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
                                    <div className="flex items-center gap-2">
                                        <GitBranch size={18} className="text-violet-500" />
                                        <h2 className="text-sm font-bold text-gray-700">{t('Workflow Editor', 'Editor de Workflow')}</h2>
                                    </div>
                                    <div className="flex gap-2">
                                        {agent?.id && (
                                            <button
                                                type="button"
                                                onClick={handlePreviewWorkflow}
                                                disabled={!workflowDefinition || isPreviewLoading}
                                                className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-violet-50 text-violet-700 border border-violet-200 rounded-lg hover:bg-violet-100 disabled:opacity-50 transition-colors"
                                            >
                                                {isPreviewLoading ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} />}
                                                {t('Preview Script', 'Previsualizar guion')}
                                            </button>
                                        )}
                                    </div>
                                </div>

                                {/* Prompt global (contexto adicional para el LLM) */}
                                <div className="px-5 pt-3 pb-2">
                                    <label className="block text-xs font-medium text-gray-500 mb-1">
                                        {t('Global context (optional)', 'Contexto global (opcional)')}
                                        <span className="ml-1 text-gray-400 font-normal">
                                            — {t('Added as context before the compiled script', 'Se añade como contexto antes del guion compilado')}
                                        </span>
                                    </label>
                                    <textarea
                                        rows={3}
                                        value={formData.instructions}
                                        onChange={(e) => setFormData({ ...formData, instructions: e.target.value })}
                                        placeholder={t('Personality, tone, company context...', 'Personalidad, tono, contexto de empresa...')}
                                        className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-xs focus:ring-2 focus:ring-violet-500/20 outline-none resize-none"
                                    />
                                </div>

                                <div style={{ height: 480 }}>
                                    <WorkflowEditor
                                        value={workflowDefinition}
                                        onChange={setWorkflowDefinition}
                                        mode={agentMode as 'workflow' | 'mixed'}
                                    />
                                </div>
                            </section>
                        )}
                    </div>
                </div>
            )}

            {/* Workflow Preview Modal */}
            {showWorkflowPreview && workflowPreviewData && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
                    <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl border border-violet-100 overflow-hidden flex flex-col max-h-[85vh]">
                        <div className="bg-gradient-to-r from-violet-600 to-purple-600 px-6 py-4 flex justify-between items-center flex-shrink-0">
                            <h2 className="text-white font-bold text-lg flex items-center gap-2">
                                <Eye size={20} /> {t('Compiled Script Preview', 'Previsualización del guion compilado')}
                            </h2>
                            <button onClick={() => setShowWorkflowPreview(false)} className="text-white/80 hover:text-white">
                                <X size={20} />
                            </button>
                        </div>
                        <div className="overflow-y-auto flex-1 p-6 space-y-4">
                            {workflowPreviewData.warnings.length > 0 && (
                                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-1">
                                    <p className="text-xs font-bold text-amber-700">⚠️ {t('Warnings', 'Advertencias')}</p>
                                    {workflowPreviewData.warnings.map((w, i) => (
                                        <p key={i} className="text-xs text-amber-600">• {w}</p>
                                    ))}
                                </div>
                            )}
                            <div className="flex gap-4 text-xs text-gray-500">
                                <span className="bg-gray-100 rounded px-2 py-1">
                                    {workflowPreviewData.node_count} {t('nodes', 'nodos')}
                                </span>
                                <span className="bg-gray-100 rounded px-2 py-1">
                                    {workflowPreviewData.step_count} {t('compiled steps', 'pasos compilados')}
                                </span>
                            </div>
                            <div>
                                <p className="text-xs font-bold text-gray-600 mb-2">{t('Compiled prompt (sent to LLM):', 'Prompt compilado (enviado al LLM):')}</p>
                                <pre className="bg-gray-900 text-green-300 text-xs p-4 rounded-xl overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
                                    {workflowPreviewData.compiled_prompt}
                                </pre>
                            </div>
                        </div>
                        <div className="px-6 py-4 border-t border-gray-100 flex justify-end flex-shrink-0">
                            <button
                                onClick={() => setShowWorkflowPreview(false)}
                                className="px-5 py-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium rounded-lg transition-colors"
                            >
                                {t('Close', 'Cerrar')}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* AI Generator Modal */}
            {showAiPromptModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
                    <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg border border-purple-100 overflow-hidden transform transition-all">
                        <div className="bg-gradient-to-r from-purple-600 to-indigo-600 px-6 py-4 flex justify-between items-center">
                            <h2 className="text-white font-bold text-lg flex items-center gap-2">
                                <Sparkles size={20} /> {t('AI Wizard Assistant', 'Asistente Mago IA')}
                            </h2>
                            <button onClick={() => setShowAiPromptModal(false)} className="text-white/80 hover:text-white transition-colors">
                                <X size={20} />
                            </button>
                        </div>
                        <div className="p-6 space-y-4">
                            <p className="text-sm text-gray-600">
                                {t('Describe how you want your agent to be or what questions it should ask.', 'Describe cómo quieres que sea tu agente o qué preguntas debe realizar.')}
                                {t('Artificial Intelligence will structure the rules and prompt for you.', 'La Inteligencia Artificial estructurará las reglas y el prompt por ti.')}
                            </p>
                            <textarea
                                value={aiPromptRequest}
                                onChange={(e) => setAiPromptRequest(e.target.value)}
                                rows={5}
                                placeholder={t('Ex: I want it to act like a friendly secretary and do a satisfaction survey with 3 questions...', 'Ej: Quiero que actúe como una secretaria amable y haga una encuesta de satisfacción con 3 preguntas...')}
                                className="w-full px-4 py-3 border border-purple-200 rounded-xl focus:ring-2 focus:ring-purple-500/30 outline-none text-sm resize-none bg-purple-50/30"
                            />

                            <div className="flex justify-end gap-3 pt-2">
                                <button
                                    onClick={() => setShowAiPromptModal(false)}
                                    className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg text-sm font-medium transition-colors"
                                >
                                    {t('Cancel', 'Cancelar')}
                                </button>
                                <button
                                    onClick={handleGenerateAIPrompt}
                                    disabled={!aiPromptRequest.trim() || isGeneratingPrompt}
                                    className="flex items-center gap-2 px-6 py-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-sm font-semibold rounded-lg shadow-md shadow-purple-500/20 transition-all disabled:opacity-50"
                                >
                                    {isGeneratingPrompt ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
                                    {isGeneratingPrompt ? t('Creating Magic...', 'Creando Magia...') : t('Generate Prompt', 'Generar Prompt')}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default AgentFormView;
