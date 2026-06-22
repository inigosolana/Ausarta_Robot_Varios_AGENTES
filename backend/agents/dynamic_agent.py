import logging
from typing import Optional, Any
import os
import time
import asyncio
import sys
import json
import re
import random
from dotenv import load_dotenv
from config import settings

# Solo cargar .env en desarrollo local; en producción Docker las vars vienen del entorno del contenedor.
if os.getenv("ENVIRONMENT", "production") == "development":
    load_dotenv()

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AudioConfig,
    BackgroundAudioPlayer,
    BuiltinAudioClip,
    JobContext,
    RunContext,
    cli,
    function_tool,
    AutoSubscribe,
    llm,
)
from livekit.agents.llm.tool_context import StopResponse
from livekit.plugins import (
    silero,
    openai,
    deepgram, 
    cartesia  
)

# --- CONFIGURACIÓN DE LOGS ---
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True) # type: ignore
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True) # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("agent.log", mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("agent-dynamic")

from agents.agent_common import (
    ALLOWED_ROOM_PREFIXES,
    BRIDGE_SERVER_URL_INTERNAL,
    DISPATCH_AGENT_NAME,
    _extract_transcript_from_session,
    _is_inbound_agent_config,
    _normalize_message_text,
    _parse_inbound_caller_from_room,
    _room_name_allowed,
    anonymize_text,
)
from agents.semantic_routes import resolve_semantic_routing_config
from agents.agent_lifecycle import CallSessionLifecycleMixin, DynamicAgentLifecycleMixin
from agents.agent_tools import AgentToolsMixin
from agents.config_fetcher import (
    _fetch_with_retries,
    _register_inbound_call_record,
    fetch_agent_config,
    fetch_agent_config_by_agent_id,
)
from agents.post_call_processor import finalize_call_session
from agents.stt_tts_builder import (
    DEFAULT_CARTESIA_VOICE,
    _build_stt_plugin,
    _build_tts_plugin,
    build_resilient_stt_plugin,
    build_resilient_tts_plugin,
    get_vad_model,
)

def _extraction_schema_to_json_schema(properties: list) -> dict[str, Any]:
    """Convierte extraction_schema de campaña a JSON Schema (OpenAI strict)."""
    props: dict[str, Any] = {}
    required: list[str] = []
    for item in properties:
        if not isinstance(item, dict):
            continue
        key = (item.get("key") or "").strip()
        if not key:
            continue
        field_type = (item.get("type") or "text").strip().lower()
        if field_type == "boolean":
            props[key] = {"type": "boolean", "description": item.get("label") or key}
        elif field_type == "number":
            props[key] = {"type": "number", "description": item.get("label") or key}
        elif field_type == "enum":
            options = item.get("options") or []
            if options:
                props[key] = {
                    "type": "string",
                    "enum": options,
                    "description": item.get("label") or key,
                }
            else:
                props[key] = {"type": "string", "description": item.get("label") or key}
        else:
            props[key] = {"type": "string", "description": item.get("label") or key}
        required.append(key)
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def _build_guardar_encuesta_raw_schema(extraction_schema: list) -> dict[str, Any]:
    """Schema OpenAI strict para la herramienta guardar_encuesta."""
    datos_extra_schema = _extraction_schema_to_json_schema(extraction_schema)
    return {
        "type": "function",
        "name": "guardar_encuesta",
        "description": (
            "Guarda los datos de la encuesta/llamada. "
            "datos_extra debe cumplir el esquema de extracción definido."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "id_encuesta": {"type": "integer"},
                "nota_comercial": {"type": ["integer", "null"]},
                "nota_instalador": {"type": ["integer", "null"]},
                "nota_rapidez": {"type": ["integer", "null"]},
                "comentarios": {"type": ["string", "null"]},
                "status": {
                    "type": ["string", "null"],
                    "enum": ["completed", "failed", "incomplete", "rejected_opt_out"],
                },
                "datos_extra": datos_extra_schema,
            },
            "required": ["id_encuesta", "datos_extra"],
            "additionalProperties": False,
        },
    }

from prompts import _LANG_OVERRIDE_MSGS
from utils.kb_settings import resolve_kb_allow_internet
from utils.prompt_builder import build_agent_prompt
from utils.prompt_sanitizer import sanitize_untrusted_text
from utils.workflow_compiler import compile_workflow_to_prompt
from utils.workflow_state import WorkflowStateMachine
from services.queue_service import (
    enqueue_colgar_sala,
    enqueue_guardar_encuesta,
    enqueue_transfer_briefing,
    enqueue_transfer_to_human,
)
from services.call_results_service import prepare_transcription_for_storage
from services.semantic_router_service import SemanticRouterService

