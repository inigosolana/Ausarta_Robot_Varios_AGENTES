import os
import sys
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Servicios internos
from services.rate_limiter import limiter
from services.auth import get_supabase_jwt_secret
from services.redis_service import get_redis, close_redis
from services.queue_service import get_arq_pool, close_arq_pool
from services.queue_service import enqueue_telegram_alert
from middleware.tenant_context import TenantContextMiddleware

# Routers
from routers.logs import router as logs_router
from routers.dashboard import router as dashboard_router
from routers.settings import router as settings_router
from routers.agents import router as agents_router
from routers.telephony import router as telephony_router
from routers.admin import router as admin_router
from routers.campaigns import router as campaigns_router
from routers.n8n_proxy import router as n8n_proxy_router
from routers.auth_public import router as auth_public_router
from routers.assistant import router as assistant_router
from routers.api_credits import router as api_credits_router
from routers.monitoring import router as monitoring_router
from routers.knowledge import router as knowledge_router
from routers.contacts import router as contacts_router
# --- CONFIGURACIÓN DE LOGS ---
# Configurado antes de load_dotenv para capturar cualquier problema de arranque
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

# Inicialización anticipada de clientes singleton (Supabase / LiveKit)
# Se importan por efecto secundario: el módulo registra su cliente al cargarse.
import services.supabase_service  # noqa: F401
import services.livekit_service   # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌅 Iniciando API Ausarta v2 (scheduler delegado a ARQ worker)...")

    if not get_supabase_jwt_secret():
        logger.critical(
            "SUPABASE_JWT_SECRET no definida: el backend no puede validar el Bearer JWT. "
            "En Portainer: añade la variable al stack (Supabase → Settings → API → JWT Secret), "
            "asegúrate de que docker-compose pasa SUPABASE_JWT_SECRET al servicio backend, "
            "y haz Pull/Redeploy. Alternativa: SUPABASE_JWT_SECRET_FILE con ruta a un archivo."
        )
    else:
        logger.info("✅ JWT de sesión: SUPABASE_JWT_SECRET cargada correctamente.")

    try:
        await get_redis()
    except Exception as e:
        logger.warning(
            f"⚠️ Redis no disponible al arrancar: {e}. Los locks usarán fallback en memoria."
        )

    try:
        await get_arq_pool()
        logger.info("✅ Cliente ARQ inicializado.")
    except Exception as e:
        logger.warning(f"⚠️ ARQ no disponible al arrancar: {e}.")

    yield

    logger.info("🌙 Apagando API Ausarta v2...")
    try:
        await close_redis()
    except Exception:
        pass
    try:
        await close_arq_pool()
    except Exception:
        pass


app = FastAPI(title="Ausarta Voice Agent API", version="2.0.0", lifespan=lifespan)

# Rate Limiting — límite global de 120 req/min por IP (instancia en services/rate_limiter.py)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("❌ [api] Error 500 no controlado en %s", request.url.path)
    try:
        await enqueue_telegram_alert(
            f"[AUSARTA][500] {request.method} {request.url.path}: {type(exc).__name__}: {exc}"
        )
    except Exception:
        pass
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

# CORS — orígenes explícitos en lugar de wildcard
def _expand_dev_cors_origins(raw_origins: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()

    def _add(origin: str) -> None:
        if origin and origin not in seen:
            seen.add(origin)
            expanded.append(origin)

    for origin in raw_origins:
        value = origin.strip()
        if not value:
            continue
        _add(value)

        if value.startswith("http://localhost:"):
            port = value.rsplit(":", 1)[-1]
            _add(f"http://127.0.0.1:{port}")
        elif value.startswith("http://127.0.0.1:"):
            port = value.rsplit(":", 1)[-1]
            _add(f"http://localhost:{port}")

    return expanded


ALLOWED_ORIGINS = _expand_dev_cors_origins([
    o.strip() for o in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000,http://15.216.15.30,http://15.216.15.30,https://www.ausarta.net"
    ).split(",") if o.strip()
])

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

# Aislamiento multi-tenant: ContextVar empresa_id por request (OWASP)
app.add_middleware(TenantContextMiddleware)

# --- REGISTRO DE ROUTERS ---
app.include_router(logs_router)
app.include_router(dashboard_router)
app.include_router(settings_router)
app.include_router(agents_router)
app.include_router(telephony_router)
app.include_router(admin_router)
app.include_router(campaigns_router)
app.include_router(n8n_proxy_router)
app.include_router(auth_public_router)
app.include_router(assistant_router)
app.include_router(api_credits_router)
app.include_router(monitoring_router)
app.include_router(knowledge_router)
app.include_router(contacts_router)

# --- ENDPOINTS BASE ---

@app.get("/")
async def root():
    return {"status": "ok", "service": "Ausarta Backend v2", "database": "Supabase"}
