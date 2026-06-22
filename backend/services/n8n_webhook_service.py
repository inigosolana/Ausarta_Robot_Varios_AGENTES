"""Helpers para llamadas backend → webhooks n8n (HMAC + legacy X-N8N-Secret)."""
from __future__ import annotations

import os

from services.webhook_signature import (
    build_outbound_webhook_headers,
    merge_legacy_n8n_secret,
    serialize_webhook_json,
)


def n8n_webhook_base_url() -> str:
    return (os.getenv("N8N_WEBHOOK_BASE_URL") or "https://n8n.ausarta.net/webhook").rstrip("/")


def n8n_outbound_headers(payload: dict | None = None, *, body: bytes | None = None) -> dict[str, str]:
    """Cabeceras firmadas para el reverse proxy de n8n.ausarta.net."""
    secret = (os.getenv("N8N_PROXY_SECRET") or "").strip()
    if body is None and payload is not None:
        body = serialize_webhook_json(payload)
    if body is None:
        body = b"{}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if not secret:
        return headers
    headers.update(build_outbound_webhook_headers(secret, body))
    return merge_legacy_n8n_secret(headers, secret)
