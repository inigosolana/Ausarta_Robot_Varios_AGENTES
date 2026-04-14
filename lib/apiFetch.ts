/**
 * apiFetch — wrapper sobre fetch que adjunta automáticamente el Bearer JWT
 * de la sesión activa de Supabase al header Authorization.
 *
 * El token se mantiene en una variable de módulo actualizada por
 * `onAuthStateChange`, eliminando el `await getSession()` en cada petición.
 *
 * Uso:
 *   import { apiFetch } from '../lib/apiFetch';
 *   const res = await apiFetch('/api/admin/users/123', { method: 'DELETE' });
 */
import { supabase } from './supabase';

// Caché en memoria del access_token activo.
// Se hidrata en la importación inicial y se mantiene sincronizado por el listener.
let _cachedToken: string | null = null;

// Hidratación inicial: una sola llamada async al importar el módulo.
supabase.auth.getSession().then(({ data }) => {
    _cachedToken = data.session?.access_token ?? null;
});

// Mantiene el caché actualizado en tiempo real ante login / logout / refresh.
supabase.auth.onAuthStateChange((_event, session) => {
    _cachedToken = session?.access_token ?? null;
});

export async function apiFetch(
    url: string,
    options: RequestInit = {},
): Promise<Response> {
    const API_URL = (import.meta.env.VITE_API_URL as string | undefined) || '';

    if (!_cachedToken) {
        const { data } = await supabase.auth.getSession();
        _cachedToken = data.session?.access_token ?? null;
        if (!_cachedToken) {
            await supabase.auth.signOut();
            window.location.href = '/login?session_expired=true';
            throw new Error('No autorizado');
        }
    }

    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> | undefined),
    };

    headers['Authorization'] = `Bearer ${_cachedToken}`;

    const impersonateToken = localStorage.getItem('impersonateToken');
    if (impersonateToken) {
        headers['X-Impersonate-Token'] = impersonateToken;
    }

    const fullUrl = url.startsWith('http') ? url : `${API_URL}${url}`;
    const response = await fetch(fullUrl, { ...options, headers });

    if (response.status === 401) {
        _cachedToken = null;
        await supabase.auth.signOut();
        window.location.href = '/login?session_expired=true';
        throw new Error('No autorizado');
    }

    return response;
}
