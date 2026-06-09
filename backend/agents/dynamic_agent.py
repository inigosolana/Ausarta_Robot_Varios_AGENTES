import logging
from typing import Optional, Any
import os
import time
import aiohttp
import asyncio
from datetime import datetime
import redis.asyncio as aioredis
import sys
import json
import re
import random
from dotenv import load_dotenv
from config import settings
load_dotenv() # Cargar antes de cualquier otra cosa para que los decoradores lo vean

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
    AutoSubscribe
)
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


def _require_bridge_server_url() -> str:
    """URL interna del backend (obligatoria en Docker/multi-contenedor)."""
    url = settings.bridge_server_url_internal.strip().rstrip("/")
    if not url:
        raise RuntimeError(
            "BRIDGE_SERVER_URL_INTERNAL no está configurada. "
            "En Docker debe apuntar al servicio backend (ej. http://backend:8001), "
            "no a 127.0.0.1 del contenedor LiveKit."
        )
    return url


# Precalculada al arranque del worker: falla rápido si falta la variable.
BRIDGE_SERVER_URL_INTERNAL = _require_bridge_server_url()

# FIX 5: TTL reducido de 3600 → 300 s para que los cambios de prompt/voz se propaguen rápidamente
_AGENT_CONFIG_CACHE_TTL = settings.agent_config_cache_ttl
_REDIS_URL = settings.redis_url


def _validate_agent_config_tenant(config: dict, expected_empresa_id: str) -> None:
    """Sello multi-tenant: la config cacheada debe pertenecer al tenant de la sala."""
    config_empresa_id = str(config.get("empresa_id", "0"))
    if (
        expected_empresa_id
        and expected_empresa_id != "0"
        and config_empresa_id != "0"
        and expected_empresa_id != config_empresa_id
    ):
        raise Exception(
            f"Violación de seguridad Multi-Tenant: El ID de la empresa no coincide. "
            f"Metadata: {expected_empresa_id}, Config: {config_empresa_id}"
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
from utils.call_analyzer import analyze_call_disposition
from utils.prompt_builder import build_agent_prompt
from utils.workflow_compiler import compile_workflow_to_prompt
from utils.workflow_state import WorkflowStateMachine
from services.queue_service import (
    enqueue_colgar_sala,
    enqueue_guardar_encuesta,
    enqueue_transfer_briefing,
    enqueue_transfer_to_human,
)

_GLOBAL_VAD_MODEL = None
_VAD_LOCK = asyncio.Lock()


async def get_vad_model(min_silence_duration: float):
    global _GLOBAL_VAD_MODEL
    async with _VAD_LOCK:
        if _GLOBAL_VAD_MODEL is None:
            _GLOBAL_VAD_MODEL = await asyncio.to_thread(
                silero.VAD.load, min_silence_duration=min_silence_duration
            )
            logger.info("✅ VAD Silero cargado (singleton global)")
    return _GLOBAL_VAD_MODEL


def _build_stt_plugin(
    stt_provider: str, stt_model: str, language: str
) -> tuple[Any, bool]:
    """
    Construye el plugin STT. Si delegate_turn_to_stt es True, el turno se delega al STT
    (Deepgram vad_events) y AgentSession puede omitir Silero VAD.
    """
    import inspect

    if language in ("eu", "gl") or stt_provider == "openai":
        logger.info("🎙️ Usando STT: OpenAI Whisper")
        return openai.STT(language=language), False

    dg_kwargs: dict[str, Any] = {
        "model": stt_model,
        "language": language,
        "vad_events": True,
        "endpointing_ms": int(os.getenv("AGENT_DEEPGRAM_ENDPOINTING_MS", "300")),
        "no_delay": True,
        "interim_results": True,
    }
    try:
        sig = inspect.signature(deepgram.STT.__init__)
        if "flush_signal" in sig.parameters:
            dg_kwargs["flush_signal"] = True
            logger.info("🎙️ Deepgram STT: flush_signal=True")
    except Exception:
        pass

    try:
        plugin = deepgram.STT(**dg_kwargs)
    except TypeError:
        dg_kwargs.pop("flush_signal", None)
        plugin = deepgram.STT(**dg_kwargs)
        logger.warning("🎙️ Deepgram STT: flush_signal no soportado en esta versión del SDK")

    logger.info(f"🎙️ Usando STT: Deepgram {stt_model} (vad_events=True)")
    return plugin, True


def anonymize_text(text: str) -> str:
    """
    Redacta PII del texto antes de loguearlo: teléfonos, emails,
    NIFs/NIEs, IBANs y secuencias numéricas largas.
    """
    if not text:
        return ""
    # Emails
    anon = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', '[REDACTED_EMAIL]', text)
    # Teléfonos internacionales y nacionales (con +, espacios, guiones, puntos)
    anon = re.sub(r'(?<!\w)(\+?[\d][\d\s\-\.()]{7,15}\d)(?!\w)', '[REDACTED_PHONE]', anon)
    # NIF/NIE/DNI español: 8 dígitos + letra o X/Y/Z + dígitos + letra
    anon = re.sub(r'\b[XYZxyz]?\d{7,8}[A-Za-z]\b', '[REDACTED_DOC]', anon)
    # IBAN (2 letras + 2 dígitos + hasta 30 alfanuméricos, con posibles espacios)
    anon = re.sub(r'\b[A-Z]{2}\d{2}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{4}[\s]?[\dA-Z]{0,14}\b', '[REDACTED_IBAN]', anon)
    # Números largos sueltos (tarjetas, cuentas, etc.)
    anon = re.sub(r'\b\d{4,}\b', '[REDACTED_NUM]', anon)
    if len(anon) > 120:
        return anon[:120] + "... [TRUNCATED]"
    return anon


ROOM_PREFIX = os.getenv("LIVEKIT_ROOM_PREFIX", "llamada_ausarta_")
DEFAULT_CARTESIA_VOICE = os.getenv("VOICE_ID_AUSARTA", settings.default_cartesia_voice)
DISPATCH_AGENT_NAME = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()

# ─── Language Auto-Detection ──────────────────────────────────────────────────
# Tokens mínimos para declarar un idioma. Basta con que el cliente diga
# "Hello?" o "Bonjour!" para detectarlo.

_LANG_TOKENS: list[tuple[str, frozenset[str], int]] = [
    # (código BCP-47, tokens, mínimo de coincidencias para declarar)
    ("en", frozenset({
        "hello", "hi", "hey", "yes", "no", "not", "okay", "ok", "sure",
        "sorry", "thanks", "thank", "what", "who", "please", "speak",
        "english", "good", "morning", "afternoon", "evening", "moment",
        "dont", "don't", "i'm", "i am", "can", "you", "me",
    }), 1),
    ("fr", frozenset({
        "allô", "allo", "bonjour", "bonsoir", "salut", "oui", "non",
        "merci", "qui", "quoi", "je", "vous", "parle", "français",
        "francais", "pardon", "comment", "excusez",
    }), 1),
    ("de", frozenset({
        "hallo", "guten", "ja", "nein", "bitte", "danke", "wer",
        "was", "ich", "deutsch", "sprechen", "morgen", "tag",
    }), 1),
    ("it", frozenset({
        "ciao", "salve", "pronto", "sì", "prego", "grazie", "chi",
        "cosa", "italiano", "buongiorno", "buonasera", "scusi",
    }), 1),
    ("pt", frozenset({
        "olá", "ola", "oi", "sim", "não", "nao", "obrigado", "obrigada",
        "quem", "português", "portugues", "bom", "boa",
    }), 1),
]

def _detect_language(text: str) -> str | None:
    """
    Detecta el idioma de una frase corta usando tokens léxicos.
    Retorna el código BCP-47 detectado (ej: 'en', 'fr') o None si no hay
    suficiente evidencia para cambiar el idioma configurado.
    """
    if not text:
        return None

    # Normalizar: minúsculas, eliminar puntuación salvo acentos
    normalized = re.sub(r"[^\w\s\u00c0-\u017e]", " ", text.lower())
    words = set(normalized.split())
    if not words:
        return None

    for lang_code, tokens, min_hits in _LANG_TOKENS:
        hits = len(words & tokens)
        if hits >= min_hits:
            return lang_code

    return None


def _is_uuid_like(value: str) -> bool:
    if not value:
        return False
    return bool(
        re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            value.strip(),
        )
    )


