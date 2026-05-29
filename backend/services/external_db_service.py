"""
External DB Service — consulta la BD externa del cliente (CRM, ERP, etc.).
SEGURIDAD: solo ejecuta queries predefinidos en empresa_external_db.queries.
Nunca acepta SQL libre del agente o de la API.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from services.supabase_service import supabase, sb_query
from services.crypto_service import decrypt_data

logger = logging.getLogger("api-backend")

_MAX_ROWS = 20
_QUERY_TIMEOUT = 8.0


async def query_external_db(
    empresa_id: int,
    query_name: str,
    params: list[Any] | None = None,
) -> list[dict] | None:
    """
    Ejecuta un query predefinido en la BD externa de la empresa.

    Devuelve lista de filas (máx. 20) o None si:
    - No hay config para la empresa
    - El query_name no está en la lista blanca
    - La conexión falla o hay timeout
    """
    if not supabase:
        return None

    try:
        config_res = await sb_query(
            lambda eid=empresa_id: supabase.table("empresa_external_db")
            .select(
                "db_type, connection_url, api_url, api_key_enc, "
                "api_key_header, queries, activo"
            )
            .eq("empresa_id", eid)
            .eq("activo", True)
            .limit(1)
            .execute()
        )
        if not config_res.data:
            return None

        cfg = config_res.data[0]
        queries: dict = cfg.get("queries") or {}

        # SECURITY: solo queries en lista blanca
        if query_name not in queries:
            logger.warning(
                "[ext_db] Query '%s' no está en la lista blanca de empresa %s",
                query_name, empresa_id,
            )
            return None

        db_type = (cfg.get("db_type") or "rest").lower()

        result = await asyncio.wait_for(
            _execute_query(cfg, db_type, query_name, queries[query_name], params or []),
            timeout=_QUERY_TIMEOUT,
        )
        if result is None:
            return None
        return result[:_MAX_ROWS]

    except asyncio.TimeoutError:
        logger.warning(
            "[ext_db] Timeout (%ss) en query '%s' empresa %s",
            _QUERY_TIMEOUT, query_name, empresa_id,
        )
        return None
    except Exception as e:
        logger.warning("[ext_db] Error consultando BD externa empresa %s: %s", empresa_id, e)
        return None


async def _execute_query(
    cfg: dict,
    db_type: str,
    query_name: str,
    query_template: Any,
    params: list[Any],
) -> list[dict] | None:
    if db_type in ("postgresql", "postgres"):
        return await _query_postgres(cfg, query_template, params)
    return await _query_rest_api(cfg, query_name, params)


async def _query_postgres(
    cfg: dict,
    query_template: Any,
    params: list[Any],
) -> list[dict] | None:
    """Ejecuta SQL predefinido via asyncpg."""
    try:
        import asyncpg  # type: ignore
    except ImportError:
        logger.warning("[ext_db] asyncpg no disponible. Instala con: pip install asyncpg")
        return None

    connection_url_raw = cfg.get("connection_url") or ""
    if not connection_url_raw:
        return None

    try:
        connection_url = decrypt_data(connection_url_raw)
    except Exception:
        connection_url = connection_url_raw

    sql = (
        query_template
        if isinstance(query_template, str)
        else (query_template or {}).get("sql", "")
    )
    if not sql or not sql.strip():
        return None

    try:
        conn = await asyncpg.connect(connection_url, timeout=5)
        try:
            rows = await conn.fetch(sql, *params)
            return [dict(row) for row in rows]
        finally:
            await conn.close()
    except Exception as pg_err:
        logger.warning("[ext_db] PostgreSQL error: %s", pg_err)
        return None


async def _query_rest_api(
    cfg: dict,
    query_name: str,
    params: list[Any],
) -> list[dict] | None:
    """Llama a la REST API externa con los parámetros como query params."""
    api_url = (cfg.get("api_url") or "").rstrip("/")
    api_key_enc = cfg.get("api_key_enc") or ""
    api_key_header = cfg.get("api_key_header") or "Authorization"

    if not api_url:
        return None

    api_key = ""
    if api_key_enc:
        try:
            api_key = decrypt_data(api_key_enc)
        except Exception:
            api_key = api_key_enc

    headers: dict = {}
    if api_key:
        if api_key_header.lower() == "authorization":
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers[api_key_header] = api_key

    req_params: dict = {}
    for i, p in enumerate(params):
        req_params[f"param{i}"] = str(p)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{api_url}/{query_name}",
                params=req_params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        return [data]
                    return []
                logger.warning(
                    "[ext_db] REST API HTTP %s para '%s'", resp.status, query_name
                )
                return None
    except Exception as rest_err:
        logger.warning("[ext_db] REST API error: %s", rest_err)
        return None


def format_customer_context(rows: list[dict]) -> str:
    """
    Formatea filas de la BD externa como contexto para el agente.
    """
    if not rows:
        return ""
    lines = ["=== DATOS DEL CLIENTE (BD externa) ==="]
    for row in rows[:3]:
        for k, v in row.items():
            if v is not None and str(v).strip():
                lines.append(f"{k.replace('_', ' ').title()}: {v}")
    lines.append("===")
    return "\n".join(lines)
