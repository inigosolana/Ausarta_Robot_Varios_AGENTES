import React, { useState, useEffect } from 'react';
import { Save, Phone, Loader2, Bot, Mic, Speaker, Brain } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { apiFetch } from '../lib/apiFetch';

const API_URL = import.meta.env.VITE_API_URL || window.location.origin + '/api' || 'http://localhost:8001/api';

interface AgentConfig {
  id?: string;
  name: string;
  useCase: string;
  description: string;
  instructions: string;
  greeting: string;
  tipo_resultados?: string;
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
  const { t } = useTranslation();
  const [agent, setAgent] = useState<AgentConfig>({
    name: '',
    useCase: '',
    description: '',
    instructions: '',
    greeting: ''
  });

  const [templates, setTemplates] = useState<PromptTemplate[]>([]);

  const [aiConfig, setAiConfig] = useState<AIConfig>({
    llm_provider: 'groq',
    llm_model: 'llama-3.3-70b-versatile',
    tts_provider: 'cartesia',
    tts_model: 'sonic-multilingual',
    tts_voice: 'b5aa8098-49ef-475d-89b0-c9262ecf33fd',
    stt_provider: 'deepgram',
    stt_model: 'nova-2',
    language: 'es'
  });

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  // Call Dialog State
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
        const agents = await agentRes.json();
        if (agents.length > 0) setAgent(agents[0]);
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

  const handleSave = async () => {
    try {
      setIsSaving(true);

      // Save Agent Config
      const agentPromise = fetch(`${API_URL}/agents/1`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agent)
      });

