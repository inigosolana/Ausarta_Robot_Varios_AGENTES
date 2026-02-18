import React, { useState, useEffect } from 'react';
import { Save, Phone, Loader2, Bot, Mic, Speaker, Brain } from 'lucide-react';

const API_URL = import.meta.env.VITE_API_URL || window.location.origin + '/api' || 'http://localhost:8001/api';

interface AgentConfig {
  id?: string;
  name: string;
  useCase: string;
  description: string;
  instructions: string;
  greeting: string;
}

interface AIConfig {
  llm_provider: string;
  llm_model: string;
  tts_provider: string;
  tts_model: string;
  tts_voice: string;
  stt_provider: string;
  stt_model: string;
  language: string;
}

interface PromptTemplate {
  id: number;
  name: string;
  description: string;
  content: string;
}

const VoiceAgentsView: React.FC<{ onStartCall: () => void }> = ({ onStartCall }) => {
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  // Default empty agent for creation/fallback
  const emptyAgent: AgentConfig = {
    name: 'Nuevo Agente',
    useCase: 'General',
    description: '',
    instructions: 'Eres un asistente útil.',
    greeting: 'Hola, ¿en qué puedo ayudarte?'
  };

  const selectedAgent = agents.find(a => a.id === selectedAgentId) || agents[0] || emptyAgent;

  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [aiConfig, setAiConfig] = useState<AIConfig>({
    llm_provider: 'groq',
    llm_model: 'llama-3.3-70b-versatile',
    tts_provider: 'cartesia',
    tts_model: 'sonic-multilingual',
    tts_voice: 'fb926b21-4d92-411a-85d0-9d06859e2171',
    stt_provider: 'deepgram',
    stt_model: 'nova-2',
    language: 'es'
  });

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [showCallDialog, setShowCallDialog] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState('+34');
  const [isCalling, setIsCalling] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setIsLoading(true);
      const [agentRes, aiRes, templatesRes] = await Promise.all([
        fetch(`${API_URL}/agents`),
        fetch(`${API_URL}/ai/config`),
        fetch(`${API_URL}/prompts`)
      ]);

      if (agentRes.ok) {
        const agentsData = await agentRes.json();
        setAgents(agentsData);
        if (agentsData.length > 0 && !selectedAgentId) {
          setSelectedAgentId(agentsData[0].id);
        }
      }

      if (aiRes.ok) {
        const aiData = await aiRes.json();
        if (Object.keys(aiData).length > 0) setAiConfig(aiData);
      }

      if (templatesRes.ok) {
        setTemplates(await templatesRes.json());
      }
    } catch (error) {
      console.error('Error loading data:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateAgent = async () => {
    try {
      setIsSaving(true);
      const res = await fetch(`${API_URL}/agents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(emptyAgent)
      });
      if (res.ok) {
        const newAgent = await res.json();
        newAgent.id = str(newAgent.id); // Ensure string ID
        setAgents([...agents, newAgent]);
        setSelectedAgentId(newAgent.id);
        alert('✨ Agente creado');
      }
    } catch (e) {
      console.error(e);
      alert('Error al crear agente');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteAgent = async (id: string) => {
    if (!confirm('¿Seguro que quieres eliminar este agente?')) return;
    try {
      await fetch(`${API_URL}/agents/${id}`, { method: 'DELETE' });
      setAgents(agents.filter(a => a.id !== id));
      if (selectedAgentId === id) setSelectedAgentId(agents[0]?.id || null);
    } catch (e) {
      alert('Error al eliminar');
    }
  };

  // Helper to update local state of selected agent
  const updateSelectedAgent = (field: keyof AgentConfig, value: string) => {
    if (!selectedAgentId) return;
    setAgents(prev => prev.map(a =>
      a.id === selectedAgentId ? { ...a, [field]: value } : a
    ));
  };

  function str(id: any) { return String(id); } // Helper safe string

  const handleSave = async () => {
    if (!selectedAgentId) return;
    try {
      setIsSaving(true);

      // Save Agent Config
      const agentPromise = fetch(`${API_URL}/agents/${selectedAgentId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(selectedAgent)
      });

      // Save AI Config (Global)
      const aiPromise = fetch(`${API_URL}/ai/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(aiConfig)
      });

      const [agentRes, aiRes] = await Promise.all([agentPromise, aiPromise]);

      if (agentRes.ok && aiRes.ok) {
        alert('✅ Cambios guardados');
      } else {
        alert('❌ Error al guardar');
      }
    } catch (error) {
      console.error('Error saving:', error);
      alert('Error al guardar');
    } finally {
      setIsSaving(false);
    }
  };

  const handleMakeCall = async () => {
    if (!phoneNumber || phoneNumber.length < 5) return alert('Número inválido');
    try {
      setIsCalling(true);
      const response = await fetch(`${API_URL}/calls/outbound`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agentId: selectedAgent.id,
          phoneNumber: phoneNumber,
          agentName: selectedAgent.name
        }) // Backend should probably use agentId to fetch config
      });
      const data = await response.json();
      if (response.ok) {
        alert(`✅ Llamada iniciada! Sala: ${data.roomName}`);
        setShowCallDialog(false);
      } else {
        alert(`❌ Error: ${data.detail}`);
      }
    } catch (error) {
      alert('Error de conexión');
    } finally {
      setIsCalling(false);
    }
  };

  if (isLoading) return <div className="p-8 text-center text-gray-500">Cargando agentes...</div>;

  return (
    <div className="h-[calc(100vh-100px)] flex gap-6 pb-6">

      {/* SIDEBAR LISTA AGENTES */}
      <div className="w-64 bg-white rounded-xl border border-gray-100 flex flex-col overflow-hidden shrink-0">
        <div className="p-4 border-b border-gray-100 flex justify-between items-center bg-gray-50">
          <h3 className="font-bold text-gray-700">Mis Agentes</h3>
          <button onClick={handleCreateAgent} className="p-1 hover:bg-white rounded-full transition-colors" title="Crear Nuevo Agente">
            <Plus className="w-5 h-5 text-blue-600" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {agents.map(agent => (
            <div
              key={agent.id}
              onClick={() => setSelectedAgentId(agent.id!)}
              className={`p-3 rounded-lg cursor-pointer flex justify-between items-center group transition-all ${selectedAgentId === agent.id ? 'bg-blue-50 border-blue-200 shadow-sm' : 'hover:bg-gray-50 border border-transparent'}`}
            >
              <div className="truncate">
                <p className={`font-medium text-sm truncate ${selectedAgentId === agent.id ? 'text-blue-900' : 'text-gray-700'}`}>{agent.name}</p>
                <p className="text-xs text-gray-400 truncate">{agent.useCase}</p>
              </div>
              {agents.length > 1 && (
                <button
                  onClick={(e) => { e.stopPropagation(); handleDeleteAgent(agent.id!); }}
                  className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-600 text-gray-400 transition-opacity"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          ))}
          {agents.length === 0 && <p className="text-xs text-center text-gray-400 mt-4">No hay agentes.</p>}
        </div>
      </div>

      {/* CONTENIDO PRINCIPAL - EDITOR */}
      <div className="flex-1 overflow-y-auto space-y-6 pr-2">

        {/* HEADER */}
        <header className="flex justify-between items-center bg-white p-6 rounded-xl border border-gray-100 shadow-sm sticky top-0 z-10">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              {selectedAgent.name}
              <span className="text-xs text-gray-400 font-normal border border-gray-200 px-2 py-0.5 rounded-full">ID: {selectedAgent.id}</span>
            </h1>
            <p className="text-gray-500 text-sm">Editando configuración del agente</p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => setShowCallDialog(true)}
              className="flex items-center gap-2 px-4 py-2 bg-green-500 text-white font-medium rounded-lg hover:bg-green-600 transition-colors shadow-sm"
            >
              <Phone size={18} /> Pruebas
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-2 px-4 py-2 bg-black text-white font-medium rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-50 shadow-sm"
            >
              {isSaving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />}
              Guardar
            </button>
          </div>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Columna Izquierda: Detalles del Agente */}
          <div className="md:col-span-2 space-y-6">

            {/* Identity */}
            <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
              <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                <Bot size={20} className="text-blue-500" />
                Identidad y Rol
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-1">Nombre</label>
                  <input
                    type="text"
                    value={selectedAgent.name}
                    onChange={(e) => updateSelectedAgent('name', e.target.value)}
                    className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-1">Caso de Uso</label>
                  <input
                    type="text"
                    value={selectedAgent.useCase}
                    onChange={(e) => updateSelectedAgent('useCase', e.target.value)}
                    className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">Saludo Inicial</label>
                <input
                  type="text"
                  value={selectedAgent.greeting}
                  onChange={(e) => updateSelectedAgent('greeting', e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">Descripción Interna</label>
                <textarea
                  rows={1}
                  value={selectedAgent.description}
                  onChange={(e) => updateSelectedAgent('description', e.target.value)}
                  className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none resize-none"
                />
              </div>
            </section>

            {/* Instructions */}
            <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
              <div className="flex justify-between items-center">
                <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                  <Brain size={20} className="text-purple-500" />
                  Instrucciones del Sistema (Prompt)
                </h3>
                <div className="flex items-center gap-2">
                  <select
                    className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-gray-50 max-w-[150px]"
                    onChange={(e) => {
                      const template = templates.find(t => t.id === Number(e.target.value));
                      if (template && confirm('¿Sobrescribir prompt con plantilla?')) {
                        updateSelectedAgent('instructions', template.content);
                      }
                    }}
                    value=""
                  >
                    <option value="" disabled>📂 Cargar Plantilla...</option>
                    {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </div>
              </div>
              <textarea
                rows={15}
                value={selectedAgent.instructions}
                onChange={(e) => updateSelectedAgent('instructions', e.target.value)}
                className="w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-purple-500/20 outline-none font-mono text-sm bg-gray-50 leading-relaxed"
                placeholder="Eres un agente telefónico..."
              />
            </section>
          </div>

          {/* Columna Derecha: Configuración Global AI */}
          <div className="space-y-6">
            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-sm text-blue-800 flex items-start gap-2">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <p>Nota: La configuración de voz y modelos AI es global y compartida por todos los agentes por ahora.</p>
            </div>

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
                    const newProvider = e.target.value;
                    let defaultModel = 'llama-3.3-70b-versatile';
                    if (newProvider === 'google') defaultModel = 'models/gemini-1.5-flash';
                    if (newProvider === 'openai') defaultModel = 'gpt-4o';
                    if (newProvider === 'deepseek') defaultModel = 'deepseek-chat';
                    setAiConfig({ ...aiConfig, llm_provider: newProvider, llm_model: defaultModel });
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
                      <option value="gpt-4o">GPT-4o</option>
                      <option value="gpt-4o-mini">GPT-4o mini</option>
                      <option value="gpt-4-turbo">GPT-4 Turbo</option>
                    </>
                  ) : aiConfig.llm_provider === 'google' ? (
                    <>
                      <option value="models/gemini-2.0-flash">Gemini 2.0 Flash</option>
                      <option value="models/gemini-1.5-flash">Gemini 1.5 Flash</option>
                    </>
                  ) : aiConfig.llm_provider === 'deepseek' ? (
                    <>
                      <option value="deepseek-chat">DeepSeek-V3</option>
                      <option value="deepseek-reasoner">DeepSeek-R1</option>
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

          </div>
        </div>

        {/* Call Dialog */}
        {showCallDialog && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-white rounded-xl p-6 shadow-2xl max-w-md w-full mx-4">
              <h3 className="text-lg font-bold text-gray-900 mb-2">Probar {selectedAgent.name}</h3>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-semibold text-gray-800 mb-2">Tu número de teléfono</label>
                  <input
                    type="tel"
                    value={phoneNumber}
                    onChange={(e) => setPhoneNumber(e.target.value)}
                    placeholder="+34600123456"
                    className="w-full h-10 px-4 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none font-mono"
                    disabled={isCalling}
                  />
                </div>
                <div className="flex gap-3 pt-2">
                  <button
                    onClick={() => setShowCallDialog(false)}
                    className="flex-1 py-2.5 bg-gray-200 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-300"
                    disabled={isCalling}
                  >
                    Cancelar
                  </button>
                  <button
                    onClick={handleMakeCall}
                    className="flex-1 py-2.5 bg-green-500 text-white text-sm font-medium rounded-lg hover:bg-green-600 flex items-center justify-center gap-2"
                    disabled={isCalling}
                  >
                    {isCalling ? <Loader2 size={16} className="animate-spin" /> : <Phone size={16} />}
                    Llamar
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default VoiceAgentsView;
