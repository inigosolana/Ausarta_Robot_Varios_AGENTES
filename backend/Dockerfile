# Backend Dockerfile - API + Agent (Easypanel / Docker Compose)
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# Una sola capa: deps del sistema, pip y limpieza de compiladores
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        ffmpeg \
        curl \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Modelos/plugins de voz (Silero VAD, etc.) — evita descarga en la primera llamada
RUN python agent.py download-files 2>/dev/null || echo "⚠️ download-files omitido (se descargará en runtime)"

COPY start.sh /start.sh
COPY agent_start.sh /agent_start.sh
RUN chmod +x /start.sh /agent_start.sh

ENV PYTHONUNBUFFERED=1
ENV BRIDGE_SERVER_URL=http://127.0.0.1:8001

RUN groupadd -r appuser \
    && useradd -r -g appuser -u 1000 -d /app -s /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app /start.sh /agent_start.sh

USER appuser

EXPOSE 8001

CMD ["/start.sh"]
