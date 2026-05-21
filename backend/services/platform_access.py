"""
Matriz de acceso plataforma Ausarta vs tenant cliente.

- has_global_access: superadmin O admin de la empresa Ausarta (mismo poder de datos).
- can_create_ausarta_admins: solo superadmin (crear admin dentro de empresa Ausarta).
"""
from __future__ import annotations

import os
import logging
from typing import Optional

from services.auth import CurrentUser

logger = logging.getLogger("api-backend")

_MASTER_EMPRESA_ID_CACHE: Optional[int] = None


def get_master_empresa_id() -> Optional[int]:
    """ID de la empresa plataforma (Ausarta). Env AUSARTA_MASTER_EMPRESA_ID o 1 por defecto."""
    global _MASTER_EMPRESA_ID_CACHE
    if _MASTER_EMPRESA_ID_CACHE is not None:
        return _MASTER_EMPRESA_ID_CACHE

    raw = os.getenv("AUSARTA_MASTER_EMPRESA_ID") or os.getenv("MASTER_EMPRESA_ID")
    if raw:
        try:
            _MASTER_EMPRESA_ID_CACHE = int(raw)
            return _MASTER_EMPRESA_ID_CACHE
        except ValueError:
            logger.warning("AUSARTA_MASTER_EMPRESA_ID inválido: %s", raw)

    _MASTER_EMPRESA_ID_CACHE = 1
    return _MASTER_EMPRESA_ID_CACHE


def is_ausarta_platform_admin(user: CurrentUser) -> bool:
    master = get_master_empresa_id()
    return (
        user.role == "admin"
        and master is not None
        and user.empresa_id == master
    )


def has_global_access(user: CurrentUser) -> bool:
    """Acceso a todos los tenants (datos globales)."""
    if user.role == "superadmin":
        return True
    return is_ausarta_platform_admin(user)


def can_create_ausarta_admins(user: CurrentUser) -> bool:
    """Único privilegio exclusivo de superadmin respecto a admin Ausarta."""
    return user.role == "superadmin"
