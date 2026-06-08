"""Helpers para llamadas backend → webhooks n8n (proxy con X-N8N-Secret)."""
from __future__ import annotations

import os


def n8n_webhook_base_url() -> str:
    return (os.getenv("N8N_WEBHOOK_BASE_URL") or "https://n8n.ausarta.net/webhook").rstrip("/")


def n8n_outbound_headers() -> dict[str, str]:
    """Cabeceras para el reverse proxy de n8n.ausarta.net."""
    secret = (os.getenv("N8N_PROXY_SECRET") or "").strip()
    if not secret:
        return {}
    return {"X-N8N-Secret": secret}
