import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import { useLocation, useNavigate } from 'react-router-dom';
import { Loader2, ArrowLeft, CheckCircle } from 'lucide-react';

type ViewMode = 'login' | 'forgot' | 'forgot-sent' | 'update-password';

const HERO_IMAGE =
    'https://lh3.googleusercontent.com/aida-public/AB6AXuBI0FAyCBh5GD1o0HyH4mJd5H0_03ddB65__x_JvjZ41QFFoWcfXkstBeEdZ_cK-_OZP9ADsNkNA-LMGni6tjxCF3yrXmbb8aHC2n2BBZlQX2NBi52-5K5pihmH1lXAUb8rKSKuhQCjFqpJ8O20iJdYGO-UvDmF3nqbfB3-HMcMczLRpNhySEcUJ2DLyxeBle-XVaiBdQAVZyps2ERicJHt_lVmJuedV5uZRPs3HuN1LOYNbexenkqLo_B29Z6YNhBe2bTkUrp2guDg';

function MaterialIcon({
    name,
    className = '',
    filled = false,
}: {
    name: string;
    className?: string;
    filled?: boolean;
}) {
    return (
        <span
            className={`material-symbols-outlined leading-none ${className}`}
            style={{
                fontVariationSettings: `'FILL' ${filled ? 1 : 0}, 'wght' 400, 'GRAD' 0, 'opsz' 24`,
            }}
        >
            {name}
        </span>
    );
}

const inputClass =
    'w-full bg-surface-container border border-outline-variant rounded-lg py-2.5 pl-10 pr-3 text-on-surface text-base placeholder:text-on-surface-variant/50 focus:border-primary focus:ring-1 focus:ring-primary transition-colors outline-none';

