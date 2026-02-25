import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import { Loader2, LogIn, Eye, EyeOff, ArrowLeft, Mail, CheckCircle, KeyRound } from 'lucide-react';

type ViewMode = 'login' | 'forgot' | 'forgot-sent' | 'update-password';

const LoginView: React.FC = () => {
    const { signIn } = useAuth();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [viewMode, setViewMode] = useState<ViewMode>('login');

    // Check URL params for password recovery or invitation
    React.useEffect(() => {
        const hash = window.location.hash;
        if (hash && (hash.includes('type=recovery') || hash.includes('type=signup') || hash.includes('type=invite'))) {
            setViewMode('update-password');
        }
    }, []);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        const { error: authError } = await signIn(email, password);
        if (authError) {
            setError(authError.message === 'Invalid login credentials'
                ? 'Email o contraseña incorrectos'
                : authError.message);
        }
        setLoading(false);
    };

    const handleForgotPassword = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!email) {
            setError('Introduce tu email');
            return;
        }
        setError('');
        setLoading(true);

        try {
            // Call Backend Proxy instead of n8n directly to avoid CORS issues
            const API_URL = import.meta.env.VITE_API_URL || '';
            const PROXY_URL = `${API_URL}/api/n8n/recover`;

            const res = await fetch(PROXY_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });


            if (!res.ok) {
                const errorText = await res.text();
                throw new Error(errorText || 'Error al conectar con el sistema de recuperación');
            }

            setViewMode('forgot-sent');
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleUpdatePassword = async (e: React.FormEvent) => {
        e.preventDefault();
        if (newPassword.length < 6) {
            setError('La contraseña debe tener al menos 6 caracteres');
            return;
        }
        if (newPassword !== confirmPassword) {
            setError('Las contraseñas no coinciden');
            return;
        }
        setError('');
        setLoading(true);

        const { error } = await supabase.auth.updateUser({ password: newPassword });
        if (error) {
            setError(error.message);
        } else {
            // Clear hash from URL and reload
            window.location.hash = '';
            window.location.reload();
        }
        setLoading(false);
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 relative overflow-hidden">
            {/* Background decoration */}
            <div className="absolute inset-0">
                <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-blue-500/10 rounded-full blur-[128px] animate-pulse" />
                <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-purple-500/10 rounded-full blur-[128px] animate-pulse" style={{ animationDelay: '1s' }} />
            </div>

            <div className="relative z-10 w-full max-w-md mx-4">
                {/* Logo + Title */}
                <div className="text-center mb-8">
                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-white/10 backdrop-blur-sm border border-white/20 mb-4 shadow-2xl">
                        <img src="/ausarta.png" alt="Ausarta" className="h-10 w-10 object-contain" />
                    </div>
                    <h1 className="text-3xl font-bold text-white tracking-tight">Ausarta</h1>
                    <p className="text-gray-400 text-sm mt-1">Voice AI Platform</p>
                </div>

                {/* ============ LOGIN VIEW ============ */}
                {viewMode === 'login' && (
                    <div className="bg-white/5 backdrop-blur-xl rounded-2xl border border-white/10 shadow-2xl p-8">
                        <h2 className="text-xl font-semibold text-white mb-6">Iniciar Sesión</h2>

                        {error && (
                            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 text-red-300 text-sm rounded-lg">
                                {error}
                            </div>
                        )}

                        <form onSubmit={handleSubmit} className="space-y-5">
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Email</label>
                                <input
                                    type="email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-all"
                                    placeholder="tu@email.com"
                                    required
                                    autoFocus
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Contraseña</label>
                                <div className="relative">
                                    <input
                                        type={showPassword ? 'text' : 'password'}
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-all pr-12"
                                        placeholder="••••••••"
                                        required
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPassword(!showPassword)}
                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
                                    >
                                        {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                                    </button>
                                </div>
                            </div>

                            {/* Forgot Password Link */}
                            <div className="flex justify-end">
                                <button
                                    type="button"
                                    onClick={() => { setError(''); setViewMode('forgot'); }}
                                    className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
                                >
                                    ¿Olvidaste tu contraseña?
                                </button>
                            </div>

                            <button
                                type="submit"
                                disabled={loading}
                                className="w-full py-3 bg-gradient-to-r from-blue-600 to-blue-500 text-white font-semibold rounded-xl hover:from-blue-500 hover:to-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 shadow-lg shadow-blue-500/25"
                            >
                                {loading ? (
                                    <>
                                        <Loader2 size={18} className="animate-spin" />
                                        Entrando...
                                    </>
                                ) : (
                                    <>
                                        <LogIn size={18} />
                                        Entrar
                                    </>
                                )}
                            </button>
                        </form>
                    </div>
                )}

                {/* ============ FORGOT PASSWORD VIEW ============ */}
                {viewMode === 'forgot' && (
                    <div className="bg-white/5 backdrop-blur-xl rounded-2xl border border-white/10 shadow-2xl p-8">
                        <button
                            onClick={() => { setError(''); setViewMode('login'); }}
                            className="flex items-center gap-1 text-sm text-gray-400 hover:text-white transition-colors mb-4"
                        >
                            <ArrowLeft size={16} /> Volver al login
                        </button>

                        <div className="flex items-center gap-3 mb-4">
                            <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center">
                                <Mail size={20} className="text-amber-400" />
                            </div>
                            <div>
                                <h2 className="text-xl font-semibold text-white">Recuperar contraseña</h2>
                                <p className="text-gray-400 text-sm">Te enviaremos un enlace para restablecerla</p>
                            </div>
                        </div>

                        {error && (
                            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 text-red-300 text-sm rounded-lg">
                                {error}
                            </div>
                        )}

                        <form onSubmit={handleForgotPassword} className="space-y-5">
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Email</label>
                                <input
                                    type="email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 transition-all"
                                    placeholder="tu@email.com"
                                    required
                                    autoFocus
                                />
                            </div>

                            <button
                                type="submit"
                                disabled={loading}
                                className="w-full py-3 bg-gradient-to-r from-amber-600 to-amber-500 text-white font-semibold rounded-xl hover:from-amber-500 hover:to-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-500/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 shadow-lg shadow-amber-500/25"
                            >
                                {loading ? (
                                    <>
                                        <Loader2 size={18} className="animate-spin" />
                                        Enviando...
                                    </>
                                ) : (
                                    <>
                                        <Mail size={18} />
                                        Enviar enlace de recuperación
                                    </>
                                )}
                            </button>
                        </form>
                    </div>
                )}

                {/* ============ EMAIL SENT CONFIRMATION ============ */}
                {viewMode === 'forgot-sent' && (
                    <div className="bg-white/5 backdrop-blur-xl rounded-2xl border border-white/10 shadow-2xl p-8 text-center">
                        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-500/10 mb-4">
                            <CheckCircle size={32} className="text-green-400" />
                        </div>
                        <h2 className="text-xl font-semibold text-white mb-2">¡Email enviado!</h2>
                        <p className="text-gray-400 text-sm mb-6">
                            Hemos enviado un enlace de recuperación a <strong className="text-white">{email}</strong>.
                            Revisa tu bandeja de entrada (y la carpeta de spam).
                        </p>
                        <button
                            onClick={() => { setError(''); setViewMode('login'); }}
                            className="px-6 py-2.5 bg-white/10 text-white rounded-xl hover:bg-white/20 transition-all text-sm font-medium"
                        >
                            Volver al login
                        </button>
                    </div>
                )}

                {/* ============ UPDATE PASSWORD VIEW ============ */}
                {viewMode === 'update-password' && (
                    <div className="bg-white/5 backdrop-blur-xl rounded-2xl border border-white/10 shadow-2xl p-8">
                        <div className="flex items-center gap-3 mb-6">
                            <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center">
                                <KeyRound size={20} className="text-blue-400" />
                            </div>
                            <div>
                                <h2 className="text-xl font-semibold text-white">Crear nueva contraseña</h2>
                                <p className="text-gray-400 text-sm">Introduce tu nueva contraseña</p>
                            </div>
                        </div>

                        {error && (
                            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 text-red-300 text-sm rounded-lg">
                                {error}
                            </div>
                        )}

                        <form onSubmit={handleUpdatePassword} className="space-y-5">
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Nueva contraseña</label>
                                <div className="relative">
                                    <input
                                        type={showPassword ? 'text' : 'password'}
                                        value={newPassword}
                                        onChange={(e) => setNewPassword(e.target.value)}
                                        className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-all pr-12"
                                        placeholder="Mínimo 6 caracteres"
                                        required
                                        autoFocus
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPassword(!showPassword)}
                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
                                    >
                                        {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                                    </button>
                                </div>
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-1.5">Confirmar contraseña</label>
                                <input
                                    type="password"
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-all"
                                    placeholder="Repite la contraseña"
                                    required
                                />
                            </div>

                            <button
                                type="submit"
                                disabled={loading}
                                className="w-full py-3 bg-gradient-to-r from-blue-600 to-blue-500 text-white font-semibold rounded-xl hover:from-blue-500 hover:to-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 shadow-lg shadow-blue-500/25"
                            >
                                {loading ? (
                                    <>
                                        <Loader2 size={18} className="animate-spin" />
                                        Guardando...
                                    </>
                                ) : (
                                    <>
                                        <KeyRound size={18} />
                                        Guardar contraseña
                                    </>
                                )}
                            </button>
                        </form>
                    </div>
                )}

                <p className="text-center text-gray-600 text-xs mt-6">
                    Ausarta Voice AI v2.0 · © {new Date().getFullYear()}
                </p>
            </div>
        </div>
    );
};

export default LoginView;
