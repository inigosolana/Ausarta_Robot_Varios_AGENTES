import logging
from typing import Optional
import os
import aiohttp
import asyncio
import sys
import json
import re
import random
from dotenv import load_dotenv
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
    ToolError,
    cli,
    function_tool,
    room_io,
    utils,
    stt,
    AutoSubscribe,
    llm
)
from livekit.plugins import (
    silero,
    openai,
    deepgram, 
    cartesia  
)

# --- CONFIGURACIÓN DE LOGS ---
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("agent.log", mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("agent-dynamic")
load_dotenv()

ROOM_PREFIX = os.getenv("LIVEKIT_ROOM_PREFIX", "llamada_ausarta_")
DEFAULT_CARTESIA_VOICE = "a2f12ebd-80df-4de7-83f3-809599135b1d"
DISPATCH_AGENT_NAME = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()

# ============================================================================
# INSTRUCCIONES BASE - Se combinan con las instrucciones específicas del agente
# ============================================================================
BASE_RULES = """
REGLAS DE ORO (¡MUY IMPORTANTE!):
1. IDENTIDAD: Si te preguntan quién eres o cómo te llamas, preséntate con el nombre de la empresa para la que trabajas. NUNCA reveles nombres internos de sistema.
2. PROHIBIDO NARRAR ACCIONES: NUNCA digas en voz alta que vas a guardar un dato, NUNCA menciones el "ID de la encuesta", y NUNCA leas comandos de sistema. Habla SOLO como una persona normal.
3. PRONUNCIACIÓN: Di siempre "UNO" (ej: "del UNO al diez"), nunca "un".
4. PARA COLGAR: Usa SIEMPRE la herramienta 'finalizar_llamada' con un mensaje de despedida CORTÍSIMO (máx. 6-8 palabras). La herramienta lo dice y colgará enseguida. Ej: "Gracias por su tiempo. ¡Hasta luego!" 
5. SI EL CLIENTE NO TE ENTIENDE O DICE "¿CÓMO?", "¿QUÉ?": Repite la última pregunta que hiciste de forma amable y clara.
6. SI ESCUCHAS RUIDO, SILENCIO O UNA PALABRA SIN SENTIDO: reconduce SIEMPRE la conversación con una pregunta corta de seguimiento en 1-2 segundos ("¿Sigue ahí?", "¿Me escucha bien?", "Si le parece, seguimos con la pregunta...").
7. TÉCNICA DE RECONDUCCIÓN ESTRICTA: Eres amable pero tienes una misión. Si el cliente te responde contando una historia larga, quejándose, o hablando de un tema que no tiene nada que ver con tu pregunta, DEBES aplicar la fórmula "VALIDACIÓN CORTA + PREGUNTA ORIGINAL". NUNCA te enredes en conversaciones paralelas que duren más de 1 frase.
8. RESPUESTAS AMBIGUAS: Si pides una nota del 1 al 10 y el cliente responde 'Bien' o 'Normal', NO LO ACEPTES. Dile: 'Me alegra que haya ido bien, ¿pero qué número del 1 al 10 le pondría?'.
9. SI TE PREGUNTAN "¿QUIÉN ERES?", "¿DE PARTE DE QUIÉN LLAMAS?" O SIMILAR: responde tu identidad en una frase y CONTINÚA la encuesta. NUNCA cuelgues por esa pregunta.
10. VALIDACIÓN DE NOTAS: Si el usuario te da un número menor a 1 o mayor a 10 (ej: 0, 11), NO guardes el dato. Di "Disculpe, la nota debe ser entre 1 y 10. ¿Qué nota le daría?" y espera su respuesta.

REGLA CRÍTICA DE DESPEDIDA — LEE ESTO ATENTAMENTE:
- Cuando vayas a terminar, primero llama a 'guardar_encuesta' con el status final.
- Luego llama a 'finalizar_llamada' con un mensaje de despedida CÁLIDO pero ULTRA-BREVE.
- OBLIGATORIO: Máximo 6-8 palabras. La llamada colgará al terminar de hablar; si es largo, el cliente espera.
- Ejemplos correctos (cortos):
    * "Muchas gracias. ¡Hasta luego!"
    * "Perfecto, gracias. ¡Hasta pronto!"
    * "Gracias por atendernos. ¡Adiós!"
- PROHIBIDO: Despedidas largas ("Muchas gracias por su tiempo y por atendernos, de verdad. Que tenga..."). Usa UNA sola frase corta.
- NO digas la despedida antes de llamar a la herramienta; deja que la herramienta la diga para que no se corte.

EXCEPCIÓN - BUZÓN DE VOZ / FUERA DE COBERTURA:
- Si escuchas "fuera de cobertura", "móvil apagado", "buzón de voz", "contestador", "terminado el tiempo de grabación" o mensajes automáticos similares:
  - Usa 'guardar_encuesta' (status='failed').
  - Usa 'finalizar_llamada' (mensaje_despedida_manual="Buzón de voz detectado, finalizando.").

EXCEPCIÓN INTERRUPCIÓN/COLGAR:
- Usa 'guardar_encuesta' (status='incomplete').
- Usa 'finalizar_llamada' (mensaje_despedida_manual="Entendido, que tenga buen día. ¡Hasta luego!").

NOTA FINAL: UNA VEZ LLAMES A 'finalizar_llamada', LA CONVERSACIÓN HA TERMINADO. NO RESPONDAS A NADA MÁS.
"""

HUMAN_STYLE_RULES = """
ESTILO HUMANO (NATURAL Y CERCANO):
1. HABLA COMO PERSONA REAL: usa frases cortas, cálidas y naturales, evitando tono de robot.
2. MICRO-EMPATÍA: valida al cliente con expresiones breves ("entiendo", "qué bien", "perfecto", "gracias por comentarlo", "me alegra escucharle").
3. VARIACIÓN NATURAL: evita repetir siempre la misma estructura; alterna inicios de frase.
4. UNA PREGUNTA CADA VEZ: no lances bloques largos; pregunta, escucha, confirma y continúa.
5. ESCUCHA ACTIVA: si el cliente da un dato, refléjalo en una frase corta antes de seguir. Ej: "Entendido, un siete entonces..."
6. CLARIDAD ORAL: prioriza lenguaje cotidiano, simple y directo.
7. CIERRE CÁLIDO Y HUMANO: la despedida debe ser muy breve (1 frase, 4-8 palabras), con agradecimiento y "hasta luego" o "adiós" al final.
8. MENOS FRIALDAD: evita sonar corporativo o distante; usa un tono conversacional amable. Nada de frases estilo robot.
9. ARRANQUE NATURAL: al iniciar la llamada, saluda de forma ágil y humana, sin pausas largas.
10. RELLENOS NATURALES DE CONVERSACIÓN: usa ocasionalmente "A ver...", "Pues mira...", "Perfecto...", "Estupendo...", "Muy bien..." para sonar más fluido entre preguntas.
11. RECONOCE LO QUE DICE EL CLIENTE: si menciona algo positivo o negativo, hazlo notar brevemente. Ej: "Ah, me alegra que haya sido buena experiencia" o "Vaya, lo siento, lo tendré en cuenta".
"""

HUMANIZATION_PROMPT = """
Eres una persona real haciendo una llamada telefónica. No eres un robot ni una IA — eres una persona profesional y cercana que trabaja para esta empresa.

Reglas para sonar humano:
1) Usa marcadores discursivos naturales: "A ver...", "Pues mira...", "Eh...", "Vale, entiendo", "Claro que sí", "Perfecto".
2) NO hagas listas numeradas en la conversación hablada. Habla de forma fluida y natural.
3) Si el usuario te interrumpe, DETENTE y di "Sí, dígame..." o "Claro, cuénteme" antes de continuar.
4) Mantén respuestas ágiles pero completas (normalmente 15-40 palabras). Evita respuestas telegráficas.
5) Si necesitas tiempo, di "Un momento..." o "A ver, déjeme apuntar eso..." en lugar de silencio.
6) Si el cliente dice que no tiene tiempo, NO insistas: cierra de forma rápida pero genuinamente cálida.
7) Antes de finalizar, asegúrate de guardar el estado final con guardar_encuesta.
8) En cuestionarios abiertos, continúa con la siguiente pregunta salvo rechazo explícito.
9) DESPEDIDA NATURAL: cuando llegue el momento de despedirte, usa una sola frase corta (4-8 palabras). Ejemplo: "Muchas gracias. Hasta luego."
10) NUNCA SUENES FRÍO: si el cliente fue amable, devuelve esa amabilidad. Si fue escueto, sé respetuoso y directo. Adáptate al tono del cliente.
"""

ENTHUSIASM_INSTRUCTIONS = {
    "Bajo": "Mantén un tono calmado, pausado y profesional. Evita sonar efusivo.",
    "Normal": "Mantén un tono cercano, claro y profesional con energía equilibrada.",
    "Alto": "Habla con energía positiva y dinamismo, sin perder claridad ni profesionalidad.",
    "Extremo": "Usa un tono muy entusiasta y motivador, con mucha energía y amabilidad.",
}


def _resolve_enthusiasm_instruction(level: str) -> str:
    if level in ENTHUSIASM_INSTRUCTIONS:
        return ENTHUSIASM_INSTRUCTIONS[level]
    return ENTHUSIASM_INSTRUCTIONS["Normal"]


def _is_uuid_like(value: str) -> bool:
    if not value:
        return False
    return bool(
        re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            value.strip(),
        )
    )


