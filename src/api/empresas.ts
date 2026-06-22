import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/apiFetch';
import { fetchEmpresasList } from '../lib/campaignsSupabase';
import type { Empresa } from '../types';

export const empresaAdminKeys = {
  all: ['empresas', 'admin'] as const,
  list: (empresaId?: number) => [...empresaAdminKeys.all, empresaId ?? 'all'] as const,
};

export async function fetchEmpresasAdmin(empresaId?: number): Promise<Empresa[]> {
  try {
    const res = await apiFetch('/api/empresas');
    const data = await res.json();
    if (Array.isArray(data)) {
      if (empresaId) return data.filter((e: Empresa) => e.id === empresaId);
      return data;
    }
  } catch (err) {
    console.error('fetchEmpresasAdmin:', err);
  }
  return (await fetchEmpresasList(empresaId)) as Empresa[];
}

export function useEmpresasAdmin(empresaId?: number, enabled = true) {
  return useQuery({
    queryKey: empresaAdminKeys.list(empresaId),
    queryFn: () => fetchEmpresasAdmin(empresaId),
    enabled,
    staleTime: 60_000,
  });
}

export function useInvalidateEmpresasAdmin() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: empresaAdminKeys.all });
}
