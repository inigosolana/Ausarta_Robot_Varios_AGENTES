import os
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

async def get_ui_cache(key: str, max_age_minutes: int = 5):
    """Obtiene datos de ui_cache si tienen menos de X minutos"""
    if not supabase: return None
    try:
        res = supabase.table("ui_cache").select("*").eq("key", key).limit(1).execute()
        if res.data and len(res.data) > 0:
            updated_at = datetime.fromisoformat(res.data[0]["updated_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - updated_at < timedelta(minutes=max_age_minutes):
                logger.info(f"🚀 Cache HIT for {key}")
                return res.data[0]["data"]
    except Exception as e:
        logger.error(f"Error reading cache {key}: {e}")
    return None
