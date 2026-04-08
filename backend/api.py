import os
import aiohttp
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, List
from dotenv import load_dotenv
from livekit import api
from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client, Client
import logging
import sys
import json
from openai import AsyncOpenAI
from concurrent.futures import ThreadPoolExecutor

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

# --- CONFIGURACIÓN SUPABASE Y LIVEKIT ---
from services.supabase_service import supabase, get_ui_cache
from services.livekit_service import lkapi

app = FastAPI(title="Ausarta Voice Agent API", version="2.0.0")
executor = ThreadPoolExecutor(max_workers=20)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers.logs import router as logs_router
app.include_router(logs_router)

from models.schemas import (
    VoiceAgentCreate, VoiceAgentUpdate, CampaignCreate, CampaignLeadModel,
    CampaignModel, LlmConfig, EncuestaData, CallEndRequest, AIPromptRequest,
    AssistantChatRequest, AssistantToolResponse
)


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


# --- LIFECYCLE: Arrancar Redis + cliente ARQ al iniciar ---

@app.on_event("startup")
async def startup_event():
    logger.info("🌅 Iniciando API Ausarta v2 (scheduler delegado a ARQ worker)...")

    # 1. Inicializar Redis (necesario antes del scheduler para locks distribuidos)
    try:
        from services.redis_service import get_redis
        await get_redis()
    except Exception as e:
        logger.warning(f"⚠️ Redis no disponible al arrancar: {e}. Los locks usarán fallback en memoria.")

    # 2. Inicializar cliente ARQ (enqueue de jobs desde endpoints)
    try:
        from services.queue_service import get_arq_pool
        await get_arq_pool()
        logger.info("✅ Cliente ARQ inicializado.")
    except Exception as e:
        logger.warning(f"⚠️ ARQ no disponible al arrancar: {e}.")


@app.on_event("shutdown")
async def shutdown_event():
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
