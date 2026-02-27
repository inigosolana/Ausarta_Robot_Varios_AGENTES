import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Sparkles, Loader2, X, MessageSquare, BotMessageSquare } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from 'react-i18next';

interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
}

interface AssistantPanelProps {
    isOpen: boolean;
    onClose: () => void;
}

const AssistantPanel: React.FC<AssistantPanelProps> = ({ isOpen, onClose }) => {
    const { profile } = useAuth();
    const { t } = useTranslation();
    const [messages, setMessages] = useState<Message[]>([
        {
            id: 'greeting',
            role: 'assistant',
            content: `${t('Hi', '¡Hola')} ${profile?.full_name?.split(' ')[0] || ''}! ${t('I am Ausarta Copilot. I am here to help you analyze your data, create agents, or use the platform. How can I help you today?', 'Soy Ausarta Copilot. Estoy aquí para ayudarte a analizar tus datos, crear agentes o usar la plataforma. ¿En qué te puedo ayudar hoy?')}`,
        }
    ]);
    const [inputMessage, setInputMessage] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const API_URL = import.meta.env.VITE_API_URL || window.location.origin;

    const quickActions = [
        { label: t("Today's Summary", "Resumen de hoy"), query: "Dáme un resumen de las llamadas de hoy" },
        { label: t("API Status", "Estado de APIs"), query: "¿Cómo están las integraciones y APIs?" },
        { label: t("CRM Help", "Ayuda con CRM"), query: "¿Cómo configuro mi CRM?" },
    ];

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        if (isOpen) {
            scrollToBottom();
        }
    }, [messages, isLoading, isOpen]);

    const handleSendMessage = async (text: string) => {
        if (!text.trim()) return;

        const newUserMessage: Message = {
            id: Date.now().toString(),
            role: 'user',
            content: text
        };

        setMessages(prev => [...prev, newUserMessage]);
        setInputMessage('');
        setIsLoading(true);

        try {
            const response = await fetch(`${API_URL}/api/assistant/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: text,
                    empresa_id: profile?.empresa_id,
                    user_id: profile?.id
                })
            });

            if (!response.ok) throw new Error('Network response was not ok');

            const data = await response.json();

            const newAssistantMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: data.response
            };

            setMessages(prev => [...prev, newAssistantMessage]);
        } catch (error) {
            console.error('Error communicating with Copilot:', error);
            const errorMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: t("Sorry, an error occurred while connecting to my systems. Could you try again later?", "Lo siento, ha ocurrido un error al conectarme con mis sistemas. ¿Podrías intentar de nuevo más tarde?")
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <aside
            className={`fixed top-0 right-0 h-full z-50 transition-all duration-300 ease-in-out flex flex-col
                ${isOpen ? 'translate-x-0 w-full sm:w-[400px]' : 'translate-x-full w-0'}
                bg-white/80 dark:bg-gray-900/80 backdrop-blur-xl border-l border-white/20 dark:border-gray-800/50 shadow-2xl overflow-hidden`}
        >
            {/* Header */}
            <div className="px-6 py-5 border-b border-gray-100 dark:border-gray-800/50 bg-white/40 dark:bg-gray-900/40 flex items-center justify-between shrink-0">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 flex items-center justify-center text-white shrink-0 shadow-lg shadow-blue-500/20">
                        <Sparkles size={20} />
                    </div>
                    <div>
                        <h2 className="text-base font-bold text-gray-900 dark:text-white leading-tight">Ausarta Copilot</h2>
                        <div className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
                            <p className="text-[11px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{t("Online", "En línea")}</p>
                        </div>
                    </div>
                </div>
                <button
                    onClick={onClose}
                    className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-full text-gray-400 dark:text-gray-500 transition-colors"
                >
                    <X size={20} />
                </button>
            </div>

            {/* Quick Actions at Top */}
            <div className={`px-4 py-3 bg-gray-50/50 dark:bg-gray-800/30 border-b border-gray-100 dark:border-gray-800/30 overflow-x-auto no-scrollbar ${messages.length > 2 && 'hidden'}`}>
                <div className="flex gap-2 w-max mx-auto px-2">
                    {quickActions.map((action, idx) => (
                        <button
                            key={idx}
                            onClick={() => handleSendMessage(action.query)}
                            className="px-3 py-1.5 whitespace-nowrap bg-white/80 dark:bg-gray-800/80 hover:bg-blue-50 dark:hover:bg-blue-900/20 text-blue-600 dark:text-blue-400 text-[12px] font-bold rounded-lg border border-blue-100 dark:border-blue-900/30 transition-all shadow-sm"
                        >
                            {action.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
                {messages.map((message) => (
                    <div
                        key={message.id}
                        className={`flex gap-3 ${message.role === 'user' ? 'flex-row-reverse' : ''}`}
                    >
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 shadow-sm ${message.role === 'user'
                            ? 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
                            : 'bg-gradient-to-br from-blue-600 to-blue-700 text-white'
                            }`}>
                            {message.role === 'user' ? <User size={14} /> : <Bot size={14} />}
                        </div>

                        <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 shadow-sm ${message.role === 'user'
                            ? 'bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 border border-gray-100 dark:border-gray-700'
                            : 'bg-blue-600 dark:bg-blue-700 text-white'
                            }`}>
                            <div
                                className="whitespace-pre-wrap leading-relaxed text-[14px]"
                                dangerouslySetInnerHTML={{ __html: message.content.replace(/\n/g, '<br/>') }}
                            />
                        </div>
                    </div>
                ))}

                {isLoading && (
                    <div className="flex gap-3">
                        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-600 to-blue-700 text-white flex items-center justify-center shrink-0 shadow-sm">
                            <Bot size={14} />
                        </div>
                        <div className="max-w-[85%] rounded-2xl px-4 py-3 bg-white dark:bg-gray-800 text-gray-400 dark:text-gray-500 border border-gray-100 dark:border-gray-700 flex items-center gap-2">
                            <span className="text-[13px] italic font-medium">{t("Copilot is thinking...", "Copilot está pensando...")}</span>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="p-4 bg-white/40 dark:bg-gray-900/40 border-t border-gray-100 dark:border-gray-800/50 shrink-0">
                <form
                    onSubmit={(e) => {
                        e.preventDefault();
                        handleSendMessage(inputMessage);
                    }}
                    className="flex gap-2 relative"
                >
                    <input
                        type="text"
                        value={inputMessage}
                        onChange={(e) => setInputMessage(e.target.value)}
                        placeholder={t("Ask Copilot anything...", "Pregunta algo a Copilot...")}
                        className="flex-1 h-11 px-4 pr-12 rounded-xl border border-gray-200 dark:border-gray-800 bg-white/50 dark:bg-gray-800/50 focus:bg-white dark:focus:bg-gray-800 text-gray-900 dark:text-white text-[14px] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all shadow-inner"
                        disabled={isLoading}
                    />
                    <button
                        type="submit"
                        disabled={!inputMessage.trim() || isLoading}
                        className="absolute right-1 top-1 w-9 h-9 rounded-lg bg-blue-600 hover:bg-blue-700 text-white flex items-center justify-center transition-all disabled:opacity-50 shadow-md shadow-blue-500/20"
                    >
                        <Send size={16} />
                    </button>
                </form>
                <p className="text-[10px] text-center text-gray-400 mt-3 uppercase tracking-tighter">
                    {t("Ausarta Voice AI Assistant", "Asistente AI de Ausarta Voice")}
                </p>
            </div>
        </aside>
    );
};

export default AssistantPanel;
