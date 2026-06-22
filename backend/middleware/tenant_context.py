"""
Middleware HTTP: limpia y aísla el ContextVar de empresa_id por petición.

También expone validación de cortafuego financiero (límite de gasto mensual).
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from services.tenant_context import reset_current_empresa_id, set_current_empresa_id


async def assert_tenant_within_spending_limit(empresa_id: int) -> None:
    """
    Bloquea emisión de nuevas llamadas si el tenant superó su tope mensual (HTTP 402).
    Usar en validación de inicio de llamada outbound/campañas.
    """
    from services.billing_limits_service import enforce_tenant_spending_limit

    await enforce_tenant_spending_limit(int(empresa_id), raise_http=True)


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
