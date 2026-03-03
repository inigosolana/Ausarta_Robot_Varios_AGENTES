import logging
from typing import Optional
import os
import aiohttp
import asyncio
import sys
from dotenv import load_dotenv
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
    AutoSubscribe
)
from livekit.plugins import (
    noise_cancellation,
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

# ============================================================================
# INSTRUCCIONES BASE - Se combinan con las instrucciones específicas del agente
# ============================================================================
BASE_RULES = """
REGLAS DE ORO (¡MUY IMPORTANTE!):
1. IDENTIDAD: Si te preguntan quién eres o cómo te llamas, preséntate con el nombre de la empresa para la que trabajas. NUNCA reveles nombres internos de sistema.
2. PROHIBIDO NARRAR ACCIONES: NUNCA digas en voz alta que vas a guardar un dato, NUNCA menciones el "ID de la encuesta", y NUNCA leas comandos de sistema. Habla SOLO como una persona normal.
3. PRONUNCIACIÓN: Di siempre "UNO" (ej: "del UNO al diez"), nunca "un".
4. PARA COLGAR: Usa SIEMPRE la herramienta 'finalizar_llamada' proporcionando el texto de despedida que quieras decir (ej: "Muchas gracias por su llamada, adiós"). La herramienta se encargará de decirlo y colgar. 
5. SI EL CLIENTE NO TE ENTIENDE O DICE "¿CÓMO?", "¿QUÉ?": Repite la última pregunta que hiciste de forma amable y clara.
6. SI ESCUCHAS RUIDO O UNA PALABRA SIN SENTIDO: Ignóralo o di "Disculpe, no le he escuchado bien, ¿me lo puede repetir?" si persiste.
7. VALIDACIÓN DE NOTAS: Si el usuario te da un número menor a 1 o mayor a 10 (ej: 0, 11), NO guardes el dato. Di "Disculpe, la nota debe ser entre 1 y 10. ¿Qué nota le daría?" y espera su respuesta.

REGLA CRÍTICA DE DESPEDIDA:
Cuando termines la interacción, llama a 'finalizar_llamada' con tu mensaje de despedida. No lo digas antes en el texto normal, la herramienta lo hará por ti para asegurar que no se corte.

EXCEPCIÓN - BUZÓN DE VOZ / FUERA DE COBERTURA:
- Si escuchas "fuera de cobertura", "móvil apagado", "buzón de voz", "contestador", "terminado el tiempo de grabación" o mensajes automáticos similares:
  - Usa 'guardar_encuesta' (status='failed').
  - Usa 'finalizar_llamada' (mensaje_despedida_manual="Buzón de voz detectado, finalizando.").

EXCEPCIÓN INTERRUPCIÓN/COLGAR:
- Usa 'guardar_encuesta' (status='incomplete').
- Usa 'finalizar_llamada' (mensaje_despedida_manual="Entiendo, que tenga un buen día. Adiós.").

NOTA FINAL: UNA VEZ LLAMES A 'finalizar_llamada', LA CONVERSACIÓN HA TERMINADO. NO RESPONDAS A NADA MÁS.
"""


class DynamicAgent(Agent):
    """Agente dinámico que carga sus instrucciones desde Supabase."""
    
    def __init__(self, room_name: str, agent_config: dict) -> None:
        self.server_url = os.getenv("BRIDGE_SERVER_URL", "http://127.0.0.1:8001")
        self.data_saved = False
        self.room_name = room_name
        self.agent_config = agent_config
        self.greeting = agent_config.get("greeting", "Buenas, ¿tiene un momento?")
        
        try:
            parts = room_name.split('_')
            if len(parts) >= 2 and parts[0] == "encuesta":
                self.survey_id = parts[1]
            else:
                self.survey_id = parts[-1]
        except:
            self.survey_id = "0"

        # Combinar las instrucciones específicas del agente con las reglas base
        agent_instructions = agent_config.get("instructions", "Eres un asistente virtual.")
        agent_name = agent_config.get("name", "Bot")
        
        base_rules_to_use = BASE_RULES
        inst_lower = agent_instructions.lower()
        has_preguntas = "pregunta 1" in inst_lower or "pregunta 2" in inst_lower or "pregunta:" in inst_lower
        is_numeric = "1 al 10" in inst_lower or "del uno al diez" in inst_lower or "numérica" in inst_lower or "puntuación" in inst_lower
        if has_preguntas and not is_numeric:
            base_rules_to_use += """
REGLA ESPECIAL PARA CUESTIONARIOS ABIERTOS:
- Como este es un cuestionario de preguntas abiertas, USA el campo 'comentarios' de la herramienta 'guardar_encuesta' para guardar todas las respuestas de las preguntas planteadas recopiladas en forma de texto descriptivo.
- IGNORA la regla estructurada de "Validación de notas de 1 al 10" si no aplica a tus preguntas.
"""
            # Add "tienes un minuto" to the greeting if not already present
            greet_lower = self.greeting.lower()
            if "minuto" not in greet_lower:
                self.greeting = f"{self.greeting.strip()} ¿Tienes un minuto para responder unas preguntas?"
        
        full_instructions = f"""{agent_instructions}

DATOS TÉCNICOS (INVISIBLES PARA EL CLIENTE):
- SALA ACTUAL: '{room_name}'
- ID DE LA ENCUESTA: {self.survey_id}
- NOMBRE DEL AGENTE (INTERNO, NO DECIR AL CLIENTE): {agent_name}

{base_rules_to_use}
"""

        critical_rules = agent_config.get("critical_rules")
        if critical_rules:
            full_instructions += f"\n🚨 REGLAS CRÍTICAS ADICIONALES (¡CUMPLIR A RAJA TABLA!):\n{critical_rules}\n"

        super().__init__(instructions=full_instructions)
        logger.info(f"🤖 Agente '{agent_name}' creado con instrucciones dinámicas (Survey: {self.survey_id})")

    async def on_enter(self):
        """Método para manejar la entrada a la sala. 
        Se llama explícitamente desde el entrypoint para evitar duplicidad."""
        logger.info(f"🎤 Agente entrando en acción para Survey ID: {self.survey_id}")
        
        # Pausa de cortesía: 1.5 segundos para que la red telefónica se estabilice
        await asyncio.sleep(1.5)
        
        # Solo generamos el saludo si el LLM no ha empezado ya
        await self.session.generate_reply(
            instructions=f"Di exactamente: '{self.greeting}' y espera la respuesta del usuario.",
            allow_interruptions=False
        )

    async def _fire_and_forget_save(self, url, payload):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=2) as resp:
                    logger.info(f"✅ (Background) Guardado ID {payload.get('id_encuesta')}: {payload}")
        except Exception as e:
            logger.error(f"❌ (Background) Error: {e}")

    @function_tool(name="guardar_encuesta")
    async def _http_tool_guardar_encuesta(
        self, 
        context: RunContext, 
        id_encuesta: int, 
        nota_comercial: Optional[int] = None, 
        nota_instalador: Optional[int] = None, 
        nota_rapidez: Optional[int] = None, 
        comentarios: Optional[str] = None,
        status: Optional[str] = None
    ) -> str | None:
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
        
        asyncio.create_task(self._fire_and_forget_save(url, payload))
        return "Dato guardado."

    @function_tool(name="finalizar_llamada")
    async def _http_tool_finalizar_llamada(
        self, context: RunContext, mensaje_despedida_manual: str
    ) -> str | None:
        """
        Herramienta para decir unas últimas palabras y colgar la llamada.
        Debes proporcionar obligatoriamente el mensaje de despedida.
        """
        logger.info(f"🗣️ Forzando despedida: {mensaje_despedida_manual}")
        
        # 1. Forzar al agente a decir el mensaje de despedida de forma inmediata y sin interrupciones
        asyncio.create_task(self.session.generate_reply(
            instructions=f"Di exactamente: '{mensaje_despedida_manual}' y no digas nada más.",
            allow_interruptions=False
        ))
        
        # 2. Programar el cuelgue físico de la sala con un margen mayor
        async def delayed_hangup():
            wait_time = 8.0 # Aumentado a 8s para asegurar que se escuche todo
            logger.info(f"⏳ Esperando {wait_time}s para asegurar despedida en {self.room_name}...")
            await asyncio.sleep(wait_time) 
            url = f"{self.server_url}/colgar"
            payload = {"nombre_sala": self.room_name}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, timeout=5, json=payload) as resp:
                        logger.info(f"✂️ COLGANDO: {self.room_name}")
            except Exception as e:
                logger.error(f"Error Colgar: {e}")
                
        asyncio.create_task(delayed_hangup())
        return "Llamada finalizándose. Despidiéndome..."


