from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from supabase import create_client
from services.supabase_service import supabase, clear_ui_cache, sb_query
from services.auth import CurrentUser, require_admin, require_superadmin, invalidate_user_profile_cache
from services.platform_access import (
    get_master_empresa_id,
    has_global_access,
    is_ausarta_platform_admin,
)
from services.audit import log_audit_event
from slowapi import Limiter
from slowapi.util import get_remote_address
import os
from datetime import datetime, timezone
import aiohttp
import logging
import json
import hmac
import hashlib
import base64
import time

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/admin", tags=["admin"])
limiter = Limiter(key_func=get_remote_address)


def _canonical_role(raw_role: str | None) -> str:
    role = (raw_role or "").strip().lower()
    if role == "superadmin":
        return "superadmin"
    if role in {"admin", "admin_empresa"}:
        return "admin"
    if role in {"user", "viewer"}:
        return "user"
    return role


def _resolve_master_empresa_id() -> int | None:
    """Tenant Ausarta: env primero, luego consulta BD."""
    env_id = get_master_empresa_id()
    if env_id:
        return env_id
    if not supabase:
        return None
    try:
        res = (
            supabase.table("empresas")
            .select("id,nombre")
            .ilike("nombre", "ausarta")
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0].get("id")
    except Exception as e:
        logger.warning(f"⚠️ [admin] No se pudo resolver empresa maestra Ausarta: {e}")
    return None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _sign_impersonation_payload(payload: dict) -> str:
    """
    Token firmado (HMAC SHA-256) para modo impersonation.
    Formato: base64url(json).base64url(signature)
    """
    secret = os.getenv("IMPERSONATION_SECRET") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not secret:
        raise HTTPException(status_code=500, detail="IMPERSONATION_SECRET no configurado")
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return f"{_b64url(raw)}.{_b64url(sig)}"


def _canonical_impersonation_role(raw_role: str | None) -> str:
    role = _canonical_role(raw_role)
    # El modo de soporte debe simular contexto de cliente, nunca superadmin.
    if role not in {"admin", "user"}:
        return "admin"
    return role


VALID_PLANS = {"basico", "profesional", "enterprise"}


# ──────────────────────────────────────────────────────────────────────────────
# Fase 1 SaaS — Gestión de planes y límites de empresa
# ──────────────────────────────────────────────────────────────────────────────

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


@router.get("/users")
async def list_admin_users(
    empresa_id: int | None = None,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Lista usuarios con sus empresas asociadas para el panel de administración.

    - Superadmin / admin global: puede ver todos los usuarios o filtrar por empresa_id.
    - Admin de cliente: solo ve los usuarios de su propia empresa.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    query = supabase.table("user_profiles").select("*, empresas(*)").order("created_at", desc=True)

    if has_global_access(current_user) or is_ausarta_platform_admin(current_user):
        if empresa_id is not None:
            query = query.eq("empresa_id", empresa_id)
    else:
        if not current_user.empresa_id:
            raise HTTPException(status_code=400, detail="Usuario sin empresa asignada")
        query = query.eq("empresa_id", current_user.empresa_id)

    res = await sb_query(lambda: query.execute())
    return res.data or []


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


@router.post("/impersonate")
@limiter.limit("10/minute")
async def impersonate_tenant(request: Request, payload: dict, current_user: CurrentUser = Depends(require_superadmin)):
    """
    Modo infiltración (soporte): sólo superadmin.
    Recibe empresa_id de destino y devuelve:
      - token firmado y expiración corta
      - estado de spoof compatible con frontend actual
    """
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "No hay conexión con la base de datos"})

    target_empresa_id = payload.get("empresa_id")
    if target_empresa_id is None:
        raise HTTPException(status_code=400, detail="empresa_id es obligatorio")
    try:
        target_empresa_id = int(target_empresa_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="empresa_id inválido")

    desired_role = _canonical_impersonation_role(payload.get("role"))

    # Validar que la empresa existe
    empresa_res = await sb_query(
        lambda: supabase.table("empresas")
        .select("id,nombre")
        .eq("id", target_empresa_id)
        .limit(1)
        .execute()
    )
    if not empresa_res.data:
        raise HTTPException(status_code=404, detail="Empresa destino no encontrada")

    ttl_seconds = int(os.getenv("IMPERSONATION_TTL_SECONDS", "1800"))  # 30 min
    now = int(time.time())
    exp = now + max(60, ttl_seconds)

    token_payload = {
        "iss": "ausarta-backend",
        "type": "impersonation",
        "actor_user_id": current_user.user_id,
        "target_empresa_id": target_empresa_id,
        "target_role": desired_role,
        "iat": now,
        "exp": exp,
    }
    token = _sign_impersonation_payload(token_payload)

    logger.warning(
        f"🕵️ [impersonation] superadmin={current_user.user_id} -> "
        f"empresa={target_empresa_id}, role={desired_role}, exp={exp}"
    )
    await log_audit_event(
        user_id=current_user.user_id,
        action="impersonate_tenant",
        target_type="empresa",
        target_id=str(target_empresa_id),
        metadata={"role": desired_role, "expires_at": exp},
    )

    # Compatible con el frontend actual (AuthContext usa localStorage spoofedRole/spoofedEmpresa)
    return {
        "status": "ok",
        "token": token,
        "expires_at": exp,
        "impersonation": {
            "spoofedRole": desired_role,
            "spoofedEmpresa": target_empresa_id,
        },
        "empresa": empresa_res.data[0],
    }

