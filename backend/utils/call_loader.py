"""
call_loader.py — Carga de contexto pre-llamada (KB, BD externa, CRM).

Extraído de dynamic_agent.py para reducir el tamaño de CallSession.
Expone `enrich_agent_config_with_context`, que inyecta en agent_config:
  - _kb_context       : chunks relevantes de la Knowledge Base (RAG)
  - _customer_context : datos del cliente desde BD externa y/o CRM Supabase
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("agent")


async def _load_kb(
    job_id: str,
    empresa_id_int: int,
    agent_config: dict[str, Any],
) -> str:
    """Carga los chunks más relevantes de la KB para el saludo del agente."""
    try:
        from services.embedding_service import search_knowledge

        greeting = agent_config.get("greeting") or agent_config.get("instructions", "")
        query = (greeting or "información general servicios empresa")[:500]

        agent_id_int: int | None = None
        try:
            raw_agent_id = agent_config.get("agent_id")
            if raw_agent_id is not None:
                agent_id_int = int(str(raw_agent_id))
        except (TypeError, ValueError):
            agent_id_int = None

        results = await asyncio.wait_for(
            search_knowledge(
                empresa_id_int,
                query,
                limit=3,
                threshold=0.70,
                agent_id=agent_id_int,
            ),
            timeout=5,
        )
        if not results:
            return ""
        context = "\n\n".join(f"[{r['titulo']}]\n{r['contenido']}" for r in results)
        logger.info("[%s] KB context cargado: %d chunks (%.0f chars)", job_id, len(results), len(context))
        return context
    except Exception as kb_err:
        logger.warning("[%s] KB context no disponible: %s", job_id, kb_err)
        return ""


async def _load_customer(
    job_id: str,
    empresa_id_int: int,
    telefono: str,
) -> str:
    """Carga datos del cliente desde la BD externa configurada."""
    try:
        from services.external_db_service import query_external_db, format_customer_context

        rows = await asyncio.wait_for(
            query_external_db(empresa_id_int, "cliente_por_telefono", [telefono]),
            timeout=5,
        )
        if not rows:
            return ""
        ctx_str = format_customer_context(rows)
        logger.info("[%s] Customer context cargado desde BD externa: %d filas", job_id, len(rows))
        return ctx_str
    except Exception as ext_err:
        logger.warning("[%s] Customer context BD externa no disponible: %s", job_id, ext_err)
        return ""


async def _load_crm_contact(
    job_id: str,
    empresa_id_int: int,
    telefono: str,
) -> str:
    """Carga datos del contacto desde la tabla `contactos` de Supabase."""
    try:
        from services.supabase_service import supabase, sb_query

        if not supabase:
            return ""

        # Intentamos con columnas opcionales primero, luego fallback
        res = None
        for fields in (
            "nombre,email,empresa_nombre,cargo,notas,datos_extra,historial_llamadas,ultima_disposicion",
            "nombre,email,empresa_nombre,notas,datos_extra,ultima_disposicion",
            "nombre,email,notas,datos_extra",
        ):
            try:
                res = await asyncio.wait_for(
                    sb_query(
                        lambda f=fields: supabase.table("contactos")
                        .select(f)
                        .eq("empresa_id", empresa_id_int)
                        .eq("telefono", telefono)
                        .limit(1)
                        .execute()
                    ),
                    timeout=5,
                )
                if res and res.data:
                    break
            except Exception:
                res = None

        if not res or not res.data:
            return ""

        c = res.data[0]
        lines: list[str] = []
        for key, label in [
            ("nombre", "Nombre"),
            ("empresa_nombre", "Empresa"),
            ("cargo", "Cargo"),
            ("notas", "Notas"),
            ("ultima_disposicion", "Última disposición"),
        ]:
            if c.get(key):
                lines.append(f"{label}: {c[key]}")

        # Historial de llamadas — columna propia o fallback en datos_extra
        historial = c.get("historial_llamadas") or []
        if isinstance(historial, list) and historial:
            ultima = historial[-1] if isinstance(historial[-1], dict) else {}
            lines.append(f"Ultima llamada: {ultima.get('fecha', '?')} - {ultima.get('disposicion', '?')}")
        elif isinstance(c.get("datos_extra"), dict):
            llamadas = c["datos_extra"].get("llamadas") or []
            if isinstance(llamadas, list) and llamadas:
                ultima = llamadas[-1] if isinstance(llamadas[-1], dict) else {}
                lines.append(f"Ultima llamada: {ultima.get('fecha', '?')} - {ultima.get('disposicion', '?')}")

        return "\n".join(lines)
    except Exception as crm_err:
        logger.warning("[%s] CRM contact lookup failed: %s", job_id, crm_err)
        return ""


async def enrich_agent_config_with_context(
    job_id: str,
    agent_config: dict[str, Any],
    empresa_id_str: str,
    meta_data: dict[str, Any],
) -> None:
    """
    Carga en paralelo (timeout 5s por operación):
      1. Chunks de KB relevantes al saludo del agente.
      2. Datos del cliente desde BD externa (si hay teléfono en metadata).
      3. Contacto CRM en Supabase (si la BD externa no devuelve resultados).

    Inyecta en agent_config:
      - ``_kb_context``       → str (vacío si no hay KB disponible)
      - ``_customer_context`` → str (vacío si no hay datos)

    Nunca lanza excepción: si cualquier fuente falla, continúa sin ese contexto.
    """
    try:
        empresa_id_int = int(empresa_id_str) if str(empresa_id_str).isdigit() else 0
    except Exception:
        empresa_id_int = 0

    if not empresa_id_int:
        agent_config["_kb_context"] = ""
        agent_config["_customer_context"] = ""
        return

    telefono = str(
        meta_data.get("contacto_phone")
        or meta_data.get("telefono")
        or meta_data.get("phone")
        or ""
    )

    tasks: list[asyncio.Task] = [
        asyncio.create_task(_load_kb(job_id, empresa_id_int, agent_config))
    ]
    crm_task: asyncio.Task | None = None
    if telefono:
        crm_task = asyncio.create_task(_load_crm_contact(job_id, empresa_id_int, telefono))
        tasks.append(crm_task)

    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    kb_context: str = results_list[0] if isinstance(results_list[0], str) else ""
    customer_context = ""

    if crm_task is not None and len(results_list) > 1:
        crm_result = results_list[1] if isinstance(results_list[1], str) else ""
        if crm_result:
            customer_context = crm_result
        else:
            # Fallback a BD externa si CRM no devuelve datos
            customer_context = await _load_customer(job_id, empresa_id_int, telefono)

    agent_config["_kb_context"] = kb_context
    agent_config["_customer_context"] = customer_context