class DynamicAgent(Agent, AgentToolsMixin, DynamicAgentLifecycleMixin):
    """Agente dinámico que carga sus instrucciones desde Supabase."""
    
    def __init__(self, room_name: str, agent_config: dict) -> None:
        self.server_url = BRIDGE_SERVER_URL_INTERNAL
        self._extraction_schema = agent_config.get("extraction_schema") or []
        self.data_saved = False
        self.room_name = room_name
        self.agent_config = agent_config
        self.empresa_id = str(agent_config.get("empresa_id", "0") or "0")
        self.greeting = agent_config.get("greeting", "Buenas, ¿tiene un momento?")
        self.company_context = agent_config.get("company_context", "") or ""
        self.kb_allow_internet = resolve_kb_allow_internet(agent_config)
        self.enthusiasm_level = agent_config.get("enthusiasm_level", "Normal") or "Normal"
        self.voice_id = agent_config.get("voice_id", "") or ""
        self.tts_model = agent_config.get("tts_model", settings.default_tts_model)
        self.speaking_speed = agent_config.get("speaking_speed", 1.0)
        self.hangup_started = False
        self._transfer_completed = asyncio.Event()
        self._transfer_in_progress = False

        routing_enabled, custom_phrases = resolve_semantic_routing_config(agent_config)
        self._semantic_router: SemanticRouterService | None = (
            SemanticRouterService(custom_phrases=custom_phrases) if routing_enabled else None
        )
        
        try:
            # Soportamos formatos:
            # 1. inigo_local_encuesta_123
            # 2. encuesta_123
            # 3. 123
            parts = room_name.split('_')
            self.survey_id = parts[-1] if parts else "0"
            
            # Verificación extra por si el formato es distinto
            if not self.survey_id.isdigit() and len(parts) >= 2:
                # Si el último no es dígito, probamos con el penúltimo
                self.survey_id = parts[-2]
        except Exception as survey_parse_err:
            logger.warning(
                f"Error parseando survey_id desde room_name '{room_name}': {survey_parse_err}"
            )
            self.survey_id = "0"

        try:
            speaking_speed_f = float(self.speaking_speed)
        except Exception:
            speaking_speed_f = 1.0

        # ── Modo de agente: prompt (existente) | workflow | mixed ──────────
        self._agent_mode: str = (agent_config.get("agent_mode") or "prompt").strip().lower()
        self._workflow_sm: "WorkflowStateMachine | None" = None

        # _kb_context y _customer_context son inyectados en agent_config
        # por entrypoint() antes de crear DynamicAgent (Fase 2).
        agent_language = str(agent_config.get("language") or "es")
        base_instructions = build_agent_prompt(
            agent_config,
            self.enthusiasm_level,
            speaking_speed_f,
            language=agent_language,
        )

        # Nombre del cliente detectado en conversación (Fase 2)
        self._detected_customer_name: str = ""

        if self._agent_mode in ("workflow", "mixed"):
            wf_def = agent_config.get("workflow_definition") or {}
            wf_vars = agent_config.get("workflow_variables") or {}
            if wf_def:
                try:
                    compiled_prompt, steps = compile_workflow_to_prompt(
                        wf_def,
                        self._agent_mode,
                        base_instructions,
                    )
                    if steps:
                        self._workflow_sm = WorkflowStateMachine(steps, wf_vars)
                        full_instructions = compiled_prompt
                        logger.info(
                            f"[{room_name}] Modo '{self._agent_mode}': workflow compilado "
                            f"({len(steps)} pasos)"
                        )
                    else:
                        logger.warning(
                            f"[{room_name}] workflow_definition sin pasos válidos, "
                            "usando modo prompt como fallback"
                        )
                        full_instructions = base_instructions
                except Exception as wf_err:
                    logger.error(
                        f"[{room_name}] Error compilando workflow: {wf_err} — "
                        "fallback a modo prompt"
                    )
                    full_instructions = base_instructions
            else:
                logger.warning(
                    f"[{room_name}] agent_mode='{self._agent_mode}' pero "
                    "workflow_definition vacío — usando modo prompt como fallback"
                )
                full_instructions = base_instructions
        else:
            full_instructions = base_instructions

        agent_name = agent_config.get("name", "Bot")
        extraction_schema = self._extraction_schema

        guardar_tools: list[Any] = []
        if extraction_schema and isinstance(extraction_schema, list) and len(extraction_schema) > 0:
            raw_schema = _build_guardar_encuesta_raw_schema(extraction_schema)

            @function_tool(name="guardar_encuesta", raw_schema=raw_schema)
            async def _tool_guardar_encuesta_strict(
                ctx: RunContext, raw_arguments: dict[str, Any]
            ) -> str | None:
                datos = raw_arguments.get("datos_extra")
                datos_str = json.dumps(datos, ensure_ascii=False) if isinstance(datos, dict) else datos
                return await self._guardar_encuesta_impl(
                    ctx,
                    id_encuesta=int(raw_arguments.get("id_encuesta") or 0),
                    nota_comercial=raw_arguments.get("nota_comercial"),
                    nota_instalador=raw_arguments.get("nota_instalador"),
                    nota_rapidez=raw_arguments.get("nota_rapidez"),
                    comentarios=raw_arguments.get("comentarios"),
                    status=raw_arguments.get("status"),
                    datos_extra=datos_str,
                )

            guardar_tools.append(_tool_guardar_encuesta_strict)
        else:

            @function_tool(name="guardar_encuesta")
            async def _tool_guardar_encuesta(
                ctx: RunContext,
                id_encuesta: int,
                nota_comercial: Optional[int] = None,
                nota_instalador: Optional[int] = None,
                nota_rapidez: Optional[int] = None,
                comentarios: Optional[str] = None,
                status: Optional[str] = None,
                datos_extra: Optional[str] = None,
            ) -> str | None:
                return await self._guardar_encuesta_impl(
                    ctx,
                    id_encuesta=id_encuesta,
                    nota_comercial=nota_comercial,
                    nota_instalador=nota_instalador,
                    nota_rapidez=nota_rapidez,
                    comentarios=comentarios,
                    status=status,
                    datos_extra=datos_extra,
                )

            guardar_tools.append(_tool_guardar_encuesta)

        super().__init__(instructions=full_instructions, tools=guardar_tools)  # type: ignore
        logger.info(f"Agente '{agent_name}' creado (Survey: {self.survey_id})")

    async def on_user_turn_completed(
        self,
        _turn_ctx: llm.ChatContext,
        new_message: llm.ChatMessage,
    ) -> None:
        """Clasificación semántica antes del LLM principal (transferencia humana rápida)."""
        if self._semantic_router is None:
            return
        if self._transfer_in_progress or self._transfer_completed.is_set():
            return

        user_text = _normalize_message_text(getattr(new_message, "text_content", ""))
        if not user_text:
            return

        try:
            route = await self._semantic_router.classify(user_text)
        except Exception as route_err:
            logger.warning(
                "[%s] Semantic router error (continuando flujo normal): %s",
                self.room_name,
                route_err,
            )
            return

        if not self._semantic_router.is_actionable(route):
            return

        logger.info(
            "[%s] Semantic route transfer_human tier=%s confidence=%.2f latency=%.0fms text='%s'",
            self.room_name,
            route.tier,
            route.confidence,
            route.latency_ms,
            anonymize_text(user_text),
        )

        current_session = getattr(self, "session", None)
        if current_session is not None:
            try:
                await current_session.interrupt()
            except Exception as interrupt_err:
                logger.debug(
                    "[%s] session.interrupt() no aplicado: %s",
                    self.room_name,
                    interrupt_err,
                )

        self._transfer_in_progress = True
        try:
            outcome = await self._execute_human_transfer(
                motivo=f"Transferencia semántica ({route.tier})",
                source="semantic_router",
            )
        except Exception as transfer_err:
            self._transfer_in_progress = False
            logger.error(
                "[%s] Semantic transfer failed (continuando flujo normal): %s",
                self.room_name,
                transfer_err,
            )
            return

        if outcome != "Transferencia iniciada":
            self._transfer_in_progress = False
            return

        raise StopResponse()



