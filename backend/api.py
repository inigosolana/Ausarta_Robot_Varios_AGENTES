import os
import sys
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Servicios internos
from services.rate_limiter import limiter
from services.auth import get_supabase_jwt_secret
from services.redis_service import get_redis, close_redis
from services.queue_service import get_arq_pool, close_arq_pool
from services.livekit_service import close_livekit_api
from services.queue_service import enqueue_telegram_alert
from middleware.tenant_context import TenantContextMiddleware

# Routers
from routers.logs import router as logs_router
from routers.dashboard import router as dashboard_router
from routers.settings import router as settings_router
from routers.agents import router as agents_router
from routers.telephony import router as telephony_router
from routers.telephony_extensions import router as telephony_extensions_router
from routers.telephony_transfer import router as telephony_transfer_router
from routers.telephony_livekit_webhook import router as telephony_livekit_webhook_router
from routers.telephony_yeastar_webhook import router as telephony_yeastar_webhook_router
from routers.telephony_encuesta import router as telephony_encuesta_router
from routers.telephony_outbound import router as telephony_outbound_router
from routers.admin import router as admin_router
from routers.campaigns import router as campaigns_router
from routers.campaign_webhook_legacy import router as campaign_webhook_legacy_router
from routers.campaign_agent_config import router as campaign_agent_config_router
from routers.n8n_proxy import router as n8n_proxy_router
from routers.auth_public import router as auth_public_router
from routers.assistant import router as assistant_router
from routers.api_credits import router as api_credits_router
from routers.monitoring import router as monitoring_router
from routers.knowledge import router as knowledge_router
from routers.contacts import router as contacts_router
from routers.usage import router as usage_router
from routers.voices import router as voices_router
from routers.campaign_webhook import router as campaign_webhook_router
from routers.calls import router as calls_router
# --- CONFIGURACIÓN DE LOGS ---
# Logs en JSON estructurado (timestamp, level, logger, msg, empresa_id, request_id).
# LOG_FORMAT=plain desactiva JSON (útil para desarrollo local).
# Compatible con el FileHandler en api.log.
_LOG_FORMAT = os.environ.get("LOG_FORMAT", "json").lower()
if _LOG_FORMAT == "json":
    from services.json_logger import configure_json_logging
    configure_json_logging(level=logging.INFO, log_file="api.log", force=True)
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("api.log", mode="a", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
logger = logging.getLogger("api-backend")

load_dotenv()

# Inicialización anticipada de clientes singleton (Supabase / LiveKit)
# Se importan por efecto secundario: el módulo registra su cliente al cargarse.
from utils.env_validation import validate_startup_config
import services.supabase_service  # noqa: F401
import services.livekit_service   # noqa: F401
from services.auth import require_admin
from services.health_service import collect_health_dependencies


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

    startup_issues = validate_startup_config()
    if startup_issues:
        for issue in startup_issues:
            logger.critical("🚨 Configuración insegura/incompleta: %s", issue)
        raise RuntimeError(
            "Configuración obligatoria incompleta: " + ", ".join(startup_issues)
        )

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

    from utils.tracing import init_tracing, instrument_aiohttp_client, shutdown_tracing

    init_tracing(service_name=os.getenv("OTEL_SERVICE_NAME", "ausarta-voice-api"))
    instrument_aiohttp_client()

    yield

    shutdown_tracing()

    logger.info("🌙 Apagando API Ausarta v2...")
    try:
        await close_redis()
    except Exception:
        pass
    try:
        await close_arq_pool()
    except Exception:
        pass
    try:
        await close_livekit_api()
    except Exception:
        pass


app = FastAPI(title="Ausarta Voice Agent API", version="2.0.0", lifespan=lifespan)

from utils.tracing import instrument_fastapi

instrument_fastapi(app)

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
        "http://localhost:5173,http://localhost:3000,http://localhost:8080"
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
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Impersonate-Token",
        "X-N8N-Secret",
        "traceparent",
        "tracestate",
    ],
)

# Aislamiento multi-tenant: ContextVar empresa_id por request (OWASP)
app.add_middleware(TenantContextMiddleware)

# --- REGISTRO DE ROUTERS ---
app.include_router(logs_router)
app.include_router(dashboard_router)
app.include_router(settings_router)
app.include_router(agents_router)
app.include_router(telephony_router)
app.include_router(telephony_extensions_router)
app.include_router(telephony_transfer_router)
app.include_router(telephony_livekit_webhook_router)
app.include_router(telephony_yeastar_webhook_router)
app.include_router(telephony_encuesta_router)
app.include_router(telephony_outbound_router)
app.include_router(admin_router)
app.include_router(campaigns_router)
app.include_router(campaign_webhook_legacy_router)
app.include_router(campaign_agent_config_router)
app.include_router(n8n_proxy_router)
app.include_router(auth_public_router)
app.include_router(assistant_router)
app.include_router(api_credits_router)
app.include_router(monitoring_router)
app.include_router(knowledge_router)
app.include_router(contacts_router)
app.include_router(usage_router)
app.include_router(voices_router)
app.include_router(campaign_webhook_router)
app.include_router(calls_router)

# --- ENDPOINTS BASE ---

@app.get("/")
async def root():
    return {"status": "ok", "service": "Ausarta Backend v2", "database": "Supabase"}


@app.get("/health", tags=["health"])
async def health_check():
    """
    Health check público para balanceadores.

    En producción solo expone el estado agregado (sin detalles de infraestructura).
    Ver /health/detail para diagnóstico completo (requiere admin).
    """
    overall, deps = await collect_health_dependencies()
    status_code = 503 if overall == "down" else 200
    if os.getenv("ENVIRONMENT", "production").lower() in ("development", "dev", "local", "test"):
        return JSONResponse(content={"status": overall, "dependencies": deps}, status_code=status_code)
    return JSONResponse(content={"status": overall}, status_code=status_code)


@app.get("/health/detail", tags=["health"])
async def health_check_detail(_admin=Depends(require_admin)):
    """Health check detallado para monitoring interno (requiere JWT admin)."""
    overall, deps = await collect_health_dependencies()
    status_code = 503 if overall == "down" else 200
    return JSONResponse(content={"status": overall, "dependencies": deps}, status_code=status_code)
