from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import os
import aiohttp
import logging

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/n8n", tags=["n8n"])

@router.post("/invite")
async def proxy_n8n_invite(request: Request):
    payload = await request.json()
    base_url = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook")
    webhook_url = f"{base_url}/d0952789-a4a1-4eae-b0db-494356a9e3fa"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=10) as resp:
                data = await resp.json() if resp.content_type == 'application/json' else await resp.text()
                if not isinstance(data, dict):
                    data = {"message": data}
                return JSONResponse(status_code=resp.status, content=data)
    except Exception as e:
        logger.error(f"❌ Error en proxy n8n invite: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/recover")
async def proxy_n8n_recover(request: Request):
    payload = await request.json()
    base_url = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook")
    webhook_url = f"{base_url}/fbdb6333-c473-493a-a1da-6c1756d5ae04"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=10) as resp:
                data = await resp.json() if resp.content_type == 'application/json' else await resp.text()
                if not isinstance(data, dict):
                    data = {"message": data}
                return JSONResponse(status_code=resp.status, content=data)
    except Exception as e:
        logger.error(f"❌ Error en proxy n8n recover: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