def _build_tts_plugin(voice_id: str, language: str, speaking_speed: float, tts_model: str = settings.default_tts_model):
    """
    Crea el plugin TTS aplicando voz + velocidad + modelo.
    Si el SDK no soporta el parámetro speed en la versión actual, hace fallback seguro.
    """
    safe_speed = 1.0
    try:
        safe_speed = float(speaking_speed or 1.0)
    except Exception:
        safe_speed = 1.0

    safe_voice = (voice_id or "").strip()
    if not _is_uuid_like(safe_voice):
        logger.warning(
            f"⚠️ voice_id inválida para Cartesia ('{voice_id}'). Usando voz por defecto."
        )
        safe_voice = DEFAULT_CARTESIA_VOICE

    safe_model = (tts_model or settings.default_tts_model).strip()

    try:
        return cartesia.TTS(
            model=safe_model,
            voice=safe_voice,
            language=language,
            speed=safe_speed,
        )
    except TypeError:
        logger.warning(f"⚠️ cartesia.TTS con modelo {safe_model} no soporta 'speed' en esta versión. Usando fallback sin speed.")
        return cartesia.TTS(
            model=safe_model,
            voice=safe_voice,
            language=language,
        )


def _normalize_message_text(content) -> str:
    """
    Convierte distintos formatos de contenido de LiveKit a texto plano.
    Soporta str, dict, listas y objetos con atributos text/content.
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, dict):
        # Formatos comunes tipo {"text": "..."} o {"content": "..."}
        text = content.get("text") or content.get("content") or ""
        return str(text).strip()

    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                chunk = item.get("text") or item.get("content") or ""
                if chunk:
                    chunks.append(str(chunk))
            else:
                chunk = getattr(item, "text", None) or getattr(item, "content", None)
                if chunk:
                    chunks.append(str(chunk))
        return " ".join(chunks).strip()

    text_attr = getattr(content, "text", None)
    if text_attr:
        return str(text_attr).strip()

    content_attr = getattr(content, "content", None)
    if content_attr:
        return str(content_attr).strip()

    return str(content).strip()


def _normalize_goodbye_message(message: str) -> str:
    """
    Garantiza una despedida corta para evitar retrasos al colgar.
    """
    default_goodbye = "Muchas gracias. Hasta luego."
    text = _normalize_message_text(message)
    if not text:
        return default_goodbye

    text = " ".join(text.split())
    low = text.lower()

    # Si el LLM se alarga, forzamos una plantilla breve.
    if len(text.split()) > 8:
        if any(k in low for k in ("buzón", "buzon", "contestador", "fuera de cobertura")):
            return "Buzón detectado. Hasta luego."
        if any(k in low for k in ("no es un buen momento", "no le quito más tiempo")):
            return "Entendido, gracias. Hasta luego."
        return default_goodbye

    # Asegurar cierre explícito para señal de fin al cliente.
    if not any(k in low for k in ("adiós", "adios", "hasta luego", "hasta pronto")):
        if text[-1] in ".!?":
            text = f"{text} Hasta luego."
        else:
            text = f"{text}. Hasta luego."
    return text


def _count_words(text: str) -> int:
    if not text:
        return 0
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _is_likely_noise_transcript(text: str) -> bool:
    """
    Filtra micro-transcripciones típicas de ruido, respiración o backchannel corto.
    """
    t = _normalize_message_text(text).lower()
    if not t:
        return True

    t = re.sub(r"^[\W_]+|[\W_]+$", "", t).strip()
    if not t:
        return True

    short_noise = {
        "eh", "ehh", "mmm", "mhm", "ajá", "aja", "uh", "hum",
        "ok", "vale", "si", "sí", "hola", "hello", "hmm", "mm",
    }
    if _count_words(t) <= 2 and t in short_noise:
        return True

    alpha = re.sub(r"[^a-záéíóúüñ]", "", t)
    if len(alpha) <= 1:
        return True

    return False


def _estimate_thinking_complexity(user_text: str) -> tuple[float, int]:
    """
    Devuelve (volumen_teclado_extra, ráfagas) según longitud/complejidad percibida.
    """
    words = _count_words(user_text)
    if words >= 22:
        return 0.95, 3
    if words >= 12:
        return 0.8, 2
    if words >= 6:
        return 0.65, 1
    return 0.5, 1


def _extract_transcript_from_session(session_obj) -> tuple[list[dict], str]:
    """
    Extrae mensajes user/assistant desde session.chat_ctx/chat_context y
    devuelve (raw_messages, transcript) en formato:
      Cliente: ...
      Agente: ...
    """
    raw_messages: list[dict] = []
    transcript_lines: list[str] = []

    if not session_obj:
        return raw_messages, ""

    chat_ctx = getattr(session_obj, "chat_ctx", getattr(session_obj, "chat_context", None))
    if not chat_ctx or not getattr(chat_ctx, "messages", None):
        return raw_messages, ""

    for m in chat_ctx.messages:
        role = getattr(m, "role", "")
        if role not in ("user", "assistant"):
            continue

        content = _normalize_message_text(getattr(m, "content", None))
        if not content or len(content) <= 1:
            continue

        raw_messages.append({"role": role, "content": content})
        role_label = "Cliente" if role == "user" else "Agente"
        transcript_lines.append(f"{role_label}: {content}")

    return raw_messages, ("\n".join(transcript_lines).strip() + ("\n" if transcript_lines else ""))


class DynamicAgent(Agent):
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
        self.enthusiasm_level = agent_config.get("enthusiasm_level", "Normal") or "Normal"
        self.voice_id = agent_config.get("voice_id", "") or ""
        self.tts_model = agent_config.get("tts_model", settings.default_tts_model)
        self.speaking_speed = agent_config.get("speaking_speed", 1.0)
        self.hangup_started = False
        self._transfer_completed = asyncio.Event()
        
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
        except:
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
        base_instructions = build_agent_prompt(
            agent_config,
            self.enthusiasm_level,
            speaking_speed_f,
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

    async def on_enter(self, *args, **kwargs) -> None:
        """Método llamado cuando el agente entra en la sesión. Lanza el saludo inicial."""
        logger.info(f"--- 🎭 AGENTE EN SALA: {self.room_name} (Survey ID: {self.survey_id}) ---")

        # FIX 3 — on_enter sin reintentos suficientes.
        # Problema: un único reintento de 500 ms no era suficiente cuando la sesión
        # tarda más en asociarse; el agente arrancaba mudo sin error visible.
        # Solución: hasta 20 intentos x 300 ms (máx. 6 s de espera total).
        current_session = getattr(self, 'session', None)
        if not current_session:
            for attempt in range(1, 21):
                await asyncio.sleep(0.3)
                current_session = getattr(self, 'session', None)
                if current_session:
                    break
                logger.info(
                    f"⏳ [{self.room_name}] on_enter: esperando sesión (intento {attempt}/20)..."
                )

        if not current_session:
            logger.error(
                f"❌ [{self.room_name}] No se pudo obtener la sesión tras 20 intentos (6 s). "
                "El agente no puede saludar. Colgando sala."
            )
            await enqueue_colgar_sala(self.room_name)
            return

        logger.info(f"🎙️ Saludando en sala: {self.room_name} con: '{self.greeting}'")
        greeting_delay = float(os.getenv("AGENT_GREETING_DELAY_SECONDS", str(settings.agent_greeting_delay)))
        greeting_delay = max(0.1, min(greeting_delay, 3.0))
        await asyncio.sleep(greeting_delay)
        try:
            await current_session.say(self.greeting, allow_interruptions=True)
        except Exception as e:
            logger.error(f"❌ Error al saludar: {e}")




    async def _guardar_encuesta_impl(
        self,
        context: RunContext,
        id_encuesta: int,
        nota_comercial: Optional[int] = None,
        nota_instalador: Optional[int] = None,
        nota_rapidez: Optional[int] = None,
        comentarios: Optional[str] = None,
        status: Optional[str] = None,
        datos_extra: Optional[str | dict] = None,
    ) -> str | None:
        """Persiste datos de encuesta en el backend (invocado por la tool pública)."""
        self.data_saved = True

        real_id = int(self.survey_id) if str(self.survey_id).isdigit() else id_encuesta

        if status == "completed" and not comentarios:
            comentarios = "Sin comentarios"

        payload: dict[str, Any] = {
            "id_encuesta": real_id,
            "nota_comercial": nota_comercial,
            "nota_instalador": nota_instalador,
            "nota_rapidez": nota_rapidez,
            "comentarios": comentarios,
            "status": status,
        }

        # Normalizar datos_extra del LLM
        llm_datos: dict = {}
        if datos_extra is not None:
            if isinstance(datos_extra, dict):
                llm_datos = datos_extra
            elif isinstance(datos_extra, str) and datos_extra.strip():
                try:
                    llm_datos = json.loads(datos_extra)
                except Exception:
                    llm_datos = {"raw": datos_extra}

        # PARTE 4: fusionar variables del workflow si hay máquina de estados activa
        if self._workflow_sm is not None:
            wf_vars = self._workflow_sm.get_variables()
            if wf_vars:
                merged = {**wf_vars, **llm_datos}  # LLM tiene prioridad
                logger.info(
                    f"[{self.room_name}] guardar_encuesta: fusionando "
                    f"{len(wf_vars)} variable(s) de workflow en datos_extra"
                )
                payload["datos_extra"] = merged
            elif llm_datos:
                payload["datos_extra"] = llm_datos
        elif llm_datos:
            payload["datos_extra"] = llm_datos

        job_id = await enqueue_guardar_encuesta(payload)
        if job_id:
            logger.info(
                f"📬 [{self.room_name}] guardar_encuesta encolado (job={job_id}, encuesta={real_id})"
            )
        else:
            logger.warning(f"⚠️ [{self.room_name}] guardar_encuesta no encolado (encuesta={real_id})")

        return "Dato guardado."

    def _build_transfer_transcript(self) -> str:
        raw_msgs, _ = _extract_transcript_from_session(getattr(self, "session", None))
        last_10 = raw_msgs[-10:] if len(raw_msgs) > 10 else raw_msgs
        if not last_10:
            return ""

        lines = []
        for m in last_10:
            role_label = "Cliente" if m["role"] == "user" else "Agente"
            lines.append(f"{role_label}: {m['content']}")
        return "\n".join(lines)


    async def _resolve_transfer_extension(self, extension_number: str, empresa_id_int: int) -> str:
        """
        Resuelve la extensión de transferencia:
        1. extension_number si viene especificada
        2. Primera extensión activa de yeastar_extensions para la empresa
        3. Fallback a YEASTAR_HUMAN_TRANSFER_EXTENSION env var
        """
        if extension_number and extension_number.strip():
            return extension_number.strip()

        try:
            url = f"{BRIDGE_SERVER_URL_INTERNAL}/api/empresas/{empresa_id_int}/extensions"
            async with aiohttp.ClientSession() as http_session:
                async with http_session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=4),
                    headers={"X-Internal-Request": "agent"},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list) and data:
                            ext = str(data[0].get("extension_number", "")).strip()
                            if ext:
                                logger.info(
                                    f"📞 [{self.room_name}] Extensión dinámica: {ext} "
                                    f"({data[0].get('extension_name', '')})"
                                )
                                return ext
        except Exception as ext_err:
            logger.warning(f"⚠️ [{self.room_name}] No se pudo obtener extensión dinámica: {ext_err}")

        return os.getenv("YEASTAR_HUMAN_TRANSFER_EXTENSION", "1000")

    async def _wait_and_signal_transfer(self) -> None:
        """Espera 4 s tras encolar la transferencia y señaliza desconexión limpia del agente IA."""
        await asyncio.sleep(4)
        self._transfer_completed.set()
        logger.info(f"🔄 [{self.room_name}] Señal de transferencia completada emitida")

    @function_tool(name="consultar_conocimiento")
    async def _tool_consultar_conocimiento(
        self,
        context: RunContext,
        consulta: str,
        limite: int = 3,
        threshold: float = 0.70,
    ) -> str:
        """
        Busca información relevante en la base de conocimiento de la empresa de esta llamada.
        Úsala para responder preguntas del cliente con contexto documental interno.
        """
        try:
            empresa_id_int = int(str(getattr(self, "empresa_id", "0") or "0"))
        except (TypeError, ValueError):
            empresa_id_int = 0

        if not empresa_id_int:
            logger.warning(f"⚠️ [{self.room_name}] consultar_conocimiento sin empresa_id válido")
            return ""

        if not consulta or not consulta.strip():
            return ""

        try:
            from services.embedding_service import search_knowledge

            agent_id_int = None
            try:
                raw_agent_id = self.agent_config.get("agent_id")
                if raw_agent_id is not None:
                    agent_id_int = int(str(raw_agent_id))
            except (TypeError, ValueError):
                agent_id_int = None

            rows = await asyncio.wait_for(
                search_knowledge(
                    empresa_id=empresa_id_int,
                    query=consulta.strip(),
                    limit=max(1, min(int(limite), 8)),
                    threshold=float(threshold),
                    agent_id=agent_id_int,
                ),
                timeout=5,
            )
            if not rows:
                return ""

            lines: list[str] = []
            for row in rows[:3]:
                titulo = str(row.get("titulo") or "").strip()
                contenido = str(row.get("contenido") or "").strip()
                if titulo:
                    lines.append(f"Título: {titulo}")
                if contenido:
                    lines.append(f"Contenido: {contenido}")
            return "\n".join(lines).strip()
        except Exception as e:
            logger.warning(f"⚠️ [{self.room_name}] Error en consultar_conocimiento: {e}")
            return ""

    @function_tool(name="consultar_cliente")
    async def _tool_consultar_cliente(
        self,
        context: RunContext,
        query_name: str,
        params: str = "[]",
    ) -> str:
        """
        Consulta datos del cliente en la BD externa usando solo queries predefinidos y permitidos.
        No acepta SQL libre.
        """
        try:
            empresa_id_int = int(str(getattr(self, "empresa_id", "0") or "0"))
        except (TypeError, ValueError):
            empresa_id_int = 0

        if not empresa_id_int:
            logger.warning(f"⚠️ [{self.room_name}] consultar_cliente sin empresa_id válido")
            return ""

        qname = (query_name or "").strip()
        if not qname:
            return ""

        allowed_queries_cfg = self.agent_config.get("external_db_allowed_queries")
        if isinstance(allowed_queries_cfg, list) and allowed_queries_cfg:
            allowed_queries = {str(x).strip() for x in allowed_queries_cfg if str(x).strip()}
        else:
            allowed_queries = {"cliente_por_telefono", "cliente_por_id", "cliente_por_email"}

        if qname not in allowed_queries:
            logger.warning(
                f"⚠️ [{self.room_name}] Query externa no permitida en tool: {qname}"
            )
            return ""

        parsed_params: list[Any] = []
        if params and params.strip():
            try:
                loaded = json.loads(params)
                if isinstance(loaded, list):
                    parsed_params = loaded
                else:
                    parsed_params = [loaded]
            except Exception:
                parsed_params = [params]

        try:
            from services.external_db_service import query_external_db, format_customer_context

            rows = await asyncio.wait_for(
                query_external_db(
                    empresa_id=empresa_id_int,
                    query_name=qname,
                    params=parsed_params,
                ),
                timeout=5,
            )
            if not rows:
                return ""
            return format_customer_context(rows) or ""
        except Exception as e:
            logger.warning(f"⚠️ [{self.room_name}] Error en consultar_cliente: {e}")
            return ""

    @function_tool(name="transferir_a_agente_humano")
    async def _http_tool_transferir_humano(
        self,
        context: RunContext,
        motivo: str = "El cliente solicita hablar con una persona",
        extension_number: str = "",
    ) -> str | None:
        """
        Transfiere la llamada a un agente humano via backend multi-tenant (Yeastar).
        Usa esta herramienta SOLO cuando el cliente pida EXPLICITAMENTE hablar con una persona.
        """
        survey_id_raw = self.survey_id
        survey_id: int | None = int(survey_id_raw) if str(survey_id_raw).isdigit() else None

        logger.info(
            f"[{self.room_name}] Transferencia solicitada "
            f"(survey={survey_id_raw}, motivo: {motivo}, ext: {extension_number or 'auto'})"
        )

        busy_message = "Lo siento, nuestros agentes estan ocupados, puedo tomar nota?"

        empresa_id_raw = (
            getattr(self, "empresa_id", None)
            or self.agent_config.get("empresa_id")
            or "0"
        )
        try:
            empresa_id_int = int(empresa_id_raw)
        except (TypeError, ValueError):
            empresa_id_int = 0

        if not empresa_id_int:
            logger.warning(f"[{self.room_name}] empresa_id no disponible para transferencia")
            return busy_message

        datos_extra = self.agent_config.get("datos_extra") or {}
        if isinstance(datos_extra, str):
            try:
                datos_extra = json.loads(datos_extra)
            except Exception:
                datos_extra = {}
        yeastar_call_id = (
            datos_extra.get("yeastar_callid") or datos_extra.get("yeastar_call_id")
            if isinstance(datos_extra, dict)
            else None
        )

        ext_task = asyncio.create_task(
            self._resolve_transfer_extension(extension_number, empresa_id_int)
        )
        transcript_text = self._build_transfer_transcript()
        resolved_extension = await ext_task

        if transcript_text and survey_id is not None:
            try:
                await enqueue_transfer_briefing(
                    {
                        "encuesta_id": survey_id,
                        "transcript": transcript_text,
                        "empresa_id": empresa_id_int,
                        "extension": resolved_extension,
                        "room_name": self.room_name,
                    }
                )
                logger.info(f"[{self.room_name}] Briefing de transferencia encolado para encuesta {survey_id}")
            except Exception as briefing_err:
                logger.warning(f"[{self.room_name}] Error encolando briefing: {briefing_err}")

        transfer_payload: dict[str, Any] = {
            "room_name": self.room_name,
            "empresa_id": empresa_id_int,
            "call_id": str(yeastar_call_id or self.room_name),
            "extension": resolved_extension,
        }
        if survey_id is not None:
            transfer_payload["survey_id"] = survey_id
        if motivo:
            transfer_payload["motivo"] = motivo

        queue_payload = {
            "guardar_payload": {
                "id_encuesta": survey_id or 0,
                "status": "transferred",
                "comentarios": f"Transferido a humano: {motivo}",
            },
            "transfer_payload": transfer_payload,
        }

        current_session = getattr(self, "session", None)
        try:
            job_id = await enqueue_transfer_to_human(queue_payload)
            logger.info(
                f"[{self.room_name}] Transferencia encolada "
                f"(job={job_id}, survey={survey_id_raw}, ext={resolved_extension})"
            )
            if current_session:
                try:
                    await current_session.say(
                        "Perfecto, le paso con un companero. Un momento por favor.",
                        allow_interruptions=False,
                    )
                except Exception as say_err:
                    logger.warning(f"[{self.room_name}] No se pudo reproducir aviso TTS: {say_err}")

            asyncio.create_task(self._wait_and_signal_transfer())
            return "Transferencia iniciada"
        except Exception as transfer_err:
            logger.error(f"[{self.room_name}] Error encolando transferencia: {transfer_err}")
            if current_session:
                try:
                    await current_session.say(busy_message, allow_interruptions=True)
                except Exception:
                    pass
            return busy_message

    @function_tool(name="finalizar_llamada")
    async def _http_tool_finalizar_llamada(
        self, context: RunContext, mensaje_despedida_manual: str
    ) -> str | None:
        """
        Herramienta para decir unas ?ltimas palabras y colgar la llamada.
        Debes proporcionar obligatoriamente el mensaje de despedida; debe ser calida y breve.
        """
        # Protección anti-duplicado: evita repetir despedida si el LLM llama dos veces a la tool.
        if self.hangup_started:
            logger.info(f"⚠️ [{self.room_name}] finalizar_llamada duplicado detectado. No se repite despedida.")
            return "Cierre ya en curso."

        # Guardrail: no permitir colgar por una simple pregunta de identidad.
        # Solo aceptamos este cierre "rápido por no buen momento" cuando hay rechazo explícito.
        try:
            latest_user = ""
            chat_ctx = getattr(self.session, "chat_ctx", getattr(self.session, "chat_context", None))
            if chat_ctx and getattr(chat_ctx, "messages", None):
                for m in reversed(chat_ctx.messages):
                    if getattr(m, "role", "") == "user":
                        latest_user = _normalize_message_text(getattr(m, "content", None)).lower()
                        if latest_user:
                            break

            safe_goodbye = _normalize_goodbye_message(mensaje_despedida_manual)
            safe_goodbye.lower()
            identity_cues = (
                "quien eres", "quién eres", "de parte de", "quien llama", "quién llama", "de donde", "de dónde"
            )
            explicit_reject_cues = (
                "no me interesa", "no tengo tiempo", "no quiero", "no deseo",
                "no llames", "dejadme", "adios", "adiós", "cuelgo"
            )
            is_identity_question = any(k in latest_user for k in identity_cues)
            has_explicit_reject = any(k in latest_user for k in explicit_reject_cues)

            # Si el último mensaje del cliente es de identidad y NO hay rechazo explícito,
            # nunca permitimos cerrar la llamada en ese turno.
            if is_identity_question and not has_explicit_reject:
                logger.info(f"🛡️ [{self.room_name}] Bloqueado finalizar_llamada por pregunta de identidad (sin rechazo explícito).")
                return "El cliente pidió identificación. Aclara quién eres y continúa la encuesta."
        except Exception as guard_err:
            logger.debug(f"[{self.room_name}] Guardrail de finalizar_llamada no aplicado: {guard_err}")

        self.hangup_started = True

        async def process_goodbye_and_hangup():
            try:
                # Decir despedida sin interrupciones y colgar casi al instante al terminar
                safe_goodbye = _normalize_goodbye_message(mensaje_despedida_manual)
                if safe_goodbye != _normalize_message_text(mensaje_despedida_manual):
                    logger.info(f"✂️ [{self.room_name}] Despedida normalizada a formato corto: '{safe_goodbye}'")
                await self.session.say(safe_goodbye, allow_interruptions=False)

                # Margen corto para evitar silencios largos tras despedida.
                # Si se necesita ajustar, usar AGENT_HANGUP_DELAY_SECONDS en entorno.
                wait_seconds = float(os.getenv("AGENT_HANGUP_DELAY_SECONDS", str(settings.agent_hangup_delay)))
                wait_seconds = max(0.1, min(wait_seconds, 1.0))
                logger.info(f"⏳ Esperando {wait_seconds:.1f}s antes de colgar.")
                await asyncio.sleep(wait_seconds)
            except Exception as say_err:
                logger.error(f"❌ Error diciendo despedida: {say_err}")
                await asyncio.sleep(0.5)
            finally:
                job_id = await enqueue_colgar_sala(self.room_name)
                if job_id:
                    logger.info(f"📬 Sala {self.room_name} colgar encolado (job={job_id}).")
                else:
                    logger.warning(f"⚠️ No se pudo encolar colgar para sala {self.room_name}.")

        asyncio.create_task(process_goodbye_and_hangup())
        return "Llamada finalizada."


# ============================================================================
# CLASE CallSession — encapsula toda la lógica de una llamada activa
# ============================================================================
class CallSession:
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
        # FIX B — serializa los turns de workflow para evitar advance() en paralelo.
        self._workflow_lock = asyncio.Lock()
        # FIX F — control de fillers de latencia.
        self._filler_task: asyncio.Task | None = None
        self._llm_responding = False

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
                    "transcription": t,
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
                        sub_prompt = (next_step.get("prompt") or next_step.get("content") or "").strip()
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
                                            f"[Nodo libre activo] Responde ahora usando este sub-prompt: "
                                            f"{sub_prompt}"
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

    async def _try_switch_language(self, user_text: str) -> None:
        if self.lang_state["detected"]:
            return
        self.lang_state["detected"] = True
        detected = _detect_language(user_text)
        if not detected or detected == self.lang_state["original_lang"]:
            return
        self.lang_state["switched"] = True
        self.lang_state["active_lang"] = detected
        logger.info(
            f"🌐 [{self.job_id}] Idioma detectado: '{detected}' "
            f"(configurado: '{self.lang_state['original_lang']}'). Cambiando idioma."
        )
        override_msg = _LANG_OVERRIDE_MSGS.get(detected)
        if not override_msg:
            return
        try:
            chat_ctx = getattr(self.session, "chat_ctx", getattr(self.session, "chat_context", None))
            if chat_ctx is not None:
                if hasattr(chat_ctx, "add_message"):
                    chat_ctx.add_message(role="system", content=override_msg)
                elif hasattr(self.session, "update_chat_ctx"):
                    from livekit.agents.llm import ChatMessage
                    new_ctx = chat_ctx.copy() if hasattr(chat_ctx, "copy") else chat_ctx
                    new_ctx.messages.append(ChatMessage.create(text=override_msg, role="system"))
                    await self.session.update_chat_ctx(new_ctx)
                logger.info(f"🌐 [{self.job_id}] Override de idioma '{detected}' inyectado.")
        except Exception as ctx_err:
            logger.warning(f"⚠️ [{self.job_id}] No se pudo inyectar override de idioma: {ctx_err}")
        try:
            new_tts = _build_tts_plugin(
                voice_id=self.voice_id,
                language=detected,
                speaking_speed=self.speaking_speed,
                tts_model=self.tts_model,
            )
            await self.session.update_options(tts=new_tts)
            logger.info(f"🎙️ [{self.job_id}] TTS actualizado a idioma '{detected}'.")
        except Exception as tts_err:
            logger.warning(f"⚠️ [{self.job_id}] No se pudo actualizar TTS al idioma '{detected}': {tts_err}")

    # ── Tareas en background ───────────────────────────────────────────────────

    async def run_amd(self) -> None:
        """Monitoriza transcripciones tempranas para detectar contestador automático."""
        start_time = self.loop_obj.time()
        while not self.stop_guard.is_set():
            await asyncio.sleep(0.5)
            elapsed = self.loop_obj.time() - start_time
            if elapsed > self.AMD_WINDOW_SECONDS or self.amd_state["human_confirmed"]:
                logger.info(
                    f"✅ [{self.job_id}] AMD: Interlocutor humano confirmado (elapsed={elapsed:.1f}s)"
                )
                return
            if not self.transcript_event_buffer:
                continue
            for item in self.transcript_event_buffer:
                if item.get("role") != "user":
                    continue
                text = item.get("content", "").lower()
                self.amd_state["check_count"] += 1
                for pattern in self.VOICEMAIL_PATTERNS:
                    if pattern in text:
                        self.amd_state["detected"] = True
                        logger.warning(
                            f"📵 [{self.job_id}] AMD: BUZÓN DETECTADO — "
                            f"patrón '{pattern}' en '{anonymize_text(text)}'"
                        )
                        try:
                            enc_id = int(self.survey_id) if str(self.survey_id).isdigit() else 0
                            await enqueue_guardar_encuesta({
                                "id_encuesta": enc_id,
                                "status": "failed",
                                "comentarios": f"Buzón de voz detectado automáticamente (AMD): {pattern}",
                            })
                            await enqueue_colgar_sala(self.room_name)
                            logger.info(
                                f"📵 [{self.job_id}] AMD: encuesta {self.survey_id} failed + colgar encolados."
                            )
                        except Exception as amd_err:
                            logger.error(f"❌ [{self.job_id}] AMD: Error al encolar cierre: {amd_err}")
                        return
                user_msgs = [i for i in self.transcript_event_buffer if i.get("role") == "user"]
                total_user_words = sum(_count_words(i.get("content", "")) for i in user_msgs)
                if len(user_msgs) >= 2 or total_user_words > 8:
                    self.amd_state["human_confirmed"] = True
                    return

    async def run_ghost_kicker(self) -> None:
        """
        FIX 4 — Ghost kicker demasiado agresivo.

        Problema: allowed_prefixes limitado expulsaba participantes legítimos de
        Yeastar/LiveKit; polling de 2 s era agresivo y no había período de gracia.

        Solución:
        - Prefijos extendidos: caller_, phone_, client_, agent-
        - Período de gracia de 10 s antes de expulsar a cualquier desconocido
        - Polling aumentado de 2 s → 5 s para reducir carga
        - Log WARNING detallado con la identity completa antes de expulsar
        """
        # FIX 4: prefijos extendidos
        allowed_prefixes = ("user_", "sip_", "caller_", "phone_", "client_", "agent-")
        # dict identity → tiempo de primera detección (período de gracia)
        first_seen: dict[str, float] = {}
        grace_seconds = 10.0

        while not self.stop_guard.is_set():
            try:
                now = self.loop_obj.time()
                for p in list(self.ctx.room.remote_participants.values()):
                    identity = getattr(p, "identity", "") or ""
                    if identity.startswith(allowed_prefixes):
                        first_seen.pop(identity, None)
                        continue
                    # Primera vez que se ve: registrar y dar período de gracia
                    if identity not in first_seen:
                        first_seen[identity] = now
                        logger.info(
                            f"👻 [{self.job_id}] Participante desconocido '{identity}' "
                            f"en sala {self.room_name}. Período de gracia: {grace_seconds:.0f}s."
                        )
                        continue
                    # Aún dentro del período de gracia
                    time_in_room = now - first_seen[identity]
                    if time_in_room < grace_seconds:
                        continue
                    # FIX 4: log WARNING detallado antes de expulsar
                    logger.warning(
                        f"👻 [{self.job_id}] Expulsando participante no autorizado '{identity}' "
                        f"de sala {self.room_name} (en sala {time_in_room:.0f}s, "
                        f"prefijos permitidos: {allowed_prefixes})"
                    )
                    try:
                        from livekit import api as _lk_api
                        _lk = _lk_api.LiveKitAPI()
                        await _lk.room.remove_participant(
                            _lk_api.RoomParticipantIdentity(room=self.room_name, identity=identity)
                        )
                        await _lk.aclose()
                        first_seen.pop(identity, None)
                        logger.info(
                            f"✅ [{self.job_id}] Participante '{identity}' expulsado de {self.room_name}"
                        )
                    except Exception as kick_err:
                        logger.error(
                            f"❌ [{self.job_id}] Error expulsando '{identity}': {kick_err}"
                        )
            except Exception as guard_err:
                logger.error(f"⚠️ [{self.job_id}] Error en ghost kicker: {guard_err}")
            # FIX 4: intervalo aumentado de 2 s → 5 s para reducir carga
            await asyncio.sleep(5)

    async def run_backchannel(self) -> None:
        """Backchanneling: inserta señal de escucha activa si el usuario habla largo."""
        pending_user_idx = None
        pending_since = None
        last_backchannel_at = 0.0
        cooldown_seconds = 14.0
        trigger_seconds = 5.0
        fillers = [
            "Entiendo...", "Sí, claro.", "Ya veo...", "Ajá, sí.",
            "Mhm, le escucho.", "Sí, sigo con usted.", "Perfecto, adelante.", "Claro, dígame.",
        ]
        while not self.stop_guard.is_set():
            try:
                chat_ctx = getattr(
                    self.session, "chat_ctx", getattr(self.session, "chat_context", None)
                )
                if not chat_ctx or not getattr(chat_ctx, "messages", None):
                    await asyncio.sleep(0.7)
                    continue
                normalized_msgs = []
                for m in chat_ctx.messages:
                    role = getattr(m, "role", "")
                    content = _normalize_message_text(getattr(m, "content", None))
                    if role in ("user", "assistant") and content:
                        normalized_msgs.append((role, content))
                if not normalized_msgs:
                    await asyncio.sleep(0.7)
                    continue
                last_idx = len(normalized_msgs) - 1
                last_role, last_content = normalized_msgs[last_idx]
                now = self.loop_obj.time()
                if last_role == "user" and len(last_content) >= 25:
                    if pending_user_idx != last_idx:
                        pending_user_idx = last_idx
                        pending_since = now
                    if (
                        pending_since is not None
                        and (float(now) - float(pending_since)) >= trigger_seconds
                        and (float(now) - float(last_backchannel_at)) >= cooldown_seconds
                    ):
                        try:
                            await self.session.say(random.choice(fillers), allow_interruptions=True)
                            last_backchannel_at = now
                        except Exception as be:
                            logger.debug(f"[{self.job_id}] Backchannel no enviado: {be}")
                        finally:
                            pending_since = None
                else:
                    pending_user_idx = None
                    pending_since = None
            except Exception as e:
                logger.debug(f"[{self.job_id}] Error en backchannel loop: {e}")
            await asyncio.sleep(0.7)

    async def run_autosave(self) -> None:
        """Guarda la transcripción parcial cada 40 s durante la llamada."""
        await asyncio.sleep(30)
        while not self.stop_guard.is_set():
            await self._save_transcript_snapshot("autosave-30s")
            await asyncio.sleep(40)

    async def run_silence_watchdog(self) -> None:
        """Reprompt cuando el cliente no responde tras SILENCE_REPROMPT_DELAY segundos."""
        self.reprompt_state["last_assistant_at"] = self.loop_obj.time()
        self.reprompt_state["waiting_user"] = True
        while not self.stop_guard.is_set():
            await asyncio.sleep(0.25)
            try:
                # FIX C — no repromptear si el workflow no espera respuesta.
                wf_sm = getattr(self.agent_instance, "_workflow_sm", None)
                if wf_sm is not None and not wf_sm.is_finished():
                    current = wf_sm.current_step()
                    if current and current.get("type") in ("message", "condition", "transfer", "end"):
                        await asyncio.sleep(0.25)
                        continue

                now = self.loop_obj.time()
                if not self.reprompt_state["waiting_user"]:
                    continue
                assistant_silent_for = now - float(self.reprompt_state["last_assistant_at"])
                user_silent_for = now - float(self.reprompt_state["last_user_at"])
                can_reprompt = self.reprompt_state["reprompt_count"] < 3
                if (
                    assistant_silent_for >= self.SILENCE_REPROMPT_DELAY
                    and user_silent_for >= self.SILENCE_REPROMPT_DELAY
                    and can_reprompt
                ):
                    self.reprompt_state["reprompt_count"] += 1
                    self.reprompt_state["last_assistant_at"] = now
                    try:
                        await self.session.say(
                            random.choice(self.REPROMPT_PHRASES), allow_interruptions=True
                        )
                        logger.info(
                            f"🔁 [{self.job_id}] Reprompt por silencio "
                            f"(#{self.reprompt_state['reprompt_count']})"
                        )
                    except Exception as _re:
                        logger.debug(f"[{self.job_id}] Reprompt no enviado: {_re}")
            except Exception as _e:
                logger.debug(f"[{self.job_id}] Error en silence_reprompt_loop: {_e}")

    # ── Registro de eventos ────────────────────────────────────────────────────

    def setup_events(self) -> None:
        """Registra todos los handlers de session y ctx.room."""

        @self.session.on("user_input_transcribed")
        async def _on_user_input_transcribed(ev):
            try:
                content = _normalize_message_text(getattr(ev, "transcript", ""))
                is_final = bool(getattr(ev, "is_final", True))
                if not content or not is_final:
                    return
                if _is_likely_noise_transcript(content):
                    logger.debug(
                        f"🔇 [{self.job_id}] Transcripción descartada como ruido: '{anonymize_text(content)}'"
                    )
                    return
                word_count = _count_words(content)
                self.runtime_state["last_user_text"] = content
                if not self.lang_state["detected"] and word_count >= 1:
                    asyncio.create_task(self._try_switch_language(content))
                if (
                    self.runtime_state["agent_state"] in ("speaking", "thinking")
                    and word_count < self.max_short_interrupt_words
                ):
                    logger.debug(
                        f"🛡️ [{self.job_id}] Interrupción corta ignorada "
                        f"({word_count} palabras): '{anonymize_text(content)}'"
                    )
                    return
                now = self.loop_obj.time()
                if (
                    self.runtime_state["agent_state"] in ("speaking", "thinking")
                    and word_count >= self.max_short_interrupt_words
                ):
                    if (now - float(self.runtime_state["last_interrupt_ack_at"])) > 1.2:
                        self.runtime_state["last_interrupt_ack_at"] = now
                        async def _say_interrupt_ack():
                            try:
                                await self.session.say(
                                    random.choice(self.INTERRUPTION_ACKS),
                                    allow_interruptions=True,
                                )
                            except Exception as ack_err:
                                logger.debug(
                                    f"[{self.job_id}] Ack de interrupción no enviado: {ack_err}"
                                )
                        asyncio.create_task(_say_interrupt_ack())
                self._append_transcript_event("user", content)
                self.reprompt_state["last_user_at"] = now
                self.reprompt_state["waiting_user"] = False
                self.reprompt_state["reprompt_count"] = 0

                # Fase 2 — Detección de nombre del cliente en conversación
                if not getattr(self.agent_instance, "_detected_customer_name", ""):
                    _name_match = re.search(
                        r"(?:soy|me llamo|mi nombre es)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+"
                        r"(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?)",
                        content,
                        re.IGNORECASE,
                    )
                    if _name_match:
                        detected = _name_match.group(1).strip()
                        self.agent_instance._detected_customer_name = detected
                        logger.info(
                            "[%s] Nombre del cliente detectado: %s",
                            self.job_id, detected,
                        )

                # PARTE 4 — Integración workflow: avanzar máquina de estados
                wf_sm = getattr(self.agent_instance, "_workflow_sm", None)
                if wf_sm is not None and not wf_sm.is_finished():
                    await self._handle_workflow_turn(content, wf_sm)
            except Exception as ev_err:
                logger.debug(f"[{self.job_id}] Error evento user_input_transcribed: {ev_err}")

        @self.session.on("conversation_item_added")
        def _on_conversation_item_added(ev):
            try:
                item = getattr(ev, "item", None)
                role = getattr(item, "role", "")
                content = _normalize_message_text(getattr(item, "content", None))
                if role not in ("user", "assistant") or not content:
                    return
                now = self.loop_obj.time()
                lower = content.strip().lower()
                if role == "assistant":
                    if lower in self.reprompt_phrases_lc:
                        return
                    self._append_transcript_event("assistant", content)
                    self.reprompt_state["last_assistant_at"] = now
                    self.reprompt_state["waiting_user"] = True
                    self.reprompt_state["reprompt_count"] = 0
                else:
                    self._append_transcript_event("user", content)
                    self.reprompt_state["last_user_at"] = now
                    self.reprompt_state["waiting_user"] = False
                    self.reprompt_state["reprompt_count"] = 0
            except Exception as ev_err:
                logger.debug(f"[{self.job_id}] Error evento conversation_item_added: {ev_err}")

        @self.session.on("agent_state_changed")
        def _on_agent_state_changed(ev):
            try:
                new_state = str(getattr(ev, "new_state", "")).lower()
                old_state = str(getattr(ev, "old_state", "")).lower()
                now = self.loop_obj.time()
                self.runtime_state["agent_state"] = new_state
                if new_state == "listening" and old_state in ("speaking", "thinking"):
                    self.reprompt_state["last_assistant_at"] = now
                    self.reprompt_state["waiting_user"] = True
                    self._llm_responding = False
                if new_state == "thinking":
                    # FIX F — cancela fillers anteriores para evitar solapamientos.
                    if self._filler_task and not self._filler_task.done():
                        self._filler_task.cancel()
                    if (now - float(self.runtime_state["last_filler_at"])) > 1.0:
                        self.runtime_state["last_filler_at"] = now
                        async def _say_latency_filler():
                            try:
                                if self._llm_responding:
                                    return
                                await self.session.say(
                                    random.choice(self.LATENCY_FILLERS), allow_interruptions=True
                                )
                            except Exception as fill_err:
                                logger.debug(
                                    f"[{self.job_id}] Filler de latencia no enviado: {fill_err}"
                                )
                        self._filler_task = asyncio.create_task(_say_latency_filler())
                    try:
                        if self.bg_player is not None:
                            dyn_volume, bursts = _estimate_thinking_complexity(
                                str(self.runtime_state.get("last_user_text", ""))
                            )
                            for _ in range(bursts):
                                self.bg_player.play(
                                    AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=dyn_volume),
                                    loop=False,
                                )
                    except Exception as k_err:
                        logger.debug(f"[{self.job_id}] No se pudo aplicar teclado dinámico: {k_err}")
                if new_state == "speaking":
                    # FIX F — el LLM ya está respondiendo: suprimir fillers pendientes.
                    self._llm_responding = True
                    if self._filler_task and not self._filler_task.done():
                        self._filler_task.cancel()
            except Exception as ev_err:
                logger.debug(f"[{self.job_id}] Error evento agent_state_changed: {ev_err}")

        @self.ctx.room.on("disconnected")
        def _on_disconnect():
            logger.info(f"🔌 [{self.job_id}] Desconectado.")
            self.finished.set()

        @self.ctx.room.on("participant_disconnected")
        def _on_participant_disconnected(participant: rtc.RemoteParticipant):
            if not participant.identity.startswith("agent-"):
                logger.info(
                    f"[{self.job_id}] Cliente se desconectó. Guardando transcripción y terminando sala."
                )
                async def disconnect_tasks():
                    await self._save_transcript_snapshot("client-hangup")
                    try:
                        await enqueue_colgar_sala(self.room_name)
                    except Exception as e:
                        logger.error(
                            f"Error encolando colgar desde participant_disconnected: {e}"
                        )
                asyncio.create_task(disconnect_tasks())

    # ── Ciclo de vida ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Arranca el audio de fondo, crea todas las tareas y espera al fin de la llamada."""
        if os.getenv("AGENT_OFFICE_NOISE", "true").lower() not in ("false", "0", "no"):
            try:
                self.bg_player = BackgroundAudioPlayer(
                    ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.85),
                    thinking_sound=AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.45),
                )
                await self.bg_player.start(room=self.ctx.room, agent_session=self.session)
                logger.info(f"🎙️ [{self.job_id}] Ruido de fondo de oficina activado.")
            except Exception as bg_err:
                logger.warning(f"⚠️ [{self.job_id}] No se pudo iniciar ruido de fondo: {bg_err}")

        self._tasks = [
            asyncio.create_task(self.run_amd()),
            asyncio.create_task(self.run_ghost_kicker()),
            asyncio.create_task(self.run_backchannel()),
            asyncio.create_task(self.run_autosave()),
            asyncio.create_task(self.run_silence_watchdog()),
        ]

        transfer_event = getattr(self.agent_instance, "_transfer_completed", None)
        finished_task = asyncio.create_task(self.finished.wait())
        transfer_task = asyncio.create_task(
            transfer_event.wait() if transfer_event else asyncio.sleep(float("inf"))
        )

        try:
            done, pending = await asyncio.wait(
                {finished_task, transfer_task},
                timeout=self.CALL_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for p in pending:
                p.cancel()

            if transfer_task in done and transfer_event and transfer_event.is_set():
                # Transferencia limpia: desconectamos el agente IA sin cerrar la sala
                logger.info(
                    f"🔄 [{self.job_id}] Transferencia completada — desconectando agente IA "
                    f"sin cerrar sala '{self.room_name}'"
                )
                self.stop_guard.set()
                for t in self._tasks:
                    t.cancel()

                survey_id_int = int(self.survey_id) if str(self.survey_id).isdigit() else 0
                if survey_id_int:
                    try:
                        await enqueue_guardar_encuesta({
                            "id_encuesta": survey_id_int,
                            "status": "transferred",
                            "comentarios": "Agente IA desconectado tras transferencia a humano",
                        })
                    except Exception as save_err:
                        logger.warning(f"⚠️ [{self.job_id}] Error guardando estado transferred: {save_err}")

                try:
                    await self.session.aclose()
                except Exception:
                    pass

                # Solo desconectar el agente IA — NO cerrar la sala ni expulsar al participante SIP
                try:
                    await self.ctx.room.disconnect()
                except Exception as disc_err:
                    logger.debug(f"[{self.job_id}] Desconexión tras transferencia: {disc_err}")

                self.finished.set()
                return

            if not done:
                # Timeout de seguridad
                logger.error(
                    f"🚨 [{self.job_id}] KILL SWITCH: Timeout de seguridad "
                    f"({self.CALL_TIMEOUT_SECONDS}s) alcanzado. "
                    f"Forzando desconexión del worker para sala '{self.room_name}'."
                )
                try:
                    await self.ctx.room.disconnect()
                except Exception as disc_err:
                    logger.warning(f"[{self.job_id}] Error al forzar desconexión: {disc_err}")
                self.finished.set()

        except asyncio.TimeoutError:
            logger.error(
                f"🚨 [{self.job_id}] KILL SWITCH: Timeout de seguridad "
                f"({self.CALL_TIMEOUT_SECONDS}s) alcanzado. "
                f"Forzando desconexión del worker para sala '{self.room_name}'."
            )
            try:
                await self.ctx.room.disconnect()
            except Exception as disc_err:
                logger.warning(f"[{self.job_id}] Error al forzar desconexión: {disc_err}")
            self.finished.set()

    def stop(self) -> None:
        """Señaliza el fin y cancela todas las tareas en curso."""
        self.stop_guard.set()
        for t in self._tasks:
            t.cancel()

    async def finalize(self) -> None:
        """
        Post-procesamiento tras el fin de la llamada: extrae transcripción,
        clasifica disposición con LLM y encola la persistencia de resultados.
        """
        try:
            raw_messages: list[dict] = []
            transcript = ""
            try:
                raw_messages, transcript = _extract_transcript_from_session(self.session)
                logger.info(
                    f"📝 [{self.job_id}] Transcripción extraída en finally: {len(transcript)} chars"
                )
                if not transcript:
                    raw_messages, transcript = self._build_transcript_from_event_buffer()
                    if transcript:
                        logger.info(
                            f"📝 [{self.job_id}] Usando buffer de eventos: {len(transcript)} chars"
                        )
                if not transcript and self.transcript_snapshot.get("transcript"):
                    transcript = self.transcript_snapshot["transcript"]
                    raw_messages = self.transcript_snapshot.get("raw", [])
                    logger.info(
                        f"📝 [{self.job_id}] Usando snapshot de transcripción: {len(transcript)} chars"
                    )
            except Exception as ex:
                logger.error(f"Error procesando historia para transcripción local: {ex}")
                if not transcript:
                    raw_messages, transcript = self._build_transcript_from_event_buffer()
                if not transcript and self.transcript_snapshot.get("transcript"):
                    transcript = self.transcript_snapshot["transcript"]
                    raw_messages = self.transcript_snapshot.get("raw", [])

            seconds_used = 0
            if self.call_start_time is not None:
                seconds_used = max(0, int(time.time() - self.call_start_time))

            agent_type = self.agent_config.get("agent_type", "ENCUESTA_NUMERICA")
            data_saved = getattr(self.agent_instance, "data_saved", False)
            datos_extra = None
            call_disposition = None

            if transcript:
                logger.info(
                    f"🧠 Clasificando disposición de llamada y extrayendo datos "
                    f"para encuesta {self.survey_id} (Tipo: {agent_type})"
                )
                call_disposition, datos_extra = await analyze_call_disposition(
                    transcript,
                    agent_type,
                    data_saved,
                    self.lang_state.get("active_lang", self.language),
                )
            else:
                call_disposition = "no_contesta"
                datos_extra = {
                    "sentimiento_cliente": "Neutral",
                    "idioma": self.lang_state.get("active_lang", self.language),
                }
                logger.info(
                    f"📵 Sin transcripción para encuesta {self.survey_id} → "
                    f"disposición: no_contesta"
                )

            if not call_disposition:
                call_disposition = "completada" if data_saved else "parcial"

            enc_id = int(self.survey_id) if str(self.survey_id).isdigit() else 0

            if data_saved:
                logger.info(
                    f"📝 Guardando transcripción/disposición/datos_extra para encuesta "
                    f"{self.survey_id} (datos numéricos ya guardados por tool)"
                )
                try:
                    _enc_job = await enqueue_guardar_encuesta({
                        "id_encuesta": enc_id,
                        "transcription": transcript,
                        "datos_extra": datos_extra,
                        "seconds_used": seconds_used,
                    })
                    logger.info(f"📬 Extras post-llamada encolados (job={_enc_job})")
                except Exception as save_err:
                    logger.error(f"Error encolando extras: {save_err}")
            else:
                logger.warning(
                    f"⚠️ La sesión terminó sin guardar datos explícitos por tool "
                    f"(Survey ID: {self.survey_id}) → Disposición: {call_disposition}"
                )
                try:
                    _enc_job = await enqueue_guardar_encuesta({
                        "id_encuesta": enc_id,
                        "transcription": transcript,
                        "status": call_disposition,
                        "comentarios": (
                            "Llamada finalizada sin interacción"
                            if call_disposition == "no_contesta"
                            else f"Llamada {call_disposition} via post-call"
                        ),
                        "datos_extra": datos_extra,
                        "seconds_used": seconds_used,
                    })
                    logger.info(
                        f"📬 Fallback post-llamada encolado "
                        f"(disposición: {call_disposition}, job={_enc_job})"
                    )
                except Exception as save_err:
                    logger.error(f"Error encolando fallback: {save_err}")

            # Fase 2 — Actualizar ficha de contacto post-llamada (no bloqueante)
            try:
                from utils.call_analyzer import upsert_contacto_post_call
                _telefono = (
                    (datos_extra or {}).get("telefono")
                    or self.agent_config.get("contacto_phone")
                    or ""
                )
                _nombre = getattr(self.agent_instance, "_detected_customer_name", "") or None
                _empresa_id_int = int(self.agent_config.get("empresa_id") or 0)
                if _telefono and _empresa_id_int:
                    resumen = (datos_extra or {}).get("resumen_narrativo")
                    asyncio.create_task(
                        upsert_contacto_post_call(
                            empresa_id=_empresa_id_int,
                            telefono=str(_telefono),
                            nombre_detectado=_nombre,
                            disposicion=call_disposition,
                            resumen=resumen,
                            datos_llamada={
                                "encuesta_id": enc_id,
                                "duracion_segundos": seconds_used,
                                "agent_name": self.agent_config.get("name"),
                                "fecha": datetime.now().isoformat(),
                                "notas_agente": datos_extra or {},
                            },
                        )
                    )
            except Exception as contact_err:
                logger.warning("[%s] Error actualizando ficha de contacto: %s", self.job_id, contact_err)

        except Exception as fatal_post:
            logger.error(
                f"🚨 [{self.job_id}] EXCEPCIÓN FATAL NO CAPTURADA en finalize: {fatal_post}"
            )


# ============================================================================
# FUNCIÓN PARA OBTENER LA CONFIGURACIÓN DEL AGENTE DESDE LA API
# ============================================================================
async def fetch_agent_config(survey_id: str, expected_empresa_id: str = "0") -> dict:
    """Consulta config del agente: Redis (TTL 1h) → HTTP fallback → escribe en Redis."""
    cache_key = f"ausarta:agent_config:survey_{survey_id}"

    try:
        redis_client = aioredis.from_url(_REDIS_URL, decode_responses=True)
        try:
            cached_raw = await redis_client.get(cache_key)
            if cached_raw:
                config = json.loads(cached_raw)
                _validate_agent_config_tenant(config, expected_empresa_id)
                logger.info(f"📋 Config desde Redis para survey {survey_id}")
                return config
        finally:
            await redis_client.close()
    except Exception as cache_err:
        logger.warning(f"⚠️ Redis cache miss/error para survey {survey_id}: {cache_err}")

    server_url = BRIDGE_SERVER_URL_INTERNAL
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        url = f"{server_url}/api/agent_config_by_survey/{survey_id}?_ts={int(asyncio.get_running_loop().time() * 1000)}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=5,
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                ) as resp:
                    if resp.status == 200:
                        config = await resp.json()
                        _validate_agent_config_tenant(config, expected_empresa_id)

                        try:
                            redis_client = aioredis.from_url(_REDIS_URL, decode_responses=True)
                            try:
                                await redis_client.set(
                                    cache_key,
                                    json.dumps(config, ensure_ascii=False),
                                    ex=_AGENT_CONFIG_CACHE_TTL,
                                )
                            finally:
                                await redis_client.close()
                        except Exception as write_err:
                            logger.warning(
                                f"⚠️ No se pudo cachear config en Redis survey {survey_id}: {write_err}"
                            )

                        logger.info(
                            f"📋 Config HTTP para survey {survey_id} (attempt {attempt}/{max_attempts}): "
                            f"nombre='{config.get('name')}', modelo='{config.get('llm_model')}', "
                            f"cfg_updated_at='{config.get('config_updated_at')}'"
                        )
                        return config
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

    logger.warning("⚠️ No se pudo obtener config fresca tras reintentos. Usando defaults.")
    return {}


