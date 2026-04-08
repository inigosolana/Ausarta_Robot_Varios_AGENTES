from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from supabase import create_client
from services.supabase_service import supabase, clear_ui_cache
from services.auth import CurrentUser, require_admin, require_superadmin
from services.audit import log_audit_event
import os
import aiohttp
import logging
import json
import hmac
import hashlib
import base64
import time

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _canonical_role(raw_role: str | None) -> str:
    role = (raw_role or "").strip().lower()
    if role == "superadmin":
        return "superadmin"
    if role in {"admin", "admin_empresa"}:
        return "admin"
    if role in {"user", "viewer"}:
        return "user"
    return role


def _get_master_empresa_id() -> int | None:
    """
    Tenant maestro (Ausarta):
    1) Preferencia: env AUSARTA_MASTER_EMPRESA_ID o MASTER_EMPRESA_ID
    2) Fallback: buscar empresa cuyo nombre sea "Ausarta"
    """
    raw = os.getenv("AUSARTA_MASTER_EMPRESA_ID") or os.getenv("MASTER_EMPRESA_ID")
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning(f"⚠️ [admin] MASTER_EMPRESA_ID inválido: {raw}")
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


def _is_admin_ausarta(current_user: CurrentUser, master_empresa_id: int | None) -> bool:
    return (
        current_user.role == "admin"
        and master_empresa_id is not None
        and current_user.empresa_id == master_empresa_id
    )


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


@router.post("/impersonate")
async def impersonate_tenant(payload: dict, current_user: CurrentUser = Depends(require_superadmin)):
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
    empresa_res = (
        supabase.table("empresas")
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
async def create_auth_user(payload: dict, current_user: CurrentUser = Depends(require_admin)):
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
    master_empresa_id = _get_master_empresa_id()
    requested_role = _canonical_role(role)
    if requested_role not in {"superadmin", "admin", "user"}:
        raise HTTPException(status_code=400, detail="Rol inválido")

    if current_user.role == "superadmin":
        effective_role = requested_role
        effective_empresa_id = empresa_id
    elif _is_admin_ausarta(current_user, master_empresa_id):
        # Admin de Ausarta:
        # - puede gestionar clientes
        # - NO puede crear superadmin
        # - NO puede crear admin dentro de Ausarta
        if requested_role == "superadmin":
            raise HTTPException(status_code=403, detail="Solo superadmin puede crear superadmins")
        if requested_role == "admin" and empresa_id == master_empresa_id:
            raise HTTPException(status_code=403, detail="Admin Ausarta no puede crear admin de Ausarta")
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
        "password": password or "",
        "full_name": full_name,
        "role": role,
        "empresa_id": empresa_id,
        "redirect_to": payload.get("redirect_to") or os.getenv("INVITE_REDIRECT_TO") or os.getenv("FRONTEND_URL", "https://app.ausarta.net")
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=safe_payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
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
        supabase.table("user_permissions").insert(perms).execute()
        logger.info(f"✅ [admin] Permisos creados para {user_id}")
    except Exception as perm_err:
        # No bloquear la respuesta: el usuario se creó, los permisos se pueden arreglar después
        logger.error(f"⚠️ [admin] Error creando permisos (no fatal): {perm_err}")

    # Paso 3: Limpiar cache de lista de usuarios
    await clear_ui_cache("users_list")

    should_invite = str(password or "").strip() == ""
    await log_audit_event(
        user_id=current_user.user_id,
        action="create_user",
        target_type="user",
        target_id=str(user_id),
        metadata={
            "email": email,
            "role": role,
            "empresa_id": empresa_id,
            "invited": should_invite,
        },
    )
    return {"status": "ok", "user_id": user_id, "invited": should_invite}


async def _fallback_create_user(payload: dict) -> str:
    """Fallback: crear usuario directamente vía Supabase Auth Admin SDK si n8n no responde."""
    email = payload["email"]
    password = str(payload.get("password") or "").strip()
    full_name = payload["full_name"]
    role = payload["role"]
    empresa_id = payload.get("empresa_id")

    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    admin_client = create_client(os.getenv("SUPABASE_URL"), service_role_key)

    if not password:
        options: dict = {"data": {"full_name": full_name, "role": role}}
        redirect_to = payload.get("redirect_to") or os.getenv("INVITE_REDIRECT_TO") or os.getenv("FRONTEND_URL")
        if redirect_to:
            options["redirect_to"] = redirect_to
        res = admin_client.auth.admin.invite_user_by_email(email, options)
    else:
        res = admin_client.auth.admin.create_user({
            "email": email,
            "password": password,
            "user_metadata": {"full_name": full_name, "role": role},
            "email_confirm": True
        })

    user_id = res.user.id

    supabase.table("user_profiles").upsert({
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "role": role,
        "empresa_id": empresa_id
    }).execute()

    logger.info(f"✅ [admin-fallback] Usuario {user_id} creado directamente")
    return user_id


@router.delete("/users/{user_id}")
async def delete_auth_user(user_id: str, current_user: CurrentUser = Depends(require_admin)):
    """Elimina un usuario de Supabase Auth (requiere Service Role Key)"""
    if not supabase: 
        return JSONResponse(status_code=500, content={"error": "No hay conexión con la base de datos"})
    
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not service_role_key:
        service_role_key = os.getenv("SUPABASE_KEY")

    try:
        master_empresa_id = _get_master_empresa_id()
        prof = (
            supabase.table("user_profiles")
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
        elif _is_admin_ausarta(current_user, master_empresa_id):
            if target_role == "superadmin":
                raise HTTPException(status_code=403, detail="Admin Ausarta no puede borrar superadmin")
            if target_role == "admin" and target_empresa == master_empresa_id:
                raise HTTPException(status_code=403, detail="Admin Ausarta no puede borrar admin de Ausarta")
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
        supabase.table("user_permissions").delete().eq("user_id", user_id).execute()
        supabase.table("user_profiles").delete().eq("id", user_id).execute()
        
        # 3. Limpiar cache
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
