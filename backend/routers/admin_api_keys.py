"""API keys por tenant (admin plataforma)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from models.schemas import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyListItem
from services.api_key_service import create_api_key, list_api_keys, revoke_api_key
from services.audit import log_audit_event
from services.auth import CurrentUser, require_platform_admin
from services.rate_limiter import limiter

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/api-keys", response_model=list[ApiKeyListItem])
async def list_tenant_api_keys(
    empresa_id: int | None = None,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """Lista API keys (solo plataforma Ausarta). Sin valor en claro."""
    rows = await list_api_keys(empresa_id=empresa_id)
    return rows


@router.post("/api-keys", response_model=ApiKeyCreateResponse)
@limiter.limit("10/minute")
async def create_tenant_api_key(
    request: Request,
    payload: ApiKeyCreateRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """Genera una API key para un tenant. El valor en claro solo se devuelve una vez."""
    if not payload.empresa_id:
        raise HTTPException(status_code=400, detail="empresa_id requerido")

    target_empresa = int(payload.empresa_id)

    if current_user.role != "superadmin":
        forbidden = [s for s in payload.scopes if s in ("admin", "*")]
        if forbidden:
            raise HTTPException(
                status_code=403,
                detail="Solo superadmin puede crear keys con scope admin",
            )

    try:
        created = await create_api_key(
            empresa_id=target_empresa,
            description=payload.description,
            scopes=payload.scopes,
            expires_at=payload.expires_at,
            created_by=current_user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await log_audit_event(
        user_id=current_user.user_id,
        action="api_key.create",
        target_type="api_key",
        target_id=created["id"],
        metadata={"empresa_id": target_empresa, "scopes": created["scopes"]},
    )
    return created


@router.delete("/api-keys/{key_id}")
@limiter.limit("20/minute")
async def revoke_tenant_api_key(
    request: Request,
    key_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """Revoca una API key (is_active=false)."""
    revoked = await revoke_api_key(key_id, empresa_id=None)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key no encontrada")

    await log_audit_event(
        user_id=current_user.user_id,
        action="api_key.revoke",
        target_type="api_key",
        target_id=key_id,
        metadata={"empresa_id": None},
    )
    return {"status": "revoked", "id": key_id}
