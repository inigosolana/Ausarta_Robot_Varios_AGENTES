"""Endpoints de resolución de config de agente (survey / inbound)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from routers.campaign_access import raise_not_found_if_cross_tenant, resolve_campaign_empresa
from services.auth import CurrentUser, get_current_user
from services.campaign_agent_config_service import (
    resolve_agent_config_by_agent,
    resolve_agent_config_by_survey,
)
from services.supabase_service import supabase

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["campaign-agent-config"])

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


@router.get("/agent_config_by_survey/{survey_id}")
async def get_agent_config_by_survey(
    survey_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Supabase not connected"})
    try:
        survey_row = (
            supabase.table("encuestas")
            .select("empresa_id")
            .eq("id", survey_id)
            .limit(1)
            .execute()
        )
        if survey_row.data:
            raise_not_found_if_cross_tenant(current_user, survey_row.data[0].get("empresa_id"))

        payload = resolve_agent_config_by_survey(survey_id)
        return JSONResponse(status_code=200, content=payload, headers=_NO_CACHE_HEADERS)
    except LookupError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error agent config by survey: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/agent_config_by_agent/{agent_id}")
async def get_agent_config_by_agent(
    agent_id: int,
    empresa_id: int | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Config interna para llamadas entrantes SIP, donde no existe encuesta previa."""
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Supabase not connected"})
    try:
        empresa_id = resolve_campaign_empresa(current_user, empresa_id)
        payload = resolve_agent_config_by_agent(agent_id, empresa_id)
        raise_not_found_if_cross_tenant(current_user, payload.get("empresa_id"))
        return JSONResponse(status_code=200, content=payload, headers=_NO_CACHE_HEADERS)
    except LookupError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error agent config by agent: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
