import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import { passwordResetRedirectUrl, requestPasswordReset } from '../lib/passwordReset';
import { useLocation, useNavigate } from 'react-router-dom';
import {
    Loader2,
    ArrowLeft,
    CheckCircle,
    Mail,
    Lock,
    Eye,
    EyeOff,
    ArrowRight,
    type LucideIcon,
} from 'lucide-react';
import './login.css';

type ViewMode = 'login' | 'forgot' | 'forgot-sent' | 'update-password';

const isPasswordResetFlow = () => {
    const params = window.location.hash + window.location.search;
    return (
        params.includes('type=recovery') ||
        params.includes('type=signup') ||
        params.includes('type=invite')
    );
};

/** Logo grande, fondo transparente, colores claros para UI oscura */
const LOGO_SRC = '/ausarta-logo-light.png';

type LoginFieldProps = {
    id: string;
    label: string;
    type: string;
    value: string;
    onChange: (v: string) => void;
    placeholder: string;
    icon: LucideIcon;
    showToggle?: boolean;
    showPassword?: boolean;
    onTogglePassword?: () => void;
};

/** Fuera de LoginView para no perder foco del input en cada tecla */
const LoginField: React.FC<LoginFieldProps> = ({
    id,
    label,
    type,
    value,
    onChange,
    placeholder,
    icon: Icon,
    showToggle,
    showPassword,
    onTogglePassword,
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
                autoComplete={
                    id.includes('password') || id.includes('pw') ? 'current-password' : 'email'
                }
            />
            {showToggle && onTogglePassword && (
                <button
                    type="button"
                    onClick={onTogglePassword}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86948a] hover:text-[#4edea3] transition-colors"
                    aria-label={showPassword ? 'Ocultar' : 'Mostrar'}
                >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
            )}
        </div>
    </div>
);

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
        if (isPasswordResetFlow()) {
            setViewMode('update-password');
        }
    }, []);

    useEffect(() => {
        // Tras recovery Supabase crea sesión; no redirigir al dashboard hasta cambiar contraseña
        if (!authLoading && user && profile && !isPasswordResetFlow() && viewMode !== 'update-password') {
            navigate(redirectTo, { replace: true });
        }
    }, [authLoading, user, profile, navigate, redirectTo, viewMode]);

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
            await requestPasswordReset(email, passwordResetRedirectUrl());
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
                ? 'Abre el email y sigue los 3 pasos del mensaje.'
                : 'Escribe la nueva contraseña dos veces y confírmala.';

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
                                <LoginField
                                    id="email"
                                    label="Email"
                                    type="email"
                                    value={email}
                                    onChange={setEmail}
                                    placeholder="tu@empresa.com"
                                    icon={Mail}
                                />
                                <LoginField
                                    id="password"
                                    label="Contraseña"
                                    type={showPassword ? 'text' : 'password'}
                                    value={password}
                                    onChange={setPassword}
                                    placeholder="••••••••"
                                    icon={Lock}
                                    showToggle
                                    showPassword={showPassword}
                                    onTogglePassword={() => setShowPassword((v) => !v)}
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
                                    <LoginField
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
                                <p className="text-[#bbcabf] text-sm mb-4 text-left">
                                    Hemos enviado un email a{' '}
                                    <strong className="text-[#dae2fd]">{email}</strong> con el asunto
                                    «Cómo restablecer tu contraseña».
                                </p>
                                <ol className="text-left text-sm text-[#86948a] space-y-2 mb-6 pl-5 list-decimal">
                                    <li>Abre el correo y pulsa <strong className="text-[#bbcabf]">Crear nueva contraseña</strong>.</li>
                                    <li>En la web de Ausarta, escribe la nueva contraseña dos veces.</li>
                                    <li>Vuelve aquí e inicia sesión con tu email y la clave nueva.</li>
                                </ol>
                                <p className="text-xs text-[#6b7a70] mb-6">Revisa la carpeta de spam si no lo ves en unos minutos.</p>
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
                                <LoginField
                                    id="new-pw"
                                    label="Nueva contraseña"
                                    type={showPassword ? 'text' : 'password'}
                                    value={newPassword}
                                    onChange={setNewPassword}
                                    placeholder="Mínimo 6 caracteres"
                                    icon={Lock}
                                    showToggle
                                    showPassword={showPassword}
                                    onTogglePassword={() => setShowPassword((v) => !v)}
                                />
                                <LoginField
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
