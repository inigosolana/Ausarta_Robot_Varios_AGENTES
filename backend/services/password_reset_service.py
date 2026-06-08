"""
Envío de email de recuperación de contraseña vía n8n (plantilla Ausarta en español).
"""
from __future__ import annotations

import logging
import os
import re

import aiohttp

logger = logging.getLogger("api-backend")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _recovery_webhook_url() -> str:
    base = (os.getenv("N8N_WEBHOOK_BASE_URL") or "https://n8n.ausarta.net/webhook").rstrip("/")
    path = os.getenv(
        "N8N_PASSWORD_RECOVERY_WEBHOOK_PATH",
        "fbdb6333-c473-493a-a1da-6c1756d5ae04",
    ).strip("/")
    return f"{base}/{path}"


def _redirect_to(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip().rstrip("/")
    return (
        os.getenv("INVITE_REDIRECT_TO")
        or os.getenv("FRONTEND_URL")
        or "https://app.ausarta.net"
    ).strip().rstrip("/")


async def send_password_reset_email(email: str, redirect_to: str | None = None) -> None:
    """
    Encola el email de recuperación en n8n. No lanza si el email no existe en Supabase
    (n8n/Supabase responden igual); errores de red se registran y se propagan.
    """
    normalized = (email or "").strip().lower()
    if not normalized or not _EMAIL_RE.match(normalized):
        raise ValueError("Email inválido")

    payload = {
        "email": normalized,
        "redirect_to": _redirect_to(redirect_to),
    }
    url = _recovery_webhook_url()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.warning(
                        "[password-reset] n8n respondió HTTP %s: %s",
                        resp.status,
                        text[:300],
                    )
                    raise RuntimeError("No se pudo enviar el email de recuperación")
                logger.info("[password-reset] Solicitud enviada a n8n para %s", normalized)
    except aiohttp.ClientError as exc:
        logger.error("[password-reset] Error de red con n8n: %s", exc)
        raise RuntimeError("No se pudo conectar con el servicio de recuperación") from exc
