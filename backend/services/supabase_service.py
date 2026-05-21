import os
import asyncio
from dataclasses import dataclass
from dotenv import load_dotenv
from supabase import create_client, Client
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

load_dotenv()
logger = logging.getLogger("api-backend")

# PostgREST devuelve como máximo 1000 filas por petición sin range()
POSTGREST_PAGE_SIZE = int(os.getenv("SUPABASE_PAGE_SIZE", "1000"))
POSTGREST_MAX_PAGES = int(os.getenv("SUPABASE_MAX_QUERY_PAGES", "100"))

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


@dataclass
class TableQueryResult:
    """Resultado paginado con conteo exacto PostgREST (count='exact')."""
    data: list[dict[str, Any]]
    count: int


async def sb_query(fn):
    """Ejecuta una función síncrona de Supabase en un thread para no bloquear el event loop."""
    return await asyncio.to_thread(fn)


def _apply_eq_filters(query, filters: dict[str, Any]):
    for col, val in filters.items():
        query = query.eq(col, val)
    return query


async def get_user_profile_async(user_id: str):
    if not supabase:
        return None
    response = await sb_query(
        lambda: supabase.table("user_profiles").select("*").eq("id", user_id).execute()
    )
    return response.data[0] if response.data else None


async def get_table_async(
    table: str,
    select: str = "*",
    *,
    page_size: int = POSTGREST_PAGE_SIZE,
    max_pages: int = POSTGREST_MAX_PAGES,
    **filters,
) -> TableQueryResult:
    """
    Lee una tabla con filtros .eq(), paginación automática (range) y conteo exacto.

    Evita el límite oculto de 1000 filas de PostgREST concatenando páginas hasta
    agotar resultados o alcanzar max_pages (protección ante bucles).
    """
    if not supabase:
        return TableQueryResult(data=[], count=0)

    page_size = max(1, min(int(page_size), 1000))
    max_pages = max(1, int(max_pages))

    def _fetch_page(offset: int, with_count: bool):
        if with_count:
            q = supabase.table(table).select(select, count="exact")
        else:
            q = supabase.table(table).select(select)
        q = _apply_eq_filters(q, filters)
        end = offset + page_size - 1
        return q.range(offset, end).execute()

    all_rows: list[dict[str, Any]] = []
    total_count = 0
    offset = 0
    pages_fetched = 0

    while pages_fetched < max_pages:
        with_count = pages_fetched == 0
        response = await sb_query(lambda off=offset, wc=with_count: _fetch_page(off, wc))
        batch = list(response.data or [])
        all_rows.extend(batch)

        if with_count:
            # postgrest-py expone el total en response.count con count='exact'
            total_count = int(response.count) if response.count is not None else len(batch)

        pages_fetched += 1
        if len(batch) < page_size:
            break
        offset += page_size

    if pages_fetched >= max_pages and len(all_rows) >= page_size * max_pages:
        logger.warning(
            "get_table_async(%s): tope max_pages=%s alcanzado; pueden quedar filas sin leer",
            table,
            max_pages,
        )

    if total_count == 0 and all_rows:
        total_count = len(all_rows)

    return TableQueryResult(data=all_rows, count=total_count)


async def get_ui_cache(key: str, max_age_minutes: int = 5):
    """Obtiene datos de ui_cache si tienen menos de X minutos"""
    if not supabase:
        return None
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
    if not supabase:
        return
    try:
        await sb_query(
            lambda: supabase.table("ui_cache").delete().eq("key", key).execute()
        )
        logger.info(f"🗑️ Cache CLEARED for {key}")
    except Exception as e:
        logger.error(f"Error clearing cache {key}: {e}")


def _client_or_raise() -> Client:
    if not supabase:
        raise RuntimeError("Supabase no configurado: defina SUPABASE_URL y SUPABASE_KEY")
    return supabase


async def count_rows_async(
    table: str,
    *,
    count_column: str = "id",
    **filters,
) -> int:
    """Conteo exacto PostgREST con filtros .eq()."""
    client = _client_or_raise()

    def _run():
        q = client.table(table).select(count_column, count="exact")
        q = _apply_eq_filters(q, filters)
        r = q.execute()
        return int(r.count) if r.count is not None else 0

    return await sb_query(_run)


async def insert_row_async(table: str, data: dict[str, Any] | list[dict[str, Any]]):
    client = _client_or_raise()
    return await sb_query(lambda: client.table(table).insert(data).execute())


async def update_row_async(table: str, data: dict[str, Any], **filters):
    client = _client_or_raise()

    def _run():
        q = client.table(table).update(data)
        q = _apply_eq_filters(q, filters)
        return q.execute()

    return await sb_query(_run)


async def delete_rows_async(table: str, **filters):
    client = _client_or_raise()

    def _run():
        q = client.table(table).delete()
        q = _apply_eq_filters(q, filters)
        return q.execute()

    return await sb_query(_run)


async def select_rows_async(
    table: str,
    select: str = "*",
    *,
    order: tuple[str, bool] | None = None,
    limit: int | None = None,
    **filters,
) -> list[dict[str, Any]]:
    """Select con filtros eq; order=(column, desc)."""
    client = _client_or_raise()

    def _run():
        q = client.table(table).select(select)
        q = _apply_eq_filters(q, filters)
        if order:
            col, desc = order
            q = q.order(col, desc=desc)
        if limit is not None:
            q = q.limit(limit)
        return q.execute()

    res = await sb_query(_run)
    return list(res.data or [])
