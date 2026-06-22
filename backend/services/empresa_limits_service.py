"""Límites de concurrencia configurables por empresa."""

from __future__ import annotations

import os

from services.supabase_service import sb_query, supabase

_DEFAULT = max(1, int(os.getenv("MAX_CALLS_PER_EMPRESA", "5")))


async def get_empresa_max_concurrent_calls(empresa_id: int) -> int:
    if not supabase or empresa_id <= 0:
        return _DEFAULT
    try:

        def _fetch():
            return (
                supabase.table("empresas")
                .select("max_concurrent_calls")
                .eq("id", empresa_id)
                .limit(1)
                .execute()
            )

        res = await sb_query(_fetch)
        if res.data:
            raw = res.data[0].get("max_concurrent_calls")
            if raw is not None:
                return max(1, int(raw))
    except Exception:
        pass
    return _DEFAULT
