import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';

export interface KBDoc {
  titulo: string;
  source_type: string;
  chunks: number;
  created_at: string;
  ids: number[];
}

export interface KnowledgeCompanyContext {
  company_context: string;
  kb_allow_internet_search: boolean;
}

export interface KnowledgeSearchResult {
  titulo: string;
  contenido: string;
  similarity: number;
}

export const knowledgeKeys = {
  all: ['knowledge'] as const,
  docs: (empresaId: number) => [...knowledgeKeys.all, 'docs', empresaId] as const,
  context: (empresaId: number) => [...knowledgeKeys.all, 'context', empresaId] as const,
};

export async function fetchKnowledgeDocs(empresaId: number): Promise<KBDoc[]> {
  const res = await apiFetch(`/api/knowledge/?empresa_id=${empresaId}`);
  if (!res.ok) return [];
  return res.json();
}

export async function fetchKnowledgeCompanyContext(
  empresaId: number,
): Promise<KnowledgeCompanyContext> {
  const res = await apiFetch(`/api/knowledge/company-context?empresa_id=${empresaId}`);
  if (!res.ok) {
    return { company_context: '', kb_allow_internet_search: false };
  }
  const data = await res.json();
  return {
    company_context: data.company_context || '',
    kb_allow_internet_search: Boolean(data.kb_allow_internet_search),
  };
}

export async function searchKnowledge(
  empresaId: number,
  query: string,
  threshold: number,
): Promise<KnowledgeSearchResult[]> {
  const params = new URLSearchParams({
    q: query.trim(),
    threshold: String(threshold),
    limit: '8',
    empresa_id: String(empresaId),
  });
  const res = await apiFetch(`/api/knowledge/search?${params}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.results || [];
}

export function useKnowledgeDocs(empresaId: number | null | undefined, enabled = true) {
  return useQuery({
    queryKey: knowledgeKeys.docs(empresaId ?? 0),
    queryFn: () => fetchKnowledgeDocs(empresaId!),
    enabled: enabled && Boolean(empresaId),
    staleTime: 30_000,
  });
}

export function useKnowledgeCompanyContext(
  empresaId: number | null | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: knowledgeKeys.context(empresaId ?? 0),
    queryFn: () => fetchKnowledgeCompanyContext(empresaId!),
    enabled: enabled && Boolean(empresaId),
    staleTime: 30_000,
  });
}

export function useInvalidateKnowledge() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
}