def _build_tts_plugin(voice_id: str, language: str, speaking_speed: float):
    """
    Crea el plugin TTS aplicando voz + velocidad.
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

    try:
        return cartesia.TTS(
            model="sonic-multilingual",
            voice=safe_voice,
            language=language,
            speed=safe_speed,
        )
    except TypeError:
        logger.warning("⚠️ cartesia.TTS no soporta 'speed' en esta versión. Usando fallback sin speed.")
        return cartesia.TTS(
            model="sonic-multilingual",
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
        # Base URL del backend/bridge. En despliegues multi-contenedor, 127.0.0.1 suele NO ser el backend.
        # Priorizamos INTERNAL (misma red), luego BRIDGE_SERVER_URL (red docker / host), y por último loopback.
        self.server_url = (
            os.getenv("BRIDGE_SERVER_URL_INTERNAL")
            or os.getenv("BRIDGE_SERVER_URL")
            or "http://127.0.0.1:8001"
        ).rstrip("/")
        self.data_saved = False
        self.room_name = room_name
        self.agent_config = agent_config
        self.greeting = agent_config.get("greeting", "Buenas, ¿tiene un momento?")
        self.company_context = agent_config.get("company_context", "") or ""
        self.enthusiasm_level = agent_config.get("enthusiasm_level", "Normal") or "Normal"
        self.voice_id = agent_config.get("voice_id", "") or ""
        self.speaking_speed = agent_config.get("speaking_speed", 1.0)
        self.hangup_started = False
        
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

        # Combinar las instrucciones específicas del agente con las reglas base
        agent_instructions = agent_config.get("instructions", "Eres un asistente virtual.")
        agent_name = agent_config.get("name", "Bot")
        company_name = (
            agent_config.get("company_name")
            or agent_config.get("empresa_nombre")
            or "Ausarta"
        )
        
        base_rules_to_use = BASE_RULES
        inst_lower = agent_instructions.lower()
        # Detección de tipo de agente (Campo explícito 'tipo_resultados' o fallback)
        tipo_res = agent_config.get("tipo_resultados")
        
        is_numeric = (tipo_res in ['ENCUESTA_NUMERICA', 'ENCUESTA_MIXTA'])
        has_preguntas = (tipo_res in ['PREGUNTAS_ABIERTAS', 'CUALIFICACION_LEAD', 'AGENDAMIENTO_CITA', 'SOPORTE_CLIENTE'])
        is_mixed = (tipo_res == 'ENCUESTA_MIXTA')
        
        # Fallback para agentes antiguos o si n8n aún no lo clasificó
        if tipo_res is None:
            survey_type_legacy = agent_config.get("survey_type")
            is_numeric = (survey_type_legacy == 'numeric')
            has_preguntas = (survey_type_legacy in ['open_questions', 'mixed'])
            
            if survey_type_legacy is None:
                numeric_keywords = ["1 al 10", "0 al 10", "del uno al diez", "numérica", "puntuación", "uno al 10", "uno al diez", "1 al 5"]
                is_numeric = any(kw in inst_lower for kw in numeric_keywords) or "dakota" in agent_name.lower()
                has_preguntas = any(p in inst_lower for p in ["pregunta 1", "pregunta 2", "pregunta:"])
                # Detectar encuesta mixta: tiene numéricas + condicionales o "SI ... pregunta"
                condicional_markers = ["si la nota", "condicional", "si responde", "si dice", "si fue 1", "si fue 2", "si fue 3"]
                is_mixed = is_numeric and any(m in inst_lower for m in condicional_markers)
            
            if survey_type_legacy == 'mixed':
                is_numeric = True
                has_preguntas = True
                is_mixed = True
        
        if is_mixed:
            base_rules_to_use += """
REGLA ESPECIAL PARA ENCUESTAS MIXTAS (numéricas + condicionales/abiertas):
- Obtén las puntuaciones numéricas y usa 'nota_comercial', 'nota_instalador', 'nota_rapidez' según corresponda.
- Si hay preguntas condicionales o abiertas, pasa 'datos_extra' como cadena JSON, ej: '{"detalle_problema":"...","motivo_contratacion":"comercial","experiencia_general":4}'.
- Llama a guardar_encuesta con notas numéricas y datos_extra (string JSON).
"""
        elif is_numeric:
            base_rules_to_use += """
