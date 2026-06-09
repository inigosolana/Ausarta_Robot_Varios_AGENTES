/**
 * Solicitud de recuperación de contraseña (backend → Supabase Auth o SMTP Ausarta).
 */
export async function requestPasswordReset(
    email: string,
    redirectTo?: string,
): Promise<void> {
    const API_URL =
        (import.meta as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL || '';
    const res = await fetch(`${API_URL}/api/auth/password-reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            email: email.trim(),
            ...(redirectTo ? { redirect_to: redirectTo } : {}),
        }),
    });
    if (!res.ok) {
        let detail = 'No se pudo enviar el email de recuperación';
        try {
            const data = await res.json();
            if (data?.error) {
                detail = data.error;
            } else if (Array.isArray(data?.detail)) {
                const msgs = data.detail
                    .map((d: { msg?: string }) => d.msg)
                    .filter(Boolean)
                    .map((m: string) =>
                        m === 'Field required' ? 'El email es obligatorio' : m,
                    );
                detail = msgs.join('. ') || detail;
            } else if (typeof data?.detail === 'string') {
                detail = data.detail === 'Field required' ? 'El email es obligatorio' : data.detail;
            }
        } catch {
            /* ignore */
        }
        throw new Error(detail);
    }
}

export function passwordResetRedirectUrl(): string {
    const productionUrl = 'http://15.216.15.30/login';
    if (typeof window === 'undefined') return productionUrl;
    if (window.location.origin.includes('localhost')) return productionUrl;
    return `${window.location.origin}/login`;
}
