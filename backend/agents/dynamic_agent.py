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
from agents.agent_logging import configure_agent_logging

logger = configure_agent_logging("agent-dynamic")

from utils.tracing import init_tracing, instrument_aiohttp_client

init_tracing(service_name=os.getenv("OTEL_SERVICE_NAME", "ausarta-livekit-agent"))
instrument_aiohttp_client()

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


# Re-exports para compatibilidad (agent.py, tests, config_loader).
from agents.call_session import CallSession  # noqa: E402,F401
from agents.entrypoint import entrypoint, notify_system_alert, server  # noqa: E402,F401
from agents.text_utils import (  # noqa: E402
    _detect_language,
    _normalize_goodbye_message,
    anonymize_text,
)
from agents.config_fetcher import fetch_agent_config, fetch_agent_config_by_agent_id  # noqa: E402,F401
from utils.call_loader import enrich_agent_config_with_context as _enrich_agent_config_with_context  # noqa: E402,F401
