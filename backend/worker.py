"""
worker.py — ARQ Worker para el motor de campañas Ausarta.

PROCESO SEPARADO a la API FastAPI. Consume tareas de Redis de forma
persistente: si el servidor se reinicia, los jobs pendientes sobreviven.

Arranque (imagen Docker: WORKDIR /app = raíz del backend):
    arq worker.WorkerSettings

Fases:
    Fase 1 (este archivo): Configuración base + stubs de tareas.
    Fase 2: Implementación real de campaign_scheduler_task y dispatch_lead_drip_task.
    Fase 3: Eliminación del asyncio.create_task() en api.py; endpoints usan arq.enqueue_job().

Flujo de datos:
    [API FastAPI]  →  enqueue_job("dispatch_lead_drip_task", lead_id, campaign_id)  →  [Redis]
    [ARQ Worker]   ←  consume job  →  _dispatch_single_lead_drip(lead, campaign)
    
    Cron cada 30s: campaign_scheduler_task escanea campañas activas y
    encola dispatch_lead_drip_task por cada empresa sin lock activo.
"""
import os
import json
import logging
from typing import Any
from datetime import datetime, timezone, timedelta
import asyncio

from arq import cron
from arq.connections import ArqRedis, RedisSettings
from utils.call_schedule import is_call_allowed
from services.trunk_service import resolve_outbound_trunk_id
from config import settings

logger = logging.getLogger("arq-worker")


# ──────────────────────────────────────────────
# Configuración Redis
# Reutiliza REDIS_URL del mismo .env que la API.
# ──────────────────────────────────────────────

def _build_redis_settings() -> RedisSettings:
    """
    Parsea REDIS_URL y construye RedisSettings para ARQ.

    Formato soportado: redis://[:password@]host[:port][/db]
    Ejemplo:           redis://redis:6379/0
                       redis://:mysecret@redis:6379/1
    """
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")

    try:
        # ARQ >= 0.25 expone from_dsn directamente
        return RedisSettings.from_dsn(url)
    except AttributeError:
        # Fallback manual para versiones más antiguas
        import re
        m = re.match(r"redis://(?::([^@]*)@)?([^:/]+)(?::(\d+))?(?:/(\d+))?", url)
        if m:
            password = m.group(1) or None
            host     = m.group(2) or "redis"
            port     = int(m.group(3) or 6379)
            database = int(m.group(4) or 0)
        else:
            logger.warning(f"No se pudo parsear REDIS_URL='{url}'. Usando redis://redis:6379/0")
            host, port, database, password = "redis", 6379, 0, None
        return RedisSettings(host=host, port=port, database=database, password=password)


# ──────────────────────────────────────────────
# Lifecycle del Worker
# ──────────────────────────────────────────────

async def startup(ctx: dict[str, Any]) -> None:
    """
    Inicialización del worker: conexiones compartidas entre tareas.
    ctx es inyectado por ARQ en cada tarea.
    """
    logger.info("🚀 [ARQ Worker] Arrancando...")

    redis: ArqRedis = ctx["redis"]
    await redis.set("ausarta:arq:worker_started", "1", ex=300)
    logger.info("✅ [ARQ Worker] Redis OK.")
    logger.info("✅ [ARQ Worker] Listo para consumir tareas.")


async def shutdown(ctx: dict[str, Any]) -> None:
    """Limpieza al apagar el worker."""
    logger.info("🌙 [ARQ Worker] Apagando...")


# ──────────────────────────────────────────────────────────────────────────────
# PARTE 1: Procesamiento de transcripciones con LLM (asíncrono, max_tries=3)
# ──────────────────────────────────────────────────────────────────────────────

