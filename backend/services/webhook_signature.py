"""HMAC-SHA256 para webhooks entrantes y salientes (anti-spoofing)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time


def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "production").lower() not in (
        "development",
        "dev",
        "local",
        "test",
    )


def webhook_hmac_required() -> bool:
    """En producción exige X-Signature salvo WEBHOOK_REQUIRE_HMAC=false explícito."""
    explicit = os.getenv("WEBHOOK_REQUIRE_HMAC", "").strip().lower()
    if explicit in ("0", "false", "no"):
        return False
    if explicit in ("1", "true", "yes"):
        return True
    return _is_production()


def compute_webhook_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _normalize_signature_header(provided: str | None) -> str | None:
    if not provided or not str(provided).strip():
        return None
    sig = str(provided).strip()
    if sig.lower().startswith("sha256="):
        return sig.split("=", 1)[1].strip()
    if sig.lower().startswith("v1="):
        return sig.split("=", 1)[1].strip()
    return sig


def verify_webhook_signature(secret: str, body: bytes, provided_header: str | None) -> bool:
    if not secret or not body:
        return False
    provided = _normalize_signature_header(provided_header)
    if not provided:
        return False
    expected = compute_webhook_signature(secret, body)
    try:
        return hmac.compare_digest(expected, provided)
    except TypeError:
        return False


def verify_webhook_timestamp(
    timestamp_header: str | None,
    *,
    max_age_seconds: int = 300,
) -> bool:
    if not timestamp_header:
        return not webhook_hmac_required()
    try:
        ts = int(str(timestamp_header).strip())
    except ValueError:
        return False
    now = int(time.time())
    return abs(now - ts) <= max_age_seconds


def build_outbound_webhook_headers(secret: str, body: bytes) -> dict[str, str]:
    """Cabeceras para llamadas backend → n8n u otros webhooks."""
    if not secret:
        return {}
    ts = str(int(time.time()))
    headers = {
        "X-Signature": f"sha256={compute_webhook_signature(secret, body)}",
        "X-Webhook-Timestamp": ts,
    }
    return headers


def serialize_webhook_json(payload: dict) -> bytes:
    """Serialización estable para firmar y verificar el mismo byte-string."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def merge_legacy_n8n_secret(headers: dict[str, str], secret: str) -> dict[str, str]:
    """Compatibilidad transitoria: algunos flujos n8n aún validan X-N8N-Secret."""
    if secret:
        headers = dict(headers)
        headers["X-N8N-Secret"] = secret
    return headers
