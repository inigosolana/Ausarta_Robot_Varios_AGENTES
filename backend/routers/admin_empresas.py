"""Gestión de empresas, planes, troncales y CRM (admin)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from services.admin_helpers import VALID_PLANS
from services.audit import log_audit_event
from services.auth import CurrentUser, require_admin, require_superadmin
from services.platform_access import has_global_access
from services.supabase_service import sb_query, supabase

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/empresas")
async def list_empresas_with_limits(
    current_user: CurrentUser = Depends(require_superadmin),
):
    """
    Lista todas las empresas con sus columnas de plan/límites.
    Solo accesible para superadmin.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    _ = current_user
    res = await sb_query(
        lambda: supabase.table("empresas")
        .select(
            "id, nombre, responsable, plan, max_llamadas_mes, "
            "max_agentes, llamadas_consumidas_mes, sip_outbound_trunk_id, "
            "sip_inbound_trunk_id, created_at"
        )
        .order("nombre")
        .execute()
    )
    return res.data or []


@router.put("/empresas/{empresa_id}/limits")
async def update_empresa_limits(
    empresa_id: int,
    payload: dict,
    current_user: CurrentUser = Depends(require_superadmin),
):
    """
    Actualiza el plan y los límites de una empresa.
    Solo accesible para superadmin.

    Body (todos opcionales):
      - plan: "basico" | "profesional" | "enterprise"
      - max_llamadas_mes: int ≥ 0
      - max_agentes: int ≥ 0
      - reset_consumidas: bool — si true, pone llamadas_consumidas_mes = 0
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    # Validar que la empresa exista
    emp_check = await sb_query(
        lambda: supabase.table("empresas")
        .select("id, nombre")
        .eq("id", empresa_id)
        .limit(1)
        .execute()
    )
    if not emp_check.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    update: dict = {}

    plan = payload.get("plan")
    if plan is not None:
        if str(plan) not in VALID_PLANS:
            raise HTTPException(
                status_code=400,
                detail=f"Plan inválido. Valores permitidos: {', '.join(sorted(VALID_PLANS))}",
            )
        update["plan"] = str(plan)

    max_llamadas = payload.get("max_llamadas_mes")
    if max_llamadas is not None:
        try:
            val = int(max_llamadas)
            if val < 0:
                raise ValueError
            update["max_llamadas_mes"] = val
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_llamadas_mes debe ser un entero ≥ 0")

    max_agentes = payload.get("max_agentes")
    if max_agentes is not None:
        try:
            val = int(max_agentes)
            if val < 0:
                raise ValueError
            update["max_agentes"] = val
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_agentes debe ser un entero ≥ 0")

    if payload.get("reset_consumidas"):
        update["llamadas_consumidas_mes"] = 0

    if not update:
        raise HTTPException(status_code=400, detail="No se proporcionaron campos a actualizar")

    res = await sb_query(
        lambda: supabase.table("empresas")
        .update(update)
        .eq("id", empresa_id)
        .select("id, nombre, plan, max_llamadas_mes, max_agentes, llamadas_consumidas_mes")
        .execute()
    )

    empresa_nombre = emp_check.data[0].get("nombre", str(empresa_id))
    logger.info(
        "📦 [admin] Límites actualizados empresa=%s (%s) por superadmin=%s → %s",
        empresa_id,
        empresa_nombre,
        current_user.user_id,
        update,
    )
    await log_audit_event(
        user_id=current_user.user_id,
        action="update_empresa_limits",
        target_type="empresa",
        target_id=str(empresa_id),
        metadata={"changes": update, "empresa_nombre": empresa_nombre},
    )

    return {"status": "ok", "empresa": res.data[0] if res.data else {}}


@router.put("/empresas/{empresa_id}/trunks")
async def update_empresa_trunks(
    empresa_id: int,
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Actualiza los IDs de troncales SIP por empresa.
    - Superadmin / admin global: puede editar cualquier empresa.
    - Admin de cliente: solo su propia empresa.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    if not has_global_access(current_user):
        if not current_user.empresa_id or int(current_user.empresa_id) != int(empresa_id):
            raise HTTPException(status_code=403, detail="No tienes permisos para editar esta empresa")

    emp_check = await sb_query(
        lambda: supabase.table("empresas")
        .select("id, nombre")
        .eq("id", empresa_id)
        .limit(1)
        .execute()
    )
    if not emp_check.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    def _norm_trunk(raw: object) -> str | None:
        s = str(raw or "").strip()
        return s if s else None

    update = {
        "sip_outbound_trunk_id": _norm_trunk(payload.get("sip_outbound_trunk_id")),
        "sip_inbound_trunk_id": _norm_trunk(payload.get("sip_inbound_trunk_id")),
    }

    await sb_query(
        lambda: supabase.table("empresas")
        .update(update)
        .eq("id", empresa_id)
        .execute()
    )

    res = await sb_query(
        lambda: supabase.table("empresas")
        .select("id, nombre, sip_outbound_trunk_id, sip_inbound_trunk_id")
        .eq("id", empresa_id)
        .limit(1)
        .execute()
    )
    empresa_nombre = emp_check.data[0].get("nombre", str(empresa_id))
    await log_audit_event(
        user_id=current_user.user_id,
        action="update_empresa_trunks",
        target_type="empresa",
        target_id=str(empresa_id),
        metadata={"empresa_nombre": empresa_nombre, "changes": update},
    )
    return {"status": "ok", "empresa": res.data[0] if res.data else {}}
@router.get("/empresas/{empresa_id}/crm-config")
async def get_empresa_crm_config(
    empresa_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Devuelve la configuración CRM y webhook de automatización de una empresa.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    if not has_global_access(current_user):
        if not current_user.empresa_id or int(current_user.empresa_id) != int(empresa_id):
            raise HTTPException(status_code=403, detail="No tienes permisos para ver esta empresa")

    # `webhook_url` is being rolled out gradually. Keep the view working even
    # if the column is not yet present in the target database.
    res = await sb_query(
        lambda: supabase.table("empresas")
        .select("id, nombre, crm_type, crm_webhook_url")
        .eq("id", empresa_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    row = dict(res.data[0])
    row.setdefault("webhook_url", None)
    return row


@router.put("/empresas/{empresa_id}/crm-config")
async def update_empresa_crm_config(
    empresa_id: int,
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Actualiza la configuración CRM y webhook de automatización de una empresa.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    if not has_global_access(current_user):
        if not current_user.empresa_id or int(current_user.empresa_id) != int(empresa_id):
            raise HTTPException(status_code=403, detail="No tienes permisos para editar esta empresa")

    def _clean_url(value: object) -> str | None:
        text = str(value or "").strip()
        return text or None

    updates: dict[str, object] = {}
    if "crm_type" in payload:
        updates["crm_type"] = str(payload.get("crm_type") or "custom").strip().lower() or "custom"
    if "crm_webhook_url" in payload:
        updates["crm_webhook_url"] = _clean_url(payload.get("crm_webhook_url"))
    if "webhook_url" in payload:
        updates["webhook_url"] = _clean_url(payload.get("webhook_url"))

    if not updates:
        raise HTTPException(status_code=400, detail="No se proporcionaron cambios")

    try:
        res = await sb_query(
            lambda: supabase.table("empresas")
            .update(updates)
            .eq("id", empresa_id)
            .select("id, nombre, crm_type, crm_webhook_url, webhook_url")
            .execute()
        )
    except Exception as e:
        if "webhook_url" in str(e) and "does not exist" in str(e):
            raise HTTPException(
                status_code=409,
                detail="La columna empresas.webhook_url aun no existe en esta base de datos. Aplica la migracion 20260603_add_empresas_webhook_url.sql y vuelve a intentarlo.",
            ) from e
        raise
    if not res.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    return {"status": "ok", "empresa": res.data[0]}


@router.post("/empresas/{empresa_id}/reset-consumidas")
async def reset_llamadas_consumidas(
    empresa_id: int,
    current_user: CurrentUser = Depends(require_superadmin),
):
    """Reinicia el contador mensual de llamadas consumidas a 0. Solo superadmin."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    _ = current_user
    await sb_query(
        lambda: supabase.table("empresas")
        .update({"llamadas_consumidas_mes": 0})
        .eq("id", empresa_id)
        .execute()
    )
    await log_audit_event(
        user_id=current_user.user_id,
        action="reset_llamadas_consumidas",
        target_type="empresa",
        target_id=str(empresa_id),
        metadata={},
    )
    return {"status": "ok", "empresa_id": empresa_id, "llamadas_consumidas_mes": 0}