REGLA ESPECIAL PARA ENCUESTAS NUMÉRICAS:
- Esta es una encuesta de puntuación del 0 al 10.
- Debes obtener una nota numérica para cada pregunta. 
- Si el cliente responde con texto, pídele amablemente una puntuación del 0 al 10.
- OBLIGATORIO: Tras recibir las 3 notas (comercial, instalador, rapidez), SIEMPRE pregunta por un comentario final antes de terminar (ej: "¿Quiere añadir algún comentario antes de terminar?"). Solo después de la respuesta del cliente, llama a guardar_encuesta con comentarios y status='completed', y luego finalizar_llamada. NUNCA omitas esta pregunta de comentario.
"""
        elif has_preguntas:
            base_rules_to_use += """
REGLA ESPECIAL PARA CUESTIONARIOS ABIERTOS:
- Como este es un cuestionario de preguntas abiertas, USA el campo 'comentarios' de la herramienta 'guardar_encuesta' para guardar todas las respuestas de las preguntas planteadas recopiladas en forma de texto descriptivo.
- IGNORA la regla estructurada de "Validación de notas de 1 al 10" si no aplica a tus preguntas.
"""
        
        # Construcción del Prompt Final: Reglas -> Datos -> GUION (EL GUION ES LO MÁS IMPORTANTE)
        full_instructions = f"{base_rules_to_use}\n\n"
        full_instructions += f"{HUMAN_STYLE_RULES}\n\n"
        full_instructions += f"{HUMANIZATION_PROMPT}\n\n"
        full_instructions += f"DATOS DEL AGENTE:\n- NOMBRE: {agent_name}\n- EMPRESA: {company_name}\n"
        full_instructions += f"- NIVEL DE ENTUSIASMO: {self.enthusiasm_level}\n"
        full_instructions += f"- VELOCIDAD DE VOZ OBJETIVO: {self.speaking_speed}\n\n"
        full_instructions += "CONTEXTO DE EMPRESA (Knowledge Base):\n"
        full_instructions += f"{self.company_context if self.company_context else 'No disponible.'}\n\n"
        full_instructions += (
            "REGLAS DE USO DEL CONTEXTO DE EMPRESA:\n"
            "- Si el cliente pregunta por servicios, productos, precios, horarios, garantías o políticas, "
            "responde SIEMPRE usando primero el CONTEXTO DE EMPRESA.\n"
            "- No inventes datos fuera del CONTEXTO DE EMPRESA.\n"
            "- Si la información no está en el contexto, dilo de forma transparente y ofrece derivar o tomar nota para seguimiento.\n"
            "- Mantén respuestas breves, claras y orientadas al negocio de la empresa.\n\n"
        )
        full_instructions += f"ESTILO DE ENTREGA: {_resolve_enthusiasm_instruction(self.enthusiasm_level)}\n\n"
        full_instructions += (
            "OBJETIVO DE EXPERIENCIA:\n"
            "- El cliente debe sentir que habla con una persona profesional, cercana y resolutiva.\n"
            "- Si dudas entre sonar 'perfecto' o 'humano', prioriza humano siempre sin perder precisión.\n\n"
            "PLANTILLAS DE DESPEDIDA (úsalas como guía, adáptalas al contexto):\n"
            "- Cuando todo salió bien: 'Muchas gracias. Hasta luego.'\n"
            "- Cuando el cliente se mostró amable: 'Gracias por todo. Hasta pronto.'\n"
            "- Cuando fue breve: 'Perfecto, gracias. Adiós.'\n"
            "- Cuando el cliente rechazó o no tenía tiempo: 'Entendido, gracias. Hasta luego.'\n"
            "- SIEMPRE termina con un 'adiós', 'hasta luego' o 'hasta pronto' explícito al final para que el cliente sepa que la llamada acaba.\n\n"
        )
        full_instructions += "SIGUE ESTE GUION AL PIE DE LA LETRA:\n"
        full_instructions += f"{agent_instructions}\n"

        super().__init__(instructions=full_instructions)
        logger.info(f"Agente '{agent_name}' creado (Survey: {self.survey_id})")

    async def on_enter(self, *args, **kwargs) -> None:
        """Método llamado cuando el agente entra en la sesión. Lanza el saludo inicial."""
        # Aseguramos que survey_id sea correcto antes de saludar
        logger.info(f"--- 🎭 AGENTE EN SALA: {self.room_name} (Survey ID: {self.survey_id}) ---")
        
        # En versiones recientes de LiveKit, la sesión se accede vía self.session
        # Si no está asoaciada aún, intentamos obtenerla de los argumentos si viniera
        current_session = getattr(self, 'session', None)
        if not current_session:
            logger.warning(f"⚠️ [{self.room_name}] No session available in on_enter immediately.")
            # Pequeña espera para que se asocie
            await asyncio.sleep(0.5)
            current_session = getattr(self, 'session', None)

        if not current_session:
            logger.error(f"❌ [{self.room_name}] No se pudo obtener la sesión para saludar.")
            return

        logger.info(f"🎙️ Saludando en sala: {self.room_name} con: {self.greeting}")
        # Pausa natural al descolgar (casi inmediato por defecto)
        greeting_delay = float(os.getenv("AGENT_GREETING_DELAY_SECONDS", "0.15"))
        greeting_delay = max(0.1, min(greeting_delay, 3.0))
        await asyncio.sleep(greeting_delay)
        try:
            # Permitimos interrupción para que no suene rígido si el cliente responde enseguida
            await current_session.say(self.greeting, allow_interruptions=True)
        except Exception as e:
            logger.error(f"❌ Error al saludar: {e}")

    async def notify_n8n_transcription(self, survey_id: str, messages: list):
        """Envía la transcripción cruda a n8n para que él la procese."""
        webhook_url = os.getenv("N8N_WEBHOOK_URL_TRANSCRIPTS") or os.getenv("N8N_WEBHOOK_URL")
        if not webhook_url: return
        try:
            payload = {
                "survey_id": survey_id,
                "room_name": self.room_name,
                "messages": messages
            }
            async with aiohttp.ClientSession() as session:
                await session.post(webhook_url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Error enviando a n8n: {e}")

    @function_tool(name="guardar_encuesta")
    async def _http_tool_guardar_encuesta(
        self, 
        context: RunContext, 
        id_encuesta: int, 
        nota_comercial: Optional[int] = None, 
        nota_instalador: Optional[int] = None, 
        nota_rapidez: Optional[int] = None, 
        comentarios: Optional[str] = None,
        status: Optional[str] = None,
        datos_extra: Optional[str] = None
    ) -> str | None:
        """
        Guarda los datos de la encuesta/llamada. 
        - Si la encuesta es NUMÉRICA, usa 'nota_comercial', 'nota_instalador', 'nota_rapidez' (1-10).
        - IMPORTANTE: Para encuestas numéricas, SIEMPRE pregunta "¿Quiere añadir algún comentario antes de terminar?" ANTES de llamar con status='completed'. El campo 'comentarios' debe reflejar la respuesta real del cliente (o "Sin comentarios" si no añade nada).
        - Si la encuesta es ABIERTA o hay feedback extra, usa 'comentarios'.
        - Para ENCUESTA_MIXTA, pasa 'datos_extra' como JSON string, ej: '{"experiencia_general":4,"detalle_problema":"...","motivo_contratacion":"comercial"}'.
        - 'status': 'completed', 'failed', 'incomplete' o 'rejected_opt_out'.
        """
        self.data_saved = True
        
        url = f"{self.server_url}/guardar-encuesta"
        real_id = int(self.survey_id) if str(self.survey_id).isdigit() else id_encuesta

        if status == 'completed' and not comentarios:
            comentarios = "Sin comentarios"

        payload = {
            "id_encuesta": real_id,
            "nota_comercial": nota_comercial,
            "nota_instalador": nota_instalador,
            "nota_rapidez": nota_rapidez,
            "comentarios": comentarios,
            "status": status
        }
        if datos_extra and isinstance(datos_extra, str):
            try:
                import json
                payload["datos_extra"] = json.loads(datos_extra)
            except Exception:
                payload["datos_extra"] = {"raw": datos_extra}
        
        # IMPORTANTE: Await directo en vez de fire-and-forget para asegurar que se guarda
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload, timeout=10) as resp:
                    logger.info(f"✅ guardar_encuesta tool: HTTP {resp.status} para encuesta {real_id}")
        except Exception as e:
            logger.error(f"❌ Error en guardar_encuesta tool: {e}")
        
        return "Dato guardado."

    @function_tool(name="finalizar_llamada")
    async def _http_tool_finalizar_llamada(
        self, context: RunContext, mensaje_despedida_manual: str
    ) -> str | None:
        """
        Herramienta para decir unas últimas palabras y colgar la llamada.
        Debes proporcionar obligatoriamente el mensaje de despedida — debe ser cálida y breve.
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
            goodbye_l = safe_goodbye.lower()
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
                wait_seconds = float(os.getenv("AGENT_HANGUP_DELAY_SECONDS", "0.15"))
                wait_seconds = max(0.1, min(wait_seconds, 1.0))
                logger.info(f"⏳ Esperando {wait_seconds:.1f}s antes de colgar.")
                await asyncio.sleep(wait_seconds)
            except Exception as say_err:
                logger.error(f"❌ Error diciendo despedida: {say_err}")
                await asyncio.sleep(0.5)
            finally:
                url = f"{self.server_url}/colgar"
                payload = {"nombre_sala": self.room_name}
                try:
                    async with aiohttp.ClientSession() as sess:
                        await sess.post(url, timeout=5, json=payload)
                    logger.info(f"📵 Sala {self.room_name} colgada correctamente.")
                except Exception as hang_err:
                    logger.error(f"❌ Error colgando sala: {hang_err}")

        asyncio.create_task(process_goodbye_and_hangup())
        return "Llamada finalizada."


