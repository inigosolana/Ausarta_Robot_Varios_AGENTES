"""
Middleware HTTP: limpia y aísla el ContextVar de empresa_id por petición.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from services.tenant_context import reset_current_empresa_id, set_current_empresa_id


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    Resetea el tenant al inicio de cada request y restaura al finalizar.
    get_current_user (y rutas con API key) establecen el empresa_id efectivo.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        token = set_current_empresa_id(None)
        try:
            return await call_next(request)
        finally:
            reset_current_empresa_id(token)