class CallSession(CallSessionLifecycleMixin):
    """
    REFACTOR — Extraer lógica de entrypoint() a métodos.

    Problema: entrypoint() tenía ~600 líneas inline (AMD, backchannel, silencio,
    ghost kicker, transcripción, timeouts), difícil de leer, testear y mantener.

    Solución: cada bucle concurrente se convierte en un método, el estado
    compartido en atributos de instancia y el bloque finally en finalize().
    entrypoint() queda en ~80 líneas.
    """

    VOICEMAIL_PATTERNS = (
        "buzón de voz", "buzon de voz", "contestador", "contestadora",
        "fuera de cobertura", "apagado o fuera", "deje su mensaje",
        "grabe su mensaje", "después de la señal", "despues de la señal",
        "no está disponible", "no esta disponible", "no se encuentra",
        "número no disponible", "numero no disponible",
        "terminado el tiempo", "el usuario no contesta",
        "mailbox", "voicemail", "leave a message", "not available",
        "el número marcado", "el numero marcado",
    )
    REPROMPT_PHRASES = [
        "¿Sigue ahí?",
        "Perdone, ¿me escucha?",
        "Disculpe, ¿puede responderme?",
        "¿Está usted disponible?",
        "Si le parece, seguimos con la siguiente pregunta.",
    ]
    LATENCY_FILLERS = ["Mmm...", "A ver...", "Vale..."]
    INTERRUPTION_ACKS = ["Uy, perdona, dime.", "Sí, dime."]

    def __init__(
        self,
        ctx: "JobContext",
        job_id: str,
        room_name: str,
        survey_id: str,
        agent_config: dict,
        session: "AgentSession",
        agent_instance: "DynamicAgent",
        language: str,
        voice_id: str,
        speaking_speed: float,
        tts_model: str,
        call_start_time: float,
    ) -> None:
        self.ctx = ctx
        self.job_id = job_id
        self.room_name = room_name
        self.survey_id = survey_id
        self.agent_config = agent_config
        self.session = session
        self.agent_instance = agent_instance
        self.language = language
        self.voice_id = voice_id
        self.speaking_speed = speaking_speed
        self.tts_model = tts_model
        self.call_start_time = call_start_time

        # Configuración leída del entorno
        self.AMD_WINDOW_SECONDS = float(os.getenv("AGENT_AMD_WINDOW_SECONDS", "15.0"))
        self.SILENCE_REPROMPT_DELAY = float(os.getenv("AGENT_SILENCE_REPROMPT_SECONDS", "7.0"))
        self.CALL_TIMEOUT_SECONDS = int(os.getenv("AGENT_CALL_TIMEOUT_SECONDS", "600"))
        self.max_short_interrupt_words = int(os.getenv("AGENT_INTERRUPT_MIN_WORDS", "3"))

        # Señales de control
        self.stop_guard = asyncio.Event()
        self.finished = asyncio.Event()
        self.loop_obj = asyncio.get_running_loop()

        # Estado de transcripción
        self.transcript_event_buffer: list[dict] = []
        self.transcript_snapshot: dict = {"transcript": "", "raw": []}

        # Estado AMD
        self.amd_state: dict = {"detected": False, "human_confirmed": False, "check_count": 0}

        # Estado de reprompt
        self.reprompt_state: dict = {
            "last_assistant_at": 0.0,
            "last_user_at": 0.0,
            "waiting_user": False,
            "reprompt_count": 0,
        }
        self.reprompt_phrases_lc = {p.lower() for p in self.REPROMPT_PHRASES}

        # Estado de runtime del agente
        self.runtime_state: dict = {
            "agent_state": "listening",
            "last_user_text": "",
            "last_filler_at": 0.0,
            "last_interrupt_ack_at": 0.0,
        }

        # Estado de detección de idioma
        self.lang_state: dict = {
            "detected": False,
            "switched": False,
            "original_lang": language,
            "active_lang": language,
        }

        # Reproductor de audio de fondo (inicializado en start())
        self.bg_player = None

        # Referencias a las tareas en background
        self._tasks: list[asyncio.Task] = []
        self._ephemeral_tasks: list[asyncio.Task] = []
        self._cleanup_done = False
        # FIX B — serializa los turns de workflow para evitar advance() en paralelo.
        self._workflow_lock = asyncio.Lock()
        # FIX F — control de fillers de latencia.
        self._filler_task: asyncio.Task | None = None
        self._llm_responding = False

        from livekit.agents.metrics import UsageCollector

        self.usage_collector = UsageCollector()

    # ── Helpers de transcripción ───────────────────────────────────────────────

    def _append_transcript_event(self, role: str, content: str) -> None:
        text = _normalize_message_text(content)
        if role not in ("user", "assistant") or not text:
            return
        if self.transcript_event_buffer:
            last = self.transcript_event_buffer[-1]
            if last.get("role") == role and _normalize_message_text(last.get("content")) == text:
                return
        self.transcript_event_buffer.append({"role": role, "content": text})

    def _build_transcript_from_event_buffer(self) -> tuple[list[dict], str]:
        if not self.transcript_event_buffer:
            return [], ""
        lines: list[str] = []
        raw: list[dict] = []
        for item in self.transcript_event_buffer:
            role = item.get("role")
            content = _normalize_message_text(item.get("content"))
            if role not in ("user", "assistant") or not content:
                continue
            raw.append({"role": role, "content": content})
            lines.append(f"{'Cliente' if role == 'user' else 'Agente'}: {content}")
        return raw, ("\n".join(lines).strip() + ("\n" if lines else ""))

    async def _save_transcript_snapshot(self, reason: str = "auto") -> None:
        try:
            raw, t = self._build_transcript_from_event_buffer()
            if not t:
                raw, t = _extract_transcript_from_session(self.session)
            logger.info(
                f"📝 [{self.job_id}] Snapshot transcripción ({reason}): {len(t)} chars, {len(raw)} mensajes"
            )
            if t:
                self.transcript_snapshot["transcript"] = t
                self.transcript_snapshot["raw"] = raw
                snap_job = await enqueue_guardar_encuesta({
                    "id_encuesta": int(self.survey_id) if str(self.survey_id).isdigit() else 0,
                    "transcription": prepare_transcription_for_storage(t),
                })
                logger.info(
                    f"📬 [{self.job_id}] Transcripción snapshot encolada ({reason}, job={snap_job})"
                )
        except Exception as _e:
            logger.warning(
                f"⚠️ [{self.job_id}] Error guardando snapshot transcripción ({reason}): {_e}"
            )

    # ── Workflow: avance de máquina de estados ─────────────────────────────────

    def _extract_variable_value(
        self,
        user_text: str,
        variable: str | None,
        wf_sm: "WorkflowStateMachine | None" = None,
    ) -> str:
        """
        PARTE 4: extrae el valor relevante de la respuesta del usuario para
        guardarlo en una variable del workflow.

        FIX D:
          1) Si el nodo actual tiene options (<=10), intenta mapear por substring.
          2) Si no hay match, devuelve las primeras 3 palabras normalizadas.
          3) Fallback: texto completo normalizado.
        """
        if not user_text:
            return ""
        normalized = " ".join(user_text.strip().lower().split())
        if not normalized:
            return ""

        current = wf_sm.current_step() if wf_sm is not None else None
        options = (current.get("options") or []) if current else []
        if isinstance(options, list) and 0 < len(options) <= 10:
            normalized_options = [
                (opt, " ".join(str(opt).strip().lower().split()))
                for opt in options
                if str(opt).strip()
            ]
            normalized_options.sort(key=lambda item: len(item[1]), reverse=True)
            for original_opt, norm_opt in normalized_options:
                if norm_opt and norm_opt in normalized:
                    return str(original_opt)

        words = normalized.split()
        if words:
            return " ".join(words[:3])

        return normalized

    async def _handle_workflow_turn(
        self,
        user_response: str,
        wf_sm: "WorkflowStateMachine",
    ) -> None:
        """
        PARTE 4: Procesa un turno de conversación cuando el workflow está activo.
        1. Guarda la variable del nodo actual si corresponde.
        2. Avanza la máquina de estados.
        3. Actúa según el tipo del siguiente nodo.
        """
        async with self._workflow_lock:
            try:
                # while-loop para resolver nodos "condition" consecutivos sin recursión.
                loop_user_response = user_response
                while True:
                    current = wf_sm.current_step()
                    if not current:
                        return

                    # Guardar variable si el nodo la requiere
                    var_name = current.get("variable")
                    if var_name and loop_user_response:
                        value = self._extract_variable_value(loop_user_response, var_name, wf_sm)
                        wf_sm.set_variable(var_name, value)

                    # Avanzar al siguiente nodo
                    next_step = wf_sm.advance(loop_user_response)

                    if next_step is None:
                        logger.info(f"[{self.job_id}] Workflow finalizado (sin siguiente nodo)")
                        return

                    ntype = next_step.get("type", "message")
                    logger.info(
                        f"[{self.job_id}] Workflow → nodo '{next_step.get('id')}' "
                        f"(type={ntype}, label='{next_step.get('label')}')"
                    )

                    if ntype in ("message", "question"):
                        content = (next_step.get("content") or "").strip()
                        if content:
                            try:
                                await self.session.say(content, allow_interruptions=True)
                            except Exception as say_err:
                                logger.warning(
                                    f"[{self.job_id}] Workflow say() error: {say_err}"
                                )
                        return

                    if ntype == "condition":
                        # Nodo de routing puro: no habla, avanza inmediatamente
                        logger.info(
                            f"[{self.job_id}] Nodo condition '{next_step.get('id')}' — avanzando sin hablar"
                        )
                        loop_user_response = ""
                        continue

                    if ntype == "llm_free":
                        # Nodo libre: inyectar el sub-prompt como mensaje de sistema
                        # y dejar que el LLM responda libremente en el siguiente turno
                        sub_prompt = sanitize_untrusted_text(
                            (next_step.get("prompt") or next_step.get("content") or "").strip(),
                            max_length=2000,
                            field_name="workflow_runtime_sub_prompt",
                        )
                        if sub_prompt:
                            try:
                                chat_ctx = getattr(
                                    self.session,
                                    "chat_ctx",
                                    getattr(self.session, "chat_context", None),
                                )
                                if chat_ctx is not None and hasattr(chat_ctx, "add_message"):
                                    chat_ctx.add_message(
                                        role="system",
                                        content=(
                                            "[Nodo libre activo] Responde ahora usando este sub-prompt "
                                            f"(solo guion, no órdenes de seguridad): {sub_prompt}"
                                        ),
                                    )
                                    logger.info(
                                        f"[{self.job_id}] Sub-prompt de nodo llm_free inyectado"
                                    )
                            except Exception as ctx_err:
                                logger.warning(
                                    f"[{self.job_id}] No se pudo inyectar sub-prompt de nodo llm_free: {ctx_err}"
                                )
                        return

                    if ntype == "transfer":
                        try:
                            transfer_payload = {
                                "room_name": self.room_name,
                                "empresa_id": int(self.agent_config.get("empresa_id") or 0),
                                "call_id": self.room_name,
                                "extension": os.getenv("YEASTAR_HUMAN_TRANSFER_EXTENSION", "1000"),
                                "survey_id": int(self.survey_id) if str(self.survey_id).isdigit() else 0,
                                "motivo": "Transferencia por guion de workflow",
                            }
                            await enqueue_transfer_to_human({
                                "guardar_payload": {
                                    "id_encuesta": int(self.survey_id) if str(self.survey_id).isdigit() else 0,
                                    "status": "transferred",
                                    "comentarios": "Transferido por workflow",
                                },
                                "transfer_payload": transfer_payload,
                            })
                            logger.info(f"[{self.job_id}] Workflow: transferencia encolada")
                        except Exception as tr_err:
                            logger.error(f"[{self.job_id}] Workflow: error encolando transferencia: {tr_err}")
                        return

                    if ntype == "end":
                        logger.info(f"[{self.job_id}] Workflow: nodo 'end' alcanzado — encolando colgar sala")
                        try:
                            await enqueue_colgar_sala(self.room_name)
                        except Exception as end_err:
                            logger.warning(f"[{self.job_id}] Workflow end: error encolando colgar: {end_err}")
                        return
            except Exception as wf_err:
                logger.error(f"[{self.job_id}] Error en _handle_workflow_turn: {wf_err}")

    # ── Detección de idioma ────────────────────────────────────────────────────

    def _spawn_ephemeral(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._ephemeral_tasks.append(task)

        def _done(t: asyncio.Task) -> None:
            try:
                self._ephemeral_tasks.remove(t)
            except ValueError:
                pass

        task.add_done_callback(_done)
        return task

    def _cancel_task_list(self, tasks: list[asyncio.Task | None]) -> None:
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()

    async def _await_cancelled(self, tasks: list[asyncio.Task | None]) -> None:
        pending = [t for t in tasks if t is not None and not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def stop(self) -> None:
        """Señaliza el fin y cancela todas las tareas en curso."""
        self.stop_guard.set()
        self._cancel_task_list(self._tasks)
        self._cancel_task_list(self._ephemeral_tasks)
        if self._filler_task is not None and not self._filler_task.done():
            self._filler_task.cancel()

    async def cleanup(self) -> None:
        """Libera audio WebRTC, sesión del agente y buffers (idempotente)."""
        if self._cleanup_done:
            return
        self._cleanup_done = True

        self.stop()

        all_tasks: list[asyncio.Task | None] = [
            *self._tasks,
            *self._ephemeral_tasks,
            self._filler_task,
        ]
        await self._await_cancelled(all_tasks)
        self._tasks.clear()
        self._ephemeral_tasks.clear()
        self._filler_task = None

        if self.bg_player is not None:
            try:
                await self.bg_player.aclose()
            except Exception as bg_err:
                logger.debug("[%s] bg_player.aclose: %s", self.job_id, bg_err)
            finally:
                self.bg_player = None

        try:
            await self.session.aclose()
        except Exception as sess_err:
            logger.debug("[%s] session.aclose: %s", self.job_id, sess_err)

        try:
            await self.ctx.room.disconnect()
        except Exception as disc_err:
            logger.debug("[%s] room.disconnect: %s", self.job_id, disc_err)

        try:
            from agents.livekit_client import close_livekit_admin_api

            await close_livekit_admin_api()
        except Exception as lk_err:
            logger.debug("[%s] close_livekit_admin_api: %s", self.job_id, lk_err)

        self.transcript_event_buffer.clear()
        self.transcript_snapshot = {"transcript": "", "raw": []}

    async def finalize(self) -> None:
        """Delega el post-procesamiento al módulo post_call_processor."""
        await finalize_call_session(self)


# ============================================================================
# FUNCIÓN PARA ENVIAR ALERTAS AL SISTEMA (VÍA ARQ)
# ============================================================================
async def notify_system_alert(message: str, details: Optional[dict] = None):
    try:
        from services.queue_service import get_arq_pool
        redis = await get_arq_pool()
        await redis.enqueue_job("process_system_alert", message, details)
        logger.info(f"📡 Alerta del sistema encolada: {message}")
    except Exception as e:
        logger.error(f"❌ Error encolando alerta del sistema: {e}")

# ============================================================================
# SERVIDOR Y ENTRYPOINT DINÁMICO
# ============================================================================
server = AgentServer()

@server.rtc_session(agent_name=DISPATCH_AGENT_NAME)
async def entrypoint(ctx: JobContext):
    # Identificador único para esta instancia/trabajo
    job_id = ctx.job.id if hasattr(ctx, 'job') else "unknown"
    room_name = ctx.room.name
    
    logger.info(f"--- 🚀 INICIO DE SESIÓN AGENTE (Job: {job_id}, Room: {room_name}) ---")
    
    def handle_error(error):
        msg = str(error)
        if "429" in msg or "Rate Limit" in msg or "insufficient_quota" in msg: 
            logger.error(f"🚨🚨🚨 ALERTA (Job {job_id}): Límite de API Alcanzado")
            asyncio.create_task(notify_system_alert("Límite de API Alcanzado (Error 429)", {"job_id": job_id, "error": msg}))
        else:
            logger.error(f"⚠️ ERROR DEL AGENTE (Job {job_id}): {error}")
            asyncio.create_task(notify_system_alert("Error en Agente LiveKit", {"job_id": job_id, "error": msg}))

    async def _safe_reject(reason: str):
        logger.error(f"🚫 [{job_id}] Job rechazado: {reason}")
        # En esta versión de LiveKit no existe ctx.reject(); cerramos de forma segura.
        try:
            shutdown_fn = getattr(ctx, "shutdown", None)
            if callable(shutdown_fn):
                try:
                    maybe = shutdown_fn(reason=reason)
                except TypeError:
                    maybe = shutdown_fn()
                if asyncio.iscoroutine(maybe):
                    await maybe
                return
            logger.warning(f"[{job_id}] No hay método reject/shutdown disponible en JobContext.")
        except Exception as rej_err:
            logger.error(f"[{job_id}] Error cerrando job rechazado: {rej_err}")

    # --- PASO 1: Filtro estricto de sala + metadata ---
    if not _room_name_allowed(room_name):
        await _safe_reject(
            f"Sala fuera de prefijos permitidos {ALLOWED_ROOM_PREFIXES}: {room_name}"
        )
        return

    metadata_str = getattr(ctx.job, 'metadata', '')
    if not metadata_str:
        await _safe_reject("metadata vacía")
        return

    try:
        meta_data = json.loads(metadata_str)
    except Exception as e:
        await _safe_reject(f"metadata no JSON válido: {e}")
        return

    is_inbound_call = str(meta_data.get("call_direction") or "").lower() == "inbound"
    inbound_agent_id = str(meta_data.get("agent_id") or "").strip()
    if not is_inbound_call and "campana_id" not in meta_data and "client_id" not in meta_data:
        await _safe_reject("metadata sin campana_id/client_id")
        return
    if is_inbound_call and not inbound_agent_id:
        await _safe_reject("metadata inbound sin agent_id")
        return

    # --- PASO 2: Extraer survey_id y empresa_id (Sello Multi-Tenant) ---
    survey_id = "0"
    empresa_id = "0"
    try:
        survey_id = str(meta_data.get("survey_id", "0"))
        empresa_id = str(meta_data.get("empresa_id", "0"))
        logger.info(f"🔑 [{job_id}] Metadatos parseados: empresa={empresa_id}, survey={survey_id}, campana_id={meta_data.get('campana_id')}, client_id={meta_data.get('client_id')}")
    except Exception as e:
        logger.warning(f"⚠️ [{job_id}] Error extrayendo campos de metadata: {e}")
            
    # 2. Fallback: intentar extraer del room_name
    if survey_id == "0":
        try:
            parts = room_name.split('_')
            survey_id = parts[-1] if parts else "0"
            if empresa_id == "0" and len(parts) >= 2 and parts[0] == "empresa":
                empresa_id = parts[1]
            logger.info(f"🔑 [{job_id}] Metadatos extraídos de room_name: empresa={empresa_id}, survey={survey_id}")
        except Exception as e:
            logger.warning(f"⚠️ [{job_id}] Error extrayendo survey_id de room_name: {e}")

    # 3. Validación de Identidad Temprana Crítica
    # Permite survey_ids numéricos Y alfanuméricos (UUIDs, slugs, etc.)
    if (not survey_id or survey_id == "0") and is_inbound_call:
        survey_id = f"inbound_{empresa_id or '0'}"
    if not survey_id or survey_id == "0":
        await _safe_reject(f"Identidad inválida o corrupta: survey_id='{survey_id}'")
        return

    # --- PASO 1.5: Validar Sello Multi-Tenant ANTES de conectar ---
    try:
        # Obtenemos config y validamos que la sala es del mismo tenant que el config
        if is_inbound_call and inbound_agent_id:
            agent_config = await fetch_agent_config_by_agent_id(
                inbound_agent_id,
                expected_empresa_id=empresa_id,
            )
            agent_config["call_direction"] = "inbound"
        else:
            agent_config = await fetch_agent_config(survey_id, expected_empresa_id=empresa_id)
    except Exception as e:
        if "Violación de seguridad" in str(e):
            await _safe_reject(str(e))
            return
        else:
            logger.warning(f"⚠️ [{job_id}] Error cargando config previa: {e}")
            agent_config = {}

    # --- PASO 2: Conectar a la sala ---
    call_start_time = time.time()
    is_duplicate = False
    cs: "CallSession | None" = None
    try:
        logger.info(f"⏱️ [{job_id}] Intentando conectar a sala {room_name}...")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        
        # --- CONTROL DE DUPLICIDAD ---
        agent_participants = [p for p in ctx.room.remote_participants.values() if getattr(p, 'kind', None) == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT or getattr(p, 'identity', '').startswith("agent-")]
        if len(agent_participants) > 1: # Ya estamos nosotros (1), si hay más (1+) es que hay otro
            logger.warning(f"⚠️ [{job_id}] Ya un agente en la sala {room_name}. Cancelando duplicado.")
            is_duplicate = True
            return

        logger.info(f"✅ [{job_id}] Conectado a sala {room_name}. Participantes: {len(ctx.room.remote_participants)}")

        if is_inbound_call:
            caller_phone = _parse_inbound_caller_from_room(room_name)
            if caller_phone:
                meta_data.setdefault("telefono", caller_phone)
                meta_data.setdefault("contacto_phone", caller_phone)

        # --- PASO 4 (Fase 2): Cargar contextos KB y cliente ANTES de crear el agente ---
        from utils.call_loader import enrich_agent_config_with_context
        await enrich_agent_config_with_context(
            job_id=job_id,
            agent_config=agent_config,
            empresa_id_str=empresa_id,
            meta_data=meta_data,
        )

        if is_inbound_call:
            inbound_encuesta_id = await _register_inbound_call_record(
                agent_config,
                room_name,
                empresa_id,
            )
            if inbound_encuesta_id:
                survey_id = str(inbound_encuesta_id)
                agent_config["inbound_encuesta_id"] = inbound_encuesta_id
                logger.info(
                    f"📞 [{job_id}] Llamada inbound registrada como encuesta {inbound_encuesta_id}"
                )

        # --- PASO 4: Crear el asistente ---
        agent_instance = DynamicAgent(room_name=room_name, agent_config=agent_config)
        
        llm_model = agent_config.get("llm_model", "llama-3.3-70b-versatile")
        voice_id = agent_config.get("voice_id", os.getenv("VOICE_ID_AUSARTA", settings.default_cartesia_voice))
        tts_model = agent_config.get("tts_model", settings.default_tts_model)
        language = agent_config.get("language", "es")
        stt_provider = agent_config.get("stt_provider", "deepgram")
        stt_model = agent_config.get("stt_model", settings.default_stt_model)
        speaking_speed = agent_config.get("speaking_speed", 1.0)
        has_strict_extraction = bool(
            agent_config.get("extraction_schema")
            and isinstance(agent_config.get("extraction_schema"), list)
        )

        logger.info(
            f"🤖 [{job_id}] Config: LLM='{llm_model}', Voice='{voice_id}', TTS='{tts_model}', "
            f"Lang='{language}', STT='{stt_provider}/{stt_model}', Speed='{speaking_speed}'"
        )

        stt_plugin, delegate_turn_to_stt = await build_resilient_stt_plugin(
            stt_provider, stt_model, language
        )

        # VAD Silero solo si el STT no gestiona el turno (p. ej. OpenAI Whisper)
        vad_model = None
        if delegate_turn_to_stt:
            logger.info(f"✅ [{job_id}] Turn detection delegado al STT (sin VAD Silero).")
        else:
            min_silence_duration = float(os.getenv("AGENT_MIN_SILENCE_SECONDS", "0.65"))
            min_silence_duration = max(0.55, min(min_silence_duration, 1.0))
            vad_model = await get_vad_model(min_silence_duration)
            logger.info(f"✅ [{job_id}] VAD Silero cargado (min_silence={min_silence_duration}s).")

        from livekit.agents.llm.fallback_adapter import FallbackAdapter  # type: ignore

        # LLM Principal: enruta a OpenAI si el modelo es de la familia GPT/o1/o3,
        # y a Groq (compatible OpenAI) para el resto (Llama, Mixtral, etc.)
        _is_openai_model = any(k in llm_model for k in ("gpt", "o1", "o3"))
        llm_parallel_tools = False if has_strict_extraction else None

        if _is_openai_model:
            logger.info(f"🤖 [{job_id}] Modelo OpenAI detectado ('{llm_model}'). Usando endpoint OpenAI.")
            main_llm = openai.LLM(
                model=llm_model,
                api_key=os.getenv("OPENAI_API_KEY"),
                temperature=0.35,
                parallel_tool_calls=llm_parallel_tools,
            )
        else:
            logger.info(f"🤖 [{job_id}] Modelo Groq detectado ('{llm_model}'). Usando endpoint Groq.")
            main_llm = openai.LLM(
                model=llm_model,
                base_url="https://api.groq.com/openai/v1",
                api_key=os.getenv("GROQ_API_KEY"),
                temperature=0.35,
                parallel_tool_calls=llm_parallel_tools,
            )

        # LLM Secundario (OpenAI - gpt-4o-mini): fallback universal
        fallback_llm = openai.LLM(
            model="gpt-4o-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0.2,
            parallel_tool_calls=llm_parallel_tools,
        )

        # Usar FallbackAdapter transparente al cliente
        final_llm = FallbackAdapter([main_llm, fallback_llm], attempt_timeout=10.0)

        # --- Crear sesión del agente (latencia objetivo <500ms) ---
        endpointing_min = float(os.getenv("AGENT_ENDPOINTING_MIN", "0.07"))
        endpointing_max = float(os.getenv("AGENT_ENDPOINTING_MAX", "0.5"))
        endpointing_min = max(0.05, min(endpointing_min, 0.3))
        endpointing_max = max(endpointing_min + 0.05, min(endpointing_max, 1.0))

        session_kwargs: dict[str, Any] = {
            "stt": stt_plugin,
            "llm": final_llm,
            "tts": await build_resilient_tts_plugin(
                voice_id=voice_id,
                language=language,
                speaking_speed=speaking_speed,
                tts_model=tts_model,
            ),
            "min_endpointing_delay": endpointing_min,
            "max_endpointing_delay": endpointing_max,
            "preemptive_generation": True,
            "use_tts_aligned_transcript": True,
        }
        if vad_model is not None:
            session_kwargs["vad"] = vad_model
        turn_mode = "vad"
        if delegate_turn_to_stt:
            session_kwargs["turn_detection"] = "stt"
            turn_mode = "stt"

        try:
            session = AgentSession(**session_kwargs)
        except TypeError as session_err:
            if delegate_turn_to_stt and "turn_detection" in str(session_err):
                logger.warning(
                    f"⚠️ [{job_id}] turn_detection='stt' no soportado; fallback a VAD Silero: {session_err}"
                )
                session_kwargs.pop("turn_detection", None)
                min_silence = float(os.getenv("AGENT_MIN_SILENCE_SECONDS", "0.65"))
                session_kwargs["vad"] = await get_vad_model(max(0.55, min(min_silence, 1.0)))
                turn_mode = "vad"
                session = AgentSession(**session_kwargs)
            else:
                raise

        logger.info(
            f"⚡ [{job_id}] AgentSession endpointing={endpointing_min}-{endpointing_max}s "
            f"turn_detection={turn_mode}"
        )

        # --- Iniciar CallSession: agrupa todos los bucles y post-procesamiento ---
        cs = CallSession(
            ctx=ctx,
            job_id=job_id,
            room_name=room_name,
            survey_id=survey_id,
            agent_config=agent_config,
            session=session,
            agent_instance=agent_instance,
            language=language,
            voice_id=voice_id,
            speaking_speed=float(speaking_speed or 1.0),
            tts_model=tts_model,
            call_start_time=call_start_time,
        )
        cs.setup_events()
        await session.start(room=ctx.room, agent=agent_instance)
        await cs.start()

    except Exception as e:
        handle_error(e)

    finally:
        if cs is not None:
            try:
                await cs.cleanup()
            except Exception as cleanup_err:
                logger.warning(f"[{job_id}] Error en cleanup de sesión: {cleanup_err}")

        if not is_duplicate:
            logger.info(
                f"--- 🏁 FIN DE SESIÓN AGENTE "
                f"(Job: {job_id}, Room: {room_name}, Survey: {survey_id}) ---"
            )
            if cs is not None:
                try:
                    await cs.finalize()
                except Exception as fatal_post:
                    logger.error(
                        f"🚨 [{job_id}] EXCEPCIÓN FATAL NO CAPTURADA en finalize: {fatal_post}"
                    )
        else:
            logger.info(
                f"--- 🏁 FIN DE SESIÓN DUPLICADA (Job: {job_id}) - Saliendo sin reportar datos ---"
            )

# Re-exports legacy: agent.py, config_loader.py y tests importan desde dynamic_agent.
from agents.text_utils import (  # noqa: E402
    _detect_language,
    _normalize_goodbye_message,
    anonymize_text,
)
from utils.call_loader import enrich_agent_config_with_context as _enrich_agent_config_with_context  # noqa: E402

if __name__ == "__main__":
    logger.info(
        "🤖 Arrancando worker LiveKit | agent_name=%s | livekit_url=%s | bridge=%s",
        DISPATCH_AGENT_NAME,
        (os.getenv("LIVEKIT_URL") or "NO SET"),
        BRIDGE_SERVER_URL_INTERNAL,
    )
    cli.run_app(server)