async def fetch_agent_config_by_agent_id(agent_id: str, expected_empresa_id: str = "0") -> dict:
    """Consulta config directa por agent_id para llamadas entrantes SIP sin encuesta previa."""
    cache_key = f"ausarta:agent_config:agent_{agent_id}:empresa_{expected_empresa_id or '0'}"
    try:
        redis_client = aioredis.from_url(_REDIS_URL, decode_responses=True)
        try:
            cached_raw = await redis_client.get(cache_key)
            if cached_raw:
                config = json.loads(cached_raw)
                _validate_agent_config_tenant(config, expected_empresa_id)
                logger.info(f"Config inbound desde Redis para agent_id {agent_id}")
                return config
        finally:
            await redis_client.close()
    except Exception as cache_err:
        logger.warning(f"Redis cache miss/error para agent_id {agent_id}: {cache_err}")

    server_url = BRIDGE_SERVER_URL_INTERNAL
    query_empresa = f"&empresa_id={expected_empresa_id}" if expected_empresa_id and expected_empresa_id != "0" else ""
    url = f"{server_url}/api/agent_config_by_agent/{agent_id}?_ts={int(asyncio.get_running_loop().time() * 1000)}{query_empresa}"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            timeout=5,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"No se pudo obtener config por agent_id={agent_id} (HTTP {resp.status})")
            config = await resp.json()
            _validate_agent_config_tenant(config, expected_empresa_id)
            try:
                redis_client = aioredis.from_url(_REDIS_URL, decode_responses=True)
                try:
                    await redis_client.set(
                        cache_key,
                        json.dumps(config, ensure_ascii=False),
                        ex=_AGENT_CONFIG_CACHE_TTL,
                    )
                finally:
                    await redis_client.close()
            except Exception as write_err:
                logger.warning(f"No se pudo cachear config inbound agent_id={agent_id}: {write_err}")
            return config


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
# FASE 2 — ENRIQUECIMIENTO DE CONTEXTO (KB + BD externa)
# ============================================================================

