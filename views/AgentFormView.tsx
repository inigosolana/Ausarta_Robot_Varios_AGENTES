import React, { useState, useEffect } from 'react';
import { Save, ArrowLeft, Loader2, Bot, Mic, Speaker, Brain } from 'lucide-react';
import { supabase } from '../lib/supabase';
import type { AgentConfig, AIConfig } from '../types';

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
    tts_voice: 'fb926b21-4d92-411a-85d0-9d06859e2171',
    stt_provider: 'deepgram',
    stt_model: 'nova-2',
    language: 'es'
};

const AgentFormView: React.FC<Props> = ({ agent, onSave, onCancel }) => {
    const isEditing = !!agent?.id;

    const [formData, setFormData] = useState<AgentConfig>({
        name: agent?.name || '',
        use_case: agent?.use_case || '',
        description: agent?.description || '',
        instructions: agent?.instructions || '',
        greeting: agent?.greeting || '',
    });

    const [aiConfig, setAiConfig] = useState<AIConfig>({ ...defaultAIConfig });
    const [isSaving, setIsSaving] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [templates, setTemplates] = useState<{ id: number; name: string; content: string }[]>([]);

    useEffect(() => {
        if (isEditing && agent?.id) {
            loadAIConfig(agent.id);
        }
        loadTemplates();
    }, []);

    const loadAIConfig = async (agentId: number) => {
        setIsLoading(true);
        try {
            const { data } = await supabase
                .from('ai_config')
                .select('*')
                .eq('agent_id', agentId)
                .single();
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
            alert('El nombre del agente es obligatorio');
            return;
        }

        setIsSaving(true);
        try {
            let agentId: number;

            if (isEditing && agent?.id) {
                // Update existing agent
                const { error } = await supabase
                    .from('agent_config')
                    .update({
                        name: formData.name,
                        use_case: formData.use_case,
                        description: formData.description,
                        instructions: formData.instructions,
                        greeting: formData.greeting,
                        updated_at: new Date().toISOString()
                    })
                    .eq('id', agent.id);

                if (error) throw error;
                agentId = agent.id;
            } else {
                // Create new agent
                const { data, error } = await supabase
                    .from('agent_config')
                    .insert({
                        name: formData.name,
                        use_case: formData.use_case,
                        description: formData.description,
                        instructions: formData.instructions,
                        greeting: formData.greeting,
                    })
                    .select('id')
                    .single();

                if (error) throw error;
                agentId = data.id;
            }

            // Upsert AI config
            const aiPayload = { ...aiConfig, agent_id: agentId, updated_at: new Date().toISOString() };
            const { data: existingAI } = await supabase
                .from('ai_config')
                .select('id')
                .eq('agent_id', agentId)
                .single();

            if (existingAI) {
                await supabase.from('ai_config').update(aiPayload).eq('agent_id', agentId);
            } else {
                await supabase.from('ai_config').insert(aiPayload);
            }

            onSave();
        } catch (err: any) {
            console.error('Error saving agent:', err);
            alert(`Error al guardar: ${err.message}`);
        } finally {
            setIsSaving(false);
        }
    };

    if (isLoading) return <div className="p-8 text-center text-gray-500">Cargando configuración...</div>;

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
                            {isEditing ? `Editar: ${agent?.name}` : 'Crear Nuevo Agente'}
                        </h1>
                        <p className="text-gray-500 text-sm">Configuración del Agente y Modelos AI</p>
                    </div>
                </div>
                <button
                    onClick={handleSave}
                    disabled={isSaving}
                    className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-500 text-white font-medium rounded-xl hover:from-blue-500 hover:to-blue-400 transition-all disabled:opacity-50 shadow-lg shadow-blue-500/20"
                >
                    {isSaving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />}
                    {isEditing ? 'Guardar Cambios' : 'Crear Agente'}
                </button>
            </header>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Left Column: Agent Details */}
                <div className="md:col-span-2 space-y-6">
                    {/* General Info */}
                    <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                        <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                            <Bot size={20} className="text-blue-500" />
                            Identidad del Agente
                        </h3>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-semibold text-gray-700 mb-1">Nombre del Agente *</label>
                                <input
                                    type="text"
                                    value={formData.name}
                                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                    placeholder="Ej: Dakota, Luna, Carlos..."
                                    className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-semibold text-gray-700 mb-1">Caso de Uso</label>
                                <input
                                    type="text"
                                    value={formData.use_case}
                                    onChange={(e) => setFormData({ ...formData, use_case: e.target.value })}
                                    placeholder="Ej: Encuesta de satisfacción"
                                    className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                                />
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-semibold text-gray-700 mb-1">Saludo Inicial</label>
                            <input
                                type="text"
                                value={formData.greeting}
                                onChange={(e) => setFormData({ ...formData, greeting: e.target.value })}
                                placeholder="Hola, soy..."
                                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                            />
                            <p className="text-xs text-gray-400 mt-1">Lo primero que dirá el agente al contestar.</p>
                        </div>

                        <div>
                            <label className="block text-sm font-semibold text-gray-700 mb-1">Descripción</label>
                            <textarea
                                rows={2}
                                value={formData.description}
                                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                placeholder="Breve descripción del propósito del agente"
                                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none resize-none"
                            />
                        </div>
                    </section>

                    {/* Instructions */}
                    <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                        <div className="flex justify-between items-center">
                            <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                                <Brain size={20} className="text-purple-500" />
                                Instrucciones (Prompt)
                            </h3>

                            <div className="flex items-center gap-2">
                                <select
                                    className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-gray-50 max-w-[150px]"
                                    onChange={(e) => {
                                        const template = templates.find(t => t.id === Number(e.target.value));
                                        if (template) {
                                            if (confirm('¿Reemplazar las instrucciones actuales con esta plantilla?')) {
                                                setFormData({ ...formData, instructions: template.content });
                                            }
                                        }
                                    }}
                                    value=""
                                >
                                    <option value="" disabled>📂 Cargar Plantilla...</option>
                                    {templates.map(t => (
                                        <option key={t.id} value={t.id}>{t.name}</option>
                                    ))}
                                </select>

                                <button
                                    onClick={async () => {
                                        const name = prompt('Nombre para la nueva plantilla:');
                                        if (name) {
                                            const { error } = await supabase.from('prompt_templates').insert({
                                                name,
                                                description: 'Creado desde el editor',
                                                content: formData.instructions
                                            });
                                            if (!error) {
                                                alert('Plantilla guardada!');
                                                loadTemplates();
                                            } else {
                                                alert('Error al guardar plantilla');
                                            }
                                        }
                                    }}
                                    className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded-lg border border-gray-200 transition-colors"
                                >
                                    💾 Guardar como Plantilla
                                </button>
                            </div>
                        </div>

                        <textarea
                            rows={15}
                            value={formData.instructions}
                            onChange={(e) => setFormData({ ...formData, instructions: e.target.value })}
                            placeholder="Define aquí la personalidad, misión y reglas del agente..."
                            className="w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-purple-500/20 outline-none font-mono text-sm bg-gray-50"
                        />
                        <p className="text-xs text-gray-500">Define aquí la personalidad, misión y reglas del agente.</p>
                    </section>
                </div>

                {/* Right Column: AI Config */}
                <div className="space-y-6">
                    {/* LLM Config */}
                    <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                        <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                            <Brain size={16} /> Modelo de Lenguaje (LLM)
                        </h3>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Proveedor</label>
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
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Modelo</label>
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
                                        <option value="models/gemini-2.0-flash">Gemini 2.0 Flash</option>
                                        <option value="models/gemini-2.0-flash-lite">Gemini 2.0 Flash Lite</option>
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
                    </section>

                    {/* TTS Config */}
                    <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                        <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                            <Speaker size={16} /> Voz (TTS)
                        </h3>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Proveedor</label>
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
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Modelo</label>
                            <input
                                type="text"
                                value={aiConfig.tts_model}
                                onChange={(e) => setAiConfig({ ...aiConfig, tts_model: e.target.value })}
                                className="w-full px-3 py-2 border rounded-lg"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Voice ID</label>
                            <input
                                type="text"
                                value={aiConfig.tts_voice}
                                onChange={(e) => setAiConfig({ ...aiConfig, tts_voice: e.target.value })}
                                className="w-full px-3 py-2 border rounded-lg font-mono text-xs"
                            />
                        </div>
                    </section>

                    {/* STT Config */}
                    <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
                        <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                            <Mic size={16} /> Transcripción (STT)
                        </h3>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Proveedor</label>
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
                            <label className="block text-sm font-medium text-gray-700 mb-1">Modelo</label>
                            <input
                                type="text"
                                value={aiConfig.stt_model}
                                onChange={(e) => setAiConfig({ ...aiConfig, stt_model: e.target.value })}
                                className="w-full px-3 py-2 border rounded-lg"
                            />
                        </div>
                    </section>
                </div>
            </div>
        </div>
    );
};

export default AgentFormView;