async def process_transcription_ai(
    ctx: dict[str, Any],
    encuesta_id: int,
    transcription: str,
    empresa_id: int,
) -> None:
    """
    Tarea ARQ: analiza la transcripción de una llamada con un LLM y persiste
    los resultados estructurados (notas + comentario) en la tabla encuestas.

    Registrada con max_tries=3 en WorkerSettings para tolerar errores
    transitorios de la API de OpenAI (rate limits, timeouts de red).

    Flujo:
        1. Obtener prompt de sistema de la empresa (agent_config → system_prompt).
        2. Llamar a OpenAI con la transcripción.
        3. Parsear JSON de respuesta.
        4. UPDATE en encuestas con las notas y comentarios extraídos.
    """
    from services.supabase_service import supabase, sb_query
    import openai

    logger.info(
        f"🤖 [TranscriptionAI] Iniciando análisis encuesta={encuesta_id}, "
        f"empresa={empresa_id}, chars={len(transcription)}"
    )

    if not supabase:
        logger.error("[TranscriptionAI] Supabase no disponible. Abortando.")
        return

    if not transcription or not transcription.strip():
        logger.warning(f"[TranscriptionAI] Transcripción vacía para encuesta {encuesta_id}. Skipping.")
        return

    # ── Paso 1: Obtener el prompt de sistema de la empresa ────────────────────
    system_prompt_extra = ""
    try:
        agent_res = await sb_query(
            lambda: supabase.table("agent_config")
            .select("system_prompt")
            .eq("empresa_id", empresa_id)
            .limit(1)
            .execute()
        )
        if agent_res.data:
            system_prompt_extra = agent_res.data[0].get("system_prompt") or ""
    except Exception as e:
        logger.warning(f"[TranscriptionAI] No se pudo leer agent_config empresa {empresa_id}: {e}")

    analysis_system_prompt = (
        "Eres un analizador experto de llamadas comerciales en español. "
        "Recibirás la transcripción completa de una llamada entre un agente IA y un cliente. "
        "Tu tarea es extraer las valoraciones y el comentario clave.\n\n"
        "RESPONDE ÚNICAMENTE con un JSON válido (sin markdown, sin explicaciones) con esta estructura exacta:\n"
        "{\n"
        '  "nota_comercial": <número 1-10 o null>,\n'
        '  "nota_instalador": <número 1-10 o null>,\n'
        '  "nota_rapidez": <número 1-10 o null>,\n'
        '  "comentario_resumen": "<resumen en 1-3 frases del feedback del cliente>"\n'
        "}\n\n"
        "Si una nota no fue mencionada en la llamada, devuelve null para ese campo.\n"
        f"{('Contexto adicional del agente: ' + system_prompt_extra) if system_prompt_extra else ''}"
    )

    # ── Paso 2: Llamar al LLM ─────────────────────────────────────────────────
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("[TranscriptionAI] OPENAI_API_KEY no configurada. Abortando.")
        return

    client = openai.AsyncOpenAI(api_key=openai_api_key)
    try:
        logger.info(f"[TranscriptionAI] Enviando transcripción a OpenAI para encuesta {encuesta_id}...")
        response = await client.chat.completions.create(
            model=os.getenv("TRANSCRIPTION_LLM_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": analysis_system_prompt},
                {"role": "user", "content": f"TRANSCRIPCIÓN:\n{transcription}"},
            ],
            temperature=0.1,   # Baja temperatura para respuestas deterministas
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        raw_json = response.choices[0].message.content or "{}"
        logger.info(f"[TranscriptionAI] Respuesta LLM encuesta {encuesta_id}: {raw_json[:200]}")
    except openai.RateLimitError as e:
        # Forzamos excepción para que ARQ reintente (max_tries=3)
        logger.warning(f"[TranscriptionAI] Rate limit OpenAI encuesta {encuesta_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"[TranscriptionAI] Error llamando a OpenAI para encuesta {encuesta_id}: {e}")
        raise  # Propagar para que ARQ reintente

    # ── Paso 3: Parsear JSON de respuesta ─────────────────────────────────────
    try:
        extracted = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error(f"[TranscriptionAI] JSON inválido del LLM encuesta {encuesta_id}: {e} | raw={raw_json}")
        return  # No reintentamos un JSON malformado; es error del modelo

    # ── Paso 4: Persistir resultados en Supabase ──────────────────────────────
    update_payload: dict = {"ai_analysis_done": True}

    nota_comercial = extracted.get("nota_comercial")
    nota_instalador = extracted.get("nota_instalador")
    nota_rapidez = extracted.get("nota_rapidez")
    comentario = extracted.get("comentario_resumen")

    # Solo actualizamos campos con valor real para no sobrescribir datos del agente
    if isinstance(nota_comercial, (int, float)) and 1 <= nota_comercial <= 10:
        update_payload["puntuacion_comercial"] = nota_comercial
    if isinstance(nota_instalador, (int, float)) and 1 <= nota_instalador <= 10:
        update_payload["puntuacion_instalador"] = nota_instalador
    if isinstance(nota_rapidez, (int, float)) and 1 <= nota_rapidez <= 10:
        update_payload["puntuacion_rapidez"] = nota_rapidez
    if comentario:
        update_payload["comentarios_ai"] = str(comentario)[:1000]  # Limitar longitud

    try:
        await sb_query(
            lambda: supabase.table("encuestas")
            .update(update_payload)
            .eq("id", encuesta_id)
            .execute()
        )
        logger.info(
            f"✅ [TranscriptionAI] Encuesta {encuesta_id} actualizada: "
            f"comercial={nota_comercial}, instalador={nota_instalador}, "
            f"rapidez={nota_rapidez}"
        )
    except Exception as e:
        logger.error(f"[TranscriptionAI] Error guardando en Supabase encuesta {encuesta_id}: {e}")
        raise  # Propagar para reintento ARQ


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _next_retry_base(attempt: int, reference: datetime) -> datetime:
    if attempt == 1:
        return reference + timedelta(hours=2)
    if attempt == 2:
        return reference + timedelta(hours=24)
    return reference + timedelta(hours=48)


def _align_retry_to_allowed_slot(
    target: datetime,
    timezone_str: str,
    allowed_hours: tuple[int, int],
    forbidden_weekdays: set[int],
) -> datetime:
    candidate = target
    for _ in range(24 * 14):
        allowed, _ = is_call_allowed(
            now=candidate,
            timezone_str=timezone_str,
            allowed_hours=allowed_hours,
            forbidden_weekdays=forbidden_weekdays,
        )
        if allowed:
            return candidate
        candidate += timedelta(hours=1)
        candidate = candidate.replace(minute=0, second=0, microsecond=0)
    return candidate


async def _schedule_failed_survey_retry(encuesta_row: dict[str, Any]) -> datetime | None:
    from services.supabase_service import supabase, sb_query

    if not supabase:
        return None

    encuesta_id = int(encuesta_row.get("id") or 0)
    retry_count = int(encuesta_row.get("retry_count") or 0)
    if not encuesta_id or retry_count >= 3:
        return None

    reference = _parse_iso_datetime(encuesta_row.get("scheduled_at")) or datetime.now(timezone.utc)
    next_retry = _next_retry_base(retry_count + 1, reference)

    timezone_str = "Europe/Madrid"
    allowed_hours = (9, 21)
    forbidden_weekdays = {6}

    campaign_id = encuesta_row.get("campaign_id")
    if campaign_id:
        try:
            campaign_res = await sb_query(
                lambda: supabase.table("campaigns")
                .select("call_start_hour, call_end_hour, call_timezone, forbidden_weekdays")
                .eq("id", campaign_id)
                .limit(1)
                .execute()
            )
            if campaign_res.data:
                campaign = campaign_res.data[0]
                timezone_str = campaign.get("call_timezone") or timezone_str
                allowed_hours = (
                    int(campaign.get("call_start_hour") or allowed_hours[0]),
                    int(campaign.get("call_end_hour") or allowed_hours[1]),
                )
                forbidden_weekdays = set(campaign.get("forbidden_weekdays") or list(forbidden_weekdays))
        except Exception as exc:
            logger.warning("⚠️ [worker] No se pudo cargar horario de campaña para retry: %s", exc)

    retry_at = _align_retry_to_allowed_slot(
        target=next_retry,
        timezone_str=timezone_str,
        allowed_hours=allowed_hours,
        forbidden_weekdays=forbidden_weekdays,
    )

    await sb_query(
        lambda: supabase.table("encuestas")
        .update({
            "status": "pending_retry",
            "retry_count": retry_count + 1,
            "scheduled_at": retry_at.isoformat(),
        })
        .eq("id", encuesta_id)
        .execute()
    )
    try:
        await sb_query(
            lambda: supabase.table("campaign_leads")
            .update({
                "status": "pending_retry",
                "next_retry_at": retry_at.isoformat(),
            })
            .eq("call_id", encuesta_id)
            .execute()
        )
    except Exception as exc:
        logger.warning("⚠️ [worker] No se pudo sincronizar pending_retry en campaign_leads: %s", exc)
    logger.info("✅ [worker] Retry programado encuesta=%s retry_count=%s", encuesta_id, retry_count + 1)
    return retry_at


async def generate_transfer_briefing_task(
    ctx: dict[str, Any],
    payload_or_encuesta_id: dict[str, Any] | int,
    transcript: str | None = None,
    empresa_id: int | None = None,
    extension: str | None = None,
    room_name: str | None = None,
) -> None:
    from services.supabase_service import supabase, sb_query
    import openai

    if isinstance(payload_or_encuesta_id, dict):
        encuesta_id = int(payload_or_encuesta_id.get("encuesta_id") or 0)
        transcript = str(payload_or_encuesta_id.get("transcript") or "")
        empresa_id = int(payload_or_encuesta_id.get("empresa_id") or 0)
        extension = str(payload_or_encuesta_id.get("extension") or "")
        room_name = str(payload_or_encuesta_id.get("room_name") or "")
    else:
        encuesta_id = int(payload_or_encuesta_id or 0)
        transcript = str(transcript or "")
        empresa_id = int(empresa_id or 0)
        extension = str(extension or "")
        room_name = str(room_name or "")

    if not supabase or not transcript.strip():
        return

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.warning("?? [worker] OPENAI_API_KEY no configurada para briefing.")
        return

    client = openai.AsyncOpenAI(api_key=openai_api_key)
    system_prompt = (
        "Genera un briefing con formato fijo para un agente humano. "
        "Debes devolver exactamente estas secciones: SISTEMA, CLIENTE, MOTIVO, DATOS CLAVE, RESUMEN y TRANSCRIPCION COMPLETA."
    )
    user_prompt = (
        "Usa este formato exacto:\n"
        "SISTEMA: Transferencia de llamada IA -> Agente Humano\n"
        "CLIENTE: {nombre_detectado o No identificado}\n"
        "MOTIVO: {motivo de la llamada en 1 frase}\n"
        "DATOS CLAVE: {maximo 3 datos relevantes}\n"
        "RESUMEN: {2-3 frases}\n"
        "TRANSCRIPCION COMPLETA:\n"
        "{transcript completo}\n\n"
        f"TRANSCRIPCION:\n{transcript[:7000]}"
    )


    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=os.getenv("TRANSCRIPTION_LLM_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=500,
            ),
            timeout=5,
        )
        briefing = (response.choices[0].message.content or "").strip()
        if not briefing:
            return

        current = await sb_query(
            lambda: supabase.table("encuestas")
            .select("datos_extra")
            .eq("id", encuesta_id)
            .limit(1)
            .execute()
        )
        datos_extra = {}
        if current.data:
            raw = current.data[0].get("datos_extra")
            if isinstance(raw, dict):
                datos_extra = raw

        datos_extra["transfer_briefing"] = briefing
        await sb_query(
            lambda: supabase.table("encuestas")
            .update({"datos_extra": datos_extra, "transfer_briefing": briefing})
            .eq("id", encuesta_id)
            .execute()
        )

        webhook_base = (os.getenv("N8N_WEBHOOK_BASE_URL") or "").strip().rstrip("/")
        if webhook_base:
            await process_n8n_webhook(
                ctx,
                {
                    "url": f"{webhook_base}/transfer-briefing",
                    "body": {
                        "encuesta_id": encuesta_id,
                        "empresa_id": empresa_id,
                        "extension": extension,
                        "room_name": room_name,
                        "transcript": transcript,
                        "resumen": briefing,
                    },
                },
            )

        logger.info("? [worker] Briefing guardado para encuesta=%s empresa=%s", encuesta_id, empresa_id)
    except Exception as exc:
        logger.warning("?? [worker] Error generando briefing para encuesta=%s: %s", encuesta_id, exc)