const LoginView: React.FC = () => {
    const { signIn, user, profile, loading: authLoading } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [rememberMe, setRememberMe] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [viewMode, setViewMode] = useState<ViewMode>('login');
    const redirectTo =
        (location.state as { from?: { pathname?: string } } | null)?.from?.pathname || '/';

    React.useEffect(() => {
        const urlParams = window.location.hash + window.location.search;
        if (
            urlParams &&
            (urlParams.includes('type=recovery') ||
                urlParams.includes('type=signup') ||
                urlParams.includes('type=invite'))
        ) {
            setViewMode('update-password');
        }
    }, []);

    React.useEffect(() => {
        if (!authLoading && user && profile) {
            navigate(redirectTo, { replace: true });
        }
    }, [authLoading, user, profile, navigate, redirectTo]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        const { error: authError } = await signIn(email, password);
        if (authError) {
            setError(
                authError.message === 'Invalid login credentials'
                    ? 'Email o contraseña incorrectos'
                    : authError.message,
            );
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
            const API_URL =
                (import.meta as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL || '';
            const res = await fetch(`${API_URL}/api/n8n/recover`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email }),
            });
            if (!res.ok) {
                const errorText = await res.text();
                throw new Error(errorText || 'Error al conectar con el sistema de recuperación');
            }
            setViewMode('forgot-sent');
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Error desconocido');
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
        const { error: updateError } = await supabase.auth.updateUser({ password: newPassword });
        if (updateError) {
            setError(updateError.message);
        } else {
            window.location.hash = '';
            window.location.reload();
        }
        setLoading(false);
    };

    const title =
        viewMode === 'login'
            ? 'Bienvenido de nuevo'
            : viewMode === 'forgot'
              ? 'Recuperar contraseña'
              : viewMode === 'forgot-sent'
                ? 'Revisa tu email'
                : 'Nueva contraseña';

    const subtitle =
        viewMode === 'login'
            ? 'Accede a tu centro de mando de voz empresarial.'
            : viewMode === 'forgot'
              ? 'Te enviaremos un enlace para restablecerla.'
              : viewMode === 'forgot-sent'
                ? 'Hemos enviado las instrucciones a tu bandeja.'
                : 'Introduce y confirma tu nueva contraseña.';

    const primaryButtonClass =
        'w-full bg-primary text-on-primary font-bold py-3 rounded-lg hover:brightness-110 transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed';

    return (
        <div className="min-h-screen flex items-center justify-center bg-background p-4 md:p-12 font-geist text-on-background antialiased">
            <main className="w-full max-w-[1440px] flex flex-col md:flex-row h-[min(90vh,800px)] min-h-[600px] rounded-2xl overflow-hidden shadow-[0_20px_50px_rgba(0,0,0,0.5)] border border-white/10">
                {/* Panel visual — desktop (mockup Voice AI Hub) */}
                <section className="hidden md:flex flex-1 relative bg-surface-container-low items-center justify-center overflow-hidden">
                    <div className="absolute inset-0 bg-gradient-to-br from-surface-container-low to-surface-container-highest z-0" />
                    <img
                        alt="Visualización abstracta de ondas de voz"
                        className="w-full h-full object-cover z-10 mix-blend-screen opacity-80"
                        src={HERO_IMAGE}
                    />
                    <div className="absolute bottom-10 left-10 z-20">
                        <div className="flex items-center gap-3 mb-3">
                            <img src="/ausarta.png" alt="Ausarta" className="h-12 w-12 object-contain" />
                        </div>
                        <h1 className="text-4xl md:text-5xl font-bold tracking-tight text-primary">
                            Ausarta
                        </h1>
                        <p className="text-lg text-on-surface-variant mt-2 max-w-md">
                            Enterprise Voice Intelligence Command Center
                        </p>
                    </div>
                </section>

                {/* Panel formulario */}
                <section className="flex-1 w-full md:w-[480px] md:max-w-[480px] bg-surface flex flex-col justify-center px-4 py-10 md:px-8 relative z-10 overflow-y-auto">
                    <div className="w-full max-w-md mx-auto">
                        {/* Marca móvil */}
                        <div className="flex items-center justify-center gap-2 mb-8 md:hidden">
                            <MaterialIcon name="graphic_eq" className="text-primary text-2xl" filled />
                            <span className="text-xl font-bold text-primary">Ausarta</span>
                        </div>

                        <div className="mb-8 text-center md:text-left">
                            <h2 className="text-2xl md:text-3xl font-semibold text-on-surface mb-1">
                                {title}
                            </h2>
                            <p className="text-base text-on-surface-variant">{subtitle}</p>
                        </div>

                        {error && (
                            <div className="mb-4 p-3 rounded-lg bg-red-950/40 border border-error/30 text-on-error-container text-sm">
                                {error}
                            </div>
                        )}

                        {viewMode === 'login' && (
                            <form onSubmit={handleSubmit} className="space-y-4">
                                <div>
                                    <label
                                        className="block text-sm font-medium text-on-surface-variant mb-1"
                                        htmlFor="email"
                                    >
                                        Email
                                    </label>
                                    <div className="relative">
                                        <MaterialIcon
                                            name="mail"
                                            className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-xl"
                                        />
                                        <input
                                            id="email"
                                            type="email"
                                            value={email}
                                            onChange={(e) => setEmail(e.target.value)}
                                            className={inputClass}
                                            placeholder="admin@enterprise.com"
                                            required
                                            autoFocus
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label
                                        className="block text-sm font-medium text-on-surface-variant mb-1"
                                        htmlFor="password"
                                    >
                                        Contraseña
                                    </label>
                                    <div className="relative">
                                        <MaterialIcon
                                            name="lock"
                                            className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-xl"
                                        />
                                        <input
                                            id="password"
                                            type={showPassword ? 'text' : 'password'}
                                            value={password}
                                            onChange={(e) => setPassword(e.target.value)}
                                            className={`${inputClass} pr-10`}
                                            placeholder="••••••••"
                                            required
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowPassword(!showPassword)}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-primary transition-colors"
                                            aria-label={
                                                showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'
                                            }
                                        >
                                            <MaterialIcon
                                                name={showPassword ? 'visibility' : 'visibility_off'}
                                                className="text-xl"
                                            />
                                        </button>
                                    </div>
                                </div>

                                <div className="flex items-center justify-between pt-1 pb-2">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={rememberMe}
                                            onChange={(e) => setRememberMe(e.target.checked)}
                                            className="rounded border-outline-variant bg-surface-container text-primary focus:ring-primary focus:ring-offset-background"
                                        />
                                        <span className="text-sm text-on-surface-variant">Recordarme</span>
                                    </label>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setError('');
                                            setViewMode('forgot');
                                        }}
                                        className="text-sm text-primary hover:text-primary-fixed-dim transition-colors"
                                    >
                                        ¿Olvidaste tu contraseña?
                                    </button>
                                </div>

                                <button type="submit" disabled={loading} className={primaryButtonClass}>
                                    {loading ? (
                                        <>
                                            <Loader2 size={18} className="animate-spin" />
                                            Entrando...
                                        </>
                                    ) : (
                                        <>
                                            Iniciar sesión
                                            <MaterialIcon name="arrow_forward" className="text-xl" />
                                        </>
                                    )}
                                </button>
                            </form>
                        )}

                        {viewMode === 'forgot' && (
                            <>
                                <button
                                    type="button"
                                    onClick={() => {
                                        setError('');
                                        setViewMode('login');
                                    }}
                                    className="flex items-center gap-1 text-sm text-on-surface-variant hover:text-on-surface mb-4 transition-colors"
                                >
                                    <ArrowLeft size={16} /> Volver al login
                                </button>
                                <form onSubmit={handleForgotPassword} className="space-y-4">
                                    <div>
                                        <label
                                            className="block text-sm font-medium text-on-surface-variant mb-1"
                                            htmlFor="forgot-email"
                                        >
                                            Email
                                        </label>
                                        <div className="relative">
                                            <MaterialIcon
                                                name="mail"
                                                className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-xl"
                                            />
                                            <input
                                                id="forgot-email"
                                                type="email"
                                                value={email}
                                                onChange={(e) => setEmail(e.target.value)}
                                                className={inputClass}
                                                placeholder="tu@email.com"
                                                required
                                                autoFocus
                                            />
                                        </div>
                                    </div>
                                    <button type="submit" disabled={loading} className={primaryButtonClass}>
                                        {loading ? (
                                            <Loader2 size={18} className="animate-spin" />
                                        ) : (
                                            <>
                                                Enviar enlace
                                                <MaterialIcon name="send" className="text-xl" />
                                            </>
                                        )}
                                    </button>
                                </form>
                            </>
                        )}

                        {viewMode === 'forgot-sent' && (
                            <div className="text-center py-4">
                                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-emerald-950/50 mb-4">
                                    <CheckCircle size={32} className="text-primary" />
                                </div>
                                <p className="text-on-surface-variant text-sm mb-6">
                                    Hemos enviado un enlace a{' '}
                                    <strong className="text-on-surface">{email}</strong>. Revisa también la
                                    carpeta de spam.
                                </p>
                                <button
                                    type="button"
                                    onClick={() => {
                                        setError('');
                                        setViewMode('login');
                                    }}
                                    className="px-6 py-2.5 bg-surface-container border border-outline-variant text-on-surface rounded-lg hover:border-primary/50 transition-all text-sm font-medium"
                                >
                                    Volver al login
                                </button>
                            </div>
                        )}

                        {viewMode === 'update-password' && (
                            <form onSubmit={handleUpdatePassword} className="space-y-4">
                                <div>
                                    <label
                                        className="block text-sm font-medium text-on-surface-variant mb-1"
                                        htmlFor="new-pw"
                                    >
                                        Nueva contraseña
                                    </label>
                                    <div className="relative">
                                        <MaterialIcon
                                            name="lock"
                                            className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-xl"
                                        />
                                        <input
                                            id="new-pw"
                                            type={showPassword ? 'text' : 'password'}
                                            value={newPassword}
                                            onChange={(e) => setNewPassword(e.target.value)}
                                            className={`${inputClass} pr-10`}
                                            placeholder="Mínimo 6 caracteres"
                                            required
                                            autoFocus
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowPassword(!showPassword)}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-primary"
                                        >
                                            <MaterialIcon
                                                name={showPassword ? 'visibility' : 'visibility_off'}
                                                className="text-xl"
                                            />
                                        </button>
                                    </div>
                                </div>
                                <div>
                                    <label
                                        className="block text-sm font-medium text-on-surface-variant mb-1"
                                        htmlFor="confirm-pw"
                                    >
                                        Confirmar contraseña
                                    </label>
                                    <div className="relative">
                                        <MaterialIcon
                                            name="lock"
                                            className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-xl"
                                        />
                                        <input
                                            id="confirm-pw"
                                            type="password"
                                            value={confirmPassword}
                                            onChange={(e) => setConfirmPassword(e.target.value)}
                                            className={inputClass}
                                            placeholder="Repite la contraseña"
                                            required
                                        />
                                    </div>
                                </div>
                                <button type="submit" disabled={loading} className={primaryButtonClass}>
                                    {loading ? (
                                        <Loader2 size={18} className="animate-spin" />
                                    ) : (
                                        <>
                                            Guardar contraseña
                                            <MaterialIcon name="check" className="text-xl" />
                                        </>
                                    )}
                                </button>
                            </form>
                        )}

                        {viewMode === 'login' && (
                            <div className="mt-8 text-center md:text-left">
                                <p className="text-base text-on-surface-variant">
                                    ¿Necesitas acceso?{' '}
                                    <a
                                        href="mailto:soporte@ausarta.net"
                                        className="text-primary hover:text-primary-fixed-dim font-medium transition-colors"
                                    >
                                        Solicitar demo
                                    </a>
                                </p>
                            </div>
                        )}

                        <p className="text-center text-outline text-xs mt-8">
                            Ausarta Voice AI v2.0 · © {new Date().getFullYear()}
                        </p>
                    </div>
                </section>
            </main>
        </div>
    );
};

export default LoginView;
