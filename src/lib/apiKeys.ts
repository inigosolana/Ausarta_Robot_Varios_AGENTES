import { apiFetch } from './apiFetch';

export type ApiKeyScope = 'outbound_call' | 'webhook' | 'read' | 'admin';

export interface ApiKeyListItem {
  id: string;
  empresa_id: number;
  key_prefix: string;
  description?: string | null;
  scopes: ApiKeyScope[];
  is_active: boolean;
  expires_at?: string | null;
  created_at?: string | null;
  last_used_at?: string | null;
}

export interface ApiKeyCreatePayload {
  description: string;
  empresa_id?: number;
  scopes: ApiKeyScope[];
  expires_at?: string | null;
}

export interface ApiKeyCreateResult {
  id: string;
  key: string;
  empresa_id: number;
  key_prefix: string;
  scopes: ApiKeyScope[];
  expires_at?: string | null;
}

export async function fetchApiKeys(empresaId?: number): Promise<ApiKeyListItem[]> {
  const qs = empresaId ? `?empresa_id=${encodeURIComponent(String(empresaId))}` : '';
  const res = await apiFetch(`/api/admin/api-keys${qs}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function createApiKey(payload: ApiKeyCreatePayload): Promise<ApiKeyCreateResult> {
  const res = await apiFetch('/api/admin/api-keys', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function revokeApiKey(keyId: string): Promise<void> {
  const res = await apiFetch(`/api/admin/api-keys/${encodeURIComponent(keyId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || `HTTP ${res.status}`);
  }
}
