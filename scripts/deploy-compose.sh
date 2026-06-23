#!/usr/bin/env bash
# Despliegue en servidor con Docker Compose (sin Portainer).
# Uso:
#   cp .env.example .env
#   nano .env          # rellena claves reales
#   ./scripts/deploy-compose.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: Falta .env en la raíz del proyecto."
  echo "  ./scripts/setup-env.sh"
  echo "  nano .env"
  exit 1
fi

if ! command -v docker &>/dev/null; then
  echo "ERROR: Docker no está instalado."
  exit 1
fi

if docker compose version &>/dev/null; then
  COMPOSE=(docker compose)
elif command -v docker-compose &>/dev/null; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: No se encontró 'docker compose' ni 'docker-compose'."
  exit 1
fi

echo "==> Build e inicio de servicios (${COMPOSE[*]})..."
"${COMPOSE[@]}" up -d --build

echo ""
echo "==> Estado:"
"${COMPOSE[@]}" ps

echo ""
echo "Listo."
echo "  Frontend:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"
echo "  Backend:   http://$(hostname -I 2>/dev/null | awk '{print $1}'):8003"
echo "  Logs:      ${COMPOSE[*]} logs -f backend livekit-agent"