# ============================================================================
# FUNCIÓN PARA OBTENER LA CONFIGURACIÓN DEL AGENTE DESDE LA API
# ============================================================================
async def fetch_agent_config(survey_id: str, expected_empresa_id: str = "0") -> dict:
    """Consulta la API local para obtener la configuración del agente asignado a esta encuesta."""
    server_url = (
        os.getenv("BRIDGE_SERVER_URL_INTERNAL")
        or os.getenv("BRIDGE_SERVER_URL")
        or "http://127.0.0.1:8001"
    ).rstrip("/")
    # Cache-busting y reintentos cortos para evitar lecturas obsoletas justo después de editar un agente.
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

                        # SELLO DE SEGURIDAD MULTI-TENANT
                        config_empresa_id = str(config.get("empresa_id", "0"))
                        if expected_empresa_id and expected_empresa_id != "0" and config_empresa_id != "0" and expected_empresa_id != config_empresa_id:
                            raise Exception(f"Violación de seguridad Multi-Tenant: El ID de la empresa no coincide. Metadata: {expected_empresa_id}, Config: {config_empresa_id}")

                        logger.info(
                            f"📋 Config FRESH obtenida para survey {survey_id} (attempt {attempt}/{max_attempts}): "
                            f"nombre='{config.get('name')}', modelo='{config.get('llm_model')}', "
                            f"cfg_updated_at='{config.get('config_updated_at')}'"
                        )
                        return config
                    else:
                        logger.warning(
                            f"⚠️ Intento {attempt}/{max_attempts}: no se pudo obtener config (HTTP {resp.status})"
                        )
        except Exception as e:
            logger.warning(
                f"⚠️ Intento {attempt}/{max_attempts}: error obteniendo config de agente: {e}"
            )

        # Pequeño backoff para dar tiempo a propagación de update en edge cases
        if attempt < max_attempts:
            await asyncio.sleep(0.25 * attempt)

    logger.warning("⚠️ No se pudo obtener config fresca tras reintentos. Usando defaults.")
    return {}


