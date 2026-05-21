"""
Contexto de tenant por petición (async-safe) para aislamiento multi-tenant OWASP.

El empresa_id efectivo se establece tras autenticación (JWT / impersonation)
y se limpia al final de cada request HTTP vía middleware en api.py.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator, Optional

# empresa_id de la petición HTTP o tarea en curso (None = sin tenant / sistema)
current_empresa_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "current_empresa_id",
    default=None,
)


def get_current_empresa_id() -> Optional[int]:
    return current_empresa_id.get()


def set_current_empresa_id(empresa_id: Optional[int]) -> contextvars.Token:
    """Establece el tenant y devuelve un token para restaurar el valor anterior."""
    if empresa_id is not None:
        try:
            empresa_id = int(empresa_id)
        except (TypeError, ValueError):
            empresa_id = None
    return current_empresa_id.set(empresa_id)


def reset_current_empresa_id(token: contextvars.Token) -> None:
    current_empresa_id.reset(token)


@contextmanager
def bind_tenant_context(empresa_id: Optional[int]) -> Iterator[None]:
    """Context manager para jobs ARQ, Yeastar, etc. sin request HTTP."""
    token = set_current_empresa_id(empresa_id)
    try:
        yield
    finally:
        reset_current_empresa_id(token)