# ============================================================================
# FUNCIÓN PARA OBTENER LA CONFIGURACIÓN DEL AGENTE DESDE LA API
# ============================================================================
async def fetch_agent_config(survey_id: str) -> dict:
    """Consulta la API local para obtener la configuración del agente asignado a esta encuesta."""
    server_url = os.getenv("BRIDGE_SERVER_URL", "http://127.0.0.1:8001")
    url = f"{server_url}/api/agent_config_by_survey/{survey_id}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    config = await resp.json()
                    logger.info(f"📋 Config de agente obtenida para survey {survey_id}: nombre='{config.get('name')}', modelo='{config.get('llm_model')}'")
                    return config
                else:
                    logger.warning(f"⚠️ No se pudo obtener config de agente (HTTP {resp.status}). Usando defaults.")
                    return {}
    except Exception as e:
        logger.warning(f"⚠️ Error obteniendo config de agente: {e}. Usando defaults.")
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

@server.rtc_session()
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

    # --- PASO 1: Extraer survey_id ---
    survey_id = "0"
    try:
        parts = room_name.split('_')
        if len(parts) >= 2 and parts[0] == "encuesta":
            survey_id = parts[1]
        else:
            survey_id = parts[-1]
    except:
        survey_id = "0"

    # --- PASO 2: Conectar a la sala ---
    try:
        logger.info(f"⏱️ [{job_id}] Conectando a sala...")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        
        # --- CONTROL DE DUPLICIDAD ---
        # Si ya hay otro agente (nosotros mismos u otra instancia) como participante, salimos.
        # LiveKit suele tener al agente como un participante de tipo AGENT.
        agent_participants = [p for p in ctx.room.remote_participants.values() if getattr(p, 'kind', None) == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT or p.identity.startswith("agent-")]
        if len(agent_participants) > 0:
            logger.warning(f"⚠️ [{job_id}] Ya hay un agente en la sala {room_name} ({agent_participants[0].identity}). Cancelando esta instancia para evitar doble voz.")
            return

        logger.info(f"✅ [{job_id}] Conectado (Instancia única).")

        # --- PASO 3: Cargar config ---
        vad_task = asyncio.to_thread(silero.VAD.load, min_silence_duration=0.5)
        config_task = fetch_agent_config(survey_id)
        
        vad_model, agent_config = await asyncio.gather(vad_task, config_task)
        logger.info(f"✅ [{job_id}] VAD y configuración cargados.")

        # --- PASO 4: Crear el agente ---
        agent_instance = DynamicAgent(room_name=room_name, agent_config=agent_config)
        
        llm_model = agent_config.get("llm_model", "llama-3.3-70b-versatile")
        voice_id = agent_config.get("voice_id", "cefcb124-080b-4655-b31f-932f3ee743de")
        language = agent_config.get("language", "es")
        stt_provider = agent_config.get("stt_provider", "deepgram")
        
        logger.info(f"🤖 [{job_id}] Config: LLM='{llm_model}', Voice='{voice_id}', Lang='{language}', STT='{stt_provider}'")

        if language in ["eu", "gl"] or stt_provider == "openai":
            # Deepgram Nova-3 no soporta Euskera ni Gallego, forzamos OpenAI
            if language in ["eu", "gl"] and stt_provider == "deepgram":
                logger.warning(f"⚠️ Idioma '{language}' no soportado por Deepgram STT en Nova-3. Usando OpenAI como fallback.")
            stt_plugin = openai.STT(language=language)
            logger.info("🎙️ Usando STT: OpenAI Whisper")
        else:
            stt_plugin = deepgram.STT(model="nova-3", language=language)
            logger.info("🎙️ Usando STT: Deepgram Nova-3")

        session = AgentSession(
            stt=stt_plugin,
            llm=openai.LLM(
                model=llm_model, 
                base_url="https://api.groq.com/openai/v1",
                api_key=os.getenv("GROQ_API_KEY"),
                temperature=0.1
            ),
            tts=cartesia.TTS(
                model="sonic-multilingual",
                voice=voice_id,
                language=language
            ),
            vad=vad_model,
            preemptive_generation=False,
        )

        @session.on("user_speech_committed")
        def on_user_speech(msg: stt.SpeechEvent):
            logger.info(f"🗣️ [{job_id}] USUARIO: {msg.alternatives[0].text}")
        
        finished = asyncio.Event()

        @ctx.room.on("disconnected")
        def on_disconnect():
            logger.info(f"🔌 [{job_id}] Desconectado.")
            finished.set()

        @ctx.room.on("participant_disconnected")
        def on_participant_disconnected(participant: rtc.RemoteParticipant):
            logger.info(f"[{job_id}] Participante {participant.identity} se desconectó.")
            if not participant.identity.startswith("agent-"):
                logger.info(f"[{job_id}] O Cliente se fue de la sala {room_name}. Procediendo a colgar la sala completamente.")
                # Llamar API para destruir sala directamente, el servidor cortará a este agente de inmediato.
                async def force_hangup_room():
                    url = f"{agent_instance.server_url}/colgar"
                    try:
                         async with aiohttp.ClientSession() as http_sess:
                             await http_sess.post(url, timeout=5, json={"nombre_sala": room_name})
                    except Exception as he:
                         logger.error(f"Error forzando cuelgue: {he}")
                asyncio.create_task(force_hangup_room())

        # Iniciar sesión
        await session.start(agent=agent_instance, room=ctx.room)
        
        # --- SALUDO CONTROLADO ---
        # Llamamos a on_enter explícitamente para asegurar que el agente salude una vez
        asyncio.create_task(agent_instance.on_enter())

        # Sonido ambiente deshabilitado para evitar eco e interferencias con SIP
        # background_audio = BackgroundAudioPlayer(
        #     ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.05),
        # )
        # await background_audio.start(room=ctx.room, agent_session=session)
        
        await finished.wait()
    
    except Exception as e:
        handle_error(e)
    
    finally:
        logger.info(f"--- 🏁 FIN DE SESIÓN AGENTE (Job: {job_id}) ---")
        data_saved = getattr(agent_instance, 'data_saved', False) if 'agent_instance' in dir() else False
        
        transcript = ""
        try:
            if 'session' in dir():
                for m in session.chat_ctx.messages:
                    if m.role == "user" and m.content:
                        transcript += f"Cliente: {m.content}\n"
                    elif m.role == "assistant" and m.content:
                        transcript += f"Agente: {m.content}\n"
        except Exception as ex:
            logger.error(f"Error generando transcripción: {ex}")
            
        try:
            fallback_payload = {
                "id_encuesta": int(survey_id) if str(survey_id).isdigit() else 0,
                "transcription": transcript,
            }
            if not data_saved:
                logger.warning(f"⚠️ La sesión terminó sin guardar datos (Survey ID: {survey_id}). Marcando como 'unreached'...")
                fallback_payload["status"] = "unreached"
                fallback_payload["comentarios"] = "Llamada finalizada sin datos (Posible No Contesta / Cuelgue inmediato)"
                
            server_url = os.getenv("BRIDGE_SERVER_URL", "http://127.0.0.1:8001")
            async def do_final_save():
                async with aiohttp.ClientSession() as sess:
                    url = f"{server_url}/guardar-encuesta"
                    async with sess.post(url, json=fallback_payload, timeout=5) as r:
                         logger.info(f"✅ Transcripción y datos finales guardados")
            asyncio.create_task(do_final_save())
        except Exception as ex:
             logger.error(f"❌ Error salvando fallback/transcripción: {ex}")

if __name__ == "__main__":
    cli.run_app(server)