"""
Endpoints de autenticación públicos (sin JWT).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from services.password_reset_service import send_password_reset_email

logger = logging.getLogger("api-backend")
router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


class PasswordResetRequest(BaseModel):
    email: EmailStr
    redirect_to: Optional[str] = Field(None, max_length=500)


@router.post("/password-reset")
@limiter.limit("8/minute")
async def request_password_reset(request: Request, body: PasswordResetRequest):
    """
    Solicita un email de recuperación con plantilla Ausarta (español + instrucciones).
    Respuesta genérica para no revelar si el email existe.
    """
    try:
        await send_password_reset_email(body.email, body.redirect_to)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Email inválido"})
    except Exception as exc:
        logger.warning("[password-reset] Fallo al enviar: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": "No se pudo enviar el email. Inténtalo de nuevo en unos minutos."},
        )

    return {
        "status": "ok",
        "message": (
            "Si el email está registrado, recibirás un mensaje con instrucciones "
            "para crear una nueva contraseña."
        ),
    }
