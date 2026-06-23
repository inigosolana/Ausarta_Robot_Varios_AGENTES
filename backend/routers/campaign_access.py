"""Helpers de acceso multitenant compartidos por routers de campañas."""
from __future__ import annotations

import logging

from fastapi import HTTPException

from services.auth import CurrentUser
from services.supabase_service import supabase

logger = logging.getLogger("api-backend")


def resolve_campaign_empresa(user: CurrentUser, empresa_id_param: int | None = None) -> int | None:
    if user.role == "superadmin" and empresa_id_param:
        return empresa_id_param
    return int(user.empresa_id or 0) if user.empresa_id else None


def raise_not_found_if_cross_tenant(user: CurrentUser, empresa_id: int | None) -> None:
    if user.role != "superadmin" and int(empresa_id or 0) != int(user.empresa_id or 0):
        raise HTTPException(status_code=404, detail="Not found")


def load_campaign_or_404(campaign_id: int, user: CurrentUser) -> dict:
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")
    res = supabase.table("campaigns").select("*").eq("id", campaign_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign = res.data[0]
    raise_not_found_if_cross_tenant(user, campaign.get("empresa_id"))
    return campaign


def load_external_db_allowed_queries(empresa_id: int | None) -> list[str]:
    """Lista blanca de queries CRM/ERP permitidos para consultar_cliente."""
    if not empresa_id or not supabase:
        return []
    try:
        res = (
            supabase.table("empresa_external_db")
            .select("queries")
            .eq("empresa_id", empresa_id)
            .eq("activo", True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return []
        queries = res.data[0].get("queries") or {}
        if isinstance(queries, dict):
            return [str(k).strip() for k in queries.keys() if str(k).strip()]
    except Exception as err:
        logger.warning(
            "No se pudo cargar external_db_allowed_queries para empresa %s: %s",
            empresa_id,
            err,
        )
    return []