async def _enrich_agent_config_with_context(
    job_id: str,
    agent_config: dict,
    empresa_id_str: str,
    meta_data: dict,
) -> None:
    """
    Carga en paralelo (timeout 5s):
    1. Base de Conocimiento RAG (top 3 chunks relevantes al greeting del agente).
    2. Datos del cliente en BD externa (si hay teléfono en metadata).

    Los resultados se inyectan en agent_config como _kb_context y _customer_context,
    que build_agent_prompt() ya sabe leer.
    Si cualquiera falla, continúa sin ese contexto (nunca bloquea la llamada).
    """
    try:
        empresa_id_int = int(empresa_id_str) if empresa_id_str.isdigit() else 0
    except Exception:
        empresa_id_int = 0

    if not empresa_id_int:
        return

    async def _load_kb() -> str:
        try:
            from services.embedding_service import search_knowledge
            greeting = agent_config.get("greeting") or agent_config.get("instructions", "")
            query = (greeting or "información general servicios empresa")[:500]
            results = await asyncio.wait_for(
                search_knowledge(empresa_id_int, query, limit=3, threshold=0.70),
                timeout=5,
            )
            if not results:
                return ""
            lines = []
            for r in results:
                lines.append(f"[{r['titulo']}]\n{r['contenido']}")
            context = "\n\n".join(lines)
            logger.info(
                "[%s] KB context cargado: %d chunks (%.0f chars)",
                job_id, len(results), len(context),
            )
            return context
        except Exception as kb_err:
            logger.warning("[%s] KB context no disponible: %s", job_id, kb_err)
            return ""

    async def _load_customer(telefono: str) -> str:
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
            logger.warning("[%s] Customer context no disponible: %s", job_id, ext_err)
            return ""

    async def _load_crm_contact(telefono: str) -> str:
        try:
            from services.supabase_service import supabase, sb_query

            if not supabase:
                return ""
            res = await asyncio.wait_for(
                sb_query(
                    lambda: supabase.table("contactos")
                    .select("nombre,email,empresa_nombre,cargo,notas,datos_crm,historial_llamadas")
                    .eq("empresa_id", empresa_id_int)
                    .eq("telefono", telefono)
                    .limit(1)
                    .execute()
                ),
                timeout=5,
            )
            if not res.data:
                return ""
            c = res.data[0]
            lines = []
            if c.get("nombre"):
                lines.append(f"Nombre: {c['nombre']}")
            if c.get("empresa_nombre"):
                lines.append(f"Empresa: {c['empresa_nombre']}")
            if c.get("cargo"):
                lines.append(f"Cargo: {c['cargo']}")
            if c.get("notas"):
                lines.append(f"Notas: {c['notas']}")
            historial = c.get("historial_llamadas") or []
            if isinstance(historial, list) and historial:
                ultima = historial[-1] if isinstance(historial[-1], dict) else {}
                lines.append(
                    f"Ultima llamada: {ultima.get('fecha', '?')} - {ultima.get('disposicion', '?')}"
                )
            return "\n".join(lines)
        except Exception as crm_err:
            logger.warning("[%s] CRM contact lookup failed: %s", job_id, crm_err)
            return ""

    # Teléfono del contacto — puede venir en varios campos de metadata
    telefono = (
        meta_data.get("contacto_phone")
        or meta_data.get("telefono")
        or meta_data.get("phone")
        or ""
    )

    tasks: list[asyncio.Task] = [asyncio.create_task(_load_kb())]
    customer_task: asyncio.Task | None = None
    if telefono:
        customer_task = asyncio.create_task(_load_crm_contact(str(telefono)))
        tasks.append(customer_task)

    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    kb_context = results_list[0] if isinstance(results_list[0], str) else ""
    customer_context = ""
    if customer_task is not None and len(results_list) > 1:
        customer_context = results_list[1] if isinstance(results_list[1], str) else ""
        if not customer_context:
            customer_context = await _load_customer(str(telefono))

    agent_config["_kb_context"] = kb_context
    agent_config["_customer_context"] = customer_context


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
    if not room_name.startswith(ROOM_PREFIX):
        await _safe_reject(f"Sala fuera de prefijo permitido '{ROOM_PREFIX}': {room_name}")
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

        # --- PASO 4 (Fase 2): Cargar contextos KB y cliente ANTES de crear el agente ---
        await _enrich_agent_config_with_context(
            job_id=job_id,
            agent_config=agent_config,
            empresa_id_str=empresa_id,
            meta_data=meta_data,
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

        stt_plugin, delegate_turn_to_stt = _build_stt_plugin(stt_provider, stt_model, language)

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
            "tts": _build_tts_plugin(
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

        await session.start(room=ctx.room, agent=agent_instance)

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
        await cs.start()

    except Exception as e:
        handle_error(e)

    finally:
        if cs is not None:
            cs.stop()

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

if __name__ == "__main__":
    logger.info(
        "🤖 Arrancando worker LiveKit | agent_name=%s | livekit_url=%s | bridge=%s",
        DISPATCH_AGENT_NAME,
        (os.getenv("LIVEKIT_URL") or "NO SET"),
        BRIDGE_SERVER_URL_INTERNAL,
    )
    cli.run_app(server)
