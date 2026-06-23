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
echo "NUNCA hagas commit de .env ni .env.local."