async def send_telegram_alert_task(ctx: dict[str, Any], message: str) -> None:
    """Tarea ARQ para enviar alertas sin bloquear el flujo principal."""
    from services.telegram_service import send_telegram_alert

    _ = ctx
    await send_telegram_alert(message)


# ──────────────────────────────────────────────────────────────────────────────
# TAREA: Envío de Alertas del Sistema
# ──────────────────────────────────────────────────────────────────────────────
async def process_n8n_webhook(ctx: dict[str, Any], payload: dict) -> None:
    """
    Tarea ARQ: POST persistente a un webhook de n8n (p. ej. classify-agent).
    Reemplaza asyncio.create_task() en routers para no perder peticiones al reiniciar la API.
    """
    import aiohttp

    url = (payload or {}).get("url")
    body = (payload or {}).get("body") or {}
    if not url:
        logger.warning("[ARQ] process_n8n_webhook: payload sin URL, ignorando")
        return

    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.warning(
                        f"[ARQ] Webhook n8n respondió HTTP {resp.status} para {url}: {text[:200]}"
                    )
                else:
                    logger.info(f"[ARQ] Webhook n8n OK ({resp.status}): {url}")
    except Exception as e:
        logger.warning(f"[ARQ] Webhook n8n falló para {url}: {e}")


