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

    if not email or not password:
        return JSONResponse(status_code=400, content={"error": "Email y contraseña son obligatorios"})

    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    try:
        admin_client = create_client(os.getenv("SUPABASE_URL"), service_role_key)
        
        # Crear en Auth con auto-confirmación
        res = admin_client.auth.admin.create_user({
            "email": email,
            "password": password,
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

        return {"status": "ok", "user_id": user_id}
    except Exception as e:
        logger.error(f"❌ Error al crear usuario admin: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

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