      // Save AI Config
      const aiPromise = fetch(`${API_URL}/ai/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(aiConfig)
      });

      const [agentRes, aiRes] = await Promise.all([agentPromise, aiPromise]);

      if (agentRes.ok && aiRes.ok) {
        alert('✅ ' + t('Configuration saved successfully!'));
      } else {
        alert('❌ ' + t('Error saving configuration'));
      }
    } catch (error) {
      console.error('Error saving:', error);
      alert(t('Error saving configuration'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleMakeCall = async () => {
    if (!phoneNumber || phoneNumber.length < 5) {
      alert('Número inválido');
      return;
    }

    try {
      setIsCalling(true);
      const response = await apiFetch('/api/calls/outbound', {
        method: 'POST',
        body: JSON.stringify({
          agentId: '1',
          phoneNumber: phoneNumber,
          agentName: agent.name
        })
      });

      const data = await response.json().catch(() => ({}));
      if (response.ok) {
        alert(`✅ Llamada iniciada! Sala: ${data.roomName}`);
        setShowCallDialog(false);
        // onStartCall(); // Deshabilitamos el overlay de "Live Call" porque es engañoso para llamadas telefónicas
      } else {
        const d = data.detail;
        const msg = Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg || '').join(' ') : (d || 'Error');
        alert(`❌ Error: ${msg}`);
      }
    } catch (error) {
      alert('Error de conexión con el backend');
    } finally {
      setIsCalling(false);
    }
  };

  if (isLoading) return (
    <div className="space-y-6 max-w-4xl mx-auto pb-20 animate-pulse">
      <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm flex justify-between items-center">
        <div className="space-y-2">
          <div className="h-6 bg-gray-200 rounded w-48" />
          <div className="h-3 bg-gray-100 rounded w-64" />
        </div>
        <div className="flex gap-3">
          <div className="h-10 bg-gray-100 rounded-lg w-36" />
          <div className="h-10 bg-gray-200 rounded-lg w-40" />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 space-y-6">
          <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
            <div className="h-5 bg-gray-200 rounded w-40" />
            <div className="grid grid-cols-2 gap-4">
              <div className="h-10 bg-gray-100 rounded-lg" />
              <div className="h-10 bg-gray-100 rounded-lg" />
            </div>
            <div className="h-10 bg-gray-100 rounded-lg" />
            <div className="h-16 bg-gray-100 rounded-lg" />
          </div>
          <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
            <div className="h-5 bg-gray-200 rounded w-48" />
            <div className="h-64 bg-gray-50 rounded-lg" />
          </div>
        </div>
        <div className="space-y-6">
          {[1, 2, 3].map(i => (
            <div key={i} className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
              <div className="h-4 bg-gray-200 rounded w-32" />
              <div className="h-10 bg-gray-100 rounded-lg" />
              <div className="h-10 bg-gray-100 rounded-lg" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <div className="space-y-6 max-w-4xl mx-auto pb-20">
      <header className="flex justify-between items-center bg-white p-6 rounded-xl border border-gray-100 shadow-sm">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">{agent.name || (t('Voice Agents') + ' Agent')}</h1>
            {agent.tipo_resultados && (
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${agent.tipo_resultados === 'ENCUESTA_NUMERICA' ? 'bg-green-50 text-green-700 border-green-200' :
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
          <p className="text-gray-500 text-sm">{t('AI Models Description')}</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setShowCallDialog(true)}
            className="flex items-center gap-2 px-4 py-2 bg-green-500 text-white font-medium rounded-lg hover:bg-green-600 transition-colors"
          >
            <Phone size={18} />
            {t('Test Call')}
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-2 px-4 py-2 bg-black text-white font-medium rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-50"
          >
            {isSaving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />}
            {t('Save Changes')}
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Columna Izquierda: Detalles del Agente */}
        <div className="md:col-span-2 space-y-6">
          {/* General Info */}
          <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
            <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
              <Bot size={20} className="text-blue-500" />
              {t('Agent Identity')}
            </h3>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Agent Name')}</label>
                <input
                  type="text"
                  value={agent.name}
                  onChange={(e) => setAgent({ ...agent, name: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Use Case')}</label>
                <input
                  type="text"
                  value={agent.useCase}
                  onChange={(e) => setAgent({ ...agent, useCase: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Initial Greeting')}</label>
              <input
                type="text"
                value={agent.greeting}
                onChange={(e) => setAgent({ ...agent, greeting: e.target.value })}
                placeholder="Hola, soy..."
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none"
              />
              <p className="text-xs text-gray-400 mt-1">{t('Initial Greeting Hint')}</p>
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-1">{t('Description')}</label>
              <textarea
                rows={2}
                value={agent.description}
                onChange={(e) => setAgent({ ...agent, description: e.target.value })}
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500/20 outline-none resize-none"
              />
            </div>
          </section>

          {/* Instructions */}
          <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                <Brain size={20} className="text-purple-500" />
                {t('Instructions (Prompt)')}
              </h3>

              <div className="flex items-center gap-2">
                {/* Selector de Templates */}
                <select
                  className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-gray-50 max-w-[150px]"
                  onChange={(e) => {
                    const template = templates.find(t => t.id === Number(e.target.value));
                    if (template) {
                      if (confirm(t('Replace instructions with this template?'))) {
                        setAgent({ ...agent, instructions: template.content });
                      }
                    }
                  }}
                  value=""
                >
                  <option value="" disabled>{t('Load Template...')}</option>
                  {templates.map(t => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>

                <button
                  onClick={async () => {
                    const name = prompt(t('Name for the new template:'));
                    if (name) {
                      try {
                        const res = await fetch(`${API_URL}/prompts`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            name,
                            description: 'Creado desde el editor',
                            content: agent.instructions
                          })
                        });
                        if (res.ok) {
                          alert(t('Template saved!'));
                          loadData(); // Recargar templates
                        }
                      } catch (e) {
                        alert(t('Error saving template'));
                      }
                    }
                  }}
                  className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded-lg border border-gray-200 transition-colors"
                >
                  {t('Save as Template')}
                </button>
              </div>
            </div>

            <div className="relative">
              <textarea
                rows={15}
                value={agent.instructions}
                onChange={(e) => setAgent({ ...agent, instructions: e.target.value })}
                className="w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-purple-500/20 outline-none font-mono text-sm bg-gray-50"
              />
              <p className="text-xs text-gray-500 mt-2">{t('Prompt Hint')}</p>
            </div>
          </section>
        </div>

        {/* Columna Derecha: Configuración AI */}
        <div className="space-y-6">

          {/* LLM Config */}
          <section className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm space-y-4">
            <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
              <Brain size={16} /> {t('Language Model (LLM)')}
            </h3>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('Provider')}</label>
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
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('Model')}</label>
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
              <Speaker size={16} /> {t('Voice (TTS)')}
            </h3>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('Provider')}</label>
              <select
                value={aiConfig.tts_provider}
                onChange={(e) => setAiConfig({ ...aiConfig, tts_provider: e.target.value })}
                className="w-full px-3 py-2 border rounded-lg bg-gray-50"
              >
                <option value="cartesia">Cartesia (Sonic)</option>
                <option value="openai">OpenAI TTS</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('Model')}</label>
              <input
                type="text"
                value={aiConfig.tts_model}
                onChange={(e) => setAiConfig({ ...aiConfig, tts_model: e.target.value })}
                className="w-full px-3 py-2 border rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('Voice ID')}</label>
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
              <Mic size={16} /> {t('Transcription (STT)')}
            </h3>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('Provider')}</label>
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
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('Model')}</label>
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

      {/* Diálogo para llamar */}
      {showCallDialog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 shadow-2xl max-w-md w-full mx-4">
            <h3 className="text-lg font-bold text-gray-900 mb-2">{t('Test Agent')}</h3>
            <p className="text-sm text-gray-500 mb-4">
              {t('Call your phone to test')} <strong>{agent.name}</strong>
            </p>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-semibold text-gray-800 mb-2">{t('Your phone number')}</label>
                <input
                  type="tel"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)}
                  placeholder="+34600123456"
                  className="w-full h-10 px-4 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 transition-all font-mono"
                  disabled={isCalling}
                />
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => setShowCallDialog(false)}
                  className="flex-1 py-2.5 bg-gray-200 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-300 transition-colors"
                  disabled={isCalling}
                >
                  {t('Cancel')}
                </button>
                <button
                  onClick={handleMakeCall}
                  className="flex-1 py-2.5 bg-green-500 text-white text-sm font-medium rounded-lg hover:bg-green-600 transition-colors shadow-sm flex items-center justify-center gap-2"
                  disabled={isCalling}
                >
                  {isCalling ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      {t('Calling...')}
                    </>
                  ) : (
                    <>
                      <Phone size={16} />
                      {t('Call Now')}
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};

export default VoiceAgentsView;
