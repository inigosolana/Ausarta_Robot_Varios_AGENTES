import type { UserProfile } from '../types';

export function isAusartaEmpresa(profile: Pick<UserProfile, 'empresas'> | null | undefined): boolean {
  return profile?.empresas?.nombre?.toLowerCase() === 'ausarta';
}

export function canUseSimulationMode(
  profile: Pick<UserProfile, 'role' | 'empresas'> | null | undefined,
): boolean {
  if (!profile) return false;
  if (profile.role === 'superadmin') return true;
  return profile.role === 'admin' && isAusartaEmpresa(profile);
}

/** Superadmin o admin de la empresa Ausarta (gestión plataforma). */
export function canManageApiKeys(
  profile: Pick<UserProfile, 'role' | 'empresas'> | null | undefined,
): boolean {
  return canUseSimulationMode(profile);
}
