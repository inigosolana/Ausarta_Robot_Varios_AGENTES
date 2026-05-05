import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Sparkles, Loader2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
}

const AssistantView: React.FC = () => {
    const { profile } = useAuth();
    const [messages, setMessages] = useState<Message[]>([
        {
            id: 'greeting',
            role: 'assistant',
            content: `¡Hola ${profile?.full_name?.split(' ')[0] || ''}! Soy Ausarta Copilot. Estoy aquí para ayudarte a analizar tus datos, crear agentes o usar la plataforma. ¿En qué te puedo ayudar hoy?`,
        }
    ]);
    const [inputMessage, setInputMessage] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const API_URL = import.meta.env.VITE_API_URL || window.location.origin;

    const quickActions = [
        "Resumen de hoy",
        "Ayuda con CRM",
        "Crear Agente"
    ];

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, isLoading]);

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

            if (!response.ok) {
                throw new Error('Network response was not ok');
            }

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
                content: "Lo siento, ha ocurrido un error al conectarme con mis sistemas. ¿Podrías intentar de nuevo más tarde?"
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="flex flex-col h-[calc(100vh-8rem)] bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 animate-fade-in overflow-hidden">
            {/* Header */}
            <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-gradient-to-r from-blue-600 to-indigo-600 flex items-center justify-center text-white shrink-0 shadow-sm">
                    <Sparkles size={20} />
                </div>
                <div>
                    <h2 className="text-lg font-bold text-gray-900 dark:text-white">Ausarta Copilot</h2>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Asistente Inteligente de Plataforma</p>
                </div>
            </div>

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
                {messages.map((message) => (
                    <div
                        key={message.id}
                        className={`flex gap-4 ${message.role === 'user' ? 'flex-row-reverse' : ''}`}
                    >
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${message.role === 'user'
                                ? 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
                                : 'bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400'
                            }`}>
                            {message.role === 'user' ? <User size={16} /> : <Bot size={16} />}
                        </div>

                        <div className={`max-w-[80%] rounded-2xl px-5 py-3.5 ${message.role === 'user'
                                ? 'bg-blue-600 text-white rounded-tr-sm shadow-md shadow-blue-500/10'
                                : 'bg-gray-100 dark:bg-gray-700/50 text-gray-800 dark:text-gray-100 rounded-tl-sm border border-gray-200 dark:border-gray-600'
                            }`}>
                            {/* Simple markdown-like rendering for standard text */}
                            <div
                                className="whitespace-pre-wrap leading-relaxed text-[15px]"
                                dangerouslySetInnerHTML={{ __html: message.content.replace(/\n/g, '<br/>') }}
                            />
                        </div>
                    </div>
                ))}

                {isLoading && (
                    <div className="flex gap-4">
                        <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400 flex items-center justify-center shrink-0">
                            <Bot size={16} />
                        </div>
                        <div className="max-w-[80%] rounded-2xl rounded-tl-sm px-5 py-4 bg-gray-100 dark:bg-gray-700/50 text-gray-800 dark:text-gray-100 border border-gray-200 dark:border-gray-600 flex items-center gap-2">
                            <Loader2 size={16} className="animate-spin text-blue-500" />
                            <span className="text-sm text-gray-500 dark:text-gray-400">Pensando...</span>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="p-4 bg-white dark:bg-gray-800 border-t border-gray-100 dark:border-gray-700">
                {/* Quick Actions */}
                {messages.length === 1 && (
                    <div className="flex flex-wrap gap-2 mb-4 justify-center">
                        {quickActions.map((action, idx) => (
                            <button
                                key={idx}
                                onClick={() => handleSendMessage(action)}
                                className="px-4 py-2 bg-gray-50 hover:bg-gray-100 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300 text-sm font-medium rounded-full border border-gray-200 dark:border-gray-600 transition-colors"
                            >
                                {action}
                            </button>
                        ))}
                    </div>
                )}

                <form
                    onSubmit={(e) => {
                        e.preventDefault();
                        handleSendMessage(inputMessage);
                    }}
                    className="flex gap-2 max-w-4xl mx-auto"
                >
                    <input
                        type="text"
                        value={inputMessage}
                        onChange={(e) => setInputMessage(e.target.value)}
                        placeholder="Pregunta o pide algo a Copilot..."
                        className="flex-1 h-12 px-5 rounded-full border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 focus:bg-white dark:focus:bg-gray-800 text-gray-900 dark:text-white text-[15px] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all shadow-sm"
                        disabled={isLoading}
                    />
                    <button
                        type="submit"
                        disabled={!inputMessage.trim() || isLoading}
                        className="w-12 h-12 rounded-full bg-blue-600 hover:bg-blue-700 text-white flex items-center justify-center transition-colors disabled:opacity-50 disabled:hover:bg-blue-600 shrink-0 shadow-md shadow-blue-500/20"
                    >
                        <Send size={20} className="ml-0.5" />
                    </button>
                </form>
            </div>
        </div>
    );
};

export default AssistantView;
