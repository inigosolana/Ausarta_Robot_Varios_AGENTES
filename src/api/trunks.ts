import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch, fetchTrunks, type TelephonyTrunksResponse } from '../lib/apiFetch';

export type TrunkEmpresaRow = {
  id: number;
  nombre: string;
  sip_outbound_trunk_id?: string | null;
  sip_inbound_trunk_id?: string | null;
};

export type TrunkExtension = {
  id: string;
  extension_number: string;
  extension_name: string | null;
  departamento: string | null;
};

export const trunkKeys = {
  all: ['trunks'] as const,
  empresas: ['trunks', 'empresas'] as const,
  extensions: (empresaId: number) => ['trunks', 'extensions', empresaId] as const,
  data: (empresaId: number) => ['trunks', 'data', empresaId] as const,
};

export async function fetchTrunkEmpresas(): Promise<TrunkEmpresaRow[]> {
  const res = await apiFetch('/api/admin/empresas');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data: TrunkEmpresaRow[] = await res.json();
  return data || [];
}

export async function fetchTrunkExtensions(empresaId: number): Promise<TrunkExtension[]> {
  const res = await apiFetch(`/api/empresas/${empresaId}/extensions`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data: TrunkExtension[] = await res.json();
  return data || [];
}

export async function fetchTrunksData(empresaId: number): Promise<TelephonyTrunksResponse> {
  return fetchTrunks(empresaId);
}

export function useTrunkEmpresas(enabled = true) {
  return useQuery({
    queryKey: trunkKeys.empresas,
    queryFn: fetchTrunkEmpresas,
    enabled,
    staleTime: 60_000,
  });
}

export function useTrunkExtensions(empresaId: number | null, enabled = true) {
  return useQuery({
    queryKey: empresaId ? trunkKeys.extensions(empresaId) : ['trunks', 'extensions', 'none'],
    queryFn: () => fetchTrunkExtensions(empresaId!),
    enabled: enabled && empresaId != null,
    staleTime: 30_000,
  });
}

export function useTrunksData(empresaId: number | null, enabled = true) {
  return useQuery({
    queryKey: empresaId ? trunkKeys.data(empresaId) : ['trunks', 'data', 'none'],
    queryFn: () => fetchTrunksData(empresaId!),
    enabled: enabled && empresaId != null,
    staleTime: 30_000,
  });
}

export function useInvalidateTrunks() {
  const queryClient = useQueryClient();
  return {
    invalidateEmpresas: () => queryClient.invalidateQueries({ queryKey: trunkKeys.empresas }),
    invalidateExtensions: (empresaId: number) =>
      queryClient.invalidateQueries({ queryKey: trunkKeys.extensions(empresaId) }),
    invalidateTrunksData: (empresaId: number) =>
      queryClient.invalidateQueries({ queryKey: trunkKeys.data(empresaId) }),
    updateEmpresaRow: (empresaId: number, patch: Partial<TrunkEmpresaRow>) => {
      queryClient.setQueryData<TrunkEmpresaRow[]>(trunkKeys.empresas, (prev) =>
        (prev || []).map((row) => (row.id === empresaId ? { ...row, ...patch } : row)),
      );
    },
  };
}
