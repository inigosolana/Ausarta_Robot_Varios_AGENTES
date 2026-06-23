"""Obtención de configuración de agente vía Redis cache y HTTP con reintentos."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from agents.agent_common import (
    BRIDGE_SERVER_URL_INTERNAL,
    _AGENT_CONFIG_CACHE_TTL,
    _parse_inbound_caller_from_room,
    _validate_agent_config_tenant,
)
from services.redis_service import get_redis

logger = logging.getLogger("agent-dynamic")


async def _fetch_with_retries(url: str, max_attempts: int = 3) -> dict[str, Any] | None:
    """GET HTTP con reintentos y backoff lineal (0.25s * attempt)."""
    for attempt in range(1, max_attempts + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=ClientTimeout(total=5),
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                ) as resp:
                    if resp.status == 200:
                        body: dict[str, Any] = await resp.json()
                        return body
                    logger.warning(
                        f"⚠️ Intento {attempt}/{max_attempts}: no se pudo obtener config (HTTP {resp.status})"
                    )
        except Exception as e:
            if "Violación de seguridad" in str(e):
                raise
            logger.warning(
                f"⚠️ Intento {attempt}/{max_attempts}: error obteniendo config de agente: {e}"
            )

        if attempt < max_attempts:
            await asyncio.sleep(0.25 * attempt)

    return None


async def _cache_agent_config(cache_key: str, config: dict[str, Any], context: str) -> None:
    try:
        redis_client = await get_redis()
        await redis_client.set(
            cache_key,
            json.dumps(config, ensure_ascii=False),
            ex=_AGENT_CONFIG_CACHE_TTL,
        )
    except Exception as write_err:
        logger.warning(f"⚠️ No se pudo cachear config en Redis {context}: {write_err}")


async def fetch_agent_config(survey_id: str, expected_empresa_id: str = "0") -> dict[str, Any]:
    """Consulta config del agente: Redis (TTL 1h) → HTTP fallback → escribe en Redis."""
    cache_key = f"ausarta:agent_config:survey_{survey_id}"

    try:
        redis_client = await get_redis()
        cached_raw = await redis_client.get(cache_key)
        if cached_raw:
            config = json.loads(cached_raw)
            _validate_agent_config_tenant(config, expected_empresa_id)
            logger.info(f"📋 Config desde Redis para survey {survey_id}")
            return config
    except Exception as cache_err:
        logger.warning(f"⚠️ Redis cache miss/error para survey {survey_id}: {cache_err}")

    server_url = BRIDGE_SERVER_URL_INTERNAL
    url = (
        f"{server_url}/api/agent_config_by_survey/{survey_id}"
        f"?_ts={int(asyncio.get_running_loop().time() * 1000)}"
    )
    config = await _fetch_with_retries(url)
    if config is not None:
        _validate_agent_config_tenant(config, expected_empresa_id)
        await _cache_agent_config(cache_key, config, f"survey {survey_id}")
        logger.info(
            f"📋 Config HTTP para survey {survey_id}: "
            f"nombre='{config.get('name')}', modelo='{config.get('llm_model')}', "
            f"cfg_updated_at='{config.get('config_updated_at')}'"
        )
        return config

    logger.warning("⚠️ No se pudo obtener config fresca tras reintentos. Usando defaults.")
    return {}


async def fetch_agent_config_by_agent_id(
    agent_id: str,
    expected_empresa_id: str = "0",
) -> dict[str, Any]:
    """Consulta config directa por agent_id para llamadas entrantes SIP sin encuesta previa."""
    cache_key = f"ausarta:agent_config:agent_{agent_id}:empresa_{expected_empresa_id or '0'}"
    try:
        redis_client = await get_redis()
        cached_raw = await redis_client.get(cache_key)
        if cached_raw:
            config = json.loads(cached_raw)
            _validate_agent_config_tenant(config, expected_empresa_id)
            logger.info(f"Config inbound desde Redis para agent_id {agent_id}")
            return config
    except Exception as cache_err:
        logger.warning(f"Redis cache miss/error para agent_id {agent_id}: {cache_err}")

    server_url = BRIDGE_SERVER_URL_INTERNAL
    query_empresa = (
        f"&empresa_id={expected_empresa_id}"
        if expected_empresa_id and expected_empresa_id != "0"
        else ""
    )
    url = (
        f"{server_url}/api/agent_config_by_agent/{agent_id}"
        f"?_ts={int(asyncio.get_running_loop().time() * 1000)}{query_empresa}"
    )
    config = await _fetch_with_retries(url)
    if config is None:
        raise RuntimeError(f"No se pudo obtener config por agent_id={agent_id} tras reintentos")

    _validate_agent_config_tenant(config, expected_empresa_id)
    await _cache_agent_config(cache_key, config, f"inbound agent_id={agent_id}")
    return config


async def _register_inbound_call_record(
    agent_config: dict[str, Any],
    room_name: str,
    empresa_id: str,
) -> int:
    """Registra la llamada entrante en backend y devuelve encuesta_id numérico."""
    server_url = BRIDGE_SERVER_URL_INTERNAL
    telefono = _parse_inbound_caller_from_room(room_name)
    try:
        empresa_id_int = (
            int(empresa_id) if str(empresa_id).isdigit() else int(agent_config.get("empresa_id") or 0)
        )
    except (TypeError, ValueError):
        empresa_id_int = 0
    raw_agent_id = agent_config.get("id") or agent_config.get("agent_id")
    try:
        agent_id_int = int(raw_agent_id) if raw_agent_id is not None else None
    except (TypeError, ValueError):
        agent_id_int = None

    payload = {
        "empresa_id": empresa_id_int,
        "agent_id": agent_id_int,
        "telefono": telefono,
        "room_name": room_name,
        "agent_type": agent_config.get("agent_type"),
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{server_url}/inbound-call/register",
                json=payload,
                timeout=ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return int(data.get("encuesta_id") or 0)
                logger.warning(
                    "inbound-call/register HTTP %s room=%s", resp.status, room_name
                )
    except Exception as exc:
        logger.warning("No se pudo registrar inbound call: %s", exc)
    return 0
