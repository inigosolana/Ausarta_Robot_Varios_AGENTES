import React, { useState, useEffect } from 'react';
import { Save, ArrowLeft, Loader2, Bot, Mic, Speaker, Brain, Sparkles, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import type { AgentConfig, AIConfig, Empresa } from '../types';
import DashboardView from './DashboardView';
import ResultsView from './ResultsView';

interface Props {
    agent?: AgentConfig;
    onSave: () => void;
    onCancel: () => void;
}

const defaultAIConfig: AIConfig = {
    agent_id: 0,
    llm_provider: 'groq',
    llm_model: 'llama-3.3-70b-versatile',
    tts_provider: 'cartesia',
    tts_model: 'sonic-multilingual',
    tts_voice: 'cefcb124-080b-4655-b31f-932f3ee743de',
    stt_provider: 'deepgram',
    stt_model: 'nova-2',
    language: 'es'
};

const AgentFormView: React.FC<Props> = ({ agent, onSave, onCancel }) => {
    const { isRole, hasPermission, profile, isPlatformOwner } = useAuth();
    const { t } = useTranslation();

    const isRegularUser = isRole('usuario');

    const isEditing = !!agent?.id;
    const [empresas, setEmpresas] = useState<Empresa[]>([]);

    const [formData, setFormData] = useState<AgentConfig>({
        name: agent?.name || '',
        use_case: agent?.use_case || '',
        description: agent?.description || '',
        instructions: agent?.instructions || '',
        critical_rules: agent?.critical_rules || '',
        greeting: agent?.greeting || '',
        empresa_id: agent?.empresa_id || null,
    });

    const [aiConfig, setAiConfig] = useState<AIConfig>({ ...defaultAIConfig });
    const [isSaving, setIsSaving] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [templates, setTemplates] = useState<{ id: number; name: string; content: string }[]>([]);
    const [activeTab, setActiveTab] = useState<'config' | 'overview' | 'results'>('config');

    // AI Prompt Generation State
    const [showAiPromptModal, setShowAiPromptModal] = useState(false);
    const [aiPromptRequest, setAiPromptRequest] = useState('');
    const [isGeneratingPrompt, setIsGeneratingPrompt] = useState(false);


    useEffect(() => {
        if (isEditing && agent?.id) {
            loadAIConfig(agent.id);
        }
        loadTemplates();

        if (isPlatformOwner) {
            loadEmpresas();
        }
    }, [isEditing, agent?.id, profile, isPlatformOwner]);

    const loadEmpresas = async () => {
        const { data } = await supabase.from('empresas').select('*').order('nombre');
        if (data) setEmpresas(data);
    };

    const loadAIConfig = async (agentId: number) => {
        setIsLoading(true);
        try {
            const { data } = await supabase
                .from('ai_config')
                .select('*')
                .eq('agent_id', agentId)
                .maybeSingle();
            if (data) setAiConfig(data as AIConfig);
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
            const API_URL = import.meta.env.VITE_API_URL || '';
            const method = isEditing ? 'PUT' : 'POST';
            const url = isEditing ? `${API_URL}/api/agents/${agent!.id}` : `${API_URL}/api/agents`;

            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...formData,
                    ...aiConfig,
                    use_case: formData.use_case, // ensuring correct mapping
                    tts_voice: aiConfig.tts_voice,
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

    const handleGenerateAIPrompt = async () => {
        if (!aiPromptRequest.trim()) return;
        setIsGeneratingPrompt(true);
        try {
            const API_URL = import.meta.env.VITE_API_URL || window.location.origin;
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
                    critical_rules: Array.isArray(aiData.critical_rules) ? aiData.critical_rules.join('\n') : (aiData.critical_rules || prev.critical_rules)
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

    if (isLoading) return <div className="p-8 text-center text-gray-500">{t('Loading configuration...', 'Cargando configuración...')}</div>;

    return (
        <div className="space-y-6 max-w-4xl mx-auto pb-20">
            {/* Header */}
            <header className="flex justify-between items-center bg-white p-6 rounded-xl border border-gray-100 shadow-sm">
                <div className="flex items-center gap-4">
                    <button
                        onClick={onCancel}
                        className="p-2 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-colors"
                    >
                        <ArrowLeft size={20} />
                    </button>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-900">
                            {isEditing ? `${t('Edit', 'Editar')}: ${agent?.name}` : t('Create New Agent', 'Crear Nuevo Agente')}
                        </h1>
                        <p className="text-gray-500 text-sm">{t('Agent and AI Models Configuration', 'Configuración del Agente y Modelos AI')}</p>
                    </div>
                </div>
                <button
                    onClick={handleSave}
                    disabled={isSaving}
                    className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white font-medium rounded-xl hover:from-blue-500 hover:to-blue-400 transition-all disabled:opacity-50 shadow-lg shadow-blue-500/20"
                >
                    {isSaving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />}
                    {isEditing ? t('Save Changes', 'Guardar Cambios') : t('Create Agent', 'Crear Agente')}
                </button>
            </header>

            {/* Tabs (Only if editing) */}
            {isEditing && (
                <div className="flex border-b border-gray-100 mb-6 bg-white rounded-xl shadow-sm overflow-hidden p-1 gap-1">
                    <button
                        onClick={() => setActiveTab('config')}
                        className={`flex-1 py-2 text-sm font-semibold rounded-lg transition-all ${activeTab === 'config' ? 'bg-blue-600 text-white shadow-md' : 'text-gray-500 hover:bg-gray-50'}`}
                    >
                        {t('Configuration', 'Configuración')}
                    </button>
                    <button
                        onClick={() => setActiveTab('overview')}
                        className={`flex-1 py-2 text-sm font-semibold rounded-lg transition-all ${activeTab === 'overview' ? 'bg-blue-600 text-white shadow-md' : 'text-gray-500 hover:bg-gray-50'}`}
                    >
                        {t('Overview')}
                    </button>
                    <button
                        onClick={() => setActiveTab('results')}
                        className={`flex-1 py-2 text-sm font-semibold rounded-lg transition-all ${activeTab === 'results' ? 'bg-blue-600 text-white shadow-md' : 'text-gray-500 hover:bg-gray-50'}`}
                    >
                        {t('Results', 'Resultados')}
                    </button>
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
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 animate-fade-in">
                    {/* Left Column: Agent Details */}
                    <div className="md:col-span-2 space-y-6">
                        {/* General Info */}
                        <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                            <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                                <Bot size={20} className="text-blue-500" />
                                {t('Agent Identity', 'Identidad del Agente')}
                            </h3>

                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Agent Name', 'Nombre del Agente')} *</label>
                                    <input
                                        type="text"
                                        value={formData.name}
                                        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                        placeholder={t('Example: Dakota, Luna, Carlos...', 'Ej: Dakota, Luna, Carlos...')}
                                        className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                                    />
                                </div>
                                {!isPlatformOwner && (
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">{t('Agent Language', 'Idioma del Agente')}</label>
                                        <select
                                            value={aiConfig.language || 'es'}
                                            onChange={(e) => setAiConfig({ ...aiConfig, language: e.target.value })}
                                            className="w-full px-3 py-2 border rounded-lg bg-white"
                                        >
                                            <option value="es">{t('Spanish', 'Español')} (es)</option>
                                            <option value="en">{t('English', 'Inglés')} (en)</option>
                                            <option value="eu">{t('Basque', 'Euskera')} (eu)</option>
                                            <option value="gl">{t('Galician', 'Gallego')} (gl)</option>
                                        </select>
                                    </div>
                                )}
                                {isPlatformOwner ? (
                                    <div>
                                        <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Company / Project', 'Empresa / Proyecto')} *</label>
                                        <select
                                            value={formData.empresa_id || ''}
                                            onChange={(e) => setFormData({ ...formData, empresa_id: e.target.value ? Number(e.target.value) : null })}
                                            className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none bg-white"
                                        >
                                            <option value="" disabled>-- {t('Select Company', 'Selecciona Empresa')} --</option>
                                            {empresas.map(emp => (
                                                <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                                            ))}
                                        </select>
                                    </div>
                                ) : (
                                    !isRegularUser ? (
                                        <div>
                                            <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Use Case', 'Caso de Uso')}</label>
                                            <input
                                                type="text"
                                                value={formData.use_case}
                                                onChange={(e) => setFormData({ ...formData, use_case: e.target.value })}
                                                placeholder={t('Example: Satisfaction Survey', 'Ej: Encuesta de satisfacción')}
                                                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                                            />
                                        </div>
                                    ) : null
                                )}
                            </div>

                            {isPlatformOwner && (
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Use Case', 'Caso de Uso')}</label>
                                    <input
                                        type="text"
                                        value={formData.use_case}
                                        onChange={(e) => setFormData({ ...formData, use_case: e.target.value })}
                                        placeholder={t('Example: Satisfaction Survey', 'Ej: Encuesta de satisfacción')}
                                        className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                                    />
                                </div>
                            )}

                            {isPlatformOwner && (
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Initial Greeting', 'Saludo Inicial')}</label>
                                    <input
                                        type="text"
                                        value={formData.greeting}
                                        onChange={(e) => setFormData({ ...formData, greeting: e.target.value })}
                                        placeholder={t('Hello, I am...', 'Hola, soy...')}
                                        className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                                    />
                                    <p className="text-xs text-gray-400 mt-1">{t('The first thing the agent will say when answering.', 'Lo primero que dirá el agente al contestar.')}</p>
                                </div>
                            )}

                            {isPlatformOwner && (
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Description', 'Descripción')}</label>
                                    <textarea
                                        rows={2}
                                        value={formData.description}
                                        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                        placeholder={t('Brief description of the agent\'s purpose', 'Breve descripción del propósito del agente')}
                                        className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none resize-none"
                                    />
                                </div>
                            )}
                        </section>

                        {/* Instructions */}
                        <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                            <div className="flex justify-between items-center">
                                <div className="flex items-center gap-3">
                                    <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                                        <Brain size={20} className="text-purple-500" />
                                        {t('Instructions (Prompt)', 'Instrucciones (Prompt)')}
                                    </h3>
                                    {(hasPermission('ai_prompt_generator') || isPlatformOwner) && (
                                        <button
                                            onClick={() => setShowAiPromptModal(true)}
                                            className="flex items-center gap-1.5 px-3 py-1 bg-purple-50 hover:bg-purple-100 text-purple-700 text-xs font-bold rounded-full border border-purple-200 transition-colors"
                                        >
                                            <Sparkles size={14} />
                                            {t('Extra AI Wizard', 'Mago IA Extra')}
                                        </button>
                                    )}
                                </div>

                                {!isRegularUser && (
                                    <div className="flex items-center gap-2">
                                        <select
                                            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-gray-50 max-w-[150px]"
                                            onChange={(e) => {
                                                const template = templates.find(t => t.id === Number(e.target.value));
                                                if (template) {
                                                    if (confirm(t('Replace current instructions with this template?', '¿Reemplazar las instrucciones actuales con esta plantilla?'))) {
                                                        setFormData({ ...formData, instructions: template.content });
                                                    }
                                                }
                                            }}
                                            value=""
                                        >
                                            <option value="" disabled>📂 {t('Load Template...', 'Cargar Plantilla...')}</option>
                                            {templates.map(t => (
                                                <option key={t.id} value={t.id}>{t.name}</option>
                                            ))}
                                        </select>

                                        <button
                                            onClick={async () => {
                                                const name = prompt(t('Name for the new template:', 'Nombre para la nueva plantilla:'));
                                                if (name) {
                                                    const { error } = await supabase.from('prompt_templates').insert({
                                                        name,
                                                        description: 'Creado desde el editor',
                                                        content: formData.instructions
                                                    });
                                                    if (!error) {
                                                        alert(t('Template saved!', 'Plantilla guardada!'));
                                                        loadTemplates();
                                                    } else {
                                                        alert(t('Error saving template', 'Error al guardar plantilla'));
                                                    }
                                                }
                                            }}
                                            className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded-lg border border-gray-200 transition-colors"
                                        >
                                            💾 {t('Save as Template', 'Guardar como Plantilla')}
                                        </button>
                                    </div>
                                )}
                            </div>

                            <textarea
                                rows={15}
                                value={formData.instructions}
                                onChange={(e) => setFormData({ ...formData, instructions: e.target.value })}
                                placeholder={t('Define the agent\'s personality, mission, and rules here...', 'Define aquí la personalidad, misión y reglas del agente...')}
                                className="w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-purple-500/20 outline-none font-mono text-sm bg-gray-50"
                            />
                            <p className="text-xs text-gray-500">{t('Define the agent\'s personality, mission, and rules here.', 'Define aquí la personalidad, misión y reglas del agente.')}</p>
                        </section>

                        {/* Critical Rules (Only for Admins) */}
                        {isPlatformOwner && (
                            <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                                <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                                    <X size={20} className="text-red-500" />
                                    {t('Critical Rules (Non-negotiable)', 'Reglas Críticas (No negociables)')}
                                </h3>
                                <textarea
                                    rows={5}
                                    value={formData.critical_rules}
                                    onChange={(e) => setFormData({ ...formData, critical_rules: e.target.value })}
                                    placeholder={t('Ex: Do not hang up without thanking first. Do not give technical information. Repeat if the client does not understand...', 'Ej: No colgar sin antes agradecer. No dar información técnica. Repetir si el cliente no entiende...')}
                                    className="w-full px-4 py-3 border border-red-100 rounded-lg focus:ring-2 focus:ring-red-500/20 outline-none font-mono text-sm bg-red-50/20"
                                />
                                <p className="text-xs text-gray-500">{t('These rules will be applied with maximum priority over any other instruction.', 'Estas reglas se aplicarán con máxima prioridad sobre cualquier otra instrucción.')}</p>
                            </section>
                        )}
                    </div>

                    {/* Right Column: AI Config */}
                    <div className="space-y-6">
                        {/* LLM Config (Only Provider/Model for Admins) */}
                        {!isRegularUser && (
                            <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                                <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                                    <Brain size={16} /> {t('Intelligence and Language', 'Inteligencia e Idioma')}
                                </h3>

                                {isPlatformOwner && (
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">{t('Provider', 'Proveedor')}</label>
                                        <select
                                            value={aiConfig.llm_provider}
                                            onChange={(e) => {
                                                const p = e.target.value;
                                                let m = 'llama-3.3-70b-versatile';
                                                if (p === 'google') m = 'models/gemini-2.0-flash';
                                                if (p === 'openai') m = 'gpt-4o';
                                                if (p === 'deepseek') m = 'deepseek-chat';
                                                setAiConfig({ ...aiConfig, llm_provider: p, llm_model: m });
                                            }}
                                            className="w-full px-3 py-2 border rounded-lg bg-gray-50"
                                        >
                                            <option value="openai">OpenAI (GPT-4o)</option>
                                            <option value="groq">Groq (Llama 3, Mixtral)</option>
                                            <option value="google">Google Gemini</option>
                                            <option value="deepseek">DeepSeek (V3, R1)</option>
                                        </select>
                                    </div>
                                )}

                                {isPlatformOwner && (
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">{t('Agent Language', 'Idioma del Agente')}</label>
                                        <select
                                            value={aiConfig.language || 'es'}
                                            onChange={(e) => setAiConfig({ ...aiConfig, language: e.target.value })}
                                            className="w-full px-3 py-2 border rounded-lg bg-white"
                                        >
                                            <option value="es">{t('Spanish', 'Español')} (es)</option>
                                            <option value="en">{t('English', 'Inglés')} (en)</option>
                                            <option value="eu">{t('Basque', 'Euskera')} (eu)</option>
                                            <option value="gl">{t('Galician', 'Gallego')} (gl)</option>
                                        </select>
                                    </div>
                                )}

                                {!isPlatformOwner && (
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">{t('Intelligence Level', 'Nivel de Inteligencia')}</label>
                                        <select
                                            value={aiConfig.llm_model}
                                            onChange={(e) => setAiConfig({ ...aiConfig, llm_model: e.target.value })}
                                            className="w-full px-3 py-2 border rounded-lg bg-white"
                                        >
                                            <option value="gpt-4o">Alta (Recomendado)</option>
                                            <option value="gpt-4o-mini">Básica (Rápido)</option>
                                        </select>
                                    </div>
                                )}

                                {isPlatformOwner && (
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">{t('Model', 'Modelo')}</label>
                                        <select
                                            value={aiConfig.llm_model}
                                            onChange={(e) => setAiConfig({ ...aiConfig, llm_model: e.target.value })}
                                            className="w-full px-3 py-2 border rounded-lg bg-white"
                                        >
                                            {aiConfig.llm_provider === 'openai' ? (
                                                <>
                                                    <option value="gpt-4o">GPT-4o (High Intelligence)</option>
                                                    <option value="gpt-4o-mini">GPT-4o mini (Fast & Cheap)</option>
                                                    <option value="gpt-4-turbo">GPT-4 Turbo</option>
                                                </>
                                            ) : aiConfig.llm_provider === 'google' ? (
                                                <>
                                                    <option value="models/gemini-2.0-flash">Gemini 2.0 Flash (Fast)</option>
                                                    <option value="models/gemini-2.0-pro-exp-02-05">Gemini 2.0 Pro (Most Powerful)</option>
                                                    <option value="models/gemini-2.0-flash-lite">Gemini 2.0 Flash Lite</option>
                                                    <option value="models/gemini-1.5-pro">Gemini 1.5 Pro</option>
                                                    <option value="models/gemini-1.5-flash">Gemini 1.5 Flash</option>
                                                </>
                                            ) : aiConfig.llm_provider === 'deepseek' ? (
                                                <>
                                                    <option value="deepseek-chat">DeepSeek-V3 (Chat)</option>
                                                    <option value="deepseek-reasoner">DeepSeek-R1 (Reasoning)</option>
                                                </>
                                            ) : (
                                                <>
                                                    <option value="llama-3.3-70b-versatile">Llama 3.3 70B</option>
                                                    <option value="mixtral-8x7b-32768">Mixtral 8x7B</option>
                                                </>
                                            )}
                                        </select>
                                    </div>
                                )}
                            </section>
                        )}

                        {/* TTS Config */}
                        <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                            <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                                <Speaker size={16} /> {t('Voice (TTS)', 'Voz (TTS)')}
                            </h3>
                            {isPlatformOwner && (
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">{t('Provider', 'Proveedor')}</label>
                                    <select
                                        value={aiConfig.tts_provider}
                                        onChange={(e) => setAiConfig({ ...aiConfig, tts_provider: e.target.value })}
                                        className="w-full px-3 py-2 border rounded-lg bg-gray-50"
                                    >
                                        <option value="cartesia">Cartesia (Sonic)</option>
                                        <option value="openai">OpenAI TTS</option>
                                        <option value="elevenlabs">ElevenLabs</option>
                                    </select>
                                </div>
                            )}
                            {isPlatformOwner && (
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">{t('Model', 'Modelo')}</label>
                                    <input
                                        type="text"
                                        value={aiConfig.tts_model}
                                        onChange={(e) => setAiConfig({ ...aiConfig, tts_model: e.target.value })}
                                        className="w-full px-3 py-2 border rounded-lg"
                                    />
                                </div>
                            )}
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">{t('Select Voice', 'Seleccionar Voz')}</label>
                                <select
                                    value={aiConfig.tts_voice}
                                    onChange={(e) => setAiConfig({ ...aiConfig, tts_voice: e.target.value })}
                                    className="w-full px-3 py-2 border rounded-lg font-medium text-sm bg-white"
                                >
                                    <optgroup label={t('Spanish', 'Español')}>
                                        <option value="cefcb124-080b-4655-b31f-932f3ee743de">{t('Female (Castilian)', 'Chica (Castellano)')}</option>
                                        <option value="3380a516-6acc-4389-97c8-68273b540dd3">{t('Male (Castilian)', 'Chico (Castellano)')}</option>
                                        <option value="44c5567b-1b68-4873-8231-4e7660f749ad">{t('Female (Ausarta)', 'Chica (Ausarta)')}</option>
                                    </optgroup>
                                    <optgroup label={t('Basque', 'Euskera')}>
                                        <option value="99543693-cf6e-4e1d-9259-2e5cc9a0f76b">{t('Female', 'Chica')}</option>
                                        <option value="a62209c3-9f0a-4474-9b51-84b191593f49">{t('Male', 'Chico')}</option>
                                    </optgroup>
                                    <optgroup label={t('Galician', 'Gallego')}>
                                        <option value="96eade6e-d863-4f9a-8b08-5d7b74d1643b">{t('Female', 'Chica')}</option>
                                        <option value="4679c1e3-1fd5-45c0-a3a6-7f6e21ef82e2">{t('Male', 'Chico')}</option>
                                    </optgroup>
                                    <optgroup label={t('English', 'Inglés')}>
                                        <option value="62ae83ad-4f6a-430b-af41-a9bede9286ca">{t('Female', 'Chica')}</option>
                                        <option value="0ad65e7f-006c-47cf-bd31-52279d487913">{t('Male', 'Chico')}</option>
                                    </optgroup>
                                    {isPlatformOwner && !["cefcb124-080b-4655-b31f-932f3ee743de", "3380a516-6acc-4389-97c8-68273b540dd3", "44c5567b-1b68-4873-8231-4e7660f749ad", "a62209c3-9f0a-4474-9b51-84b191593f49", "99543693-cf6e-4e1d-9259-2e5cc9a0f76b", "4679c1e3-1fd5-45c0-a3a6-7f6e21ef82e2", "96eade6e-d863-4f9a-8b08-5d7b74d1643b", "62ae83ad-4f6a-430b-af41-a9bede9286ca", "0ad65e7f-006c-47cf-bd31-52279d487913"].includes(aiConfig.tts_voice) && (
                                        <option value={aiConfig.tts_voice}>{t('Custom', 'Personalizado')}: {aiConfig.tts_voice}</option>
                                    )}
                                </select>
                            </div>
                        </section>

                        {/* STT Config (Only if Platform Owner) */}
                        {isPlatformOwner && (
                            <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                                <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                                    <Mic size={16} /> {t('Transcription (STT)', 'Transcripción (STT)')}
                                </h3>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">{t('Provider', 'Proveedor')}</label>
                                    <select
                                        value={aiConfig.stt_provider}
                                        onChange={(e) => setAiConfig({ ...aiConfig, stt_provider: e.target.value })}
                                        className="w-full px-3 py-2 border rounded-lg bg-gray-50"
                                    >
                                        <option value="deepgram">Deepgram</option>
                                        <option value="openai">OpenAI Whisper</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">{t('Model', 'Modelo')}</label>
                                    <input
                                        type="text"
                                        value={aiConfig.stt_model}
                                        onChange={(e) => setAiConfig({ ...aiConfig, stt_model: e.target.value })}
                                        className="w-full px-3 py-2 border rounded-lg"
                                    />
                                </div>
                            </section>
                        )}
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
