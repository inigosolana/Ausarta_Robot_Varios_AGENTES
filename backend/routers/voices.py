from fastapi import APIRouter, Depends, Query

from services.auth import CurrentUser, get_current_user
from services.cartesia_voices_service import list_voices

router = APIRouter(prefix="/api", tags=["voices"])


@router.get("/voices")
async def get_voices(
    language: str | None = Query(None, description="Filtrar por idioma (es, en, eu, gl)"),
    _user: CurrentUser = Depends(get_current_user),
):
    """Lista voces Cartesia disponibles para configurar agentes."""
    return await list_voices(language=language)
