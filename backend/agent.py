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
4. PARA COLGAR: Siempre PRIMERO di el texto de despedida en voz alta, ESPERA a que termine de sonar, y DESPUÉS usa 'finalizar_llamada'. NUNCA llames a 'finalizar_llamada' sin haber dicho la despedida ANTES.
5. SI EL CLIENTE NO TE ENTIENDE O DICE "¿CÓMO?", "¿QUÉ?": Repite la última pregunta que hiciste de forma amable y clara.
6. SI ESCUCHAS RUIDO O UNA PALABRA SIN SENTIDO: Di "Disculpe, no le he escuchado bien, ¿me lo puede repetir?"
7. VALIDACIÓN DE NOTAS: Si el usuario te da un número menor a 1 o mayor a 10 (ej: 0, 11), NO guardes el dato. Di "Disculpe, la nota debe ser entre 1 y 10. ¿Qué nota le daría?" y espera su respuesta.

REGLA CRÍTICA DE DESPEDIDA:
Cuando vayas a terminar la llamada, SIEMPRE haz esto EN DOS PASOS SEPARADOS:
- PRIMER PASO: Usa 'guardar_encuesta' con el status correspondiente. En el mismo turno, DI en voz alta la frase de despedida (ej: "Gracias por su tiempo y adiós."). NO llames a 'finalizar_llamada' en este turno.
- SEGUNDO PASO: Cuando ya hayas dicho la despedida, usa 'finalizar_llamada'.
NUNCA llames a 'guardar_encuesta' y 'finalizar_llamada' en el mismo turno.

EXCEPCIÓN - BUZÓN DE VOZ / FUERA DE COBERTURA:
- Si escuchas "fuera de cobertura", "móvil apagado", "buzón de voz", "contestador", "terminado el tiempo de grabación" o mensajes automáticos similares:
  - Usa 'guardar_encuesta' (status='failed').
  - Usa 'finalizar_llamada' (sin despedida).

EXCEPCIÓN INTERRUPCIÓN/COLGAR:
- Usa 'guardar_encuesta' (status='incomplete').
- Di en voz alta: "De acuerdo. Gracias, adiós."
- Luego usa 'finalizar_llamada'.

NOTA FINAL: UNA VEZ LLAMES A 'finalizar_llamada', LA CONVERSACIÓN HA TERMINADO. NO RESPONDAS A NADA MÁS.
"""


class DynamicAgent(Agent):
    """Agente dinámico que carga sus instrucciones desde Supabase."""
    
    def __init__(self, room_name: str, agent_config: dict) -> None:
        self.server_url = os.getenv("BRIDGE_SERVER_URL", "http://127.0.0.1:8001")
        self.data_saved = False
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
        
        full_instructions = f"""{agent_instructions}

DATOS TÉCNICOS (INVISIBLES PARA EL CLIENTE):
- SALA ACTUAL: '{room_name}'
- ID DE LA ENCUESTA: {self.survey_id}
- NOMBRE DEL AGENTE (INTERNO, NO DECIR AL CLIENTE): {agent_name}

