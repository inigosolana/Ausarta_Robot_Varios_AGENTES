from fastapi import APIRouter
from fastapi.responses import JSONResponse
from supabase import create_client
from services.supabase_service import supabase
import os
import logging

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.post("/users")
async def create_auth_user(payload: dict):
    """Crea un usuario administrativamente saltando límites de correo"""
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

    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    try:
        admin_client = create_client(os.getenv("SUPABASE_URL"), service_role_key)

        password_str = str(password).strip() if password is not None else ""
        should_invite = password_str == ""

        if should_invite:
            # Enviar email de invitación para que el usuario cree su contraseña
            options = {"data": {"full_name": full_name, "role": role}}
            redirect_to = payload.get("redirect_to") or os.getenv("INVITE_REDIRECT_TO") or os.getenv("FRONTEND_URL")
            if redirect_to:
                options["redirect_to"] = redirect_to

            res = admin_client.auth.admin.invite_user_by_email(email, options)
        else:
            # Crear en Auth con auto-confirmación (sin email)
            res = admin_client.auth.admin.create_user({
                "email": email,
                "password": password_str,
                "user_metadata": {"full_name": full_name, "role": role},
                "email_confirm": True
            })

        user_id = res.user.id
        
        # Crear perfil y permisos
        supabase.table("user_profiles").upsert({
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "role": role,
            "empresa_id": empresa_id
        }).execute()

        # Permisos por defecto
        modules = ["overview", "agents", "test_call", "campaigns", "ai_models", "telephony", "results", "usage", "users", "billing", "settings"]
        perms = [{"user_id": user_id, "module": m, "enabled": True} for m in modules]
        supabase.table("user_permissions").insert(perms).execute()

        return {"status": "ok", "user_id": user_id, "invited": should_invite}
    except Exception as e:
        msg = str(e)
        logger.error(f"❌ Error al crear usuario admin: {e}")

        # Mensajes típicos de Supabase Auth
        lowered = msg.lower()
        if "user already registered" in lowered or "already exists" in lowered or "duplicate" in lowered:
            return JSONResponse(status_code=409, content={
                "error": "EMAIL_ALREADY_EXISTS",
                "message": "Ya existe un usuario con ese email."
            })
        if "foreign key" in lowered or "violates foreign key constraint" in lowered:
            return JSONResponse(status_code=400, content={
                "error": "INVALID_EMPRESA",
                "message": "La empresa seleccionada no es válida."
            })

        return JSONResponse(status_code=500, content={
            "error": "USER_CREATE_FAILED",
            "message": msg
        })

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
        admin_client.auth.admin.delete_user(user_id)
        
        supabase.table("user_permissions").delete().eq("user_id", user_id).execute()
        supabase.table("user_profiles").delete().eq("id", user_id).execute()
        
        logger.info(f"🗑️ Usuario {user_id} eliminado completamente del sistema")
        return {"status": "ok", "message": f"Usuario {user_id} eliminado correctamente"}
    except Exception as e:
        logger.error(f"❌ Error al borrar usuario admin: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