@router.post("/users")
@limiter.limit("20/minute")
async def create_auth_user(request: Request, payload: dict, current_user: CurrentUser = Depends(require_admin)):
    """Crea un usuario delegando a n8n (auth + perfil + email) y luego crea permisos localmente."""
    email = payload.get("email")
    password = payload.get("password")
    full_name = payload.get("full_name")
    role = payload.get("role")
    empresa_id = payload.get("empresa_id")

    if not email:
        return JSONResponse(status_code=400, content={"error": "Email es obligatorio"})
    if not full_name:
        return JSONResponse(status_code=400, content={"error": "Nombre es obligatorio"})
    if not role:
        return JSONResponse(status_code=400, content={"error": "Rol es obligatorio"})

    # ── Hardening roles/tenant (matriz de permisos) ─────────────────────────
    master_empresa_id = _resolve_master_empresa_id()
    requested_role = _canonical_role(role)
    if requested_role not in {"superadmin", "admin", "user"}:
        raise HTTPException(status_code=400, detail="Rol inválido")

    if current_user.role == "superadmin":
        effective_role = requested_role
        effective_empresa_id = empresa_id
    elif is_ausarta_platform_admin(current_user):
        # Admin de Ausarta: mismos datos que superadmin; NO puede crear superadmin ni admin de Ausarta
        if requested_role == "superadmin":
            raise HTTPException(status_code=403, detail="Solo superadmin puede crear superadmins")
        if requested_role == "admin" and empresa_id == master_empresa_id:
            raise HTTPException(
                status_code=403,
                detail="Solo superadmin puede crear administradores de la empresa Ausarta",
            )
        effective_role = requested_role
        effective_empresa_id = empresa_id
    else:
        # Admin de cliente:
        # - solo puede crear role=user
        # - siempre en su propio tenant
        if requested_role != "user":
            raise HTTPException(status_code=403, detail="Admin de cliente solo puede crear usuarios role=user")
        if current_user.empresa_id is None:
            raise HTTPException(status_code=403, detail="Admin sin empresa asignada")
        effective_role = "user"
        effective_empresa_id = current_user.empresa_id
        if empresa_id is not None and empresa_id != effective_empresa_id:
            logger.warning(
                f"⚠️ [admin] Tenant escalation bloqueada. user={current_user.user_id} "
                f"intentó empresa_id={empresa_id}, forzado a {effective_empresa_id}"
            )

    role = effective_role
    empresa_id = effective_empresa_id

    logger.info(
        f"📨 [admin] Creando usuario: caller={current_user.user_id} "
        f"caller_role={current_user.role}, email={email}, role={role}, empresa_id={empresa_id}"
    )

    # Paso 1: Delegamos la creación del usuario a n8n (auth + perfil + email de bienvenida)
    base_url = os.getenv("N8N_WEBHOOK_BASE_URL")
    if not base_url:
        base_url = "https://n8n.ausarta.net/webhook"
    
    # Nos aseguramos de quitar la barra final si existe
    base_url = base_url.rstrip("/")
    webhook_url = f"{base_url}/d0952789-a4a1-4eae-b0db-494356a9e3fa"

    safe_payload = {
        "email": email,
        # SEGURIDAD: La contraseña NUNCA se envía a n8n ni a ningún sistema externo.
        # El único flujo soportado es invite_user_by_email: Supabase envía un email
        # al nuevo usuario para que establezca su contraseña de forma segura.
        "full_name": full_name,
        "role": role,
        "empresa_id": empresa_id,
        "redirect_to": payload.get("redirect_to") or os.getenv("INVITE_REDIRECT_TO") or os.getenv("FRONTEND_URL", "http://15.216.15.30")
    }

    n8n_secret = os.getenv("N8N_PROXY_SECRET", "")
    n8n_headers = {"X-N8N-Secret": n8n_secret} if n8n_secret else {}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=safe_payload, headers=n8n_headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                response_text = await resp.text()
                logger.info(f"📡 [admin] n8n respondió HTTP {resp.status}: {response_text[:500]}")

                if resp.status >= 400:
                    # Intentar parsear el mensaje de error de n8n
                    try:
                        import json
                        error_data = json.loads(response_text)
                        error_msg = error_data.get("message") or error_data.get("error") or response_text
                    except Exception:
                        error_msg = response_text

                    # Detectar errores comunes de Supabase Auth
                    lowered = error_msg.lower()
                    if "already registered" in lowered or "already exists" in lowered or "duplicate" in lowered:
                        return JSONResponse(status_code=409, content={
                            "error": "EMAIL_ALREADY_EXISTS",
                            "message": "Ya existe un usuario con ese email."
                        })

                    return JSONResponse(status_code=resp.status, content={
                        "error": "N8N_CREATE_FAILED",
                        "message": f"Error al crear usuario en n8n: {error_msg}"
                    })

                # Parsear respuesta exitosa de n8n
                try:
                    import json
                    n8n_data = json.loads(response_text)
                except Exception:
                    n8n_data = {}

                user_id = n8n_data.get("user_id")
                if not user_id:
                    logger.error(f"❌ [admin] n8n no devolvió user_id. Respuesta: {response_text[:300]}")
                    return JSONResponse(status_code=500, content={
                        "error": "N8N_NO_USER_ID",
                        "message": "El usuario se creó pero n8n no devolvió el user_id."
                    })

                logger.info(f"✅ [admin] Usuario creado vía n8n: {user_id}")

    except aiohttp.ClientError as e:
        logger.error(f"❌ [admin] Error de conexión con n8n: {e}")
        # Fallback: crear directamente si n8n no está disponible
        logger.info(f"🔄 [admin] Intentando fallback directo a Supabase Auth...")
        try:
            user_id = await _fallback_create_user(safe_payload)
        except Exception as fallback_err:
            return JSONResponse(status_code=500, content={
                "error": "CREATE_FAILED",
                "message": f"n8n no disponible ({e}) y fallback falló: {fallback_err}"
            })
    except Exception as e:
        logger.error(f"❌ [admin] Error inesperado: {e}")
        return JSONResponse(status_code=500, content={
            "error": "USER_CREATE_FAILED",
            "message": str(e)
        })

    # Paso 2: Crear permisos por defecto (n8n no los crea)
    try:
        modules = ["overview", "agents", "test_call", "campaigns", "ai_models", "telephony", "results", "usage", "users", "billing", "settings"]
        perms = [{"user_id": user_id, "module": m, "enabled": True} for m in modules]
        await sb_query(lambda: supabase.table("user_permissions").insert(perms).execute())
        logger.info(f"✅ [admin] Permisos creados para {user_id}")
    except Exception as perm_err:
        # No bloquear la respuesta: el usuario se creó, los permisos se pueden arreglar después
        logger.error(f"⚠️ [admin] Error creando permisos (no fatal): {perm_err}")

    # Paso 3: Limpiar cache de lista de usuarios
    await clear_ui_cache("users_list")

    # Paso 4: Invalidar caché de perfil en Redis/mem por si hubiera una entrada previa.
    # Garantiza que no haya estado cacheado inconsistente desde el primer request del nuevo usuario.
    await invalidate_user_profile_cache(user_id)

    # Siempre es invite flow: la contraseña nunca se establece desde el panel de admin.
    await log_audit_event(
        user_id=current_user.user_id,
        action="create_user",
        target_type="user",
        target_id=str(user_id),
        metadata={
            "email": email,
            "role": role,
            "empresa_id": empresa_id,
            "invited": True,
        },
    )
    return {"status": "ok", "user_id": user_id, "invited": True}


