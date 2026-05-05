import React, { useState, useEffect } from 'react';
import { BarChart3, Globe, Cpu, Mic, Volume2, AlertTriangle, XCircle, Zap, Terminal, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';

const API_URL = import.meta.env.VITE_API_URL || window.location.origin + '/api' || 'http://localhost:8002/api';

const UsageView: React.FC = () => {
    const { profile, isRole, isPlatformOwner } = useAuth();
    const { t } = useTranslation();
    const [integrations, setIntegrations] = useState<any[]>([]);
    const [usage, setUsage] = useState<any>(null);
    const [alerts, setAlerts] = useState<any[]>([]);
    const [liveLimits, setLiveLimits] = useState<any>(null);
    const [sipLogs, setSipLogs] = useState<string[]>([]);
    const [isRefreshingLogs, setIsRefreshingLogs] = useState(false);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        loadData();
    }, [profile]);

    const loadSipLogs = async () => {
        try {
            setIsRefreshingLogs(true);
            const res = await fetch(`${API_URL}/logs/sip`);
            if (res.ok) {
                const data = await res.json();
                setSipLogs(data.logs || []);
            }
        } catch (e) {
            console.error("Error loading SIP logs:", e);
        } finally {
            setIsRefreshingLogs(false);
        }
    };

    const loadData = async () => {
        try {
            setIsLoading(true);
            const params = new URLSearchParams();

            if (!isPlatformOwner && profile?.empresa_id) {
                params.append('empresa_id', String(profile.empresa_id));
            }
            const queryParams = params.toString() ? `?${params.toString()}` : '';

            const [intRes, usageRes, limitsRes] = await Promise.all([
                fetch(`${API_URL}/dashboard/integrations`),
                fetch(`${API_URL}/dashboard/usage-stats${queryParams}`),
                fetch(`${API_URL}/ai/limits`)
            ]);

            if (intRes.ok) setIntegrations(await intRes.json());
            if (usageRes.ok) setUsage(await usageRes.json());
            if (limitsRes.ok) setLiveLimits(await limitsRes.json());

            // Fetch alerts specifically for this view too (or pass from props, but independent fetch is fine)
            const alertsRes = await fetch(`${API_URL}/alerts${queryParams}`);
            if (alertsRes.ok) setAlerts(await alertsRes.json());

            await loadSipLogs();

        } catch (error) {
            console.error('Error loading usage data:', error);
        } finally {
            setIsLoading(false);
        }
    };

    if (isLoading) return <div className="p-8 text-center text-gray-500">{t('Loading usage data...', 'Cargando datos de uso...')}</div>;

    return (
        <div className="space-y-8 animate-fade-in text-gray-900 dark:text-gray-100">
            {/* Header */}
            <div className="relative overflow-hidden p-8 rounded-3xl bg-gradient-to-br from-blue-600/10 to-purple-600/10 border border-blue-500/10 backdrop-blur-sm">
                <div className="flex items-center gap-4 relative z-10">
                    <div className="p-3 bg-blue-600 text-white rounded-2xl shadow-lg shadow-blue-500/30">
                        <BarChart3 size={32} />
                    </div>
                    <div>
                        <h2 className="text-4xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-purple-600 dark:from-blue-400 dark:to-purple-400">
                            {t('Usage and APIs', 'Uso y APIs')}
                        </h2>
                        <p className="text-gray-500 dark:text-gray-400 font-medium mt-1">
                            {t('Monitoring of external services and real consumption', 'Monitorización de servicios externos y consumo real')}
                        </p>
                    </div>
                </div>
                <div className="absolute -right-20 -top-20 w-64 h-64 bg-blue-500/5 rounded-full blur-3xl"></div>
                <div className="absolute -left-20 -bottom-20 w-64 h-64 bg-purple-500/5 rounded-full blur-3xl"></div>
            </div>

            {/* API Status Section */}
            <div className="backdrop-blur-md bg-white/70 dark:bg-gray-900/70 p-8 rounded-3xl border border-white/20 dark:border-gray-800/50 shadow-[0_8px_32px_0_rgba(31,38,135,0.07)]">
                <h3 className="text-xl font-bold mb-8 flex items-center gap-3">
                    <div className="p-2 bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-xl">
                        <Globe size={22} />
                    </div>
                    {t('Integration Status', 'Estado de Integraciones')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    {integrations.map((int, i) => (
                        <div key={i} className="group p-6 rounded-2xl border border-gray-100/50 dark:border-gray-800/50 bg-white/50 dark:bg-gray-800/30 hover:bg-white dark:hover:bg-gray-800 hover:shadow-xl hover:-translate-y-1 transition-all duration-300">
                            <div className="flex justify-between items-start mb-5">
                                <div className={`p-3 rounded-2xl shadow-sm ${int.active ? 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400' : 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400'}`}>
                                    {int.name.includes('LLM') && <Cpu size={24} />}
                                    {int.name.includes('TTS') && <Volume2 size={24} />}
                                    {int.name.includes('STT') && <Mic size={24} />}
                                    {int.name.includes('LiveKit') && <Globe size={24} />}
                                </div>
                                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white dark:bg-gray-900 shadow-inner">
                                    <span className={`w-2 h-2 rounded-full ${int.active ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`}></span>
                                    <span className={`text-[10px] font-black uppercase tracking-wider ${int.active ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                                        {int.active ? 'Online' : 'Offline'}
                                    </span>
                                </div>
                            </div>
                            <div className="space-y-1">
                                <div className="text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">{int.name}</div>
                                <div className="text-2xl font-black text-gray-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">{int.provider}</div>
                            </div>
                            <div className="mt-4 p-3 rounded-xl bg-gray-50/50 dark:bg-gray-900/50 border border-gray-100 dark:border-gray-800 font-mono text-[11px] text-gray-500 dark:text-gray-400 truncate">
                                {int.model || int.url || t('API Active', 'API Activa')}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Real usage metrics */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {[
                    { label: t('Total Tokens', 'Total Tokens'), value: usage?.total_tokens?.toLocaleString() || 0, icon: BarChart3, color: 'blue' },
                    { label: t('Total Minutes', 'Minutos Totales'), value: usage?.total_minutes?.toLocaleString() || 0, icon: Volume2, color: 'purple' },
                    { label: t('Used Models', 'Modelos Usados'), value: usage?.per_model_stats?.length || 0, icon: Zap, color: 'orange' }
                ].map((stat, i) => (
                    <div key={i} className="backdrop-blur-md bg-white/70 dark:bg-gray-900/70 p-8 rounded-3xl border border-white/20 dark:border-gray-800/50 shadow-lg flex flex-col items-center justify-center text-center group hover:scale-[1.02] transition-transform duration-300">
                        <div className={`w-14 h-14 bg-${stat.color}-50 dark:bg-${stat.color}-900/20 text-${stat.color}-600 dark:text-${stat.color}-400 rounded-2xl flex items-center justify-center mb-4 shadow-inner group-hover:rotate-6 transition-transform`}>
                            <stat.icon size={28} />
                        </div>
                        <div className="text-4xl font-black text-gray-900 dark:text-white mb-1">
                            {stat.value}
                        </div>
                        <h4 className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-[0.2em]">{stat.label}</h4>
                    </div>
                ))}
            </div>

            {/* Breakdown per Model Table */}
            <div className="backdrop-blur-md bg-white/70 dark:bg-gray-900/70 rounded-3xl border border-white/20 dark:border-gray-800/50 shadow-lg overflow-hidden">
                <div className="px-8 py-5 border-b border-gray-100/50 dark:border-gray-800/50 bg-gray-50/30 dark:bg-gray-800/20">
                    <h3 className="text-sm font-black text-gray-800 dark:text-gray-200 flex items-center gap-3 tracking-widest uppercase">
                        <div className="p-1.5 bg-blue-50 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400 rounded-lg">
                            <Cpu size={16} />
                        </div>
                        {t('CONSUMPTION BREAKDOWN PER MODEL', 'DESGLOSE DE CONSUMO POR MODELO')}
                    </h3>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                        <thead>
                            <tr className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-[0.2em] border-b border-gray-100/50 dark:border-gray-800/50">
                                <th className="px-8 py-4">{t('Model / Engine', 'Modelo / Motor')}</th>
                                <th className="px-8 py-4">{t('Calls', 'Llamadas')}</th>
                                <th className="px-8 py-4">{t('Total Tokens', 'Tokens Totales')}</th>
                                <th className="px-8 py-4">{t('Time (Min)', 'Tiempo (Min)')}</th>
                                <th className="px-8 py-4">{t('Efficiency (T/min)', 'Eficiencia (T/min)')}</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100/50 dark:divide-gray-800/50">
                            {usage?.per_model_stats?.map((stat: any, idx: number) => (
                                <tr key={idx} className="hover:bg-gray-50/50 transition-colors">
                                    <td className="px-6 py-4">
                                        <div className="flex items-center gap-2">
                                            <div className={`w-2 h-2 rounded-full ${stat.llm_model.includes('Google') ? 'bg-blue-400' :
                                                stat.llm_model.includes('Groq') ? 'bg-orange-400' :
                                                    stat.llm_model.includes('DeepSeek') ? 'bg-blue-700' :
                                                        'bg-green-400'
                                                }`}></div>
                                            <span className="text-sm font-bold text-gray-900">{stat.llm_model}</span>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4 text-sm text-gray-600 font-mono">{stat.calls}</td>
                                    <td className="px-6 py-4 text-sm font-bold text-blue-600 font-mono">{stat.tokens.toLocaleString()}</td>
                                    <td className="px-6 py-4 text-sm text-gray-600 font-mono">{Math.round(stat.seconds / 60)} {t('min', 'min')}</td>
                                    <td className="px-6 py-4 text-sm text-gray-400 font-mono">
                                        {stat.seconds > 0 ? Math.round(stat.tokens / (stat.seconds / 60)) : 0}
                                    </td>
                                </tr>
                            ))}
                            {(!usage?.per_model_stats || usage.per_model_stats.length === 0) && (
                                <tr>
                                    <td colSpan={5} className="px-6 py-8 text-center text-gray-400 text-sm italic">
                                        {t('No detailed consumption data available yet.', 'No hay datos de consumo detallados todavía.')}
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Live Quota Status - Superadmin ONLY */}
            {isRole('superadmin') && liveLimits && (
                <div className="backdrop-blur-md bg-white/70 dark:bg-gray-900/70 p-8 rounded-3xl border border-white/20 dark:border-gray-800/50 shadow-xl animate-in fade-in slide-in-from-bottom-2">
                    <h3 className="text-xl font-bold mb-8 flex items-center gap-3">
                        <div className="p-2 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400 rounded-xl">
                            <Zap size={22} />
                        </div>
                        {t('Real-Time Capacities and Limits (System)', 'Capacidades y Límites en Tiempo Real (Sistema)')}
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {/* Groq Card with Model Selector */}
                        {liveLimits.groq_models && (
                            <div className="lg:col-span-2 p-6 rounded-2xl bg-gray-50/50 dark:bg-gray-800/30 border border-gray-100/50 dark:border-gray-800/50 hover:bg-white dark:hover:bg-gray-800 transition-all duration-300">
                                <div className="flex items-center justify-between mb-6">
                                    <div className="flex items-center gap-3">
                                        <div className="p-2 bg-white dark:bg-gray-900 rounded-xl shadow-sm">
                                            <img src="https://groq.com/favicon.ico" className="w-6 h-6 rounded" alt="Groq" />
                                        </div>
                                        <span className="font-black text-gray-900 dark:text-gray-100 uppercase text-xs tracking-widest">Groq Quotas Per Model</span>
                                    </div>
                                    <span className="text-[10px] bg-blue-500 text-white px-3 py-1 rounded-full font-black tracking-wider uppercase animate-pulse">Live</span>
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                                    {Object.entries(liveLimits.groq_models).map(([model, data]: [string, any]) => (
                                        <div key={model} className="bg-white/50 dark:bg-gray-900/40 p-5 rounded-2xl border border-white/40 dark:border-gray-800/40 shadow-sm hover:shadow-md transition-all">
                                            <div className="text-[11px] font-black text-blue-600 dark:text-blue-400 truncate mb-4 uppercase tracking-wider">{model}</div>
                                            <div className="space-y-4">
                                                <div className="space-y-2">
                                                    <div className="flex justify-between text-[11px] font-bold">
                                                        <span className="text-gray-500 dark:text-gray-400 uppercase tracking-tighter">{t('Tokens (TPM):', 'Tokens (TPM):')}</span>
                                                        <span className="font-mono">
                                                            <span className="text-blue-600 dark:text-blue-400 font-black">{Number(data.tokens_remaining).toLocaleString()}</span>
                                                            <span className="text-[10px] text-gray-400"> / {data.tokens_limit ? Number(data.tokens_limit).toLocaleString() : 'Limit'}</span>
                                                        </span>
                                                    </div>
                                                    <div className="w-full bg-gray-100 dark:bg-gray-800 rounded-full h-1.5 overflow-hidden">
                                                        <div
                                                            className="bg-gradient-to-r from-blue-400 to-blue-600 h-1.5 rounded-full transition-all duration-1000"
                                                            style={{ width: data.tokens_limit ? `${Math.min(100, (data.tokens_remaining / data.tokens_limit) * 100)}%` : '100%' }}
                                                        ></div>
                                                    </div>
                                                </div>
                                                <div className="space-y-2">
                                                    <div className="flex justify-between text-[11px] font-bold">
                                                        <span className="text-gray-500 dark:text-gray-400 uppercase tracking-tighter">{t('Requests (RPM):', 'Peticiones (RPM):')}</span>
                                                        <span className="font-mono">
                                                            <span className="text-gray-800 dark:text-gray-200 font-black">{data.requests_remaining}</span>
                                                            <span className="text-[10px] text-gray-400"> / {data.requests_limit || 'Limit'}</span>
                                                        </span>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* OpenAI Card */}
                        {liveLimits.openai && liveLimits.openai.active && (
                            <div className="p-6 rounded-2xl bg-gray-50/50 dark:bg-gray-800/30 border border-gray-100/50 dark:border-gray-800/50 hover:bg-white dark:hover:bg-gray-800 transition-all">
                                <div className="flex items-center justify-between mb-6">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 bg-black dark:bg-gray-200 rounded-lg flex items-center justify-center text-white dark:text-black font-black">O</div>
                                        <span className="font-black text-gray-900 dark:text-gray-100 uppercase text-xs tracking-widest">OpenAI Limits</span>
                                    </div>
                                </div>
                                <div className="space-y-5">
                                    <div className="space-y-2">
                                        <div className="flex justify-between items-center text-[11px] font-bold">
                                            <span className="text-gray-500 dark:text-gray-400 uppercase tracking-tighter">{t('Tokens (TPM):', 'Tokens (TPM):')}</span>
                                            <span className="font-mono font-black text-green-600 dark:text-green-400">
                                                {liveLimits.openai.tokens_remaining ? Number(liveLimits.openai.tokens_remaining).toLocaleString() : '---'}
                                            </span>
                                        </div>
                                        <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden">
                                            <div
                                                className="bg-green-500 h-1.5 transition-all duration-1000"
                                                style={{ width: liveLimits.openai.tokens_limit ? `${(liveLimits.openai.tokens_remaining / liveLimits.openai.tokens_limit) * 100}%` : '100%' }}
                                            ></div>
                                        </div>
                                    </div>
                                    <div className="flex justify-between items-center text-[11px] font-bold border-t border-gray-100 dark:border-gray-800 pt-4">
                                        <span className="text-gray-500 dark:text-gray-400 uppercase tracking-tighter">{t('Requests (RPM):', 'Peticiones (RPM):')}</span>
                                        <span className="font-mono font-black text-gray-800 dark:text-gray-200">
                                            {liveLimits.openai.requests_remaining || '---'}
                                        </span>
                                    </div>
                                    <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-2xl border border-green-100 dark:border-green-800/30 text-[10px] text-green-700 dark:text-green-400 text-center font-bold uppercase tracking-wider">
                                        {liveLimits.openai.info}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* DeepSeek Card */}
                        {liveLimits.deepseek && liveLimits.deepseek.active && (
                            <div className="p-6 rounded-2xl bg-gray-50/50 dark:bg-gray-800/30 border border-gray-100/50 dark:border-gray-800/50 hover:bg-white dark:hover:bg-gray-800 transition-all">
                                <div className="flex items-center justify-between mb-6">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center text-white font-black">DS</div>
                                        <span className="font-black text-gray-900 dark:text-gray-100 uppercase text-xs tracking-widest">DeepSeek Limits</span>
                                    </div>
                                    <span className="text-[10px] bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 px-3 py-1 rounded-full font-black tracking-wider">V3 / R1</span>
                                </div>
                                <div className="space-y-5">
                                    <div className="space-y-2">
                                        <div className="flex justify-between items-center text-[11px] font-bold">
                                            <span className="text-gray-500 dark:text-gray-400 uppercase tracking-tighter">{t('Tokens (TPM):', 'Tokens (TPM):')}</span>
                                            <span className="font-mono font-black text-blue-600 dark:text-blue-400">
                                                {liveLimits.deepseek.tokens_remaining ? Number(liveLimits.deepseek.tokens_remaining).toLocaleString() : '---'}
                                            </span>
                                        </div>
                                        <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden">
                                            <div
                                                className="bg-blue-500 h-1.5 transition-all duration-1000"
                                                style={{ width: liveLimits.deepseek.tokens_limit ? `${(liveLimits.deepseek.tokens_remaining / liveLimits.deepseek.tokens_limit) * 100}%` : '100%' }}
                                            ></div>
                                        </div>
                                    </div>
                                    <div className="flex justify-between items-center text-[11px] font-bold border-t border-gray-100 dark:border-gray-800 pt-4">
                                        <span className="text-gray-500 dark:text-gray-400 uppercase tracking-tighter">{t('Requests (RPM):', 'Peticiones (RPM):')}</span>
                                        <span className="font-mono font-black text-gray-800 dark:text-gray-200">
                                            {liveLimits.deepseek.requests_remaining || '---'}
                                        </span>
                                    </div>
                                    <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-2xl border border-blue-100 dark:border-blue-800/30 text-[10px] text-blue-700 dark:text-blue-400 text-center font-bold uppercase tracking-wider">
                                        {liveLimits.deepseek.info}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Deepgram Card */}
                        {liveLimits.deepgram && (
                            <div className="p-6 rounded-2xl bg-gray-50/50 dark:bg-gray-800/30 border border-gray-100/50 dark:border-gray-800/50 hover:bg-white dark:hover:bg-gray-800 transition-all">
                                <div className="flex items-center justify-between mb-6">
                                    <div className="flex items-center gap-3">
                                        <div className="p-2 bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded-xl shadow-sm">
                                            <Mic size={20} />
                                        </div>
                                        <span className="font-black text-gray-900 dark:text-gray-100 uppercase text-xs tracking-widest">Deepgram Balance</span>
                                    </div>
                                </div>
                                <div className="space-y-6">
                                    {liveLimits.deepgram.balances?.map((b: any, i: number) => (
                                        <div key={i} className="flex flex-col gap-2">
                                            <div className="text-[10px] text-gray-400 dark:text-gray-500 font-black uppercase tracking-widest leading-none">
                                                {b.units === 'USD' ? t('Available Credits', 'Créditos Disponibles') : t('Balance', 'Balance')}
                                            </div>
                                            <div className="text-4xl font-black text-gray-900 dark:text-white tracking-tighter">
                                                {b.units === 'USD' ? `$${Number(b.amount).toFixed(2)}` : `${b.amount} ${b.units}`}
                                            </div>
                                        </div>
                                    ))}
                                    <div className="text-[10px] text-gray-500 dark:text-gray-400 italic bg-white/50 dark:bg-gray-900/50 p-4 rounded-2xl border border-gray-100 dark:border-gray-800 font-medium">
                                        {t('This balance is used for real-time transcription (STT).', 'Este saldo se usa para transcripción en tiempo real (STT).')}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* ElevenLabs Card */}
                        {liveLimits.elevenlabs && liveLimits.elevenlabs.active && (
                            <div className="p-6 rounded-2xl bg-gray-50/50 dark:bg-gray-800/30 border border-gray-100/50 dark:border-gray-800/50 hover:bg-white dark:hover:bg-gray-800 transition-all">
                                <div className="flex items-center justify-between mb-6">
                                    <div className="flex items-center gap-3">
                                        <div className="p-2 bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 rounded-xl shadow-sm">
                                            <Volume2 size={20} />
                                        </div>
                                        <span className="font-black text-gray-900 dark:text-gray-100 uppercase text-xs tracking-widest">ElevenLabs</span>
                                    </div>
                                    <span className="text-[10px] bg-purple-500 text-white px-3 py-1 rounded-full font-black tracking-wider uppercase">Characters</span>
                                </div>
                                <div className="space-y-4">
                                    <div className="flex justify-between items-center text-[11px] font-bold">
                                        <span className="text-gray-500 dark:text-gray-400 uppercase tracking-tighter">{t('Remaining:', 'Sobrantes:')}</span>
                                        <span className="font-mono font-black text-purple-600 dark:text-purple-400">
                                            {Number(liveLimits.elevenlabs.characters_remaining).toLocaleString()}
                                        </span>
                                    </div>
                                    <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2 overflow-hidden shadow-inner">
                                        <div
                                            className="bg-gradient-to-r from-purple-400 to-purple-600 h-2 transition-all duration-1000"
                                            style={{ width: `${(liveLimits.elevenlabs.characters_remaining / liveLimits.elevenlabs.characters_limit) * 100}%` }}
                                        ></div>
                                    </div>
                                    <div className="text-[10px] text-gray-400 dark:text-gray-500 text-center font-black uppercase tracking-widest">
                                        {t('Total Plan Cap:', 'Capacidad Total Plan:')} {Number(liveLimits.elevenlabs.characters_limit / 1000).toLocaleString()}k
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Cartesia Card */}
                        {liveLimits.cartesia && liveLimits.cartesia.active && (
                            <div className="p-6 rounded-2xl bg-gray-50/50 dark:bg-gray-800/30 border border-gray-100/50 dark:border-gray-800/50 hover:bg-white dark:hover:bg-gray-800 transition-all">
                                <div className="flex items-center justify-between mb-6">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 bg-purple-500 rounded-lg flex items-center justify-center text-white font-black">C</div>
                                        <span className="font-black text-gray-900 dark:text-gray-100 uppercase text-xs tracking-widest">Cartesia TTS</span>
                                    </div>
                                </div>
                                <div className="space-y-5">
                                    <div className="text-[11px] text-gray-700 dark:text-gray-300 font-bold bg-white/50 dark:bg-gray-900/50 p-4 rounded-2xl border border-gray-100 dark:border-gray-800">
                                        {liveLimits.cartesia.info}
                                    </div>
                                    <a
                                        href={liveLimits.cartesia.dashboard_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex items-center justify-center gap-2 w-full py-3 px-4 bg-gray-900 dark:bg-white text-white dark:text-black rounded-2xl font-black text-xs uppercase tracking-widest hover:bg-black dark:hover:bg-gray-100 transition-colors shadow-lg shadow-gray-900/20 dark:shadow-white/5"
                                    >
                                        <Zap size={14} />
                                        {t('Open Cartesia Dashboard', 'Abrir Dashboard de Cartesia')}
                                    </a>
                                </div>
                            </div>
                        )}

                        {/* Google Card */}
                        {liveLimits.google && liveLimits.google.active && (
                            <div className="p-6 rounded-2xl bg-gray-50/50 dark:bg-gray-800/30 border border-gray-100/50 dark:border-gray-800/50 hover:bg-white dark:hover:bg-gray-800 transition-all">
                                <div className="flex items-center justify-between mb-6">
                                    <div className="flex items-center gap-3">
                                        <div className="w-8 h-8 bg-blue-500 rounded-lg flex items-center justify-center text-white font-black">G</div>
                                        <span className="font-black text-gray-900 dark:text-gray-100 uppercase text-xs tracking-widest">Google Gemini</span>
                                    </div>
                                </div>
                                <div className="space-y-4">
                                    <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-2xl border border-blue-100 dark:border-blue-800/30 space-y-3">
                                        <div className="flex justify-between text-[11px] font-bold">
                                            <span className="text-blue-700 dark:text-blue-400 tracking-tighter uppercase">Tokens (TPM):</span>
                                            <span className="font-black text-blue-900 dark:text-blue-200">1M</span>
                                        </div>
                                        <div className="flex justify-between text-[11px] font-bold border-t border-blue-100 dark:border-blue-800/50 pt-3">
                                            <span className="text-blue-700 dark:text-blue-400 tracking-tighter uppercase">Peticiones (RPM):</span>
                                            <span className="font-black text-blue-900 dark:text-blue-200">15</span>
                                        </div>
                                    </div>
                                    <div className="text-[10px] text-gray-500 dark:text-gray-400 italic font-medium leading-relaxed">
                                        {t('Tier Standard values are used as live limits are not exposed.', 'Se usan valores Tier Standard ya que no se exponen límites live.')}
                                    </div>
                                    <button
                                        onClick={async () => {
                                            const res = await fetch(`${API_URL}/ai/diagnose-google`);
                                            const data = await res.json();
                                            if (data.status === 'success') alert("Modelos: " + data.available_models.join(", "));
                                        }}
                                        className="w-full py-3 px-4 border border-blue-200 dark:border-blue-800 text-[10px] text-blue-600 dark:text-blue-400 font-black rounded-2xl hover:bg-blue-50 dark:hover:bg-blue-900/40 transition-all uppercase tracking-widest"
                                    >
                                        {t('Diagnose Models', 'Diagnosticar Modelos')}
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Provider Dashboards Link (For Remaining Quota) */}
            <div className="bg-blue-50 p-6 rounded-xl border border-blue-100 shadow-sm">
                <div className="flex items-start gap-4">
                    <div className="bg-blue-100 p-3 rounded-full text-blue-600">
                        <Cpu size={24} />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-gray-900">{t('Check Remaining Quota & Limits', 'Check Remaining Quota & Limits')}</h3>
                        <p className="text-sm text-gray-600 mb-4">
                            {t('The metrics above show usage consumed by this agent. To see your exact remaining balance, credits, or rate limits, please visit your provider\'s dashboard:', 'Las métricas anteriores muestran el uso consumido por este agente. Para ver su saldo restante exacto, créditos o límites de velocidad, visite el panel de su proveedor:')}
                        </p>
                        <div className="flex flex-wrap gap-3">
                            <a href="https://platform.openai.com/usage" target="_blank" rel="noopener noreferrer" className="px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 flex items-center gap-2 transition-colors">
                                <span className="w-4 h-4 bg-black rounded-full flex items-center justify-center text-[8px] text-white font-bold">O</span>
                                OpenAI Usage
                            </a>
                            <a href="https://console.groq.com/settings/limits" target="_blank" rel="noopener noreferrer" className="px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 flex items-center gap-2 transition-colors">
                                <img src="https://groq.com/favicon.ico" className="w-4 h-4 rounded-sm" onError={(e) => e.currentTarget.src = ''} />
                                Groq Limits
                            </a>
                            <a href="https://aistudio.google.com/app/plan_information" target="_blank" rel="noopener noreferrer" className="px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 flex items-center gap-2 transition-colors">
                                <span className="w-4 h-4 bg-blue-500 rounded-full flex items-center justify-center text-[8px] text-white font-bold">G</span>
                                Google AI Quota
                            </a>
                            <a href="https://platform.deepseek.com/usage" target="_blank" rel="noopener noreferrer" className="px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 flex items-center gap-2 transition-colors">
                                <span className="w-4 h-4 bg-blue-600 rounded-full flex items-center justify-center text-[8px] text-white font-bold">DS</span>
                                DeepSeek Usage
                            </a>
                            <a href="https://play.cartesia.ai/settings" target="_blank" rel="noopener noreferrer" className="px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 flex items-center gap-2 transition-colors">
                                <span className="w-4 h-4 bg-purple-500 rounded-full flex items-center justify-center text-[8px] text-white font-bold">C</span>
                                Cartesia Credits
                            </a>
                        </div>
                    </div>
                </div>
            </div>

            {/* SIP Debug Area */}
            <div className="backdrop-blur-md bg-white/70 dark:bg-gray-900/70 p-8 rounded-3xl border border-white/20 dark:border-gray-800/50 shadow-xl overflow-hidden mt-8">
                <div className="flex items-center justify-between mb-8">
                    <h3 className="text-xl font-bold flex items-center gap-3">
                        <div className="p-2 bg-gray-100 dark:bg-gray-900/30 text-gray-600 dark:text-gray-400 rounded-xl">
                            <Terminal size={22} />
                        </div>
                        {t('Telephony System Logs (SIP)', 'Logs del Sistema de Telefonía (SIP)')}
                    </h3>
                    <button
                        onClick={loadSipLogs}
                        disabled={isRefreshingLogs}
                        className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-black uppercase tracking-widest rounded-2xl transition-all shadow-lg shadow-blue-500/25 disabled:opacity-50"
                    >
                        <RefreshCw size={16} className={isRefreshingLogs ? 'animate-spin' : ''} />
                        {isRefreshingLogs ? t('Syncing...', 'Sincronizando...') : t('Refresh Logs', 'Actualizar Logs')}
                    </button>
                </div>

                <div className="relative group">
                    <div className="absolute inset-0 bg-blue-500/5 group-hover:bg-blue-500/10 transition-colors pointer-events-none rounded-2xl"></div>
                    <div className="max-h-[500px] overflow-y-auto p-6 bg-gray-900/95 dark:bg-black rounded-2xl border border-gray-800 font-mono text-[11px] leading-relaxed text-blue-400 shadow-inner scrollbar-thin scrollbar-thumb-gray-800 scrollbar-track-transparent">
                        {sipLogs.length > 0 ? (
                            sipLogs.map((log, idx) => (
                                <div key={idx} className="py-0.5 whitespace-pre-wrap border-l-2 border-transparent hover:border-blue-500/50 hover:bg-blue-500/5 px-2 transition-all">
                                    <span className="text-gray-600 mr-2">[{idx + 1}]</span>
                                    <span className={log.includes('ERROR') ? 'text-red-400' : log.includes('WARN') ? 'text-yellow-400' : ''}>
                                        {log}
                                    </span>
                                </div>
                            ))
                        ) : (
                            <div className="text-center py-20 text-gray-600 font-bold uppercase tracking-[0.2em]">
                                {t('No SIP logs available at the moment.', 'No hay logs de SIP disponibles en este momento.')}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default UsageView;
