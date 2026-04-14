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

    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> | undefined),
    };

    if (_cachedToken) {
        headers['Authorization'] = `Bearer ${_cachedToken}`;
    }

    const impersonateToken = localStorage.getItem('impersonateToken');
    if (impersonateToken) {
        headers['X-Impersonate-Token'] = impersonateToken;
    }

    const fullUrl = url.startsWith('http') ? url : `${API_URL}${url}`;
    return fetch(fullUrl, { ...options, headers });
}
