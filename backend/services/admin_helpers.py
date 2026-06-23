"""Utilidades compartidas para routers de administración."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time

from fastapi import HTTPException

from services.platform_access import get_master_empresa_id
from services.supabase_service import supabase
from utils.env_validation import get_impersonation_secret

logger = logging.getLogger("api-backend")

def canonical_role(raw_role: str | None) -> str:
    role = (raw_role or "").strip().lower()
    if role == "superadmin":
        return "superadmin"
    if role in {"admin", "admin_empresa"}:
        return "admin"
    if role in {"user", "viewer"}:
        return "user"
    return role


def resolve_master_empresa_id() -> int | None:
    """Tenant Ausarta: env primero, luego consulta BD."""
    env_id = get_master_empresa_id()
    if env_id:
        return env_id
    if not supabase:
        return None
    try:
        res = (
            supabase.table("empresas")
            .select("id,nombre")
            .ilike("nombre", "ausarta")
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0].get("id")
    except Exception as e:
        logger.warning(f"⚠️ [admin] No se pudo resolver empresa maestra Ausarta: {e}")
    return None


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def sign_impersonation_payload(payload: dict) -> str:
    """
    Token firmado (HMAC SHA-256) para modo impersonation.
    Formato: base64url(json).base64url(signature)
    """
    try:
        secret = get_impersonation_secret()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not secret:
        raise HTTPException(status_code=500, detail="IMPERSONATION_SECRET no configurado")
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return f"{b64url(raw)}.{b64url(sig)}"


def canonical_impersonation_role(raw_role: str | None) -> str:
    role = canonical_role(raw_role)
    # El modo de soporte debe simular contexto de cliente, nunca superadmin.
    if role not in {"admin", "user"}:
        return "admin"
    return role


VALID_PLANS = {"basico", "profesional", "enterprise"}
