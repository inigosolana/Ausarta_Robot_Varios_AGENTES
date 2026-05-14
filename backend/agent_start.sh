#!/bin/bash
# Arranque del worker LiveKit con preflight visible en logs de Docker/Portainer.

set -u

AGENT_NAME="${AGENT_NAME_DISPATCH:-default_agent}"

echo "=============================================="
echo " Ausarta LiveKit Agent Worker"
echo " $(date -Iseconds 2>/dev/null || date)"
echo "=============================================="
echo " AGENT_NAME_DISPATCH=${AGENT_NAME}"
echo " LIVEKIT_URL=${LIVEKIT_URL:-<NO DEFINIDA>}"
echo " LIVEKIT_API_KEY: $([ -n "${LIVEKIT_API_KEY:-}" ] && echo 'OK' || echo 'FALTA')"
echo " LIVEKIT_API_SECRET: $([ -n "${LIVEKIT_API_SECRET:-}" ] && echo 'OK' || echo 'FALTA')"
echo " DEEPGRAM_API_KEY: $([ -n "${DEEPGRAM_API_KEY:-}" ] && echo 'OK' || echo 'FALTA')"
echo " CARTESIA_API_KEY: $([ -n "${CARTESIA_API_KEY:-}" ] && echo 'OK' || echo 'FALTA')"
echo " GROQ_API_KEY: $([ -n "${GROQ_API_KEY:-}" ] && echo 'OK' || echo 'FALTA')"
echo " OPENAI_API_KEY: $([ -n "${OPENAI_API_KEY:-}" ] && echo 'OK' || echo 'FALTA')"
echo " BRIDGE_SERVER_URL=${BRIDGE_SERVER_URL:-http://backend:8001}"
echo "=============================================="

if [ -z "${LIVEKIT_URL:-}" ] || [ -z "${LIVEKIT_API_KEY:-}" ] || [ -z "${LIVEKIT_API_SECRET:-}" ]; then
  echo "FATAL: Faltan LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET en stack.env"
  echo "El contenedor se queda vivo para que puedas leer este error en Portainer."
  tail -f /dev/null
  exit 1
fi

while true; do
  echo ""
  echo ">>> Iniciando python agent.py start (${AGENT_NAME})..."
  python agent.py start
  code=$?
  echo ">>> Worker terminó con código ${code}. Reinicio en 10s..."
  sleep 10
done