async def process_system_alert(ctx: dict[str, Any], message: str, details: dict = None) -> None:
    """
    Procesa las alertas del sistema enviándolas a una tabla de base de datos,
    o simplemente logueándolas de forma centralizada (reemplazo de n8n).
    """
    logger.error(f"🚨 ALERTA DEL SISTEMA: {message} | Detalles: {json.dumps(details or {})}")
    from services.supabase_service import supabase, sb_query
    if not supabase:
        return
    
    try:
        # Intentamos guardar la alerta en "system_logs" si la tabla existe.
        await sb_query(
            lambda: supabase.table("system_logs").insert({
                "level": "error",
                "message": message,
                "metadata": details or {}
            }).execute()
        )
    except Exception:
        # Silenciamos el error si la tabla no existe en este proyecto
        pass



# ──────────────────────────────────────────────────────────────────────────────
# PARTE 2: Orquestador nativo de campañas (Cron ARQ — cada minuto)
# ──────────────────────────────────────────────────────────────────────────────

async def process_yeastar_webhook(ctx: dict[str, Any], payload: dict) -> None:
    """
    Procesa webhooks de Yeastar desde ARQ para que sobrevivan a reinicios HTTP.
    """
    from services.yeastar_webhook_service import process_yeastar_webhook_payload

    _ = ctx
    await process_yeastar_webhook_payload(payload)


