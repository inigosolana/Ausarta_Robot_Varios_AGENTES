#!/usr/bin/env bash
# Crea .env y .env.local desde las plantillas (sin sobrescribir si ya existen).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

copy_if_missing() {
  local src="$1"
  local dst="$2"
  if [[ -f "$dst" ]]; then
    echo "  · $dst ya existe — no se modifica"
  else
    cp "$src" "$dst"
    echo "  ✓ Creado $dst desde $src"
  fi
}

echo "==> Configuración de entorno Ausarta"
echo ""

copy_if_missing ".env.example" ".env"
copy_if_missing ".env.local.example" ".env.local"

# Backend local (uvicorn/pytest) lee backend/.env o variables del entorno
if [[ -f .env ]]; then
  if [[ -e backend/.env ]]; then
    echo "  · backend/.env ya existe — no se modifica"
  else
    ln -sf ../.env backend/.env
    echo "  ✓ Enlace backend/.env → ../.env"
  fi
fi

echo ""
echo "Siguiente paso:"
echo "  1. Edita .env con tus claves reales (Supabase, LiveKit, Redis, etc.)"
echo "  2. Edita .env.local si vas a usar npm run dev"
echo "  3. Servidor: ./scripts/deploy-compose.sh"
echo "  4. Validar APIs: cd backend && python scripts/check_env_apis.py"
echo ""
# Validación de variables de seguridad críticas
echo ""
echo "==> Validando variables de seguridad obligatorias..."
_MISSING_VARS=0

check_required_var() {
  local varname="$1"
  local hint="$2"
  local value
  value=$(grep -E "^${varname}=" .env 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)
  if [[ -z "$value" || "$value" == '""' || "$value" == "''" ]]; then
    echo "  ✗ $varname no está definida o está vacía. $hint"
    _MISSING_VARS=$((_MISSING_VARS + 1))
  else
    echo "  ✓ $varname definida"
  fi
}

check_required_var "AGENTS_API_KEY"         "Necesaria para autenticar el agente LiveKit contra el backend."
check_required_var "DOZZLE_PASSWORD"        "Necesaria para proteger el visor de logs Docker."
check_required_var "IMPERSONATION_SECRET"   "Necesaria para tokens de impersonación admin."
check_required_var "REDIS_PASSWORD"         "Necesaria para autenticar Redis en producción."
check_required_var "SUPABASE_JWT_SECRET"    "Necesaria para validar tokens de sesión."

if [[ $_MISSING_VARS -gt 0 ]]; then
  echo ""
  echo "  ⚠️  $_MISSING_VARS variable(s) de seguridad sin definir. Edita .env antes de desplegar."
fi
echo ""
echo "NUNCA hagas commit de .env ni .env.local."
