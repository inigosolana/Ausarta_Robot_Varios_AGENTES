import os
import sys
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# --- CONFIGURACIÓN DE LOGS ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("api.log", mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("api-backend")

load_dotenv()

# --- Carga de servicios (inicializa cliente Supabase / LiveKit) ---
import services.supabase_service  # noqa: F401
import services.livekit_service  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌅 Iniciando API Ausarta v2 (scheduler delegado a ARQ worker)...")

    try:
        from services.redis_service import get_redis
        await get_redis()
    except Exception as e:
        logger.warning(
            f"⚠️ Redis no disponible al arrancar: {e}. Los locks usarán fallback en memoria."
        )

    try:
        from services.queue_service import get_arq_pool
        await get_arq_pool()
        logger.info("✅ Cliente ARQ inicializado.")
    except Exception as e:
        logger.warning(f"⚠️ ARQ no disponible al arrancar: {e}.")

    yield

    logger.info("🌙 Apagando API Ausarta v2...")
    try:
        from services.redis_service import close_redis
        await close_redis()
    except Exception:
        pass
    try:
        from services.queue_service import close_arq_pool
        await close_arq_pool()
    except Exception:
        pass


app = FastAPI(title="Ausarta Voice Agent API", version="2.0.0", lifespan=lifespan)

# Rate Limiting — límite global de 120 req/min por IP
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — orígenes explícitos en lugar de wildcard
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,https://app.ausarta.net,https://www.ausarta.net"
    ).split(",") if o.strip()
]

# Protección: wildcard + allow_credentials es un error de configuración grave
if "*" in ALLOWED_ORIGINS:
    logger.error(
        "🚨 CORS_ALLOWED_ORIGINS contiene '*' junto con allow_credentials=True. "
        "Esto es inseguro y los navegadores lo rechazarán. "
        "Define orígenes explícitos en CORS_ALLOWED_ORIGINS."
    )
    raise RuntimeError("CORS misconfiguration: wildcard origin with credentials not allowed")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers.logs import router as logs_router
app.include_router(logs_router)


# --- ENDPOINTS BASE ---

@app.get("/")
async def root():
    return {"status": "ok", "service": "Ausarta Backend v2", "database": "Supabase"}


from routers.dashboard import router as dashboard_router
from routers.settings import router as settings_router
from routers.agents import router as agents_router
app.include_router(dashboard_router)
app.include_router(settings_router)
app.include_router(agents_router)


# --- CALL CONTROL ---

from routers.telephony import router as telephony_router
app.include_router(telephony_router)


# --- CAMPAIGN MANAGEMENT ---

from routers.admin import router as admin_router
from routers.campaigns import router as campaigns_router
app.include_router(admin_router)
app.include_router(campaigns_router)


# --- N8N PROXY + ASSISTANT ---

from routers.n8n_proxy import router as n8n_proxy_router
from routers.assistant import router as assistant_router
app.include_router(n8n_proxy_router)
app.include_router(assistant_router)
