from fastapi import APIRouter
from fastapi.responses import JSONResponse
from supabase import create_client
from services.supabase_service import supabase, clear_ui_cache
import os
import aiohttp
import logging

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.post("/users")
async def create_auth_user(payload: dict):
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

    logger.info(f"📨 [admin] Creando usuario: email={email}, role={role}, empresa_id={empresa_id}")

    # Paso 1: Delegamos la creación del usuario a n8n (auth + perfil + email de bienvenida)
    base_url = os.getenv("N8N_WEBHOOK_BASE_URL")
    if not base_url:
        base_url = "https://n8n.ausarta.net/webhook"
    
    # Nos aseguramos de quitar la barra final si existe
    base_url = base_url.rstrip("/")
    webhook_url = f"{base_url}/d0952789-a4a1-4eae-b0db-494356a9e3fa"

    n8n_payload = {
        "email": email,
        "password": password or "",
        "full_name": full_name,
        "role": role,
        "empresa_id": empresa_id,
        "redirect_to": payload.get("redirect_to") or os.getenv("INVITE_REDIRECT_TO") or os.getenv("FRONTEND_URL", "https://app.ausarta.net")
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=n8n_payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
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
            user_id = await _fallback_create_user(payload)
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
        options = {"data": {"full_name": full_name, "role": role}}
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
async def delete_auth_user(user_id: str):
    """Elimina un usuario de Supabase Auth (requiere Service Role Key)"""
    if not supabase: 
        return JSONResponse(status_code=500, content={"error": "No hay conexión con la base de datos"})
    
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not service_role_key:
        service_role_key = os.getenv("SUPABASE_KEY")

    try:
        admin_client = create_client(os.getenv("SUPABASE_URL"), service_role_key)
        
        # 1. Intentar borrar de Auth
        try:
            admin_client.auth.admin.delete_user(user_id)
            logger.info(f"🔑 Auth user {user_id} deleted successfully")
        except Exception as auth_err:
            # Si el usuario no existe en Auth, logueamos pero seguimos para limpiar la DB
            logger.warning(f"⚠️ User {user_id} not found in Auth or error: {auth_err}")

        # 2. Borrar de la base de datos (independientemente de Auth)
        supabase.table("user_permissions").delete().eq("user_id", user_id).execute()
        supabase.table("user_profiles").delete().eq("id", user_id).execute()
        
        # 3. Limpiar cache
        await clear_ui_cache("users_list")
        
        logger.info(f"🗑️ Usuario {user_id} eliminado completamente del sistema")
        return {"status": "ok", "message": f"Usuario {user_id} eliminado correctamente"}
    except Exception as e:
        logger.error(f"❌ Error al borrar usuario admin: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