async def campaign_orchestrator(ctx: dict[str, Any]) -> None:
    """
    Cron ARQ: se ejecuta cada minuto.

    Orquesta el lanzamiento de llamadas para campañas activas de forma nativa,
    sin depender de n8n. Implementa:
      - Filtrado de empresas sin créditos.
      - Extracción de leads pendientes con next_retry_at <= now.
      - Concurrencia limitada con asyncio.Semaphore(5) para no saturar LiveKit.
      - Actualización de estado del lead a 'calling' antes del dispatch.
    """
    from services.supabase_service import supabase, sb_query
    from services.livekit_service import lkapi, create_isolated_room, dispatch_agent_explicit
    from livekit import api as lk_api

    if not supabase:
        logger.warning("[Orchestrator] Supabase no disponible. Skipping ciclo.")
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    batch_size = int(os.getenv("ORCHESTRATOR_BATCH_SIZE", "10"))
    max_parallel = int(os.getenv("ORCHESTRATOR_MAX_PARALLEL", "5"))

    logger.info(f"[Orchestrator] ▶ Ciclo iniciado. batch={batch_size}, max_parallel={max_parallel}")

    # ── Paso 1: Campañas activas ──────────────────────────────────────────────
    try:
        camp_res = await sb_query(
            lambda: supabase.table("campaigns")
            .select(
                "id, empresa_id, name, agent_id, call_start_hour, call_end_hour, "
                "call_timezone, forbidden_weekdays"
            )
            .eq("status", "active")
            .execute()
        )
        campaigns = camp_res.data or []
    except Exception as e:
        logger.error(f"[Orchestrator] Error leyendo campañas activas: {e}")
        return

    if not campaigns:
        logger.info("[Orchestrator] Sin campañas activas. Fin de ciclo.")
        return

    logger.info(f"[Orchestrator] {len(campaigns)} campaña(s) activa(s).")

    # ── Paso 2: Extraer leads pendientes de todas las campañas activas ───
    leads_to_dispatch: list[dict] = []

    for camp in campaigns:
        camp_id = camp["id"]
        empresa_id = camp.get("empresa_id") or 0

        try:
            leads_res = await sb_query(
                lambda: supabase.table("campaign_leads")
                .select("id, phone_number, campaign_id, empresa_id")
                .eq("campaign_id", camp_id)
                .eq("status", "pending")
                .or_(f"next_retry_at.is.null,next_retry_at.lte.{now_iso}")
                .order("next_retry_at", desc=False, nullsfirst=True)
                .limit(batch_size)
                .execute()
            )
            batch = leads_res.data or []
            if batch:
                logger.info(
                    f"[Orchestrator] Campaña {camp_id} (empresa {empresa_id}): "
                    f"{len(batch)} lead(s) pendiente(s)."
                )
            # Adjuntar metadata de campaña al lead para el dispatch
            for lead in batch:
                lead["_campaign_agent_id"] = camp.get("agent_id")
                lead["_campaign_name"] = camp.get("name", "")
            leads_to_dispatch.extend(batch)
        except Exception as e:
            logger.error(f"[Orchestrator] Error leyendo leads campaña {camp_id}: {e}")

    if not leads_to_dispatch:
        logger.info("[Orchestrator] Sin leads pendientes. Fin de ciclo.")
        return

    # FIX A — claim atómico: convertimos la carrera en operación idempotente.
    # Si otro proceso ya cambió el lead, el UPDATE no devuelve filas y lo saltamos.
    claimed_leads: list[dict] = []
    for lead in leads_to_dispatch:
        lead_id = lead["id"]
        now_utc = datetime.now(timezone.utc)
        allowed_hours = (
            int(lead.get("call_start_hour") or 9),
            int(lead.get("call_end_hour") or 21),
        )
        tz_name = lead.get("call_timezone") or "Europe/Madrid"
        forbidden_days = set(lead.get("forbidden_weekdays") or {6})
        can_call, reason = is_call_allowed(
            now=now_utc,
            timezone_str=tz_name,
            allowed_hours=allowed_hours,
            forbidden_weekdays=forbidden_days,
        )
        if not can_call:
            logger.info(
                f"[Orchestrator] Lead {lead_id} saltado por horario: {reason}"
            )
            continue

        try:
            claim_res = await sb_query(
                lambda: supabase.table("campaign_leads")
                .update(
                    {
                        "status": "calling",
                        "last_call_at": now_utc.isoformat(),
                    }
                )
                .eq("id", lead_id)
                .eq("status", "pending")
                .execute()
            )
            if not (claim_res.data or []):
                logger.info(
                    f"[Orchestrator] Lead {lead_id} ya reclamado por otro proceso. Skipping."
                )
                continue
            claimed_leads.append(lead)
        except Exception as claim_err:
            logger.error(f"[Orchestrator] Error en claim atómico lead {lead_id}: {claim_err}")

    if not claimed_leads:
        logger.info("[Orchestrator] Sin leads reclamados en este ciclo.")
        return

    logger.info(f"[Orchestrator] Total leads a despachar (claimed): {len(claimed_leads)}")

    # ── Paso 4: Dispatch con concurrencia limitada ────────────────────────────
    semaphore = asyncio.Semaphore(max_parallel)

    async def _dispatch_one(lead: dict) -> None:
        """Despacha una sola llamada SIP respetando el semáforo global."""
        lead_id = lead["id"]
        phone = lead.get("phone_number", "")
        camp_id = lead.get("campaign_id")
        empresa_id = lead.get("empresa_id") or 0
        agent_id = lead.get("_campaign_agent_id") or "1"
        camp_name = lead.get("_campaign_name", "")

        if not phone:
            logger.warning(f"[Orchestrator] Lead {lead_id} sin teléfono. Skipping.")
            return

        async with semaphore:
            try:
                # 1. Crear encuesta
                enc_res = await sb_query(
                    lambda: supabase.table("encuestas").insert({
                        "telefono": phone,
                        "fecha": datetime.now(timezone.utc).isoformat(),
                        "status": "initiated",
                        "completada": 0,
                        "agent_id": agent_id,
                        "empresa_id": empresa_id,
                        "campaign_id": camp_id,
                        "campaign_name": camp_name,
                    }).execute()
                )
                encuesta_id = enc_res.data[0]["id"]

                # 2. Vincular encuesta al lead
                await sb_query(
                    lambda: supabase.table("campaign_leads")
                    .update({"call_id": encuesta_id})
                    .eq("id", lead_id)
                    .execute()
                )

                # 3. Construir nombre de sala y metadata
                room_name = (
                    f"llamada_ausarta_empresa_{empresa_id}"
                    f"_campana_{camp_id}"
                    f"_contacto_{lead_id}"
                    f"_encuesta_{encuesta_id}"
                )
                room_metadata = {
                    "empresa_id": int(empresa_id),
                    "campaign_id": int(camp_id or 0),
                    "campana_id": int(camp_id or 0),
                    "contacto_id": int(lead_id),
                    "client_id": int(lead_id),
                    "lead_id": int(lead_id),
                    "survey_id": int(encuesta_id),
                }

                # 4. Crear sala LiveKit
                await create_isolated_room(room_name, metadata=room_metadata)

                # 5. Despachar agente antes del SIP (para que esté listo cuando conteste)
                agent_name = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()
                await dispatch_agent_explicit(
                    room_name=room_name,
                    agent_name=agent_name,
                    metadata=room_metadata,
                )
                logger.info(f"[Orchestrator] Agente despachado para lead {lead_id} en sala {room_name}.")

                # FIX 1: polling real en vez de sleep fijo — aborta si el agente no arranca
                from services.livekit_service import wait_for_agent_ready
                agent_ready = await wait_for_agent_ready(room_name)
                if not agent_ready:
                    logger.error(
                        f"[Orchestrator] Agente no listo para lead {lead_id} en sala {room_name}. "
                        "Abortando SIP, revirtiendo lead a 'pending'."
                    )
                    await sb_query(
                        lambda: supabase.table("campaign_leads")
                        .update({"status": "pending"})
                        .eq("id", lead_id)
                        .execute()
                    )
                    return

                # 6. Crear participante SIP
                sip_trunk_id = await resolve_outbound_trunk_id(int(empresa_id) if empresa_id else None)
                await lkapi.sip.create_sip_participant(
                    lk_api.CreateSIPParticipantRequest(
                        sip_trunk_id=sip_trunk_id,
                        sip_call_to=phone,
                        room_name=room_name,
                        participant_identity=f"user_{phone}_{encuesta_id}",
                        participant_name="Cliente",
                    )
                )
                logger.info(f"✅ [Orchestrator] Llamada SIP iniciada para lead {lead_id} → {phone}.")

            except Exception as e:
                logger.error(
                    f"❌ [Orchestrator] Error despachando lead {lead_id} ({phone}): {e}"
                )
                # Revertir estado del lead a 'pending' para que sea reintentado
                try:
                    await sb_query(
                        lambda: supabase.table("campaign_leads")
                        .update({"status": "pending"})
                        .eq("id", lead_id)
                        .execute()
                    )
                except Exception as revert_err:
                    logger.error(f"[Orchestrator] Error revirtiendo lead {lead_id}: {revert_err}")

    # Lanzar todos los dispatches con control de concurrencia
    await asyncio.gather(*[_dispatch_one(lead) for lead in claimed_leads])
    logger.info("[Orchestrator] ◀ Ciclo completado.")


