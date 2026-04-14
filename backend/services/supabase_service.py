import os
import asyncio
from dotenv import load_dotenv
from supabase import create_client, Client
import logging
from datetime import datetime, timedelta, timezone

load_dotenv()
logger = logging.getLogger("api-backend")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR CRITICO: Faltan variables SUPABASE_URL o SUPABASE_KEY en .env")
    supabase: Client = None
else:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print(f"Conectado a Supabase: {SUPABASE_URL}")
    except Exception as e:
        logger.error(f"Error al conectar a Supabase: {e}")
        supabase = None


async def sb_query(fn):
    """Ejecuta una función síncrona de Supabase en un thread para no bloquear el event loop."""
    return await asyncio.to_thread(fn)


async def get_user_profile_async(user_id: str):
    if not supabase:
        return None
    response = await sb_query(
        lambda: supabase.table("user_profiles").select("*").eq("id", user_id).execute()
    )
    return response.data[0] if response.data else None


async def get_table_async(table: str, select: str = "*", **filters):
    if not supabase:
        return []
    def _fetch():
        q = supabase.table(table).select(select)
        for col, val in filters.items():
            q = q.eq(col, val)
        return q.execute()
    response = await sb_query(_fetch)
    return response.data or []


async def get_ui_cache(key: str, max_age_minutes: int = 5):
    """Obtiene datos de ui_cache si tienen menos de X minutos"""
    if not supabase: return None
    try:
        res = await sb_query(
            lambda: supabase.table("ui_cache").select("*").eq("key", key).limit(1).execute()
        )
        if res.data and len(res.data) > 0:
            updated_at = datetime.fromisoformat(res.data[0]["updated_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - updated_at < timedelta(minutes=max_age_minutes):
                logger.info(f"🚀 Cache HIT for {key}")
                return res.data[0]["data"]
    except Exception as e:
        logger.error(f"Error reading cache {key}: {e}")
    return None

async def clear_ui_cache(key: str):
    """Borra una entrada de la cache"""
    if not supabase: return
    try:
        await sb_query(
            lambda: supabase.table("ui_cache").delete().eq("key", key).execute()
        )
        logger.info(f"🗑️ Cache CLEARED for {key}")
    except Exception as e:
        logger.error(f"Error clearing cache {key}: {e}")
