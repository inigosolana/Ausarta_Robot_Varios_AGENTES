"""
notion_sync.py — Endpoints JSON para alimentar Notion vía n8n.

Flujo:
  Supabase (webhook) → POST /api/notion-sync/webhook/supabase → n8n → Notion
  n8n (schedule)     → GET  /api/notion-sync/*                  → Notion upsert

Los GET requieren superadmin (JWT) o X-N8N-Secret (server-to-server).
El webhook valida firma HMAC o secret compartido antes de reenviar a n8n.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from services.audit import log_audit_event
from services.auth import CurrentUser, get_current_user
from services.supabase_service import sb_query, supabase

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/notion-sync", tags=["notion-sync"])
limiter = Limiter(key_func=get_remote_address)


def _verify_n8n_secret(provided: Optional[str]) -> bool:
    expected = os.getenv("N8N_PROXY_SECRET", "")
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def _verify_webhook_secret(provided: Optional[str]) -> bool:
    expected = os.getenv("SUPABASE_WEBHOOK_SECRET", "")
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def _verify_webhook_hmac(body: bytes, signature: Optional[str]) -> bool:
    secret = os.getenv("SUPABASE_WEBHOOK_SECRET", "")
    if not secret or not signature:
        return False
    raw = signature.strip()
    if raw.startswith("sha256="):
        raw = raw[7:]
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, raw)


async def _require_notion_sync_reader(
    request: Request,
    x_n8n_secret: Optional[str] = Header(None, alias="X-N8N-Secret"),
) -> Optional[CurrentUser]:
    if _verify_n8n_secret(x_n8n_secret):
        return None
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Se requiere JWT de superadmin o X-N8N-Secret")
    from fastapi.security import HTTPAuthorizationCredentials

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header[7:])
    user = await get_current_user(creds=creds)
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Solo superadmin puede consultar notion-sync")
    return user


def _pct_uso(consumidas: int, limite: int) -> float:
    if not limite or limite <= 0:
        return 0.0
    return round((consumidas / limite) * 100, 1)


def _estado_cliente(pct: float) -> str:
    if pct > 90:
        return "Critico"
    if pct > 70:
        return "Atencion"
    return "OK"


def _parse_desde(desde: Optional[str], horas: Optional[int] = None) -> datetime:
    if horas is not None and horas > 0:
        return datetime.now(timezone.utc) - timedelta(hours=horas)
    if desde:
        text = desde.strip().lower()
        if text in {"hace1hora", "hace_1_hora", "last_hour"}:
            return datetime.now(timezone.utc) - timedelta(hours=1)
        if text in {"ayer", "yesterday"}:
            return datetime.now(timezone.utc) - timedelta(days=1)
        try:
            parsed = datetime.fromisoformat(desde.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Parámetro 'desde' inválido: {desde}") from exc
    return datetime.now(timezone.utc) - timedelta(hours=24)


def _agent_tipo(agent: dict, inbound_ids: set[int]) -> str:
    agent_id = agent.get("id")
    if agent_id is not None and int(agent_id) in inbound_ids:
        return "entrante"
    name = str(agent.get("name") or "").lower()
    if "inbound" in name or "recepcion" in name or "entrante" in name:
        return "entrante"
    agent_type = str(agent.get("agent_type") or agent.get("tipo_resultados") or "").upper()
    if agent_type == "SOPORTE_CLIENTE":
        return "entrante"
    return "saliente"


def _resolve_inbound_agent_ids(agents: list[dict]) -> set[int]:
    by_empresa: dict[int, list[dict]] = {}
    for agent in agents:
        eid = agent.get("empresa_id")
        if eid is None:
            continue
        by_empresa.setdefault(int(eid), []).append(agent)

    inbound_ids: set[int] = set()
    for empresa_agents in by_empresa.values():
        preferred = next(
            (
                a for a in empresa_agents
                if "inbound" in str(a.get("name") or "").lower()
                or "recepcion" in str(a.get("name") or "").lower()
                or str(a.get("agent_type") or a.get("tipo_resultados") or "").upper() == "SOPORTE_CLIENTE"
            ),
            empresa_agents[0] if empresa_agents else None,
        )
        if preferred and preferred.get("id") is not None:
            inbound_ids.add(int(preferred["id"]))
    return inbound_ids


@router.get("/empresas")
@limiter.limit("60/minute")
async def list_empresas_for_notion(
    request: Request,
    current_user: Optional[CurrentUser] = Depends(_require_notion_sync_reader),
):
    """Clientes (empresas) con métricas de uso para Notion."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    emp_res = await sb_query(
        lambda: supabase.table("empresas")
        .select("id,nombre,plan,max_llamadas_mes,llamadas_consumidas_mes,max_agentes,created_at")
        .order("nombre")
        .execute()
    )
    agents_res = await sb_query(
        lambda: supabase.table("agent_config").select("id,empresa_id").execute()
    )

    agent_counts: dict[int, int] = {}
    for row in agents_res.data or []:
        eid = row.get("empresa_id")
        if eid is not None:
            agent_counts[int(eid)] = agent_counts.get(int(eid), 0) + 1

    items = []
    for row in emp_res.data or []:
        consumidas = int(row.get("llamadas_consumidas_mes") or 0)
        limite = int(row.get("max_llamadas_mes") or 0)
        pct = _pct_uso(consumidas, limite)
        items.append({
            "id": row["id"],
            "nombre": row.get("nombre"),
            "plan": row.get("plan") or "basico",
            "llamadas_este_mes": consumidas,
            "limite": limite,
            "pct_uso": pct,
            "agentes": agent_counts.get(int(row["id"]), 0),
            "max_agentes": int(row.get("max_agentes") or 0),
            "ultima_actualizacion": row.get("created_at"),
            "estado": _estado_cliente(pct),
        })

    if current_user:
        await log_audit_event(
            user_id=current_user.user_id,
            action="notion_sync_read",
            target_type="empresas",
            target_id="all",
            metadata={"count": len(items)},
        )

    return {"items": items, "total": len(items)}