# ──────────────────────────────────────────────
# Tareas heredadas del sistema de goteo (drip)
# ──────────────────────────────────────────────

async def campaign_scheduler_task(ctx: dict[str, Any]) -> None:
    """
    Cron: se ejecuta cada 30s (segundos :00 y :30 de cada minuto).

    Reemplaza campaign_scheduler_loop() de campaigns.py.
    Escanea campañas activas en Supabase y encola dispatch_lead_drip_task
    por cada empresa sin lock activo, usando ctx['redis'].enqueue_job().

    Ventaja frente al while-True en memoria: si el worker se reinicia,
    el siguiente ciclo de 30s retoma el trabajo sin pérdida de estado.
    """
    from services.supabase_service import supabase
    from routers.campaigns import (
        _is_empresa_locked, _acquire_empresa_lock, _check_campaign_completion,
        _get_active_call_count, _get_active_call_count_for_empresa,
    )

    if not supabase:
        logger.warning("[ARQ] Supabase no disponible en scheduler")
        return

    redis: ArqRedis = ctx["redis"]
    now_iso = datetime.utcnow().isoformat()
    max_concurrent_calls = int(os.getenv("MAX_CONCURRENT_CALLS", "10"))

    try:
        campaigns_res = await asyncio.to_thread(
            supabase.table("campaigns").select("*").in_("status", ["active", "running"]).execute
        )
        campaigns = campaigns_res.data or []
    except Exception as e:
        logger.error(f"[ARQ] Error leyendo campañas activas: {e}")
        return

    if campaigns:
        logger.info(f"[ARQ] Scheduler: {len(campaigns)} campañas activas.")

    active_count = await _get_active_call_count()
    if active_count >= max_concurrent_calls:
        logger.warning(f"[ARQ] Límite global de canales SIP alcanzado ({max_concurrent_calls}).")
        return

    # Rate limit por empresa: máximo de llamadas concurrentes por tenant
    max_calls_per_empresa = int(os.getenv("MAX_CALLS_PER_EMPRESA", "5"))

    for camp in campaigns:
        campaign_id = camp["id"]
        empresa_id = camp.get("empresa_id") or 0
        campaign_type = (camp.get("type") or "").strip().lower()
        use_orchestrator = bool(camp.get("use_orchestrator"))

        # FIX A — evitar doble despacho con orquestador.
        if campaign_type == "orchestrated" or use_orchestrator:
            logger.debug(
                f"[ARQ] Scheduler salta campaña {campaign_id} "
                f"(type={campaign_type}, use_orchestrator={use_orchestrator})"
            )
            continue

        cancel_key = f"ausarta:campaign:cancel:{campaign_id}"
        try:
            if await redis.exists(cancel_key):
                continue
        except Exception:
            pass

        if await _is_empresa_locked(empresa_id):
            continue

        # FIX G — cumplimiento horario por campaña.
        now_utc = datetime.now(timezone.utc)
        allowed_hours = (
            int(camp.get("call_start_hour") or 9),
            int(camp.get("call_end_hour") or 21),
        )
        tz_name = camp.get("call_timezone") or "Europe/Madrid"
        forbidden_days = set(camp.get("forbidden_weekdays") or {6})
        can_call, reason = is_call_allowed(
            now=now_utc,
            timezone_str=tz_name,
            allowed_hours=allowed_hours,
            forbidden_weekdays=forbidden_days,
        )
        if not can_call:
            logger.info(
                f"[ARQ] Scheduler salta campaña {campaign_id} por horario: {reason}"
            )
            continue

        # Per-empresa concurrent call rate limit
        empresa_active = await _get_active_call_count_for_empresa(empresa_id)
        if empresa_active >= max_calls_per_empresa:
            logger.info(
                f"[ARQ] Rate limit empresa {empresa_id}: "
                f"{empresa_active}/{max_calls_per_empresa} llamadas activas. "
                f"Skipping campaña {campaign_id}."
            )
            continue

        try:
            leads_res = await asyncio.to_thread(
                supabase.table("campaign_leads")
                .select("*")
                .eq("campaign_id", campaign_id)
                .in_("status", ["pending", "pending_retry"])
                .or_(f"next_retry_at.is.null,next_retry_at.lte.{now_iso}")
                .order("next_retry_at", desc=False, nullsfirst=True)
                .limit(1)
                .execute
            )
        except Exception as fetch_err:
            logger.error(f"[ARQ] Error leyendo leads campaña {campaign_id}: {fetch_err}")
            continue

        if not leads_res.data:
            is_done = await _check_campaign_completion(campaign_id)
            if is_done:
                try:
                    await asyncio.to_thread(
                        supabase.table("campaigns").update({"status": "completed"}).eq("id", campaign_id).execute
                    )
                    logger.info(f"[ARQ] Campaña {campaign_id} completada.")
                except Exception as done_err:
                    logger.error(f"[ARQ] Error marcando campaña {campaign_id} como completada: {done_err}")
            continue

        lead = leads_res.data[0]

        acquired = await _acquire_empresa_lock(empresa_id)
        if not acquired:
            continue

        job_id = f"dispatch:{campaign_id}:{lead['id']}"
        await redis.enqueue_job(
            "dispatch_lead_drip_task",
            lead["id"],
            campaign_id,
            _job_id=job_id,
        )