async def _fallback_create_user(payload: dict) -> str:
    """
    Fallback: crear usuario directamente vía Supabase Auth Admin SDK si n8n no responde.
    Siempre usa invite_user_by_email — nunca crea usuarios con contraseña predefinida.
    """
    email = payload["email"]
    full_name = payload["full_name"]
    role = payload["role"]
    empresa_id = payload.get("empresa_id")

    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    admin_client = create_client(os.getenv("SUPABASE_URL"), service_role_key)

    # Invite flow siempre: el usuario establece su contraseña a través del email de Supabase.
    options: dict = {"data": {"full_name": full_name, "role": role}}
    redirect_to = payload.get("redirect_to") or os.getenv("INVITE_REDIRECT_TO") or os.getenv("FRONTEND_URL")
    if redirect_to:
        options["redirect_to"] = redirect_to
    res = admin_client.auth.admin.invite_user_by_email(email, options)

    user_id = res.user.id

    await sb_query(lambda: supabase.table("user_profiles").upsert({
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "role": role,
        "empresa_id": empresa_id
    }).execute())

    logger.info(f"✅ [admin-fallback] Usuario {user_id} creado directamente vía invite")
    return user_id


@router.delete("/users/{user_id}")
@limiter.limit("20/minute")
async def delete_auth_user(request: Request, user_id: str, current_user: CurrentUser = Depends(require_admin)):
    """Elimina un usuario de Supabase Auth (requiere Service Role Key)"""
    if not supabase: 
        return JSONResponse(status_code=500, content={"error": "No hay conexión con la base de datos"})
    
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not service_role_key:
        service_role_key = os.getenv("SUPABASE_KEY")

    try:
        master_empresa_id = _resolve_master_empresa_id()
        prof = await sb_query(
            lambda: supabase.table("user_profiles")
            .select("id,role,empresa_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not prof.data:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        target = prof.data[0]
        target_role = _canonical_role(target.get("role"))
        target_empresa = target.get("empresa_id")

        # Matriz de borrado por jerarquía de negocio
        if current_user.role == "superadmin":
            pass
        elif is_ausarta_platform_admin(current_user):
            if target_role == "superadmin":
                raise HTTPException(status_code=403, detail="Admin Ausarta no puede borrar superadmin")
            if target_role == "admin" and target_empresa == master_empresa_id:
                raise HTTPException(status_code=403, detail="Solo superadmin puede eliminar admins de Ausarta")
        else:
            # Admin cliente: solo usuarios role=user de su propia empresa
            if target_empresa != current_user.empresa_id:
                raise HTTPException(status_code=403, detail="No puedes borrar usuarios de otra empresa")
            if target_role != "user":
                raise HTTPException(status_code=403, detail="Admin de cliente solo puede borrar usuarios role=user")

        admin_client = create_client(os.getenv("SUPABASE_URL"), service_role_key)
        
        # 1. Borrado fuerte de Auth (primero)
        try:
            admin_client.auth.admin.delete_user(user_id)
            logger.info(f"🔑 Auth user {user_id} deleted successfully")
        except Exception as auth_err:
            # Si falla Auth, devolvemos error: no limpiamos solo perfil para evitar inconsistencias.
            logger.error(f"❌ Error eliminando usuario {user_id} en Auth: {auth_err}")
            return JSONResponse(status_code=502, content={
                "error": "AUTH_DELETE_FAILED",
                "message": f"No se pudo eliminar el usuario en Auth: {auth_err}"
            })

        # 2. Borrar de la base de datos pública tras borrar Auth
        await sb_query(lambda: supabase.table("user_permissions").delete().eq("user_id", user_id).execute())
        await sb_query(lambda: supabase.table("user_profiles").delete().eq("id", user_id).execute())

        # 3. Revocar acceso instantáneamente: eliminar caché de perfil en Redis y memoria.
        # Sin esto, el JWT del usuario borrado seguiría siendo válido hasta que expire el TTL (60s).
        await invalidate_user_profile_cache(user_id)

        # 4. Limpiar cache de lista de usuarios
        await clear_ui_cache("users_list")
        
        logger.info(f"🗑️ Usuario {user_id} eliminado completamente del sistema")
        await log_audit_event(
            user_id=current_user.user_id,
            action="delete_user",
            target_type="user",
            target_id=str(user_id),
            metadata={"actor_role": current_user.role},
        )
        return {"status": "ok", "message": f"Usuario {user_id} eliminado correctamente"}
    except Exception as e:
        logger.error(f"❌ Error al borrar usuario admin: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.put("/users/{user_id}")
@limiter.limit("20/minute")
async def update_user(
    request: Request,
    user_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    prof = await sb_query(
        lambda: supabase.table("user_profiles").select("id,role,empresa_id").eq("id", user_id).limit(1).execute()
    )
    if not prof.data:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    target = prof.data[0]
    target_role = _canonical_role(target.get("role"))
    target_empresa = target.get("empresa_id")
    master_empresa_id = _resolve_master_empresa_id()

    if current_user.role == "superadmin":
        pass
    elif is_ausarta_platform_admin(current_user):
        if target_role == "superadmin":
            raise HTTPException(status_code=403, detail="Admin Ausarta no puede editar superadmin")
        if target_role == "admin" and target_empresa == master_empresa_id:
            raise HTTPException(status_code=403, detail="Solo superadmin puede editar admins de Ausarta")
    else:
        if target_empresa != current_user.empresa_id:
            raise HTTPException(status_code=403, detail="No puedes editar usuarios de otra empresa")
        if target_role != "user":
            raise HTTPException(status_code=403, detail="Admin cliente solo puede editar usuarios role=user")

    update: dict = {}
    if "full_name" in payload and payload["full_name"]:
        update["full_name"] = str(payload["full_name"]).strip()
    if "role" in payload:
        new_role = _canonical_role(payload["role"])
        if new_role not in {"admin", "user"}:
            raise HTTPException(status_code=400, detail="Rol inválido")
        if current_user.role != "superadmin" and new_role == "admin":
            raise HTTPException(status_code=403, detail="Solo superadmin puede asignar rol admin")
        update["role"] = new_role
    if "empresa_id" in payload:
        update["empresa_id"] = payload["empresa_id"]
    if "is_active" in payload:
        update["is_active"] = bool(payload["is_active"])

    if not update:
        raise HTTPException(status_code=400, detail="No se proporcionaron campos a actualizar")

    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    await sb_query(
        lambda: supabase.table("user_profiles").update(update).eq("id", user_id).execute()
    )

    if "role" in update:
        await invalidate_user_profile_cache(user_id)

    await log_audit_event(
        user_id=current_user.user_id,
        action="update_user",
        target_type="user",
        target_id=user_id,
        metadata={"changes": update},
    )
    return {"status": "ok", "user_id": user_id, "changes": update}


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
