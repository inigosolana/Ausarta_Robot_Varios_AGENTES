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

async function _forceLogout(): Promise<never> {
    _cachedToken = null;
    localStorage.removeItem('impersonateToken');
    localStorage.removeItem('spoofedRole');
    localStorage.removeItem('spoofedEmpresa');
    await supabase.auth.signOut();
    window.location.href = '/login?session_expired=true';
    throw new Error('Sesión expirada');
}

async function _resolveToken(): Promise<string> {
    if (_cachedToken) return _cachedToken;

    // Intento 1: refrescar sesión silenciosamente
    const { data, error } = await supabase.auth.getSession();
    _cachedToken = data.session?.access_token ?? null;
    if (_cachedToken) return _cachedToken;

    // Intento 2: forzar refresh del token
    const { data: refreshData } = await supabase.auth.refreshSession();
    _cachedToken = refreshData.session?.access_token ?? null;
    if (_cachedToken) return _cachedToken;

    // Sin sesión válida → logout
    return _forceLogout();
}

export async function apiFetch(
    url: string,
    options: RequestInit = {},
): Promise<Response> {
    const API_URL = (import.meta.env.VITE_API_URL as string | undefined) || '';

    const token = await _resolveToken();

    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> | undefined),
    };

    headers['Authorization'] = `Bearer ${token}`;

    const impersonateToken = localStorage.getItem('impersonateToken');
    if (impersonateToken) {
        headers['X-Impersonate-Token'] = impersonateToken;
    }

    const fullUrl = url.startsWith('http') ? url : `${API_URL}${url}`;
    const response = await fetch(fullUrl, { ...options, headers });

    if (response.status === 401) {
        // Intentar refresh una sola vez antes de expulsar
        const { data: refreshData } = await supabase.auth.refreshSession();
        const newToken = refreshData.session?.access_token ?? null;

        if (newToken) {
            _cachedToken = newToken;
            headers['Authorization'] = `Bearer ${newToken}`;
            const retryResponse = await fetch(fullUrl, { ...options, headers });
            if (retryResponse.status !== 401) return retryResponse;
        }

        // El token definitivamente expiró o fue revocado → logout
        return _forceLogout();
    }

    return response;
}