{BASE_RULES}
"""

        super().__init__(instructions=full_instructions)
        logger.info(f"🤖 Agente '{agent_name}' creado con instrucciones dinámicas (Survey: {self.survey_id})")

    async def on_enter(self):
        # Pausa de cortesía: 1.5 segundos para que la red telefónica se estabilice
        await asyncio.sleep(1.5)
        
        await self.session.generate_reply(
            instructions=f"Di exactamente: '{self.greeting}' y espera la respuesta.",
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
        self, context: RunContext, nombre_sala: str, mensaje_despedida: Optional[str] = None
    ) -> str | None:
        """
        Herramienta para colgar la llamada.
        Úsala COMO ÚLTIMA ACCIÓN tras despedirte.
        La despedida ya se habrá dicho en voz alta en el turno anterior.
        """
        context.disallow_interruptions()
        
        if mensaje_despedida:
             logger.info(f"🗣️ Despedida (log): {mensaje_despedida}")
        
        logger.info("⏳ Esperando 5.0s para asegurar que se escuche la despedida...")
        await asyncio.sleep(5.0) 
        
        url = f"{self.server_url}/colgar"
        payload = {"nombre_sala": nombre_sala}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, timeout=5, json=payload) as resp:
                    logger.info(f"✂️ COLGANDO: {nombre_sala}")
                    return "Llamada finalizada."
        except Exception as e:
            logger.error(f"Error Colgar: {e}")
            return "Error al colgar."


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
# SERVIDOR Y ENTRYPOINT DINÁMICO
# ============================================================================
server = AgentServer()

@server.rtc_session()
async def entrypoint(ctx: JobContext):
    
    def handle_error(error):
        msg = str(error)
        if "429" in msg: 
            logger.error("\n\n🚨🚨🚨 ALERTA: Límite de API Alcanzado 🚨🚨🚨\n")
        else:
            logger.error(f"\n⚠️ ERROR DEL AGENTE: {error}\n")

    # --- PASO 1: Extraer survey_id del nombre de sala ---
    room_name = ctx.room.name
    survey_id = "0"
    try:
        parts = room_name.split('_')
        if len(parts) >= 2 and parts[0] == "encuesta":
            survey_id = parts[1]
        else:
            survey_id = parts[-1]
    except:
        survey_id = "0"

    # --- PASO 2: Conectar a la sala PRIMERO (evitar timeout) ---
    try:
        logger.info("⏱️ Iniciando conexión a la sala (ctx.connect)...")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        logger.info("✅ Conexión a sala establecida.")

        # --- PASO 3: Cargar en paralelo el VAD y la config del agente ---
        logger.info("⏱️ Cargando VAD y configuración del agente en paralelo...")
        vad_task = asyncio.to_thread(silero.VAD.load, min_silence_duration=0.5)
        config_task = fetch_agent_config(survey_id)
        
        vad_model, agent_config = await asyncio.gather(vad_task, config_task)
        logger.info("✅ VAD y configuración cargados.")

        # --- PASO 4: Crear el agente dinámico con la config obtenida ---
        agent_instance = DynamicAgent(room_name=room_name, agent_config=agent_config)
        
        # Determinar modelo LLM y voz desde la config
        llm_model = agent_config.get("llm_model", "llama-3.3-70b-versatile")
        voice_id = agent_config.get("voice_id", "6511153f-72f9-4314-a204-8d8d8afd646a")
        agent_name_display = agent_config.get("name", "Bot")
        
        logger.info(f"🤖 Configurando sesión: Agente='{agent_name_display}', LLM='{llm_model}', Voice='{voice_id}'")

        logger.info("⏱️ Inicializando AgentSession...")
        session = AgentSession(
            stt=deepgram.STT(model="nova-3", language="es"),
            llm=openai.LLM(
                model=llm_model, 
                base_url="https://api.groq.com/openai/v1",
                api_key=os.getenv("GROQ_API_KEY"),
                temperature=0.1
            ),
            tts=cartesia.TTS(
                model="sonic-multilingual",
                voice=voice_id,
                language="es"
            ),
            vad=vad_model,
            preemptive_generation=True, 
        )
        logger.info("✅ AgentSession inicializada.")

        @session.on("user_speech_committed")
        def on_user_speech(msg: stt.SpeechEvent):
            print(f"\n🗣️  USUARIO DICE: {msg.alternatives[0].text}\n")
            logger.info(f"TRANSCRIPCIÓN: {msg.alternatives[0].text}")
        
        # --- FIX: Bloquear hasta desconexión ---
        finished = asyncio.Event()

        @ctx.room.on("disconnected")
        def on_disconnect():
            logger.info("🔌 Sala desconectada. Finalizando agente...")
            finished.set()

        await session.start(
            agent=agent_instance,
            room=ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(
                    noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
                ),
            ),
        )

        background_audio = BackgroundAudioPlayer(
            ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.1),
        )
        await background_audio.start(room=ctx.room, agent_session=session)
        
        # Esperar hasta que la llamada termine
        await finished.wait()
    
    except Exception as e:
        handle_error(e)
    
    finally:
        data_saved = getattr(agent_instance, 'data_saved', False) if 'agent_instance' in dir() else False
        if not data_saved:
            logger.warning(f"⚠️ La sesión terminó sin guardar datos (Survey ID: {survey_id}). Marcando como 'unreached'...")
            try:
                fallback_payload = {
                    "id_encuesta": int(survey_id) if str(survey_id).isdigit() else 0,
                    "status": "unreached",
                    "comentarios": "Llamada finalizada sin datos (Posible No Contesta / Cuelgue inmediato)"
                }
                server_url = os.getenv("BRIDGE_SERVER_URL", "http://127.0.0.1:8001")
                async with aiohttp.ClientSession() as sess:
                    url = f"{server_url}/guardar-encuesta"
                    async with sess.post(url, json=fallback_payload, timeout=5) as r:
                         logger.info(f"✅ (Fallback) Status guardado como 'unreached'")
            except Exception as ex:
                 logger.error(f"❌ (Fallback) Error salvando fallback status: {ex}")

if __name__ == "__main__":
    cli.run_app(server)