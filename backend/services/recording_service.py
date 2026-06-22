"""
recording_service.py — Grabación de llamadas via LiveKit Egress + Supabase Storage.

Configuración requerida en .env / docker-compose.yml:
    ENABLE_RECORDING=true
    RECORDING_BUCKET=call-recordings
    SUPABASE_S3_ACCESS_KEY
    SUPABASE_S3_SECRET_KEY
    SUPABASE_URL

Pasos en Supabase (solo una vez):
    1. Storage → New bucket → nombre: "call-recordings" → Public: OFF
    2. Storage → S3 Access → Copiar Access Key ID y Secret Access Key
    3. Añadir esas credenciales al .env con los nombres indicados arriba.
"""

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger("api-backend")

ENABLE_RECORDING: bool = os.getenv("ENABLE_RECORDING", "").lower() in ("1", "true", "yes")
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_S3_ACCESS_KEY: str = os.getenv("SUPABASE_S3_ACCESS_KEY", "")
SUPABASE_S3_SECRET_KEY: str = os.getenv("SUPABASE_S3_SECRET_KEY", "")
RECORDING_BUCKET: str = os.getenv("RECORDING_BUCKET", "call-recordings")
SIGNED_URL_TTL_SECONDS: int = int(os.getenv("RECORDING_SIGNED_URL_TTL", "3600"))

# encuesta_id → egress_id (en memoria — el worker es un proceso único por container)
_active_egress: dict[int, str] = {}


def _s3_endpoint() -> str:
    """URL del endpoint S3-compatible de Supabase Storage."""
    project_ref = SUPABASE_URL.replace("https://", "").split(".")[0]
    return f"https://{project_ref}.supabase.co/storage/v1/s3"


def _recording_path(encuesta_id: int) -> str:
    return f"recordings/{encuesta_id}.ogg"


async def create_signed_recording_url(encuesta_id: int, *, expires_in: int | None = None) -> Optional[str]:
    """Genera URL firmada de corta duración para un archivo de grabación privado."""
    from services.supabase_service import supabase

    if not supabase:
        return None

    ttl = expires_in if expires_in is not None else SIGNED_URL_TTL_SECONDS
    path = _recording_path(encuesta_id)

    def _sign() -> dict:
        return supabase.storage.from_(RECORDING_BUCKET).create_signed_url(path, ttl)

    try:
        result = await asyncio.to_thread(_sign)
        if isinstance(result, dict):
            return result.get("signedURL") or result.get("signed_url")
        return getattr(result, "signedURL", None) or getattr(result, "signed_url", None)
    except Exception as exc:
        logger.warning("[Recording] No se pudo firmar URL para encuesta %s: %s", encuesta_id, exc)
        return None


async def start_recording(room_name: str, encuesta_id: int) -> Optional[str]:
    """
    Inicia una grabación de audio de la sala vía LiveKit Egress.
    La salida se sube directamente a Supabase Storage (S3-compatible).
    Retorna el egress_id si se pudo iniciar, None en caso contrario.
    """
    if not ENABLE_RECORDING:
        return None

    if not SUPABASE_S3_ACCESS_KEY or not SUPABASE_S3_SECRET_KEY:
        logger.warning(
            "[Recording] ENABLE_RECORDING=true pero faltan SUPABASE_S3_ACCESS_KEY / "
            "SUPABASE_S3_SECRET_KEY. Grabación desactivada."
        )
        return None

    try:
        from services.livekit_service import lkapi
        from livekit.api import (
            RoomCompositeEgressRequest,
            EncodedFileOutput,
            EncodedFileType,
            S3Upload,
        )

        egress_info = await lkapi.egress.start_room_composite_egress(
            RoomCompositeEgressRequest(
                room_name=room_name,
                audio_only=True,
                file_outputs=[
                    EncodedFileOutput(
                        file_type=EncodedFileType.OGG,
                        filepath=_recording_path(encuesta_id),
                        s3=S3Upload(
                            access_key=SUPABASE_S3_ACCESS_KEY,
                            secret=SUPABASE_S3_SECRET_KEY,
                            bucket=RECORDING_BUCKET,
                            region="us-east-1",
                            endpoint=_s3_endpoint(),
                            force_path_style=True,
                        ),
                    )
                ],
            )
        )

        egress_id: str = egress_info.egress_id
        _active_egress[encuesta_id] = egress_id
        logger.info("🎙️ [Recording] Egress iniciado egress_id=%s para encuesta %s", egress_id, encuesta_id)
        return egress_id

    except Exception as exc:
        logger.warning("⚠️ [Recording] No se pudo iniciar grabación para encuesta %s: %s", encuesta_id, exc)
        return None


async def stop_recording(encuesta_id: int) -> Optional[str]:
    """
    Para la grabación asociada a una encuesta.
    Retorna una signed URL (bucket privado) si el egress estaba activo, None si no.
    """
    if not ENABLE_RECORDING:
        return None

    egress_id = _active_egress.pop(encuesta_id, None)
    if not egress_id:
        return None

    try:
        from services.livekit_service import lkapi
        from livekit.api import StopEgressRequest

        await lkapi.egress.stop_egress(StopEgressRequest(egress_id=egress_id))
        url = await create_signed_recording_url(encuesta_id)
        logger.info("✅ [Recording] Grabación parada egress_id=%s encuesta=%s", egress_id, encuesta_id)
        return url

    except Exception as exc:
        logger.warning("⚠️ [Recording] Error al parar egress %s: %s", egress_id, exc)
        return None