@router.get("/users")
@limiter.limit("60/minute")
async def list_users_for_notion(
    request: Request,
    current_user: Optional[CurrentUser] = Depends(_require_notion_sync_reader),
):
    """Usuarios con empresa relacionada para Notion."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    res = await sb_query(
        lambda: supabase.table("user_profiles")
        .select("id,email,full_name,role,empresa_id,is_active,created_at,updated_at,empresas(nombre)")
        .order("created_at", desc=True)
        .execute()
    )

    items = []
    for row in res.data or []:
        empresas = row.get("empresas") or {}
        items.append({
            "id": row["id"],
            "nombre": row.get("full_name") or row.get("email"),
            "email": row.get("email"),
            "rol": row.get("role"),
            "empresa_id": row.get("empresa_id"),
            "empresa_nombre": empresas.get("nombre") if isinstance(empresas, dict) else None,
            "activo": bool(row.get("is_active", True)),
            "creado": row.get("created_at"),
            "ultima_modificacion": row.get("updated_at"),
        })

    if current_user:
        await log_audit_event(
            user_id=current_user.user_id,
            action="notion_sync_read",
            target_type="users",
            target_id="all",
            metadata={"count": len(items)},
        )

    return {"items": items, "total": len(items)}


@router.get("/agentes")
@limiter.limit("60/minute")
async def list_agentes_for_notion(
    request: Request,
    current_user: Optional[CurrentUser] = Depends(_require_notion_sync_reader),
):
    """Agentes con tipo entrante/saliente para Notion."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    res = await sb_query(
        lambda: supabase.table("agent_config")
        .select("id,name,empresa_id,agent_type,tipo_resultados,created_at,updated_at,empresas(nombre)")
        .order("id")
        .execute()
    )

    agents = res.data or []
    inbound_ids = _resolve_inbound_agent_ids(agents)

    items = []
    for row in agents:
        empresas = row.get("empresas") or {}
        items.append({
            "id": row["id"],
            "nombre": row.get("name"),
            "empresa_id": row.get("empresa_id"),
            "empresa_nombre": empresas.get("nombre") if isinstance(empresas, dict) else None,
            "tipo": _agent_tipo(row, inbound_ids),
            "activo": bool(row.get("is_active", True)),
            "creado": row.get("created_at"),
            "ultima_modificacion": row.get("updated_at"),
        })

    if current_user:
        await log_audit_event(
            user_id=current_user.user_id,
            action="notion_sync_read",
            target_type="agentes",
            target_id="all",
            metadata={"count": len(items)},
        )

    return {"items": items, "total": len(items)}


