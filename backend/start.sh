#!/bin/bash

# API FastAPI únicamente. El worker LiveKit corre en el servicio livekit-agent (docker-compose).

echo "🚀 Iniciando API Backend Ausarta Robot (puerto 8001)..."
echo "   ℹ️  El agente de voz corre en el contenedor livekit-agent."
exec uvicorn api:app --host 0.0.0.0 --port 8001
