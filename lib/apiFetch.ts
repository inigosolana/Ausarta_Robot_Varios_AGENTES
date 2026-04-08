/**
 * apiFetch — wrapper sobre fetch que adjunta automáticamente el Bearer JWT
 * de la sesión activa de Supabase al header Authorization.
 *
 * Uso:
 *   import { apiFetch } from '../lib/apiFetch';
 *   const res = await apiFetch('/api/admin/users/123', { method: 'DELETE' });
 */
import { supabase } from './supabase';

export async function apiFetch(
    url: string,
    options: RequestInit = {},
): Promise<Response> {
    const API_URL = (import.meta.env.VITE_API_URL as string | undefined) || '';

    // Obtener token de la sesión activa (null si no hay sesión)
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;

    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> | undefined),
    };

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const fullUrl = url.startsWith('http') ? url : `${API_URL}${url}`;
    return fetch(fullUrl, { ...options, headers });
}
