"""
Endpoints de autenticación públicos (sin JWT).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

from services.password_reset_service import (
    send_password_reset_email,
    update_user_password_with_token,
)
from services.rate_limiter import limiter

logger = logging.getLogger("api-backend")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class PasswordResetRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    redirect_to: Optional[str] = Field(None, max_length=500)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


@router.post("/password-reset")
@limiter.limit("8/minute")
async def request_password_reset(request: Request):
    """
    Solicita un email de recuperación con plantilla Ausarta (español + instrucciones).
    Respuesta genérica para no revelar si el email existe.

    Nota: el body se lee con request.json() (no Pydantic en la firma) porque slowapi
    y el body injection de FastAPI no conviven bien y devuelven 422 "Field required".
    """
    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Petición inválida"})

    try:
        body = PasswordResetRequest.model_validate(raw)
    except ValidationError:
        return JSONResponse(status_code=400, content={"error": "Introduce un email válido"})

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


class PasswordUpdateRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


@router.put("/password")
@limiter.limit("10/minute")
async def update_password(request: Request):
    """Actualiza contraseña con el Bearer token de la sesión de recovery."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "Sesión inválida"})

    access_token = auth_header[7:].strip()
    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Petición inválida"})

    try:
        body = PasswordUpdateRequest.model_validate(raw)
    except ValidationError:
        return JSONResponse(
            status_code=400,
            content={"error": "La contraseña debe tener al menos 6 caracteres"},
        )

    try:
        await update_user_password_with_token(access_token, body.password)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception as exc:
        logger.warning("[password-reset] Fallo al actualizar: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": "No se pudo actualizar la contraseña. Inténtalo de nuevo."},
        )

    return {"status": "ok", "message": "Contraseña actualizada correctamente"}
