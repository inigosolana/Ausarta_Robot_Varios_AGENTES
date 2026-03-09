import React, { useState, useEffect } from 'react';
import { Save, ArrowLeft, Loader2, Bot, Mic, Speaker, Brain, Sparkles, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import type { AgentConfig, AIConfig, Empresa } from '../types';
import DashboardView from './DashboardView';
import ResultsView from './ResultsView';

const AUSARTA_FEMALE_VOICE_ID = 'a2f12ebd-80df-4de7-83f3-809599135b1d';

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
    tts_voice: AUSARTA_FEMALE_VOICE_ID,
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
    const [isGeneratingCompanyContext, setIsGeneratingCompanyContext] = useState(false);
    const [templates, setTemplates] = useState<{ id: number; name: string; content: string }[]>([]);
    const [activeTab, setActiveTab] = useState<'config' | 'overview' | 'results'>('config');

    // AI Prompt Generation State
    const [showAiPromptModal, setShowAiPromptModal] = useState(false);
    const [aiPromptRequest, setAiPromptRequest] = useState('');
    const [isGeneratingPrompt, setIsGeneratingPrompt] = useState(false);


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
            const API_URL = import.meta.env.VITE_API_URL || '';
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

    const handleGenerateCompanyContext = async () => {
        const selectedEmpresa = empresas.find(e => Number(e.id) === Number(formData.empresa_id));
        const companyName = selectedEmpresa?.nombre?.trim() || '';

        if (!companyName && !formData.empresa_id) {
            alert(t('Select a company first', 'Selecciona una empresa primero'));
            return;
        }

        setIsGeneratingCompanyContext(true);
        try {
            const API_URL = import.meta.env.VITE_API_URL || window.location.origin;
            const resp = await fetch(`${API_URL}/api/ai/company-context`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    empresa_id: formData.empresa_id || profile?.empresa_id || null,
                    company_name: companyName || undefined,
                }),
            });
            const result = await resp.json();
            if (!resp.ok || !result.success) {
                throw new Error(result.error || t('Unknown error', 'Error desconocido'));
            }
            setFormData(prev => ({
                ...prev,
                company_context: result.company_context || prev.company_context || '',
            }));
        } catch (err: any) {
            console.error('Error generating company context:', err);
            alert(`${t('Could not generate company context', 'No se pudo generar el contexto de empresa')}: ${err.message}`);
        } finally {
            setIsGeneratingCompanyContext(false);
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
                    voice_id: formData.voice_id || aiConfig.tts_voice,
                    speaking_speed: formData.speaking_speed ?? 1.0,
                    tts_voice: formData.voice_id || aiConfig.tts_voice,
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

    return (
        <div className="space-y-6 max-w-4xl mx-auto pb-20">
            {isLoading && (
                <div className="text-center text-xs text-gray-500">
                    {t('Loading configuration...', 'Cargando configuración...')}
                </div>
            )}
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
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 animate-fade-in">
                    {/* Column 1: Identity & Voice */}
                    <div className="space-y-6">
                        <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
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

                                {isPlatformOwner && (
                                    <div>
                                        <label className="block text-xs font-medium text-gray-500 mb-1 ml-1">{t('Company', 'Empresa')} *</label>
                                        <select
                                            value={formData.empresa_id || ''}
                                            onChange={(e) => setFormData({ ...formData, empresa_id: e.target.value ? Number(e.target.value) : null })}
                                            disabled={isLoadingEmpresas}
                                            className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 outline-none"
                                        >
                                            <option value="">{isLoadingEmpresas ? t('Loading...', 'Cargando...') : `-- ${t('Select', 'Seleccionar')} --`}</option>
                                            {empresas.map(emp => (
                                                <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                                            ))}
                                        </select>
                                    </div>
                                )}
                            </div>
                        </section>

                        {/* Voice Section moved to Column 1 */}
                        <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
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
                                                setAiConfig({ ...aiConfig, tts_voice: e.target.value });
                                                setFormData({ ...formData, voice_id: e.target.value });
                                            }}
                                            className="w-full bg-transparent border-none p-0 text-sm font-bold text-gray-800 focus:ring-0 cursor-pointer"
                                        >
                                            <optgroup label={t('Spanish', 'Español')}>
                                                <option value="cefcb124-080b-4655-b31f-932f3ee743de">{t('Female Normal', 'Chica Normal')}</option>
                                                <option value="3380a516-6acc-4389-97c8-68273b540dd3">{t('Male (Castilian)', 'Chico (Castellano)')}</option>
                                                <option value={AUSARTA_FEMALE_VOICE_ID}>{t('Female (Ausarta)', 'Ausarta')}</option>
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
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </section>
                    </div>

                    {/* Column 2: Personality & Context */}
                    <div className="space-y-6">
                        <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
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

                        <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                            <div className="flex items-center gap-2 mb-2">
                                <Brain size={20} className="text-green-500" />
                                <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500">{t('Knowledge Base', 'Base de Conocimiento')}</h2>
                            </div>
                            
                            <div className="space-y-4">
                                <div>
                                    <div className="flex items-center justify-between mb-1 ml-1">
                                        <label className="block text-xs font-medium text-gray-500">{t('Company Context', 'Contexto de la Empresa')}</label>
                                        <button
                                            type="button"
                                            onClick={handleGenerateCompanyContext}
                                            disabled={isGeneratingCompanyContext || (!formData.empresa_id && isPlatformOwner)}
                                            className="text-[11px] px-2 py-1 rounded-md bg-green-50 text-green-700 border border-green-200 hover:bg-green-100 disabled:opacity-50"
                                        >
                                            {isGeneratingCompanyContext
                                                ? t('Generating...', 'Generando...')
                                                : t('Auto-fill from web', 'Autorrellenar desde web')}
                                        </button>
                                    </div>
                                    <textarea
                                        rows={8}
                                        value={formData.company_context || ''}
                                        onChange={(e) => setFormData({ ...formData, company_context: e.target.value })}
                                        placeholder={t('Describe your company services, tone, and main objectives...', 'Describe los servicios, tono y objetivos principales...')}
                                        className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-green-500/20 outline-none resize-none"
                                    />
                                </div>
                            </div>
                        </section>
                    </div>

                    {/* Column 3: System Prompt (Full Height) */}
                    <div className="space-y-6">
                        <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4 h-full flex flex-col">
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

                            <div className="flex-1 relative bg-gray-50 border border-gray-200 rounded-xl overflow-hidden flex flex-col shadow-inner">
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
                                    spellCheck={false}
                                />
                            </div>

                            {/* Templates Dropdown */}
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
                                    {templates.map(t => (
                                        <option key={t.id} value={t.id}>{t.name}</option>
                                    ))}
                                </select>
                            </div>
                        </section>
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
