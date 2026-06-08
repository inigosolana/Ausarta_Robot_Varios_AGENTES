/**
 * Solicitud de recuperación de contraseña — email Ausarta en español vía n8n.
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
            if (data?.error) detail = data.error;
        } catch {
            /* ignore */
        }
        throw new Error(detail);
    }
}

export function passwordResetRedirectUrl(): string {
    if (typeof window === 'undefined') return 'https://app.ausarta.net';
    return window.location.origin.includes('localhost')
        ? 'https://app.ausarta.net'
        : window.location.origin;
}
