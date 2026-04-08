"""
auth.py — Autenticación por API Key para endpoints protegidos.

Uso:
    from services.auth import require_api_key
    @router.post("/mi-endpoint", dependencies=[Depends(require_api_key)])
    async def mi_endpoint(): ...

Configuración:
    AUSARTA_API_KEY en variables de entorno (.env / docker-compose).
    El cliente envía la key en el header X-API-Key.
"""
import os
import logging
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger("api-backend")

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_valid_keys() -> set[str]:
    """
    Carga las API keys válidas del entorno.
    Soporta múltiples keys separadas por coma para rotación sin downtime.
    """
    raw = os.getenv("AUSARTA_API_KEY", "")
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


async def require_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> str:
    """
    Dependency de FastAPI que valida el header X-API-Key.

    Si AUSARTA_API_KEY no está configurada en el entorno, deja pasar todo
    (modo desarrollo). En producción, SIEMPRE debe estar definida.
    """
    valid_keys = _get_valid_keys()

    # Modo desarrollo: si no hay keys configuradas, no bloqueamos
    if not valid_keys:
        logger.debug("[Auth] AUSARTA_API_KEY no configurada — modo abierto (desarrollo).")
        return "dev-mode"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    if api_key not in valid_keys:
        logger.warning(f"[Auth] API Key inválida recibida: {api_key[:8]}...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )

    return api_key