# ============================================================================
# FUNCIÓN PARA ENVIAR ALERTAS A N8N
# ============================================================================
async def notify_n8n_alert(message: str, details: dict = None):
    webhook_url = os.getenv("N8N_WEBHOOK_URL_ALERTS")
    if not webhook_url:
        return
    try:
        async with aiohttp.ClientSession() as session:
            payload = {"message": message, "details": details or {}}
            await session.post(webhook_url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"❌ Error sending alert to n8n: {e}")

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
            asyncio.create_task(notify_n8n_alert("Límite de API Alcanzado (Error 429)", {"job_id": job_id, "error": msg}))
        else:
            logger.error(f"⚠️ ERROR DEL AGENTE (Job {job_id}): {error}")
            asyncio.create_task(notify_n8n_alert("Error en Agente LiveKit", {"job_id": job_id, "error": msg}))

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

    if "campana_id" not in meta_data and "client_id" not in meta_data:
        await _safe_reject("metadata sin campana_id/client_id")
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
            if not survey_id.isdigit() and len(parts) >= 2:
                survey_id = parts[-2]
                
            if empresa_id == "0" and len(parts) >= 2 and parts[0] == "empresa":
                empresa_id = parts[1]
            logger.info(f"🔑 [{job_id}] Metadatos extraídos de room_name: empresa={empresa_id}, survey={survey_id}")
        except:
            pass

    # 3. Validación de Identidad Temprana Crítica
    if not str(survey_id).isdigit() or str(survey_id) == "0":
        await _safe_reject(f"Identidad inválida o corrupta: survey_id='{survey_id}'")
        return

    # --- PASO 1.5: Validar Sello Multi-Tenant ANTES de conectar ---
    try:
        # Obtenemos config y validamos que la sala es del mismo tenant que el config
        agent_config = await fetch_agent_config(survey_id, expected_empresa_id=empresa_id)
    except Exception as e:
        if "Violación de seguridad" in str(e):
            await _safe_reject(str(e))
            return
        else:
            logger.warning(f"⚠️ [{job_id}] Error cargando config previa: {e}")
            agent_config = {}

    # --- PASO 2: Conectar a la sala ---
    is_duplicate = False
    try:
        logger.info(f"⏱️ [{job_id}] Intentando conectar a sala {room_name}...")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        
        # --- CONTROL DE DUPLICIDAD ---
        agent_participants = [p for p in ctx.room.remote_participants.values() if getattr(p, 'kind', None) == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT or p.identity.startswith("agent-")]
        if len(agent_participants) > 1: # Ya estamos nosotros (1), si hay más (1+) es que hay otro
            logger.warning(f"⚠️ [{job_id}] Ya un agente en la sala {room_name}. Cancelando duplicado.")
            is_duplicate = True
            return

        logger.info(f"✅ [{job_id}] Conectado a sala {room_name}. Participantes: {len(ctx.room.remote_participants)}")

        # --- PASO 3: Cargar configuración VAD ---
        # min_silence_duration: tiempo mínimo de silencio para detectar fin de turno.
        # 0.25 → responde muy rápido tras silencio. Si el cliente habla poco o entrecortado,
        # sube a 0.4-0.5 para no interrumpir antes de que acabe.
        min_silence_duration = float(os.getenv("AGENT_MIN_SILENCE_SECONDS", "0.5"))
        min_silence_duration = max(0.4, min(min_silence_duration, 0.8))
        vad_model = await asyncio.to_thread(silero.VAD.load, min_silence_duration=min_silence_duration)
        logger.info(f"✅ [{job_id}] VAD y configuración cargados.")

        # --- PASO 4: Crear el asistente ---
        agent_instance = DynamicAgent(room_name=room_name, agent_config=agent_config)
        
        llm_model = agent_config.get("llm_model", "llama-3.3-70b-versatile")
        voice_id = agent_config.get("voice_id", "cefcb124-080b-4655-b31f-932f3ee743de")
        language = agent_config.get("language", "es")
        stt_provider = agent_config.get("stt_provider", "deepgram")
        speaking_speed = agent_config.get("speaking_speed", 1.0)
        
        logger.info(f"🤖 [{job_id}] Config: LLM='{llm_model}', Voice='{voice_id}', Lang='{language}', STT='{stt_provider}', Speed='{speaking_speed}'")

        if language in ["eu", "gl"] or stt_provider == "openai":
            stt_plugin = openai.STT(language=language)
            logger.info("🎙️ Usando STT: OpenAI Whisper")
        else:
            stt_plugin = deepgram.STT(model="nova-3", language=language)
            logger.info("🎙️ Usando STT: Deepgram Nova-3")

        from livekit.agents.llm.fallback_adapter import FallbackAdapter

        # LLM Principal (Groq)
        main_llm = openai.LLM(
            model=llm_model, 
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY"),
            temperature=0.35
        )
        
        # LLM Secundario (OpenAI - gpt-4o-mini)
        fallback_llm = openai.LLM(
            model="gpt-4o-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0.2
        )

        # Usar FallbackAdapter transparente al cliente
        final_llm = FallbackAdapter([main_llm, fallback_llm], attempt_timeout=10.0)

        # --- Crear sesión del agente ---
        # min_endpointing_delay: segundos de espera mínima tras silencio VAD antes de procesar
        # max_endpointing_delay: tope máximo de espera (por defecto 3s → usuario lo notaba como pausa larga)
        # preemptive_generation: empieza a generar respuesta mientras el usuario habla → menos latencia percibida
        endpointing_min = float(os.getenv("AGENT_ENDPOINTING_MIN", "0.5"))
        endpointing_max = float(os.getenv("AGENT_ENDPOINTING_MAX", "1.5"))
        session = AgentSession(
            vad=vad_model,
            stt=stt_plugin,
            llm=final_llm,
            tts=_build_tts_plugin(voice_id=voice_id, language=language, speaking_speed=speaking_speed),
            min_endpointing_delay=endpointing_min,
            max_endpointing_delay=endpointing_max,
            preemptive_generation=True,
            use_tts_aligned_transcript=True,
        )

        await session.start(
            room=ctx.room,
            agent=agent_instance,
        )

        # --- RUIDO DE FONDO DE OFICINA ---
        # Hace que el agente suene como si estuviera en una oficina real.
        # Se puede desactivar con AGENT_OFFICE_NOISE=false en el entorno.
        if os.getenv("AGENT_OFFICE_NOISE", "true").lower() not in ("false", "0", "no"):
            try:
                # Office noise at all times without keyboard interference
                bg_player = BackgroundAudioPlayer(
                    ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.8),
                )
                await bg_player.start(room=ctx.room)
                logger.info(f"🎙️ [{job_id}] Ruido de fondo de oficina activado.")
            except Exception as bg_err:
                logger.warning(f"⚠️ [{job_id}] No se pudo iniciar ruido de fondo: {bg_err}")
        
        # NOTA: on_enter() del DynamicAgent se encarga del saludo.
        # NO llamamos a say_greeting() por separado para evitar doble saludo.
        
        # --- EVENTOS ---
        finished = asyncio.Event()
        stop_guard = asyncio.Event()

        async def ghost_kicker_loop():
            """
            Vigila participantes remotos y expulsa cualquier "agente fantasma" o intruso.
            Permitidos: participante SIP/cliente (user_/sip_).
            """
            allowed_prefixes = ("user_", "sip_")
            while not stop_guard.is_set():
                try:
                    for p in list(ctx.room.remote_participants.values()):
                        identity = getattr(p, "identity", "") or ""
                        if identity.startswith(allowed_prefixes):
                            continue

                        # Cualquier otro participante remoto se considera intruso.
                        logger.warning(f"👻 [{job_id}] Intruso detectado en sala {room_name}: '{identity}'. Expulsando...")
                        try:
                            await lkapi.room.remove_participant(
                                api.RoomParticipantIdentity(room=room_name, identity=identity)
                            )
                            logger.info(f"✅ [{job_id}] Intruso '{identity}' expulsado de {room_name}")
                        except Exception as kick_err:
                            logger.error(f"❌ [{job_id}] Error expulsando intruso '{identity}': {kick_err}")
                except Exception as guard_err:
                    logger.error(f"⚠️ [{job_id}] Error en ghost kicker: {guard_err}")

                await asyncio.sleep(2)

        ghost_guard_task = asyncio.create_task(ghost_kicker_loop())

        async def backchanneling_loop():
            """
            Backchanneling humano:
            - Si el usuario habla largo (>5s sin respuesta del agente), inserta una
              señal breve de escucha activa para sonar más natural.
            - Cooldown generoso para no interrumpir en exceso.
            """
            pending_user_idx = None
            pending_since = None
            last_backchannel_at = 0.0
            cooldown_seconds = 14.0
            trigger_seconds = 5.0
            loop = asyncio.get_running_loop()
            # Fillers variados — mezcla de señales de escucha activa y microconfirmaciones
            fillers = [
                "Entiendo...",
                "Sí, claro.",
                "Ya veo...",
                "Ajá, sí.",
                "Mhm, le escucho.",
                "Sí, sigo con usted.",
                "Perfecto, adelante.",
                "Claro, dígame.",
            ]

            while not stop_guard.is_set():
                try:
                    chat_ctx = getattr(session, "chat_ctx", getattr(session, "chat_context", None))
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
                    now = loop.time()

                    if last_role == "user" and len(last_content) >= 25:
                        if pending_user_idx != last_idx:
                            pending_user_idx = last_idx
                            pending_since = now

                        if (
                            pending_since is not None
                            and (now - pending_since) >= trigger_seconds
                            and (now - last_backchannel_at) >= cooldown_seconds
                        ):
                            try:
                                await session.say(random.choice(fillers), allow_interruptions=True)
                                last_backchannel_at = now
                            except Exception as be:
                                logger.debug(f"[{job_id}] Backchannel no enviado: {be}")
                            finally:
                                pending_since = None
                    else:
                        pending_user_idx = None
                        pending_since = None
                except Exception as e:
                    logger.debug(f"[{job_id}] Error en backchannel loop: {e}")

                await asyncio.sleep(0.7)

        backchannel_task = asyncio.create_task(backchanneling_loop())

        # ---------- SNAPSHOT DE TRANSCRIPCIÓN ----------
        # Guardamos el snapshot en cuanto el cliente cuelga para no depender
        # del chat_ctx que LiveKit puede limpiar antes del bloque finally.
        transcript_snapshot: dict = {"transcript": "", "raw": []}
        transcript_event_buffer: list[dict] = []

        def _append_transcript_event(role: str, content: str):
            text = _normalize_message_text(content)
            if role not in ("user", "assistant") or not text:
                return
            if transcript_event_buffer:
                last = transcript_event_buffer[-1]
                if last.get("role") == role and _normalize_message_text(last.get("content")) == text:
                    return
            transcript_event_buffer.append({"role": role, "content": text})

        def _build_transcript_from_event_buffer() -> tuple[list[dict], str]:
            if not transcript_event_buffer:
                return [], ""
            lines = []
            raw = []
            for item in transcript_event_buffer:
                role = item.get("role")
                content = _normalize_message_text(item.get("content"))
                if role not in ("user", "assistant") or not content:
                    continue
                raw.append({"role": role, "content": content})
                lines.append(f"{'Cliente' if role == 'user' else 'Agente'}: {content}")
            return raw, ("\n".join(lines).strip() + ("\n" if lines else ""))

        async def _save_transcript_snapshot(reason: str = "auto"):
            """Extrae y persiste la transcripción actual en Supabase."""
            try:
                raw, t = _extract_transcript_from_session(session)
                if not t:
                    raw, t = _build_transcript_from_event_buffer()
                logger.info(f"📝 [{job_id}] Snapshot transcripción ({reason}): {len(t)} chars, {len(raw)} mensajes")
                if t:
                    transcript_snapshot["transcript"] = t
                    transcript_snapshot["raw"] = raw
                    _internal = (
                        getattr(agent_instance, "server_url", None)
                        or os.getenv("BRIDGE_SERVER_URL_INTERNAL")
                        or os.getenv("BRIDGE_SERVER_URL")
                        or "http://127.0.0.1:8001"
                    ).rstrip("/")
                    async with aiohttp.ClientSession() as _http:
                        _resp = await _http.post(
                            f"{_internal}/guardar-encuesta",
                            json={"id_encuesta": int(survey_id) if str(survey_id).isdigit() else 0,
                                  "transcription": t},
                            timeout=8,
                        )
                        logger.info(f"✅ [{job_id}] Transcripción snapshot guardada ({reason}): HTTP {_resp.status}")
            except Exception as _e:
                logger.warning(f"⚠️ [{job_id}] Error guardando snapshot transcripción ({reason}): {_e}")

        async def transcript_autosave_loop():
            """Guarda la transcripción parcial cada 40s durante la llamada."""
            await asyncio.sleep(30)
            while not stop_guard.is_set():
                await _save_transcript_snapshot("autosave-30s")
                await asyncio.sleep(40)

        transcript_autosave_task = asyncio.create_task(transcript_autosave_loop())

        # ---------- LOOP DE SILENCIO / REPROMPT ----------
        # Híbrido: eventos de conversación + watchdog por tiempo.
        SILENCE_REPROMPT_DELAY = float(os.getenv("AGENT_SILENCE_REPROMPT_SECONDS", "7.0"))
        reprompt_phrases = [
            "¿Sigue ahí?",
            "Perdone, ¿me escucha?",
            "Disculpe, ¿puede responderme?",
            "¿Está usted disponible?",
            "Si le parece, seguimos con la siguiente pregunta.",
        ]
        reprompt_phrases_lc = {p.lower() for p in reprompt_phrases}
        reprompt_state = {
            "last_assistant_at": 0.0,
            "last_user_at": 0.0,
            "waiting_user": False,
            "reprompt_count": 0,
        }
        loop_obj = asyncio.get_running_loop()

        @session.on("user_input_transcribed")
        def _on_user_input_transcribed(ev):
            try:
                content = _normalize_message_text(getattr(ev, "transcript", ""))
                is_final = bool(getattr(ev, "is_final", True))
                if not content or not is_final:
                    return

                _append_transcript_event("user", content)
                now = loop_obj.time()
                reprompt_state["last_user_at"] = now
                reprompt_state["waiting_user"] = False
                reprompt_state["reprompt_count"] = 0
            except Exception as ev_err:
                logger.debug(f"[{job_id}] Error evento user_input_transcribed: {ev_err}")

        @session.on("conversation_item_added")
        def _on_conversation_item_added(ev):
            try:
                item = getattr(ev, "item", None)
                role = getattr(item, "role", "")
                content = _normalize_message_text(getattr(item, "content", None))
                if role not in ("user", "assistant") or not content:
                    return

                now = loop_obj.time()
                lower = content.strip().lower()

                if role == "assistant":
                    # Evitar que nuestros reprompts reinicien el ciclo indefinidamente
                    if lower in reprompt_phrases_lc:
                        return
                    _append_transcript_event("assistant", content)
                    reprompt_state["last_assistant_at"] = now
                    reprompt_state["waiting_user"] = True
                    reprompt_state["reprompt_count"] = 0
                else:
                    _append_transcript_event("user", content)
                    reprompt_state["last_user_at"] = now
                    reprompt_state["waiting_user"] = False
                    reprompt_state["reprompt_count"] = 0
            except Exception as ev_err:
                logger.debug(f"[{job_id}] Error evento conversation_item_added: {ev_err}")

        @session.on("agent_state_changed")
        def _on_agent_state_changed(ev):
            try:
                new_state = str(getattr(ev, "new_state", "")).lower()
                old_state = str(getattr(ev, "old_state", "")).lower()
                now = loop_obj.time()
                # Cuando termina de hablar/pensar y vuelve a escuchar, esperamos respuesta humana.
                if new_state == "listening" and old_state in ("speaking", "thinking"):
                    reprompt_state["last_assistant_at"] = now
                    reprompt_state["waiting_user"] = True
            except Exception as ev_err:
                logger.debug(f"[{job_id}] Error evento agent_state_changed: {ev_err}")

        async def silence_reprompt_loop():
            # Bootstrap: después del saludo inicial, si no hay respuesta humana, reconducir.
            reprompt_state["last_assistant_at"] = loop_obj.time()
            reprompt_state["waiting_user"] = True

            while not stop_guard.is_set():
                await asyncio.sleep(0.25)
                try:
                    now = loop_obj.time()
                    if not reprompt_state["waiting_user"]:
                        continue

                    assistant_silent_for = now - float(reprompt_state["last_assistant_at"])
                    user_silent_for = now - float(reprompt_state["last_user_at"])
                    can_reprompt = reprompt_state["reprompt_count"] < 3

                    if (
                        assistant_silent_for >= SILENCE_REPROMPT_DELAY
                        and user_silent_for >= SILENCE_REPROMPT_DELAY
                        and can_reprompt
                    ):
                        reprompt_state["reprompt_count"] += 1
                        reprompt_state["last_assistant_at"] = now
                        try:
                            await session.say(random.choice(reprompt_phrases), allow_interruptions=True)
                            logger.info(f"🔁 [{job_id}] Reprompt por silencio enviado (#{reprompt_state['reprompt_count']})")
                        except Exception as _re:
                            logger.debug(f"[{job_id}] Reprompt no enviado: {_re}")
                except Exception as _e:
                    logger.debug(f"[{job_id}] Error en silence_reprompt_loop: {_e}")

        silence_reprompt_task = asyncio.create_task(silence_reprompt_loop())

        @ctx.room.on("disconnected")
        def on_disconnect():
            logger.info(f"🔌 [{job_id}] Desconectado.")
            finished.set()

        @ctx.room.on("participant_disconnected")
        def on_participant_disconnected(participant: rtc.RemoteParticipant):
            if not participant.identity.startswith("agent-"):
                logger.info(f"[{job_id}] Cliente se desconectó. Guardando transcripción y terminando sala.")
                async def disconnect_tasks():
                    # 1. Guardar transcripción ANTES de que LiveKit limpie la sesión
                    await _save_transcript_snapshot("client-hangup")
                    # 2. Colgar la sala
                    url = f"{agent_instance.server_url}/colgar"
                    try:
                        async with aiohttp.ClientSession() as http_sess:
                            await http_sess.post(url, timeout=5, json={"nombre_sala": room_name})
                    except:
                        pass
                asyncio.create_task(disconnect_tasks())

        # Kill switch: si la sala no se cierra en 10 minutos, forzamos la desconexión
        # para evitar workers zombi que consumen recursos indefinidamente.
        CALL_TIMEOUT_SECONDS = int(os.getenv("AGENT_CALL_TIMEOUT_SECONDS", "600"))
        try:
            await asyncio.wait_for(finished.wait(), timeout=CALL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error(
                f"🚨 [{job_id}] KILL SWITCH: Timeout de seguridad ({CALL_TIMEOUT_SECONDS}s) alcanzado. "
                f"Forzando desconexión del worker para sala '{room_name}'."
            )
            try:
                await ctx.room.disconnect()
            except Exception as disc_err:
                logger.warning(f"[{job_id}] Error al forzar desconexión: {disc_err}")
            # finished.set() asegura que el bloque finally no quede bloqueado
            finished.set()

    
    except Exception as e:
        handle_error(e)
    
    finally:
        try:
            if 'stop_guard' in locals():
                stop_guard.set()
            if 'ghost_guard_task' in locals():
                ghost_guard_task.cancel()
            if 'backchannel_task' in locals():
                backchannel_task.cancel()
            if 'transcript_autosave_task' in locals():
                transcript_autosave_task.cancel()
            if 'silence_reprompt_task' in locals():
                silence_reprompt_task.cancel()
        except Exception:
            pass

        if not is_duplicate:
            logger.info(f"--- 🏁 FIN DE SESIÓN AGENTE (Job: {job_id}, Room: {room_name}, Survey: {survey_id}) ---")
            agent_instance_exists = 'agent_instance' in locals()
            data_saved = getattr(agent_instance, 'data_saved', False) if agent_instance_exists else False
            
            try:
                # Guardados post-llamada deben ir al mismo backend accesible desde este worker
                internal_api_url = (
                    getattr(agent_instance, "server_url", None)
                    or os.getenv("BRIDGE_SERVER_URL_INTERNAL")
                    or os.getenv("BRIDGE_SERVER_URL")
                    or "http://127.0.0.1:8001"
                ).rstrip("/")
            
                raw_messages = []
                transcript = ""
                try:
                    # Intentar extraer transcripción fresca; si session ya está limpia,
                    # usar el snapshot guardado en on_participant_disconnected.
                    if 'session' in locals():
                        raw_messages, transcript = _extract_transcript_from_session(session)
                        logger.info(f"📝 [{job_id}] Transcripción extraída en finally: {len(transcript)} chars")

                    # Fallback 1: buffer de eventos en tiempo real (más fiable en desconexiones bruscas)
                    if not transcript and 'transcript_event_buffer' in locals():
                        raw_messages, transcript = _build_transcript_from_event_buffer()
                        if transcript:
                            logger.info(f"📝 [{job_id}] Usando buffer de eventos: {len(transcript)} chars")

                    # Fallback 2: snapshot previo en memoria
                    if not transcript and 'transcript_snapshot' in locals() and transcript_snapshot.get("transcript"):
                        transcript = transcript_snapshot["transcript"]
                        raw_messages = transcript_snapshot.get("raw", [])
                        logger.info(f"📝 [{job_id}] Usando snapshot de transcripción: {len(transcript)} chars")
                except Exception as ex:
                    logger.error(f"Error procesando historia para transcripción local: {ex}")
                    if not transcript and 'transcript_event_buffer' in locals():
                        raw_messages, transcript = _build_transcript_from_event_buffer()
                    if not transcript and 'transcript_snapshot' in locals() and transcript_snapshot.get("transcript"):
                        transcript = transcript_snapshot["transcript"]
                        raw_messages = transcript_snapshot.get("raw", [])
                
                # SIEMPRE guardar transcripción y datos finales en Supabase
                url_guardar = f"{internal_api_url}/guardar-encuesta"
            
                # Analytics post-llamada: Clasificar disposición + extraer datos
                agent_type = agent_config.get("agent_type", "ENCUESTA_NUMERICA")
                datos_extra = None
                call_disposition = None  # El LLM determinará: completada, parcial, rechazada, no_contesta
            
                if transcript:
                    logger.info(f"🧠 Clasificando disposición de llamada y extrayendo datos para encuesta {survey_id} (Tipo: {agent_type})")
                    try:
                        # Prompt de clasificación de disposición universal
                        disposition_prompt = (
                            "Eres un analista experto en llamadas telefónicas comerciales. "
                            "Analiza la transcripción y responde ÚNICAMENTE con JSON válido con estos campos:\n\n"
                            "1. 'disposicion': OBLIGATORIO. Clasifica la llamada en exactamente UNO de estos valores:\n"
                            "   - 'completada': El cliente respondió a todas o casi todas las preguntas/objetivos de la llamada.\n"
                            "   - 'parcial': El cliente contestó la llamada y respondió a ALGUNAS preguntas, pero colgó o se interrumpió antes de terminar.\n"
                            "   - 'rechazada': El cliente contestó pero rechazó participar (dijo 'no me interesa', 'no tengo tiempo', 'quitadme de la lista', etc.).\n"
                            "   - 'no_contesta': La llamada fue contestada por un buzón de voz, contestador automático, o no hubo interacción humana real.\n\n"
                        )
                    
                        # Prompt especifico por tipo de agente para datos_extra
                        if agent_type == "CUALIFICACION_LEAD":
                            disposition_prompt += (
                                "2. 'lead_cualificado' (booleano): ¿El lead cumple los criterios de cualificación?\n"
                                "3. 'interes' (string: 'alto', 'medio', 'bajo'): Nivel de interés detectado.\n"
                                "4. 'motivo_rechazo' (string o null): Razón por la que no cualifica o rechaza.\n"
                            )
                        elif agent_type == "AGENDAMIENTO_CITA":
                            disposition_prompt += (
                                "2. 'cita_agendada' (booleano): ¿Se agendó una cita?\n"
                                "3. 'fecha_cita' (string formato libre o null): Fecha/hora acordada.\n"
                                "4. 'disponibilidad' (string o null): Resumen de cuándo está disponible.\n"
                            )
                        elif agent_type != "ENCUESTA_NUMERICA":
                            disposition_prompt += (
                                "2. 'puntos_clave' (array de strings): Los 3 puntos más importantes de la conversación.\n"
                            )
                        else:
                            # Para encuesta numérica no necesitamos datos extra del LLM
                            disposition_prompt += "No incluyas campos adicionales para encuesta numérica.\n"
                    
                        groq_api_key = os.getenv("GROQ_API_KEY")
                        if groq_api_key:
                            async with aiohttp.ClientSession() as llm_sess:
                                headers = {
                                    "Authorization": f"Bearer {groq_api_key}",
                                    "Content-Type": "application/json"
                                }
                                payload_llm = {
                                    "model": "llama-3.3-70b-versatile",
                                    "messages": [
                                        {"role": "system", "content": disposition_prompt},
                                        {"role": "user", "content": f"Transcripción:\n{transcript}"}
                                    ],
                                    "response_format": {"type": "json_object"},
                                    "temperature": 0.1
                                }
                                async with llm_sess.post("https://api.groq.com/openai/v1/chat/completions", json=payload_llm, headers=headers, timeout=20) as llm_resp:
                                    if llm_resp.status == 200:
                                        llm_data = await llm_resp.json()
                                        json_str = llm_data["choices"][0]["message"]["content"]
                                        parsed = json.loads(json_str)
                                    
                                        # Extraer disposición del JSON
                                        call_disposition = parsed.pop("disposicion", None)
                                        valid_dispositions = ("completada", "parcial", "rechazada", "no_contesta")
                                        if call_disposition not in valid_dispositions:
                                            call_disposition = "completada" if data_saved else "parcial"
                                    
                                        # El resto del JSON son datos_extra
                                        if parsed:
                                            datos_extra = parsed
                                    
                                        logger.info(f"✅ Disposición: {call_disposition} | datos_extra: {datos_extra}")
                                    else:
                                        logger.error(f"Error HTTP del LLM al clasificar: {llm_resp.status}")
                    except Exception as e:
                        logger.error(f"Error clasificando disposición con LLM: {e}")
                else:
                    # Sin transcripción = no hubo interacción (buzón, timeout, SIP error)
                    call_disposition = "no_contesta"
                    logger.info(f"📵 Sin transcripción para encuesta {survey_id} → disposición: no_contesta")

                # Determinar status final
                if not call_disposition:
                    call_disposition = "completada" if data_saved else "parcial"
            
                try:
                    if data_saved:
                        # El LLM ya guardó notas numéricas, pero guardamos transcripción + disposición + datos_extra
                        logger.info(f"📝 Guardando transcripción/disposición/datos_extra para encuesta {survey_id} (datos numéricos ya guardados por tool)")
                        # No sobrescribimos status cuando la tool ya guardó estado/notas.
                        # Aquí solo persistimos transcripción y extras.
                        transcript_payload = {
                            "id_encuesta": int(survey_id) if str(survey_id).isdigit() else 0,
                            "transcription": transcript,
                            "datos_extra": datos_extra
                        }
                        try:
                            async with aiohttp.ClientSession() as sess:
                                async with sess.post(url_guardar, json=transcript_payload, timeout=10) as resp:
                                    logger.info(f"✅ Extras guardados: HTTP {resp.status}")
                        except Exception as save_err:
                            logger.error(f"Error guardando extras: {save_err}")
                    else:
                        # No se guardaron datos numéricos → fallback completo con disposición del LLM
                        logger.warning(f"⚠️ La sesión terminó sin guardar datos explícitos por tool (Survey ID: {survey_id}) → Disposición: {call_disposition}")
                        fallback_payload = {
                            "id_encuesta": int(survey_id) if str(survey_id).isdigit() else 0,
                            "transcription": transcript,
                            "status": call_disposition,
                            "comentarios": "Llamada finalizada sin interacción" if call_disposition == "no_contesta" else f"Llamada {call_disposition} via post-call",
                            "datos_extra": datos_extra
                        }
                        try:
                            async with aiohttp.ClientSession() as sess:
                                async with sess.post(url_guardar, json=fallback_payload, timeout=10) as resp:
                                    logger.info(f"✅ Fallback guardado (disposición: {call_disposition}): HTTP {resp.status}")
                        except Exception as save_err:
                            logger.error(f"Error en guardado final de fallback: {save_err}")
                except Exception as ex:
                     logger.error(f"❌ Error salvando datos finales: {ex}")
            except Exception as fatal_post:
                logger.error(f"🚨 [{job_id}] EXCEPCIÓN FATAL NO CAPTURADA en post-procesamiento (finally): {fatal_post}")
        else:
            logger.info(f"--- 🏁 FIN DE SESIÓN DUPLICADA (Job: {job_id}) - Saliendo sin reportar datos ---")

if __name__ == "__main__":
    cli.run_app(server)