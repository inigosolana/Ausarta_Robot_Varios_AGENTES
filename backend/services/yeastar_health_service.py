"""
yeastar_health_service.py — Lógica de health-check Yeastar y pausa/reanudación de campañas.

Usado por:
  - tasks/yeastar_health.py (cron ARQ)
  - routers/telephony.py (endpoint GET/POST health)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from services.crypto_service import decrypt_data
from services.supabase_service import supabase, sb_query
from services.yeastar_service import YeastarClient

logger = logging.getLogger("api-backend")

FAILURE_THRESHOLD = 3
HEALTH_PAUSE_REASON = "Yeastar sin respuesta"
# Si updated_at es posterior a health_paused_at + este margen, asumimos intervención manual
_MANUAL_TOUCH_GRACE_SECONDS = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def yeastar_client_from_config(row: dict) -> YeastarClient:
    """Construye YeastarClient desde una fila de company_yeastar_configs."""
    api_url = str(row.get("api_url") or "").rstrip("/")
    api_mode = str(row.get("api_mode") or "pseries").strip().lower()
    if api_mode not in ("pseries", "cloud_pbx"):
        api_mode = "pseries"
    default_port = 443
    api_port = int(row.get("api_port") or default_port)
    tail = api_url.rsplit("/", 1)[-1]
    pbx_url = f"{api_url}:{api_port}" if api_url and f":{api_port}" not in tail else api_url
    return YeastarClient(
        pbx_url=pbx_url,
        api_mode=api_mode,  # type: ignore[arg-type]
        client_id=str(row.get("api_username") or ""),
        client_secret=decrypt_data(row.get("api_password") or ""),
        tenant_id=row.get("empresa_id"),
    )


async def _get_empresa_nombre(empresa_id: int) -> str:
    if not supabase:
        return f"empresa {empresa_id}"
    try:
        res = await sb_query(
            lambda eid=empresa_id: supabase.table("empresas")
            .select("nombre")
            .eq("id", eid)
            .limit(1)
            .execute()
        )
        if res and res.data:
            return str(res.data[0].get("nombre") or f"empresa {empresa_id}")
    except Exception as exc:
        logger.debug("[yeastar_health] No se pudo leer nombre empresa %s: %s", empresa_id, exc)
    return f"empresa {empresa_id}"


async def _send_telegram(message: str) -> None:
    """Telegram opcional: si no hay TELEGRAM_BOT_TOKEN/CHAT_ID, no hace nada."""
    import os
    if not (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or not (os.getenv("TELEGRAM_CHAT_ID") or "").strip():
        logger.debug("[yeastar_health] Telegram no configurado — alerta omitida: %s", message[:80])
        return
    try:
        from services.telegram_service import send_telegram_alert
        await send_telegram_alert(message)
    except Exception as exc:
        logger.debug("[yeastar_health] No se pudo enviar Telegram: %s", exc)


async def _pause_campaigns_for_health(empresa_id: int, now_iso: str) -> int:
    """Pausa campañas active/running de la empresa. Devuelve cuántas se pausaron."""
    if not supabase:
        return 0

    res = await sb_query(
        lambda eid=empresa_id: supabase.table("campaigns")
        .select("id, status, name")
        .eq("empresa_id", eid)
        .in_("status", ["active", "running"])
        .execute()
    )
    campaigns = res.data or []
    paused = 0
    for camp in campaigns:
        camp_id = camp["id"]
        prev_status = camp.get("status") or "active"
        try:
            await sb_query(
                lambda cid=camp_id, ps=prev_status, ts=now_iso: supabase.table("campaigns")
                .update({
                    "status": "paused",
                    "paused_by_health_check": True,
                    "paused_reason": HEALTH_PAUSE_REASON,
                    "status_before_health_pause": ps,
                    "health_paused_at": ts,
                })
                .eq("id", cid)
                .execute()
            )
            # Marcar cancelación en Redis para jobs ya encolados
            try:
                from services.redis_service import get_redis
                redis = await get_redis()
                await redis.set(f"ausarta:campaign:cancel:{camp_id}", "1", ex=86400)
            except Exception:
                pass
            paused += 1
            logger.info(
                "[yeastar_health] Campaña %s (%s) pausada por health-check empresa=%s",
                camp_id, camp.get("name"), empresa_id,
            )
        except Exception as exc:
            logger.warning("[yeastar_health] Error pausando campaña %s: %s", camp_id, exc)
    return paused


def _campaign_touched_manually(campaign: dict) -> bool:
    """
    True si la campaña fue modificada después de la pausa automática por salud
    (p.ej. el operador la pausó de nuevo manualmente).
    """
    health_paused_at = _parse_dt(campaign.get("health_paused_at"))
    updated_at = _parse_dt(campaign.get("updated_at"))
    if not health_paused_at or not updated_at:
        return False
    delta = (updated_at - health_paused_at).total_seconds()
    return delta > _MANUAL_TOUCH_GRACE_SECONDS


async def _resume_campaigns_after_recovery(empresa_id: int) -> int:
    """
    Reanuda campañas pausadas por health-check si no fueron tocadas manualmente.
    Devuelve cuántas se reanudaron.
    """
    if not supabase:
        return 0

    res = await sb_query(
        lambda eid=empresa_id: supabase.table("campaigns")
        .select("id, name, status_before_health_pause, health_paused_at, updated_at, paused_reason")
        .eq("empresa_id", eid)
        .eq("paused_by_health_check", True)
        .execute()
    )
    campaigns = res.data or []
    resumed = 0
    for camp in campaigns:
        if _campaign_touched_manually(camp):
            logger.info(
                "[yeastar_health] Campaña %s no auto-reanudada (modificada manualmente tras pausa salud)",
                camp.get("id"),
            )
            continue
        if (camp.get("paused_reason") or "") != HEALTH_PAUSE_REASON:
            continue

        camp_id = camp["id"]
        restore_status = camp.get("status_before_health_pause") or "active"
        if restore_status not in ("active", "running"):
            restore_status = "active"

        try:
            await sb_query(
                lambda cid=camp_id, st=restore_status: supabase.table("campaigns")
                .update({
                    "status": st,
                    "paused_by_health_check": False,
                    "paused_reason": None,
                    "status_before_health_pause": None,
                    "health_paused_at": None,
                })
                .eq("id", cid)
                .execute()
            )
            try:
                from services.redis_service import get_redis
                redis = await get_redis()
                await redis.delete(f"ausarta:campaign:cancel:{camp_id}")
            except Exception:
                pass
            resumed += 1
            logger.info(
                "[yeastar_health] Campaña %s reanudada → %s (empresa=%s)",
                camp_id, restore_status, empresa_id,
            )
        except Exception as exc:
            logger.warning("[yeastar_health] Error reanudando campaña %s: %s", camp_id, exc)
    return resumed


async def check_single_empresa_health(config_row: dict) -> dict[str, Any]:
    """
    Ejecuta health-check para una empresa y aplica pausa/reanudación de campañas.

    Returns dict con resultado para logging / API.
    """
    empresa_id = int(config_row["empresa_id"])
    prev_status = str(config_row.get("health_status") or "unknown")
    prev_failures = int(config_row.get("consecutive_failures") or 0)
    now_iso = _now_iso()
    result: dict[str, Any] = {
        "empresa_id": empresa_id,
        "previous_health_status": prev_status,
        "ok": False,
        "campaigns_paused": 0,
        "campaigns_resumed": 0,
    }

    # Comprobar Yeastar (timeout 5s)
    is_ok = False
    try:
        async with yeastar_client_from_config(config_row) as client:
            is_ok = await client.health_check(timeout=5.0)
    except Exception as exc:
        logger.warning("[yeastar_health] Error comprobando empresa %s: %s", empresa_id, exc)
        is_ok = False

    result["ok"] = is_ok
    empresa_nombre = await _get_empresa_nombre(empresa_id)

    if is_ok:
        new_failures = 0
        new_status = "ok"
        campaigns_resumed = 0
        if prev_status == "down":
            campaigns_resumed = await _resume_campaigns_after_recovery(empresa_id)
            if campaigns_resumed > 0:
                await _send_telegram(
                    f"✅ Yeastar de {empresa_nombre} recuperado, "
                    f"{campaigns_resumed} campaña(s) reanudada(s)"
                )
            else:
                await _send_telegram(f"✅ Yeastar de {empresa_nombre} recuperado")

        await sb_query(
            lambda eid=empresa_id, ts=now_iso: supabase.table("company_yeastar_configs")
            .update({
                "health_status": new_status,
                "consecutive_failures": new_failures,
                "last_health_check_at": ts,
            })
            .eq("empresa_id", eid)
            .execute()
        )
        result["health_status"] = new_status
        result["consecutive_failures"] = new_failures
        result["campaigns_resumed"] = campaigns_resumed
        return result

    # Fallo
    new_failures = prev_failures + 1
    new_status = prev_status
    campaigns_paused = 0

    if new_failures >= FAILURE_THRESHOLD and prev_status != "down":
        new_status = "down"
        campaigns_paused = await _pause_campaigns_for_health(empresa_id, now_iso)
        await _send_telegram(
            f"🔴 Yeastar de {empresa_nombre} no responde ({new_failures} fallos) — "
            f"{campaigns_paused} campaña(s) pausada(s) automáticamente"
        )
    elif new_failures >= FAILURE_THRESHOLD:
        new_status = "down"

    await sb_query(
        lambda eid=empresa_id, st=new_status, cf=new_failures, ts=now_iso: supabase.table("company_yeastar_configs")
        .update({
            "health_status": st,
            "consecutive_failures": cf,
            "last_health_check_at": ts,
        })
        .eq("empresa_id", eid)
        .execute()
    )
    result["health_status"] = new_status
    result["consecutive_failures"] = new_failures
    result["campaigns_paused"] = campaigns_paused
    return result


async def run_yeastar_health_checks() -> dict[str, Any]:
    """
    Recorre todas las empresas con Yeastar activo y ejecuta health-check.
    Un fallo en una empresa no bloquea las demás.
    """
    if not supabase:
        logger.warning("[yeastar_health] Supabase no disponible")
        return {"checked": 0, "results": []}

    try:
        res = await sb_query(
            lambda: supabase.table("company_yeastar_configs")
            .select(
                "empresa_id, api_url, api_port, api_mode, api_username, api_password, "
                "health_status, consecutive_failures, last_health_check_at, is_active"
            )
            .eq("is_active", True)
            .execute()
        )
        configs = res.data or []
    except Exception as exc:
        logger.error("[yeastar_health] Error leyendo configs: %s", exc)
        return {"checked": 0, "results": [], "error": str(exc)}

    results: list[dict] = []
    for row in configs:
        empresa_id = row.get("empresa_id")
        try:
            outcome = await check_single_empresa_health(row)
            results.append(outcome)
            logger.info(
                "[yeastar_health] empresa=%s ok=%s status=%s failures=%s",
                empresa_id, outcome.get("ok"), outcome.get("health_status"),
                outcome.get("consecutive_failures"),
            )
        except Exception as exc:
            logger.warning("[yeastar_health] Fallo procesando empresa %s: %s", empresa_id, exc)
            results.append({"empresa_id": empresa_id, "error": str(exc)})

    return {"checked": len(results), "results": results}


async def get_yeastar_health_status(empresa_id: int) -> dict[str, Any]:
    """Devuelve estado de salud + campañas pausadas por health-check (para API)."""
    if not supabase:
        return {"health_status": "unknown", "campaigns_paused_by_health": []}

    cfg_res = await sb_query(
        lambda eid=empresa_id: supabase.table("company_yeastar_configs")
        .select("health_status, last_health_check_at, consecutive_failures, is_active")
        .eq("empresa_id", eid)
        .limit(1)
        .execute()
    )
    if not cfg_res.data:
        return {
            "empresa_id": empresa_id,
            "configured": False,
            "health_status": "unknown",
            "last_health_check_at": None,
            "consecutive_failures": 0,
            "campaigns_paused_by_health": [],
        }

    cfg = cfg_res.data[0]
    camp_res = await sb_query(
        lambda eid=empresa_id: supabase.table("campaigns")
        .select("id, name, status, paused_reason, health_paused_at")
        .eq("empresa_id", eid)
        .eq("paused_by_health_check", True)
        .execute()
    )
    paused_campaigns = [
        {
            "id": c.get("id"),
            "name": c.get("name"),
            "status": c.get("status"),
            "paused_reason": c.get("paused_reason"),
            "health_paused_at": c.get("health_paused_at"),
        }
        for c in (camp_res.data or [])
    ]

    return {
        "empresa_id": empresa_id,
        "configured": True,
        "is_active": bool(cfg.get("is_active")),
        "health_status": cfg.get("health_status") or "unknown",
        "last_health_check_at": cfg.get("last_health_check_at"),
        "consecutive_failures": int(cfg.get("consecutive_failures") or 0),
        "failure_threshold": FAILURE_THRESHOLD,
        "campaigns_paused_by_health": paused_campaigns,
        "campaigns_paused_count": len(paused_campaigns),
    }