@router.get("/llamadas")
@limiter.limit("60/minute")
async def list_llamadas_for_notion(
    request: Request,
    desde: Optional[str] = Query(None, description="ISO datetime o alias: hace1hora, ayer"),
    hasta: Optional[str] = Query(None, description="ISO datetime (opcional)"),
    horas: Optional[int] = Query(None, ge=1, le=168, description="Ventana relativa en horas"),
    empresa_id: Optional[int] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    current_user: Optional[CurrentUser] = Depends(_require_notion_sync_reader),
):
    """Llamadas (encuestas) — solo lectura, append en Notion."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    desde_dt = _parse_desde(desde, horas)
    hasta_dt = datetime.now(timezone.utc)
    if hasta:
        try:
            hasta_dt = datetime.fromisoformat(hasta.replace("Z", "+00:00"))
            if hasta_dt.tzinfo is None:
                hasta_dt = hasta_dt.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Parámetro 'hasta' inválido: {hasta}") from exc

    def _build_query():
        q = (
            supabase.table("encuestas")
            .select("id,empresa_id,agent_id,seconds_used,fecha,status,completada,empresas(nombre)")
            .gte("fecha", desde_dt.isoformat())
            .lte("fecha", hasta_dt.isoformat())
            .order("fecha", desc=True)
            .limit(limit)
        )
        if empresa_id is not None:
            q = q.eq("empresa_id", empresa_id)
        return q.execute()

    res = await sb_query(_build_query)

    agent_names: dict[int, str] = {}
    agent_ids = {int(r["agent_id"]) for r in (res.data or []) if r.get("agent_id") is not None}
    if agent_ids:
        agents_res = await sb_query(
            lambda: supabase.table("agent_config").select("id,name").in_("id", list(agent_ids)).execute()
        )
        agent_names = {int(a["id"]): a.get("name") or "" for a in (agents_res.data or [])}

    items = []
    for row in res.data or []:
        seconds = int(row.get("seconds_used") or 0)
        empresas = row.get("empresas") or {}
        agent_id = row.get("agent_id")
        resultado = row.get("status") or ("completada" if row.get("completada") else "pendiente")
        items.append({
            "id": row["id"],
            "empresa_id": row.get("empresa_id"),
            "empresa_nombre": empresas.get("nombre") if isinstance(empresas, dict) else None,
            "agente_id": agent_id,
            "agente": agent_names.get(int(agent_id), "") if agent_id is not None else "",
            "duracion_seg": seconds,
            "fecha": row.get("fecha"),
            "resultado": resultado,
            "minutos": round(seconds / 60, 2) if seconds else 0,
        })

    if current_user:
        await log_audit_event(
            user_id=current_user.user_id,
            action="notion_sync_read",
            target_type="llamadas",
            target_id="query",
            metadata={"count": len(items), "desde": desde_dt.isoformat(), "hasta": hasta_dt.isoformat()},
        )

    return {
        "items": items,
        "total": len(items),
        "desde": desde_dt.isoformat(),
        "hasta": hasta_dt.isoformat(),
    }


@router.post("/webhook/supabase")
@limiter.limit("120/minute")
async def supabase_webhook_to_notion(
    request: Request,
    x_supabase_webhook_secret: Optional[str] = Header(None, alias="X-Supabase-Webhook-Secret"),
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
):
    """
    Recibe webhooks de Supabase (INSERT/UPDATE/DELETE), valida firma y reenvía a n8n.
    n8n hace el upsert en las bases de datos de Notion.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Body vacío")

    if not (_verify_webhook_secret(x_supabase_webhook_secret) or _verify_webhook_hmac(body, x_webhook_signature)):
        logger.warning("[notion-sync] Webhook rechazado: firma/secret inválido")
        raise HTTPException(status_code=401, detail="Webhook no autorizado")

    try:
        payload: dict[str, Any] = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    table = str(payload.get("table") or payload.get("type") or "").strip()
    event_type = str(payload.get("type") or payload.get("event") or "UNKNOWN").upper()
    allowed_tables = {"empresas", "user_profiles", "agent_config", "encuestas"}
    if table not in allowed_tables:
        return JSONResponse(status_code=200, content={"status": "ignored", "table": table})

    n8n_url = os.getenv("NOTION_SYNC_N8N_WEBHOOK_URL", "").strip()
    if not n8n_url:
        base = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook").rstrip("/")
        n8n_url = f"{base}/notion-sync-supabase"

    forward_payload = {
        "source": "ausarta-supabase",
        "table": table,
        "event": event_type,
        "record": payload.get("record") or payload.get("new") or {},
        "old_record": payload.get("old_record") or payload.get("old") or None,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    n8n_secret = os.getenv("N8N_PROXY_SECRET", "")
    headers = {"Content-Type": "application/json"}
    if n8n_secret:
        headers["X-N8N-Secret"] = n8n_secret

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                n8n_url,
                json=forward_payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.error(f"[notion-sync] n8n respondió {resp.status}: {text[:300]}")
                    return JSONResponse(
                        status_code=502,
                        content={"error": "N8N_FORWARD_FAILED", "message": text[:500]},
                    )
    except aiohttp.ClientError as exc:
        logger.error(f"[notion-sync] Error reenviando a n8n: {exc}")
        return JSONResponse(status_code=502, content={"error": "N8N_UNREACHABLE", "message": str(exc)})

    await log_audit_event(
        user_id=None,
        action="notion_sync_webhook",
        target_type=table,
        target_id=str((forward_payload.get("record") or {}).get("id", "unknown")),
        metadata={"event": event_type, "forwarded_to": n8n_url},
    )

    return {"status": "ok", "table": table, "event": event_type}
