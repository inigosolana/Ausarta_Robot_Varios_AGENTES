"""
Envío de email de recuperación de contraseña.

Prioridad:
1. n8n Recuperar_Password_Ausarta_v1 (https://n8n.ausarta.net)
2. SMTP configurado → Supabase generate_link + plantilla Ausarta en español
3. Supabase Auth /recover → email del SMTP del proyecto Supabase
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiohttp

from services.n8n_webhook_service import n8n_outbound_headers, n8n_webhook_base_url

logger = logging.getLogger("api-backend")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RECOVERY_SUBJECT = "Cómo restablecer tu contraseña — Ausarta Robot"
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "password_recovery_es.html"
_DEFAULT_RECOVERY_WEBHOOK_PATH = "fbdb6333-c473-493a-a1da-6c1756d5ae04"


from utils.env_validation import resolve_frontend_url


def _redirect_to(explicit: str | None = None) -> str:
    try:
        base = resolve_frontend_url(explicit)
    except ValueError:
        raise ValueError("FRONTEND_URL no configurada") from None
    return base if base.endswith("/login") else f"{base}/login"


def _service_role_key() -> str:
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
        or ""
    ).strip()


def _anon_key() -> str:
    return (
        os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("VITE_SUPABASE_ANON_KEY")
        or ""
    ).strip()


def _supabase_url() -> str:
    return (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")


def _smtp_configured() -> bool:
    return bool(
        (os.getenv("SMTP_HOST") or "").strip()
        and (os.getenv("SMTP_USER") or "").strip()
        and (os.getenv("SMTP_PASSWORD") or "").strip()
    )


def _build_recovery_html(action_link: str) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("{{ACTION_LINK}}", action_link)


async def _supabase_generate_recovery_link(email: str, redirect_to: str) -> str:
    base = _supabase_url()
    key = _service_role_key()
    if not base or not key:
        raise RuntimeError("Falta SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY")

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {
        "type": "recovery",
        "email": email,
        "options": {"redirect_to": redirect_to},
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base}/auth/v1/admin/generate_link",
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                logger.warning(
                    "[password-reset] generate_link HTTP %s: %s",
                    resp.status,
                    text[:300],
                )
                raise RuntimeError("No se pudo generar el enlace de recuperación")

            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {}

    action_link = data.get("action_link")
    if not action_link and isinstance(data.get("properties"), dict):
        action_link = data["properties"].get("action_link")
    if not action_link:
        raise RuntimeError("Supabase no devolvió enlace de recuperación")
    return str(action_link)


async def _supabase_recover_email(email: str, redirect_to: str) -> None:
    """Usa el SMTP del proyecto Supabase (mismo canal que invite_user_by_email)."""
    base = _supabase_url()
    key = _anon_key()
    if not base or not key:
        raise RuntimeError(
            "Configura SUPABASE_ANON_KEY (o VITE_SUPABASE_ANON_KEY) en el backend"
        )

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {"email": email, "redirect_to": redirect_to}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base}/auth/v1/recover",
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                logger.warning(
                    "[password-reset] recover HTTP %s: %s",
                    resp.status,
                    text[:300],
                )
                raise RuntimeError("No se pudo solicitar el email de recuperación")


def _send_smtp_email(to_email: str, subject: str, html_body: str) -> None:
    host = (os.getenv("SMTP_HOST") or "").strip()
    port = int((os.getenv("SMTP_PORT") or "587").strip())
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    from_addr = (os.getenv("SMTP_FROM") or user or "instalaciones@ausarta.es").strip()
    use_ssl = (os.getenv("SMTP_USE_SSL") or "").strip().lower() in ("1", "true", "yes")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(user, password)
            server.sendmail(from_addr, [to_email], msg.as_string())
        return

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [to_email], msg.as_string())


def _recovery_webhook_url() -> str:
    path = os.getenv(
        "N8N_PASSWORD_RECOVERY_WEBHOOK_PATH",
        _DEFAULT_RECOVERY_WEBHOOK_PATH,
    ).strip("/")
    return f"{n8n_webhook_base_url()}/{path}"


async def _n8n_password_reset(email: str, redirect_to: str) -> None:
    url = _recovery_webhook_url()
    payload = {"email": email, "redirect_to": redirect_to}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers=n8n_outbound_headers(),
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                logger.warning(
                    "[password-reset] n8n HTTP %s: %s",
                    resp.status,
                    text[:300],
                )
                raise RuntimeError("No se pudo enviar el email de recuperación")
            if not text.strip():
                raise RuntimeError("n8n respondió vacío; el workflow puede haber fallado")
            logger.info("[password-reset] n8n OK para %s: %s", email, text[:120])


async def update_user_password_with_token(access_token: str, password: str) -> None:
    """Actualiza la contraseña usando el access_token de la sesión de recovery."""
    base = _supabase_url()
    anon = _anon_key()
    if not base or not anon:
        raise RuntimeError("Falta configuración de Supabase en el backend")

    token = (access_token or "").strip()
    if not token:
        raise ValueError("Token de sesión inválido")
    if len(password) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres")

    headers = {
        "apikey": anon,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.put(
            f"{base}/auth/v1/user",
            json={"password": password},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                logger.warning(
                    "[password-reset] update password HTTP %s: %s",
                    resp.status,
                    text[:300],
                )
                try:
                    data = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    data = {}

                error_code = data.get("error_code", "")
                if error_code == "same_password":
                    raise ValueError("La nueva contraseña debe ser diferente a la actual.")
                if resp.status in (401, 403):
                    raise ValueError(
                        "La sesión de recuperación ha expirado. Solicita un nuevo enlace."
                    )
                if resp.status == 422:
                    msg = data.get("msg") or data.get("error") or "Contraseña no válida"
                    raise ValueError(msg)
                raise RuntimeError("No se pudo actualizar la contraseña")


async def send_password_reset_email(email: str, redirect_to: str | None = None) -> None:
    """
    Envía el email de recuperación. No revela si el email existe en Supabase.
  """
    normalized = (email or "").strip().lower()
    if not normalized or not _EMAIL_RE.match(normalized):
        raise ValueError("Email inválido")

    target_redirect = _redirect_to(redirect_to)

    try:
        await _n8n_password_reset(normalized, target_redirect)
        return
    except RuntimeError:
        logger.info("[password-reset] Fallback sin n8n para %s", normalized)
    except aiohttp.ClientError as exc:
        logger.warning("[password-reset] n8n no disponible: %s", exc)

    try:
        if _smtp_configured():
            action_link = await _supabase_generate_recovery_link(
                normalized, target_redirect
            )
            html = _build_recovery_html(action_link)
            await asyncio.to_thread(
                _send_smtp_email, normalized, _RECOVERY_SUBJECT, html
            )
            logger.info("[password-reset] Email enviado vía SMTP a %s", normalized)
            return

        await _supabase_recover_email(normalized, target_redirect)
        logger.info("[password-reset] Email solicitado vía Supabase Auth a %s", normalized)
    except (aiohttp.ClientError, OSError, smtplib.SMTPException) as exc:
        logger.error("[password-reset] Error de red/SMTP: %s", exc)
        raise RuntimeError("No se pudo enviar el email de recuperación") from exc
