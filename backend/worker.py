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
from datetime import datetime, timezone
import asyncio

from arq import cron
from arq.connections import ArqRedis, RedisSettings

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


# ──────────────────────────────────────────────────────────────────────────────
# TAREA: Envío de Alertas del Sistema
# ──────────────────────────────────────────────────────────────────────────────
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
            .select("id, empresa_id, name, agent_id")
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

    logger.info(f"[Orchestrator] Total leads a despachar: {len(leads_to_dispatch)}")

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
                # 1. Marcar el lead como 'calling' antes del dispatch para evitar
                #    que el siguiente tick del cron lo vuelva a coger.
                await sb_query(
                    lambda: supabase.table("campaign_leads")
                    .update({
                        "status": "calling",
                        "last_call_at": datetime.now(timezone.utc).isoformat(),
                    })
                    .eq("id", lead_id)
                    .execute()
                )
                logger.info(f"[Orchestrator] Lead {lead_id} marcado como 'calling'.")

                # 2. Crear encuesta
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

                # 3. Vincular encuesta al lead
                await sb_query(
                    lambda: supabase.table("campaign_leads")
                    .update({"call_id": encuesta_id})
                    .eq("id", lead_id)
                    .execute()
                )

                # 4. Construir nombre de sala y metadata
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

                # 5. Crear sala LiveKit
                await create_isolated_room(room_name, metadata=room_metadata)

                # 6. Despachar agente antes del SIP (para que esté listo cuando conteste)
                agent_name = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()
                await dispatch_agent_explicit(
                    room_name=room_name,
                    agent_name=agent_name,
                    metadata=room_metadata,
                )
                logger.info(f"[Orchestrator] Agente despachado para lead {lead_id} en sala {room_name}.")

                await asyncio.sleep(float(os.getenv("DRIP_AGENT_JOIN_DELAY_SECONDS", "3")))

                # 7. Crear participante SIP
                sip_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
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
    await asyncio.gather(*[_dispatch_one(lead) for lead in leads_to_dispatch])
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

        cancel_key = f"ausarta:campaign:cancel:{campaign_id}"
        try:
            if await redis.exists(cancel_key):
                continue
        except Exception:
            pass

        if await _is_empresa_locked(empresa_id):
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
                .eq("status", "pending")
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
        process_system_alert,
        campaign_orchestrator,
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
