"""Validación de variables de entorno críticas."""

from __future__ import annotations

import os


def is_non_production() -> bool:
    return os.getenv("ENVIRONMENT", "production").lower() in (
        "development",
        "dev",
        "local",
        "test",
    )


def resolve_frontend_url(explicit: str | None = None) -> str:
    """URL pública del frontend. Obligatoria en producción."""
    if explicit and str(explicit).strip():
        return str(explicit).strip().rstrip("/")
    url = (os.getenv("INVITE_REDIRECT_TO") or os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    if url:
        return url
    if is_non_production():
        return "http://localhost:8080"
    raise ValueError("FRONTEND_URL no configurada")


def get_impersonation_secret() -> str:
    """Secreto HMAC para tokens de impersonación. Sin fallback a SERVICE_ROLE_KEY."""
    secret = (os.getenv("IMPERSONATION_SECRET") or "").strip()
    if secret:
        return secret
    if is_non_production():
        return ""
    raise RuntimeError("IMPERSONATION_SECRET es obligatorio en producción")


def validate_startup_config() -> list[str]:
    """Comprueba configuración crítica al arrancar. Devuelve warnings (no fatal en dev)."""
    issues: list[str] = []
    if is_non_production():
        return issues
    if not (os.getenv("FRONTEND_URL") or "").strip():
        issues.append("FRONTEND_URL no definida")
    if not (os.getenv("IMPERSONATION_SECRET") or "").strip():
        issues.append("IMPERSONATION_SECRET no definido (no usar SERVICE_ROLE_KEY como fallback)")
    return issues
