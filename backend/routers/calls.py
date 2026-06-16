from fastapi import APIRouter, Depends, Query

from services.auth import CurrentUser, get_current_user
from services.calls_service import list_calls

router = APIRouter(prefix="/api", tags=["calls"])


def _resolve_empresa(user: CurrentUser, empresa_id_param: int | None) -> int | None:
    if user.role == "superadmin":
        return empresa_id_param
    return int(user.empresa_id or 0) if user.empresa_id else None


@router.get("/calls")
async def get_calls(
    empresa_id: int | None = Query(None),
    agent_id: int | None = Query(None),
    campaign_id: int | None = Query(None),
    status: str | None = Query(None),
    live_only: bool = Query(False),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Lista llamadas con estado en tiempo real (salas LiveKit activas).
    Multi-tenant: usuarios normales solo ven su empresa.
    """
    resolved_empresa = _resolve_empresa(current_user, empresa_id)
    return await list_calls(
        empresa_id=resolved_empresa,
        agent_id=agent_id,
        campaign_id=campaign_id,
        status=status,
        live_only=live_only,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
