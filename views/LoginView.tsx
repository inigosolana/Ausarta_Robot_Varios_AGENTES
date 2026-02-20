import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Loader2, LogIn, Eye, EyeOff } from 'lucide-react';

const LoginView: React.FC = () => {
    const { signIn } = useAuth();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

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

                {/* Login Card */}
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

                <p className="text-center text-gray-600 text-xs mt-6">
                    Ausarta Voice AI v2.0 · © {new Date().getFullYear()}
                </p>
            </div>
        </div>
    );
};

export default LoginView;
