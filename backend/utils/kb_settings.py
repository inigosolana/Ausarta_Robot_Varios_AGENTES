"""Resolución de configuración KB / internet por empresa y agente."""

from __future__ import annotations

import logging

logger = logging.getLogger("api-backend")


def load_empresa_kb_settings(empresa_id: int | None, *, supabase_client=None) -> dict:
    """Contexto de empresa y flag de búsqueda en internet (sync, para routers)."""
    if not empresa_id:
        return {"company_context": "", "kb_allow_internet_search": False}

    sb = supabase_client
    if sb is None:
        from services.supabase_service import supabase as sb_default

        sb = sb_default

    if not sb:
        return {"company_context": "", "kb_allow_internet_search": False}

    try:
        res = (
            sb.table("empresas")
            .select("company_context, kb_allow_internet_search")
            .eq("id", empresa_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return {"company_context": "", "kb_allow_internet_search": False}
        row = res.data[0]
        return {
            "company_context": row.get("company_context") or "",
            "kb_allow_internet_search": bool(row.get("kb_allow_internet_search")),
        }
    except Exception as exc:
        logger.warning("No se pudo cargar KB settings empresa %s: %s", empresa_id, exc)
        return {"company_context": "", "kb_allow_internet_search": False}


def resolve_kb_allow_internet(agent_config: dict) -> bool:
    """
    Internet solo si la empresa lo permite Y el agente lo tiene activado.
    La empresa se configura en Base de Conocimiento; el agente elige solo KB o KB+internet.
    """
    company_allows = bool(agent_config.get("empresa_kb_allow_internet_search", False))
    agent_wants = bool(agent_config.get("kb_allow_internet_search", False))
    return company_allows and agent_wants
