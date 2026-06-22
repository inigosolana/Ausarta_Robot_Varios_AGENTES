/** Tokens de sesión sensibles en memoria (no persistir en localStorage). */

let impersonateToken: string | null = null;

export function setImpersonateToken(token: string | null): void {
  impersonateToken = token;
}

export function getImpersonateToken(): string | null {
  return impersonateToken;
}

export function clearSessionAuth(): void {
  impersonateToken = null;
  sessionStorage.removeItem('spoofedRole');
  sessionStorage.removeItem('spoofedEmpresa');
}