async def dispatch_lead_drip_task(ctx: dict[str, Any], lead_id: int, campaign_id: int) -> None:
    """
    Tarea persistida en Redis: ejecuta UNA llamada SIP para un lead.

    Reemplaza asyncio.create_task(_dispatch_single_lead_drip()) del scheduler.
    Al ser un job ARQ, su ejecución sobrevive reinicios del proceso API.

    Argumentos recibidos del job:
        lead_id:     ID del lead en campaign_leads.
        campaign_id: ID de la campaña padre.
    """
    import asyncio
    from services.supabase_service import supabase
    from routers.campaigns import _dispatch_single_lead_drip, _release_empresa_lock

    redis: ArqRedis = ctx["redis"]
    if not supabase:
        logger.warning("[ARQ] Supabase no disponible en dispatch task")
        return

    cancel_key = f"ausarta:campaign:cancel:{campaign_id}"
    if await redis.exists(cancel_key):
        try:
            lead_row = await asyncio.to_thread(
                supabase.table("campaign_leads").select("id, campaign_id").eq("id", lead_id).limit(1).execute
            )
            if lead_row.data:
                camp_row = await asyncio.to_thread(
                    supabase.table("campaigns").select("empresa_id").eq("id", campaign_id).limit(1).execute
                )
                empresa_id = (camp_row.data[0].get("empresa_id") if camp_row.data else 0) or 0
                await _release_empresa_lock(empresa_id)
        except Exception:
            pass
        logger.info(f"[ARQ] Campaña {campaign_id} cancelada, skipping lead {lead_id}")
        return

    lead_res = await asyncio.to_thread(
        supabase.table("campaign_leads").select("*").eq("id", lead_id).limit(1).execute
    )
    campaign_res = await asyncio.to_thread(
        supabase.table("campaigns").select("*").eq("id", campaign_id).limit(1).execute
    )

    if not lead_res.data or not campaign_res.data:
        logger.warning(f"[ARQ] Datos incompletos para dispatch lead={lead_id}, campaign={campaign_id}")
        return

    lead = lead_res.data[0]
    campaign = campaign_res.data[0]

    if campaign.get("status") not in ("active", "running"):
        logger.info(f"[ARQ] Campaña {campaign_id} no activa ({campaign.get('status')}), skipping lead {lead_id}")
        empresa_id = campaign.get("empresa_id") or 0
        await _release_empresa_lock(empresa_id)
        return

    await _dispatch_single_lead_drip(lead, campaign)


# ──────────────────────────────────────────────────────────────────────────────
# Puente HTTP agente LiveKit → API FastAPI (no bloquea el event loop del agente)
# ──────────────────────────────────────────────────────────────────────────────

def _agent_bridge_url() -> str:
    url = (
        os.getenv("BRIDGE_SERVER_URL_INTERNAL")
        or os.getenv("BRIDGE_SERVER_URL")
        or "http://backend:8001"
    )
    return url.strip().rstrip("/")


async def agent_post_guardar_encuesta(ctx: dict[str, Any], payload: dict) -> None:
    """POST /guardar-encuesta desde el worker ARQ."""
    import aiohttp
    from services.supabase_service import supabase, sb_query

    url = f"{_agent_bridge_url()}/guardar-encuesta"
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload, timeout=15) as resp:
            logger.info("[agent_bridge] guardar-encuesta HTTP %s encuesta=%s", resp.status, payload.get("id_encuesta"))

    if not supabase:
        return

    encuesta_id = int(payload.get("id_encuesta") or 0)
    if not encuesta_id:
        return

    try:
        encuesta_res = await sb_query(
            lambda: supabase.table("encuestas")
            .select("id, empresa_id, campaign_id, status, retry_count, scheduled_at")
            .eq("id", encuesta_id)
            .limit(1)
            .execute()
        )
        if not encuesta_res.data:
            return
        encuesta = encuesta_res.data[0]
        empresa_id = int(encuesta.get("empresa_id") or 0)
        status = (encuesta.get("status") or payload.get("status") or "").strip().lower()

        if status == "failed":
            await _schedule_failed_survey_retry(encuesta)

        if empresa_id:
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            empresa_res = await sb_query(
                lambda: supabase.table("empresas")
                .select("id, nombre, max_llamadas_mes")
                .eq("id", empresa_id)
                .limit(1)
                .execute()
            )
            if empresa_res.data:
                empresa = empresa_res.data[0]
                max_llamadas_mes = int(empresa.get("max_llamadas_mes") or 0)
                if max_llamadas_mes > 0:
                    count_res = await sb_query(
                        lambda: supabase.table("encuestas")
                        .select("id", count="exact")
                        .eq("empresa_id", empresa_id)
                        .gte("fecha", month_start.isoformat())
                        .execute()
                    )
                    consumed = int(count_res.count or 0)
                    if consumed >= int(max_llamadas_mes * 0.8):
                        await ctx["redis"].enqueue_job(
                            "send_telegram_alert_task",
                            f"[AUSARTA] Empresa {empresa.get('nombre') or empresa_id} ha superado el 80% de su cuota mensual ({consumed}/{max_llamadas_mes}).",
                        )

            streak_key = f"ausarta:failed_streak:{empresa_id}"
            if status == "failed":
                failed_streak = await ctx["redis"].incr(streak_key)
                await ctx["redis"].expire(streak_key, 86400)
                if failed_streak >= 3:
                    await ctx["redis"].enqueue_job(
                        "send_telegram_alert_task",
                        f"[AUSARTA] La empresa {empresa_id} acumula {failed_streak} llamadas consecutivas con status='failed'.",
                    )
            elif status:
                await ctx["redis"].delete(streak_key)
    except Exception as exc:
        logger.warning("⚠️ [worker] Post-procesado de guardar_encuesta falló: %s", exc)


