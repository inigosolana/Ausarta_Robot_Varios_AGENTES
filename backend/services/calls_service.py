"""Listado de llamadas (encuestas) enriquecido con estado LiveKit en tiempo real."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from services.supabase_service import sb_query, supabase

logger = logging.getLogger("api-backend")

ROOM_PREFIX = "llamada_ausarta_"
ACTIVE_STATUSES = frozenset(
    {"initiated", "calling", "in_progress", "active", "ringing", "dialing", "connected"}
)


def _parse_room_name(room_name: str) -> dict[str, int | None]:
    enc_m = re.search(r"encuesta_(\d+)", room_name)
    emp_m = re.search(r"empresa_(\d+)", room_name)
    camp_m = re.search(r"campana_(\d+)", room_name)
    return {
        "encuesta_id": int(enc_m.group(1)) if enc_m else None,
        "empresa_id": int(emp_m.group(1)) if emp_m else None,
        "campaign_id": int(camp_m.group(1)) if camp_m else None,
    }


async def fetch_live_rooms_map() -> dict[int, dict[str, Any]]:
    """Mapea encuesta_id → datos de sala LiveKit activa."""
    out: dict[int, dict[str, Any]] = {}
    try:
        from livekit import api as lk_api
        from services.livekit_service import lkapi

        if not lkapi:
            return out

        rooms_res = await asyncio.wait_for(
            lkapi.room.list_rooms(lk_api.ListRoomsRequest()),
            timeout=5,
        )
        now_ts = int(time.time())
        for room in rooms_res.rooms:
            name = room.name or ""
            if not name.startswith(ROOM_PREFIX):
                continue
            meta = _parse_room_name(name)
            enc_id = meta.get("encuesta_id")
            if not enc_id:
                continue
            out[int(enc_id)] = {
                "room_name": name,
                "num_participants": room.num_participants,
                "duration_seconds": max(0, now_ts - room.creation_time)
                if room.creation_time
                else 0,
                "created_at": room.creation_time,
            }
    except Exception as exc:
        logger.warning("📞 [calls] No se pudo listar salas LiveKit: %s", exc)
    return out


def _call_direction_from_extra(datos_extra: object) -> str | None:
    if not isinstance(datos_extra, dict):
        return None
    direction = str(datos_extra.get("call_direction") or "").strip().lower()
    return direction if direction in {"inbound", "outbound"} else None


async def list_calls(
    *,
    empresa_id: int | None = None,
    agent_id: int | None = None,
    campaign_id: int | None = None,
    status: str | None = None,
    live_only: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if not supabase:
        return {"calls": [], "live_count": 0, "total": 0}

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    cols = (
        "id, telefono, nombre_cliente, fecha, status, seconds_used, completada, "
        "empresa_id, agent_id, campaign_id, campaign_name, agent_type, datos_extra"
    )

    def _build_query():
        q = supabase.table("encuestas").select(cols, count="exact")
        if empresa_id:
            q = q.eq("empresa_id", empresa_id)
        if agent_id:
            q = q.eq("agent_id", agent_id)
        if campaign_id:
            q = q.eq("campaign_id", campaign_id)
        if status:
            q = q.eq("status", status)
        if start_date:
            q = q.gte("fecha", start_date)
        if end_date:
            q = q.lte("fecha", end_date)
        if live_only:
            q = q.in_("status", list(ACTIVE_STATUSES))
        return q.order("fecha", desc=True).range(offset, offset + limit - 1)

    enc_res, live_map = await asyncio.gather(
        sb_query(_build_query),
        fetch_live_rooms_map(),
    )

    rows = enc_res.data or []
    total = int(enc_res.count or len(rows))

    empresa_ids = {int(r["empresa_id"]) for r in rows if r.get("empresa_id")}
    agent_ids = {int(r["agent_id"]) for r in rows if r.get("agent_id")}

    emp_map: dict[int, str] = {}
    agent_map: dict[int, dict[str, str | None]] = {}

    if empresa_ids:
        emp_res = await sb_query(
            lambda: supabase.table("empresas")
            .select("id, nombre")
            .in_("id", list(empresa_ids))
            .execute()
        )
        emp_map = {int(e["id"]): e.get("nombre") or "—" for e in (emp_res.data or [])}

    if agent_ids:
        ag_res = await sb_query(
            lambda: supabase.table("agent_config")
            .select("id, name, agent_type, tipo_resultados")
            .in_("id", list(agent_ids))
            .execute()
        )
        for a in ag_res.data or []:
            agent_map[int(a["id"])] = {
                "name": a.get("name"),
                "agent_type": a.get("agent_type") or a.get("tipo_resultados"),
            }

    calls: list[dict[str, Any]] = []
    live_count = 0

    for row in rows:
        enc_id = int(row["id"])
        live = live_map.get(enc_id)
        st = (row.get("status") or "pending").lower()
        is_live = bool(live) or st in ACTIVE_STATUSES
        if live_only and not is_live:
            continue

        if is_live:
            live_count += 1

        extra = row.get("datos_extra") if isinstance(row.get("datos_extra"), dict) else {}
        eid = int(row.get("empresa_id") or 0)
        aid = int(row.get("agent_id") or 0)
        agent_info = agent_map.get(aid, {})

        calls.append(
            {
                "id": enc_id,
                "phone": row.get("telefono") or "",
                "customer_name": row.get("nombre_cliente") or "",
                "status": st,
                "is_live": is_live,
                "room_name": (live or {}).get("room_name"),
                "participants": (live or {}).get("num_participants"),
                "duration_seconds": (live or {}).get("duration_seconds")
                if live
                else row.get("seconds_used"),
                "empresa_id": eid or None,
                "empresa_name": emp_map.get(eid, "—") if eid else None,
                "agent_id": aid or None,
                "agent_name": agent_info.get("name"),
                "agent_type": row.get("agent_type") or agent_info.get("agent_type"),
                "campaign_id": row.get("campaign_id"),
                "campaign_name": row.get("campaign_name"),
                "started_at": row.get("fecha"),
                "call_direction": _call_direction_from_extra(extra),
                "completada": bool(row.get("completada")),
            }
        )

    if live_only:
        total = len(calls)

    return {
        "calls": calls,
        "live_count": live_count,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
