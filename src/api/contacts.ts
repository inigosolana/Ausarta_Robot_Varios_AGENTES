import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';

export interface Contact {
  id: string;
  nombre: string | null;
  telefono: string;
  email: string | null;
  empresa_nombre: string | null;
  etiquetas: string[];
  total_llamadas: number;
  ultima_llamada: string | null;
  ultima_disposicion: string | null;
  score: number;
  notas: string | null;
  datos_extra: Record<string, unknown> | null;
  created_at: string;
}

export interface ContactCallRecord {
  id: string;
  fecha: string;
  status: string;
  disposicion: string | null;
  sentimiento: string | null;
  resumen: string | null;
  duracion_segundos: number | null;
  comentarios: string | null;
}

export type ContactsListFilters = {
  page: number;
  pageSize: number;
  empresaId?: number | null;
  q?: string;
  disposicion?: string;
  etiqueta?: string;
};

export const contactKeys = {
  all: ['contacts'] as const,
  list: (filters: ContactsListFilters) => [...contactKeys.all, 'list', filters] as const,
  calls: (contactId: string, empresaId?: number | null) =>
    [...contactKeys.all, 'calls', contactId, empresaId ?? 'all'] as const,
};

function buildContactsQuery(filters: ContactsListFilters): string {
  const params = new URLSearchParams({
    page: String(filters.page),
    page_size: String(filters.pageSize),
  });
  if (filters.empresaId) params.set('empresa_id', String(filters.empresaId));
  if (filters.q) params.set('q', filters.q);
  if (filters.disposicion) params.set('disposicion', filters.disposicion);
  if (filters.etiqueta) params.set('etiqueta', filters.etiqueta);
  return params.toString();
}

export async function fetchContactsList(filters: ContactsListFilters): Promise<Contact[]> {
  const res = await apiFetch(`/api/contacts/?${buildContactsQuery(filters)}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

export async function fetchContactCalls(
  contactId: string,
  empresaId?: number | null,
): Promise<ContactCallRecord[]> {
  const params = empresaId ? `?empresa_id=${empresaId}` : '';
  const res = await apiFetch(`/api/contacts/${contactId}/calls${params}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

export function useContactsList(filters: ContactsListFilters, enabled = true) {
  return useQuery({
    queryKey: contactKeys.list(filters),
    queryFn: () => fetchContactsList(filters),
    enabled,
    staleTime: 15_000,
    placeholderData: (prev) => prev,
  });
}

export function useContactCalls(
  contactId: string | null,
  empresaId?: number | null,
  enabled = true,
) {
  return useQuery({
    queryKey: contactId ? contactKeys.calls(contactId, empresaId) : ['contacts', 'calls', 'none'],
    queryFn: () => fetchContactCalls(contactId!, empresaId),
    enabled: enabled && Boolean(contactId),
    staleTime: 15_000,
  });
}

export function useInvalidateContacts() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: contactKeys.all });
}
