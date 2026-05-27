import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import { useLocation, useNavigate } from 'react-router-dom';
import { Loader2, ArrowLeft, CheckCircle, Mail, Lock, Eye, EyeOff, ArrowRight } from 'lucide-react';
import './login.css';

type ViewMode = 'login' | 'forgot' | 'forgot-sent' | 'update-password';

/** Logo grande, fondo transparente, colores claros para UI oscura */
const LOGO_SRC = '/ausarta-logo-light.png';

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

    useEffect(() => {
        document.documentElement.classList.add('dark');
        const prevBodyBg = document.body.style.backgroundColor;
        document.body.style.backgroundColor = '#060e20';
        return () => {
            document.body.style.backgroundColor = prevBodyBg;
        };
    }, []);

    useEffect(() => {
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

    useEffect(() => {
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

    const Field = ({
        id,
        label,
        type,
        value,
        onChange,
        placeholder,
        icon: Icon,
        showToggle,
    }: {
        id: string;
        label: string;
        type: string;
        value: string;
        onChange: (v: string) => void;
        placeholder: string;
        icon: typeof Mail;
        showToggle?: boolean;
    }) => (
        <div className="mb-4">
            <label htmlFor={id} className="block text-sm font-medium text-[#bbcabf] mb-1.5">
                {label}
            </label>
            <div className="relative">
                <Icon
                    size={18}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-[#86948a] pointer-events-none"
                />
                <input
                    id={id}
                    type={type}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className={`login-input${showToggle ? ' !pr-10' : ''}`}
                    placeholder={placeholder}
                    required
                    autoComplete={id.includes('password') || id.includes('pw') ? 'current-password' : 'email'}
                />
                {showToggle && (
                    <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86948a] hover:text-[#4edea3] transition-colors"
                        aria-label={showPassword ? 'Ocultar' : 'Mostrar'}
                    >
                        {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                )}
            </div>
        </div>
    );

    if (authLoading) {
        return (
            <div className="login-page">
                <Loader2 size={32} className="animate-spin text-[#4edea3]" />
            </div>
        );
    }

    return (
        <div className="login-page">
            <div className="login-card">
                {/* Panel hero — solo desktop, una sola columna visual */}
                <aside className="login-hero" aria-hidden="true">
                    <div className="login-hero-glow" />
                    <div className="login-hero-wave" />
                    <div className="login-hero-brand">
                        <img
                            src={LOGO_SRC}
                            alt="Ausarta"
                            className="login-logo"
                            onError={(e) => {
                                (e.target as HTMLImageElement).src = '/ausarta.png';
                            }}
                        />
                        <p>Enterprise Voice Intelligence Command Center</p>
                    </div>
                </aside>

                {/* Panel formulario — única columna de inputs */}
                <section className="login-form-panel">
                    <div className="login-form-inner">
                        {/* Marca móvil */}
                        <div className="flex justify-center mb-10 lg:hidden">
                            <img
                                src={LOGO_SRC}
                                alt="Ausarta"
                                className="login-logo login-logo-mobile"
                                onError={(e) => {
                                    (e.target as HTMLImageElement).src = '/ausarta.png';
                                }}
                            />
                        </div>

                        <header className="mb-8 text-center lg:text-left">
                            <h2 className="font-semibold text-[#dae2fd] m-0">{title}</h2>
                            <p className="text-[#bbcabf] text-[0.9375rem] mt-2 mb-0">{subtitle}</p>
                        </header>

                        {error && <div className="login-error">{error}</div>}

                        {viewMode === 'login' && (
                            <form onSubmit={handleSubmit}>
                                <Field
                                    id="email"
                                    label="Email"
                                    type="email"
                                    value={email}
                                    onChange={setEmail}
                                    placeholder="tu@empresa.com"
                                    icon={Mail}
                                />
                                <Field
                                    id="password"
                                    label="Contraseña"
                                    type={showPassword ? 'text' : 'password'}
                                    value={password}
                                    onChange={setPassword}
                                    placeholder="••••••••"
                                    icon={Lock}
                                    showToggle
                                />

                                <div className="flex items-center justify-between mb-6 text-sm">
                                    <label className="flex items-center gap-2 cursor-pointer text-[#bbcabf]">
                                        <input
                                            type="checkbox"
                                            checked={rememberMe}
                                            onChange={(e) => setRememberMe(e.target.checked)}
                                            className="rounded border-[#3c4a42] bg-[#171f33] text-[#4edea3] focus:ring-[#4edea3]"
                                        />
                                        Recordarme
                                    </label>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setError('');
                                            setViewMode('forgot');
                                        }}
                                        className="text-[#4edea3] hover:text-[#6ffbbe] transition-colors bg-transparent border-none cursor-pointer p-0 text-sm"
                                    >
                                        ¿Olvidaste tu contraseña?
                                    </button>
                                </div>

                                <button type="submit" disabled={loading} className="login-btn-primary">
                                    {loading ? (
                                        <>
                                            <Loader2 size={18} className="animate-spin" />
                                            Entrando...
                                        </>
                                    ) : (
                                        <>
                                            Iniciar sesión
                                            <ArrowRight size={18} />
                                        </>
                                    )}
                                </button>

                                <p className="mt-8 text-center lg:text-left text-[#bbcabf] text-sm">
                                    ¿Necesitas acceso?{' '}
                                    <a
                                        href="mailto:soporte@ausarta.net"
                                        className="text-[#4edea3] hover:text-[#6ffbbe] font-medium no-underline"
                                    >
                                        Solicitar demo
                                    </a>
                                </p>
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
                                    className="flex items-center gap-1 text-sm text-[#bbcabf] hover:text-[#dae2fd] mb-5 bg-transparent border-none cursor-pointer p-0"
                                >
                                    <ArrowLeft size={16} /> Volver al login
                                </button>
                                <form onSubmit={handleForgotPassword}>
                                    <Field
                                        id="forgot-email"
                                        label="Email"
                                        type="email"
                                        value={email}
                                        onChange={setEmail}
                                        placeholder="tu@email.com"
                                        icon={Mail}
                                    />
                                    <button type="submit" disabled={loading} className="login-btn-primary">
                                        {loading ? (
                                            <Loader2 size={18} className="animate-spin" />
                                        ) : (
                                            'Enviar enlace'
                                        )}
                                    </button>
                                </form>
                            </>
                        )}

                        {viewMode === 'forgot-sent' && (
                            <div className="text-center py-4">
                                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-emerald-950/60 mb-4">
                                    <CheckCircle size={32} className="text-[#4edea3]" />
                                </div>
                                <p className="text-[#bbcabf] text-sm mb-6">
                                    Hemos enviado un enlace a{' '}
                                    <strong className="text-[#dae2fd]">{email}</strong>. Revisa también
                                    spam.
                                </p>
                                <button
                                    type="button"
                                    onClick={() => {
                                        setError('');
                                        setViewMode('login');
                                    }}
                                    className="px-6 py-2.5 bg-[#171f33] border border-[#3c4a42] text-[#dae2fd] rounded-lg hover:border-[#4edea3]/40 transition-all text-sm font-medium cursor-pointer"
                                >
                                    Volver al login
                                </button>
                            </div>
                        )}

                        {viewMode === 'update-password' && (
                            <form onSubmit={handleUpdatePassword}>
                                <Field
                                    id="new-pw"
                                    label="Nueva contraseña"
                                    type={showPassword ? 'text' : 'password'}
                                    value={newPassword}
                                    onChange={setNewPassword}
                                    placeholder="Mínimo 6 caracteres"
                                    icon={Lock}
                                    showToggle
                                />
                                <Field
                                    id="confirm-pw"
                                    label="Confirmar contraseña"
                                    type="password"
                                    value={confirmPassword}
                                    onChange={setConfirmPassword}
                                    placeholder="Repite la contraseña"
                                    icon={Lock}
                                />
                                <button type="submit" disabled={loading} className="login-btn-primary">
                                    {loading ? (
                                        <Loader2 size={18} className="animate-spin" />
                                    ) : (
                                        'Guardar contraseña'
                                    )}
                                </button>
                            </form>
                        )}

                        <p className="text-center text-[#86948a] text-xs mt-10 mb-0">
                            Ausarta Voice AI v2.0 · © {new Date().getFullYear()}
                        </p>
                    </div>
                </section>
            </div>
        </div>
    );
};

export default LoginView;
