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
    inference,
    room_io,
    utils,
    stt
)
from livekit.plugins import (
    silero,
    openai, 
)

try:
    from livekit.plugins import noise_cancellation
    HAS_NOISE_CANCELLATION = True
except ImportError:
    HAS_NOISE_CANCELLATION = False

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
logger = logging.getLogger("agent-Dakota")
load_dotenv()

class DynamicAgent(Agent):
    def __init__(self, room_name: str, server_url: str) -> None:
        self.server_url = server_url
        try:
            self.survey_id = room_name.split('_')[-1]
        except:
            self.survey_id = "0"
            
        # Default fallback config
        self.agent_config = {
            "name": "Dakota",
            "instructions": "Eres un asistente útil.",
            "greeting": "Hola."
        }
        
        # Load dynamic config
        self._load_config()

        super().__init__(
            instructions=self.agent_config["instructions"],
        )

    def _load_config(self):
        try:
            # Synchronous request to get config before initializing parent
            import requests
            url = f"{self.server_url}/api/calls/{self.survey_id}/config"
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    self.agent_config.update(data)
                    logger.info(f"✅ Configuración cargada para agente: {self.agent_config['name']}")
        except Exception as e:
            logger.error(f"⚠️ Error cargando config dinámica, usando default: {e}")

    async def on_enter(self):
        greeting = self.agent_config.get("greeting", "Hola.")
        await self.session.generate_reply(
            instructions=f"Di exactamente: '{greeting}' y espera.",
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
        comentarios: Optional[str] = None
    ) -> str | None:
        url = f"{self.server_url}/guardar-encuesta"
        real_id = int(self.survey_id) if str(self.survey_id).isdigit() else id_encuesta

        payload = {
            "id_encuesta": real_id,
            "nota_comercial": nota_comercial,
            "nota_instalador": nota_instalador,
            "nota_rapidez": nota_rapidez,
            "comentarios": comentarios,
        }
        
        asyncio.create_task(self._fire_and_forget_save(url, payload))
        return "Dato guardado."

    @function_tool(name="finalizar_llamada")
    async def _http_tool_finalizar_llamada(
        self, context: RunContext, nombre_sala: str
    ) -> str | None:
        context.disallow_interruptions()
        logger.info("⏳ Esperando 4s para colgar...")
        await asyncio.sleep(4) 
        
        url = f"{self.server_url}/colgar"
        payload = {"nombre_sala": nombre_sala}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, timeout=5, json=payload):
                    pass
            return "Llamada finalizada."
        except Exception as e:
            raise ToolError(f"Error Colgar: {e}")

server = AgentServer()

@server.rtc_session(agent_name="Ausarta-Agent")
async def entrypoint(ctx: JobContext):
    
    vad_model = silero.VAD.load()
    server_url = os.getenv("BRIDGE_SERVER_URL", "http://127.0.0.1:8001")
    
    # 1. Fetch AI Config (Global for now)
    # Ideally this runs once or cached, but per-call is safer for updates
    ai_config = {
        "llm_model": "llama-3.3-70b-versatile",
        "stt_model": "nova-2", 
        "tts_model": "sonic-multilingual",
        "tts_voice": "fb926b21-4d92-411a-85d0-9d06859e2171"
    }
    
    try:
        import requests
        resp = requests.get(f"{server_url}/api/ai/config", timeout=2)
        if resp.status_code == 200:
            remote_conf = resp.json()
            if remote_conf: ai_config.update(remote_conf)
    except: pass

    try:
        session = AgentSession(
            stt=inference.STT(model=f"deepgram/{ai_config['stt_model']}", language="es"),
            llm=openai.LLM(
                model=ai_config['llm_model'], 
                base_url="https://api.groq.com/openai/v1" if "llama" in ai_config['llm_model'] or "mixtral" in ai_config['llm_model'] else None,
                api_key=os.getenv("GROQ_API_KEY") if "llama" in ai_config['llm_model'] else os.getenv("OPENAI_API_KEY"),
                temperature=0.1
            ),
            tts=inference.TTS(
                model=f"cartesia/{ai_config['tts_model']}",
                voice=ai_config['tts_voice'],
                language="es",
                api_key=os.getenv("CARTESIA_API_KEY")
            ),
            vad=vad_model,
            preemptive_generation=True, 
        )

        @session.on("user_speech_committed")
        def on_user_speech(msg: stt.SpeechEvent):
            logger.info(f"TRANSCRIPCIÓN: {msg.alternatives[0].text}")

        # Configuración de cancelación de ruido
        noise_canceller = None
        if HAS_NOISE_CANCELLATION:
            noise_canceller = lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC()

        await session.start(
            agent=DynamicAgent(room_name=ctx.room.name, server_url=server_url),
            room=ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(
                    noise_cancellation=noise_canceller,
                ),
            ),
        )

        background_audio = BackgroundAudioPlayer(
            ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.1),
        )
        await background_audio.start(room=ctx.room, agent_session=session)
    
    except Exception as e:
        logger.error(f"⚠️ ERROR DEL AGENTE: {e}")

if __name__ == "__main__":
    cli.run_app(server)