async def agent_post_colgar(ctx: dict[str, Any], room_name: str) -> None:
    """POST /colgar desde el worker ARQ."""
    import aiohttp

    url = f"{_agent_bridge_url()}/colgar"
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json={"nombre_sala": room_name}, timeout=10) as resp:
            logger.info("[agent_bridge] colgar HTTP %s room=%s", resp.status, room_name)


async def agent_post_transfer(ctx: dict[str, Any], payload: dict) -> None:
    """Persiste estado transferred y llama a /api/calls/transfer."""
    import aiohttp

    base = _agent_bridge_url()
    guardar_payload = payload.get("guardar_payload") or {}
    transfer_payload = payload.get("transfer_payload") or {}

    async with aiohttp.ClientSession() as sess:
        if guardar_payload:
            async with sess.post(
                f"{base}/guardar-encuesta",
                json=guardar_payload,
                timeout=10,
            ) as resp:
                logger.info("[agent_bridge] transfer→guardar HTTP %s", resp.status)

        if transfer_payload:
            async with sess.post(
                f"{base}/api/calls/transfer",
                json=transfer_payload,
                timeout=20,
            ) as resp:
                body = await resp.text()
                logger.info(
                    "[agent_bridge] transfer HTTP %s room=%s body=%s",
                    resp.status,
                    transfer_payload.get("room_name"),
                    body[:200],
                )


# ──────────────────────────────────────────────
# WorkerSettings — clase leída por `arq` CLI
# ──────────────────────────────────────────────

class WorkerSettings:
    """
    Configuración del worker ARQ. La clase es leída por el CLI de arq:

        arq worker.WorkerSettings

    Variables de entorno reconocidas:
        REDIS_URL              — URL de Redis (default: redis://redis:6379/0)
        ARQ_MAX_JOBS           — Máx. tareas concurrentes (default: 10)
        ARQ_JOB_TIMEOUT        — Timeout por tarea en segundos (default: 660)
                                 Debe ser > max_call_time (300s) + max_cooldown (180s) + margen
    """

    # Conexión Redis
    redis_settings: RedisSettings = _build_redis_settings()

    # Lifecycle
    on_startup  = startup
    on_shutdown = shutdown

    # Todas las tareas disponibles para enqueue_job()
    functions = [
        campaign_scheduler_task,
        dispatch_lead_drip_task,
        process_transcription_ai,
        generate_transfer_briefing_task,
        process_n8n_webhook,
        process_system_alert,
        send_telegram_alert_task,
        process_yeastar_webhook,
        campaign_orchestrator,
        agent_post_guardar_encuesta,
        agent_post_colgar,
        agent_post_transfer,
    ]

    # Cron jobs:
    #   - campaign_scheduler_task: cada 30s (sistema de goteo legacy)
    #   - campaign_orchestrator: cada 60s (orquestador nativo, sin n8n)
    cron_jobs = [
        cron(
            campaign_scheduler_task,
            second={0, 30},
            unique=True,   # No encolar si la instancia anterior no ha terminado
            timeout=25,    # Debe terminar antes del siguiente tick (30s)
        ),
        cron(
            campaign_orchestrator,
            minute=None,   # Cada minuto (minute=None → todos los minutos)
            unique=True,   # No encolar si el ciclo anterior sigue corriendo
            timeout=55,    # Debe terminar antes del siguiente minuto
        ),
    ]

    # Concurrencia global del worker
    max_jobs: int = int(os.getenv("ARQ_MAX_JOBS", "10"))

    # Timeout: llamada SIP (max 300s) + cooldown (max 180s) + margen de seguridad.
    # process_transcription_ai usa max_tries=3 propio; el job_timeout global
    # cubre el caso de un cuelgue de red total.
    job_timeout: int = int(os.getenv("ARQ_JOB_TIMEOUT", "660"))

    # Conservar resultado de cada job 5 minutos (útil para debugging)
    keep_result: int = 300

    # Por defecto sin reintentos (el drip gestiona los suyos).
    # process_transcription_ai sobreescribe esto con max_tries=3.
    max_tries: int = 1

    # Health check en Redis cada 60s
    health_check_interval: int = 60
    health_check_key: str      = "ausarta:arq:health"


# Registro de max_tries específico por tarea.
# ARQ lee esta propiedad si se define como atributo de la función.
process_transcription_ai.max_tries = 3  # type: ignore[attr-defined]
