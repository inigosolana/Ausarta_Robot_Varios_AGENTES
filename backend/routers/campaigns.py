"""
Motor de Campañas — rutas HTTP (CRUD, detalle, export, arranque).

El goteo (drip), locks y scheduler viven en services/campaign_drip.py y campaign_locks.py.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from models.schemas import CampaignLeadModel, CampaignModel
from routers.campaign_access import (
    load_campaign_or_404,
    raise_not_found_if_cross_tenant as _raise_not_found_if_cross_tenant,
    resolve_campaign_empresa as _resolve_empresa,
)
from services.auth import CurrentUser, get_current_user, require_admin
from services.campaign_ab_service import compute_campaign_ab_stats
from services.campaign_crud_service import (
    create_campaign_record,
    delete_campaign_record,
    list_campaigns_for_user,
    start_campaign_record,
    update_campaign_record,
)
from services.campaign_details_service import fetch_campaign_details, fetch_result_transcription
from services.campaign_export_service import build_campaign_results_csv
from services.campaign_simulate_service import simulate_campaign_dispatch
from services.supabase_service import supabase

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["campaigns"])


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, current_user: CurrentUser = Depends(require_admin)):
    load_campaign_or_404(campaign_id, current_user)
    try:
        return await delete_campaign_record(campaign_id, current_user)
    except Exception as err:
        logger.error("Error deleting campaign: %s", err)
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.post("/campaigns")
async def create_campaign(
    campaign: CampaignModel,
    leads: List[CampaignLeadModel],
    current_user: CurrentUser = Depends(require_admin),
):
    try:
        return await create_campaign_record(campaign, leads, current_user)
    except Exception as err:
        logger.error("Error creando campaña: %s", err)
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.put("/campaigns/{campaign_id}")
async def update_campaign(
    campaign_id: int,
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    load_campaign_or_404(campaign_id, current_user)
    try:
        result = await update_campaign_record(campaign_id, payload, current_user)
        if isinstance(result, JSONResponse):
            return result
        return result
    except Exception as err:
        logger.error("Error updating campaign %s: %s", campaign_id, err)
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.get("/campaigns")
async def list_campaigns(
    empresa_id: Optional[int] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        scoped_empresa = _resolve_empresa(current_user, empresa_id)
        return list_campaigns_for_user(scoped_empresa)
    except Exception as err:
        logger.error("Error listing campaigns: %s", err)
        return []


@router.get("/campaigns/{campaign_id}/ab-stats")
async def get_campaign_ab_stats(
    campaign_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    """Métricas de conversión por variante A/B de una campaña."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    camp_res = supabase.table("campaigns").select(
        "id, empresa_id, name, agent_id, agent_id_b, ab_test_enabled, ab_split_ratio"
    ).eq("id", campaign_id).limit(1).execute()
    if not camp_res.data:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")

    campaign = camp_res.data[0]
    if current_user.role != "superadmin" and campaign.get("empresa_id") != current_user.empresa_id:
        raise HTTPException(status_code=403, detail="Sin permiso para esta campaña")

    enc_res = supabase.table("encuestas").select(
        "id, ab_variant, status, agent_id, puntuacion_comercial, agent_results"
    ).eq("campaign_id", campaign_id).execute()
    return compute_campaign_ab_stats(campaign, enc_res.data or [])


@router.get("/campaigns/{campaign_id}")
async def get_campaign_details(
    campaign_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        payload = await fetch_campaign_details(campaign_id)
        if not payload:
            return JSONResponse(status_code=404, content={"error": "Campaign not found"})
        _raise_not_found_if_cross_tenant(current_user, payload["campaign"].get("empresa_id"))
        return payload
    except HTTPException:
        raise
    except Exception as err:
        logger.error("Error getting campaign details %s: %s", campaign_id, err)
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.get("/results/{result_id}/transcription")
async def get_result_transcription(
    result_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        transcription, empresa_id = fetch_result_transcription(result_id)
        if empresa_id is not None:
            _raise_not_found_if_cross_tenant(current_user, empresa_id)
        return {"transcription": transcription}
    except HTTPException:
        raise
    except Exception as err:
        return {"error": str(err)}


@router.post("/campaigns/{campaign_id}/simulate")
async def simulate_campaign(
    campaign_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    """Dry-run: cuántos leads se procesarían sin lanzar llamadas."""
    camp = load_campaign_or_404(campaign_id, current_user)
    return await simulate_campaign_dispatch(camp)


@router.get("/campaigns/{campaign_id}/export")
async def export_campaign_results(
    campaign_id: int,
    format: str = "csv",
    current_user: CurrentUser = Depends(get_current_user),
):
    """Exporta resultados de la campaña (CSV)."""
    load_campaign_or_404(campaign_id, current_user)
    if format.lower() not in ("csv",):
        raise HTTPException(status_code=400, detail="format debe ser csv")

    res = await asyncio.to_thread(
        lambda: supabase.table("encuestas")
        .select("id, telefono, fecha, status, seconds_used, comentarios, datos_extra, agent_results")
        .eq("campaign_id", campaign_id)
        .order("fecha", desc=True)
        .execute()
    )
    csv_body = build_campaign_results_csv(res.data or [])
    return PlainTextResponse(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="campaign_{campaign_id}_results.csv"'},
    )


@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: int, current_user: CurrentUser = Depends(require_admin)):
    """Marca la campaña como 'active' para que el scheduler la procese."""
    load_campaign_or_404(campaign_id, current_user)
    try:
        return await start_campaign_record(campaign_id)
    except HTTPException:
        raise
    except Exception as err:
        logger.error("Error al iniciar campaña: %s", err)
        return JSONResponse(status_code=500, content={"error": "Error al iniciar campaña"})
