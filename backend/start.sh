#!/bin/bash

# Script de inicio para backend (API + Agent)
# La API queda en primer plano: si el agente LiveKit falla, la web sigue respondiendo.

echo "🚀 Iniciando Backend de Ausarta Robot..."
echo ""

echo "🤖 Iniciando LiveKit Agent (background)..."
python agent.py dev &
AGENT_PID=$!
echo "   ✅ Agent PID: $AGENT_PID"

sleep 3

echo "🔧 Iniciando API FastAPI en puerto 8001..."
exec uvicorn api:app --host 0.0.0.0 --port 8001
