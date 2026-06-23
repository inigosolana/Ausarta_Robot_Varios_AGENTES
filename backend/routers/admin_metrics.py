"""Métricas de plataforma para panel admin."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from services.auth import CurrentUser, require_admin
from services.platform_access import has_global_access
from services.supabase_service import sb_query, supabase

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ──────────────────────────────────────────────────────────────────────────────
# Métricas en tiempo real (LiveKit + Redis) — panel de administración
# ──────────────────────────────────────────────────────────────────────────────

LIVEKIT_ROOM_PREFIX = "llamada_ausarta_"


@router.get("/metrics/live-calls")
async def get_live_calls_metrics(current_user: CurrentUser = Depends(require_admin)):
    """
    Salas LiveKit activas del prefijo de llamadas Ausarta.
    Requiere rol admin o superadmin.
    """
    from livekit import api
    from services.livekit_service import lkapi

    _ = current_user
    try:
        rooms_res = await lkapi.room.list_rooms(api.ListRoomsRequest())
        rooms = []
        for r in rooms_res.rooms:
            name = r.name or ""
            if not name.startswith(LIVEKIT_ROOM_PREFIX):
                continue
            created_at = r.creation_time
            rooms.append({
                "sid": r.sid,
                "name": name,
                "num_participants": r.num_participants,
                "created_at": created_at,
                "created_at_iso": (
                    datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat()
                    if created_at
                    else None
                ),
            })
        return {"total": len(rooms), "rooms": rooms}
    except Exception as e:
        logger.error(f"[metrics] Error listando salas LiveKit: {e}")
        raise HTTPException(status_code=502, detail=f"No se pudo consultar LiveKit: {e}") from e


@router.get("/metrics/redis")
async def get_redis_metrics(current_user: CurrentUser = Depends(require_admin)):
    """
    Métricas básicas de Redis (memoria, clientes, ops/s, uptime).
    Requiere rol admin o superadmin.
    """
    import redis.asyncio as aioredis

    _ = current_user
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    client = aioredis.from_url(redis_url, decode_responses=True)
    try:
        info = await client.info()
        ops_raw = info.get("instantaneous_ops_per_sec", 0)
        clients_raw = info.get("connected_clients", 0)
        uptime_raw = info.get("uptime_in_days", 0)
        return {
            "memory_used": info.get("used_memory_human", "N/A"),
            "memory_peak": info.get("used_memory_peak_human", "N/A"),
            "connected_clients": int(clients_raw) if clients_raw is not None else 0,
            "ops_per_second": int(ops_raw) if ops_raw is not None else 0,
            "uptime_days": int(float(uptime_raw)) if uptime_raw is not None else 0,
        }
    except Exception as e:
        logger.error(f"[metrics] Error consultando Redis: {e}")
        raise HTTPException(status_code=502, detail=f"No se pudo consultar Redis: {e}") from e
    finally:
        await client.close()


@router.get("/metrics/usage-per-tenant")
async def get_usage_per_tenant(current_user: CurrentUser = Depends(require_admin)):
    """
    Consumo agregado por empresa: agentes, llamadas y minutos (seconds_used en encuestas).
    Superadmin ve todas las empresas; admin solo la suya.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    emp_res = await sb_query(
        lambda: supabase.table("empresas").select("id,nombre").execute()
    )
    agents_res = await sb_query(
        lambda: supabase.table("agent_config").select("id,empresa_id").execute()
    )
    enc_res = await sb_query(
        lambda: supabase.table("encuestas").select("id,empresa_id,seconds_used").execute()
    )

    enterprises = emp_res.data or []
    agents = agents_res.data or []
    encuestas = enc_res.data or []

    agent_counts: dict[int, int] = {}
    for row in agents:
        eid = row.get("empresa_id")
        if eid is None:
            continue
        try:
            eid_int = int(eid)
        except (TypeError, ValueError):
            continue
        agent_counts[eid_int] = agent_counts.get(eid_int, 0) + 1

    call_stats: dict[int, dict[str, int]] = {}
    for row in encuestas:
        eid = row.get("empresa_id")
        if eid is None:
            continue
        try:
            eid_int = int(eid)
        except (TypeError, ValueError):
            continue
        if eid_int not in call_stats:
            call_stats[eid_int] = {"total_calls": 0, "total_seconds": 0}
        call_stats[eid_int]["total_calls"] += 1
        su = row.get("seconds_used")
        if su is not None:
            try:
                call_stats[eid_int]["total_seconds"] += int(su)
            except (TypeError, ValueError):
                pass

    admin_empresa = current_user.empresa_id

    out: list[dict] = []
    for emp in enterprises:
        try:
            eid = int(emp["id"])
        except (TypeError, ValueError, KeyError):
            continue
        if not has_global_access(current_user):
            if admin_empresa is None or eid != int(admin_empresa):
                continue

        nombre = str(emp.get("nombre") or f"Empresa {eid}")
        total_agents = agent_counts.get(eid, 0)
        stats = call_stats.get(eid, {"total_calls": 0, "total_seconds": 0})
        total_calls = stats["total_calls"]
        total_seconds = stats["total_seconds"]
        total_minutes = round(total_seconds / 60.0, 2) if total_seconds else 0.0
        avg_duration_seconds = int(round(total_seconds / total_calls)) if total_calls else 0

        out.append({
            "empresa_id": eid,
            "empresa_nombre": nombre,
            "total_agents": total_agents,
            "total_calls": total_calls,
            "total_minutes": total_minutes,
            "avg_duration_seconds": avg_duration_seconds,
        })

    out.sort(key=lambda x: x["empresa_nombre"].lower())
    return out
