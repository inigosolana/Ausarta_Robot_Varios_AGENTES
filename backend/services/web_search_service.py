"""Búsqueda pública en internet para el agente de voz (Wikipedia + DuckDuckGo)."""
from __future__ import annotations

import logging
import re

import aiohttp

logger = logging.getLogger("api-backend")

MAX_QUERY_LEN = 200


async def _fetch_wikipedia(query: str) -> str:
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "utf8": 1,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://es.wikipedia.org/w/api.php", params=params, timeout=8
            ) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
                results = (data.get("query") or {}).get("search") or []
                if not results:
                    return ""
                top_title = results[0].get("title")
                if not top_title:
                    return ""

            summary_url = (
                f"https://es.wikipedia.org/api/rest_v1/page/summary/{top_title.replace(' ', '_')}"
            )
            async with session.get(summary_url, timeout=8) as resp2:
                if resp2.status != 200:
                    return ""
                summary_data = await resp2.json()
                return (summary_data.get("extract") or "").strip()
    except Exception as exc:
        logger.warning("Wikipedia search failed: %s", exc)
        return ""


async def _fetch_duckduckgo(query: str) -> str:
    params = {
        "q": query,
        "format": "json",
        "no_redirect": 1,
        "no_html": 1,
        "skip_disambig": 1,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.duckduckgo.com/", params=params, timeout=8
            ) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
                abstract = (data.get("AbstractText") or "").strip()
                if abstract:
                    return abstract
                snippets: list[str] = []
                for item in (data.get("RelatedTopics") or [])[:5]:
                    if isinstance(item, dict) and item.get("Text"):
                        snippets.append(str(item["Text"]).strip())
                return " ".join(snippets).strip()
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)
        return ""


async def search_web(query: str, *, max_chars: int = 1200) -> str:
    """Busca información pública en internet. Devuelve texto vacío si no hay resultados."""
    clean_query = re.sub(r"\s+", " ", (query or "").strip())[:MAX_QUERY_LEN]
    if not clean_query:
        return ""

    wiki_text = await _fetch_wikipedia(clean_query)
    ddg_text = await _fetch_duckduckgo(clean_query)
    merged = "\n".join(part for part in (wiki_text, ddg_text) if part).strip()
    merged = re.sub(r"\s+", " ", merged)
    if not merged:
        return ""
    return merged[:max_chars]
