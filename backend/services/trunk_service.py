import os
import logging

from services.supabase_service import supabase, sb_query

logger = logging.getLogger("api-backend")


async def resolve_outbound_trunk_id(empresa_id: int | None) -> str:
    """
    Resuelve el trunk de salida:
    1) empresas.sip_outbound_trunk_id (si existe y está definido)
    2) fallback global SIP_OUTBOUND_TRUNK_ID del entorno
    """
    if empresa_id and supabase:
        try:
            res = await sb_query(
                lambda eid=empresa_id: supabase.table("empresas")
                .select("sip_outbound_trunk_id")
                .eq("id", eid)
                .limit(1)
                .execute()
            )
            if res.data:
                custom = str(res.data[0].get("sip_outbound_trunk_id") or "").strip()
                if custom:
                    return custom
        except Exception as exc:
            logger.warning(
                "[trunk] No se pudo resolver trunk por empresa=%s: %s",
                empresa_id,
                exc,
            )

    return (os.getenv("SIP_OUTBOUND_TRUNK_ID") or "").strip()
