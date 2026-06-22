"""Listados de user_profiles sin embed anidado empresas(*) — 2 queries batch."""

from __future__ import annotations

from typing import Any

from services.supabase_service import sb_query, supabase

_USER_LIST_COLUMNS = "*"
_EMPRESA_EMBED_COLUMNS = "id, nombre, plan"


async def list_user_profiles_with_empresa(
    *,
    empresa_id: int | None = None,
) -> list[dict[str, Any]]:
    if not supabase:
        return []

    def _fetch_users():
        q = (
            supabase.table("user_profiles")
            .select(_USER_LIST_COLUMNS)
            .order("created_at", desc=True)
        )
        if empresa_id is not None:
            q = q.eq("empresa_id", empresa_id)
        return q.execute()

    res = await sb_query(_fetch_users)
    users: list[dict[str, Any]] = res.data or []
    if not users:
        return users

    empresa_ids = sorted({u["empresa_id"] for u in users if u.get("empresa_id") is not None})
    empresas_map: dict[int, dict[str, Any]] = {}
    if empresa_ids:
        emp_res = await sb_query(
            lambda: supabase.table("empresas")
            .select(_EMPRESA_EMBED_COLUMNS)
            .in_("id", empresa_ids)
            .execute()
        )
        empresas_map = {e["id"]: e for e in (emp_res.data or [])}

    for user in users:
        eid = user.get("empresa_id")
        user["empresas"] = empresas_map.get(eid) if eid is not None else None

    return users
