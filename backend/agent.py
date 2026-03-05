import logging
from typing import Optional
import os
import aiohttp
import asyncio
import sys
import json
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
        
        base_rules_to_use = BASE_RULES
        inst_lower = agent_instructions.lower()
        # Detección de tipo de agente (Campo explícito 'tipo_resultados' o fallback)
        tipo_res = agent_config.get("tipo_resultados")
        
        is_numeric = (tipo_res == 'ENCUESTA_NUMERICA')
        has_preguntas = (tipo_res in ['PREGUNTAS_ABIERTAS', 'CUALIFICACION_LEAD', 'AGENDAMIENTO_CITA', 'SOPORTE_CLIENTE'])
        
        # Fallback para agentes antiguos o si n8n aún no lo clasificó
        if tipo_res is None:
            survey_type_legacy = agent_config.get("survey_type")
            is_numeric = (survey_type_legacy == 'numeric')
            has_preguntas = (survey_type_legacy in ['open_questions', 'mixed'])
            
            if survey_type_legacy is None:
                numeric_keywords = ["1 al 10", "0 al 10", "del uno al diez", "numérica", "puntuación", "uno al 10", "uno al diez"]
                is_numeric = any(kw in inst_lower for kw in numeric_keywords) or "dakota" in agent_name.lower()
                has_preguntas = any(p in inst_lower for p in ["pregunta 1", "pregunta 2", "pregunta:"])
            
            if survey_type_legacy == 'mixed':
                is_numeric = True
                has_preguntas = True
        
        if is_numeric:
            base_rules_to_use += """
REGLA ESPECIAL PARA ENCUESTAS NUMÉRICAS:
- Esta es una encuesta de puntuación del 0 al 10.
- Debes obtener una nota numérica para cada pregunta. 
- Si el cliente responde con texto, pídele amablemente una puntuación del 0 al 10.
"""
        elif has_preguntas:
            base_rules_to_use += """
REGLA ESPECIAL PARA CUESTIONARIOS ABIERTOS:
- Como este es un cuestionario de preguntas abiertas, USA el campo 'comentarios' de la herramienta 'guardar_encuesta' para guardar todas las respuestas de las preguntas planteadas recopiladas en forma de texto descriptivo.
- IGNORA la regla estructurada de "Validación de notas de 1 al 10" si no aplica a tus preguntas.
"""
        
        # Construcción del Prompt Final: Reglas -> Datos -> GUION (EL GUION ES LO MÁS IMPORTANTE)
        full_instructions = f"{base_rules_to_use}\n\n"
        full_instructions += f"DATOS DEL AGENTE:\n- NOMBRE: {agent_name}\n- EMPRESA: Ausarta\n\n"
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
        await asyncio.sleep(1.2)
        try:
            await current_session.say(self.greeting, allow_interruptions=False)
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
        status: Optional[str] = None
    ) -> str | None:
        """
        Guarda los datos de la encuesta/llamada. 
        - Si la encuesta es NUMÉRICA, usa los campos 'nota_comercial', 'nota_instalador' y 'nota_rapidez' (valores del 1 al 10).
        - Si la encuesta es ABIERTA o el usuario da feedback extra, usa el campo 'comentarios'.
        - 'status' puede ser 'completed', 'failed', 'incomplete' o 'rejected_opt_out'.
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
        Debes proporcionar obligatoriamente el mensaje de despedida.
        """
        async def process_goodbye_and_hangup():
            try:
                # Usamos await porque say() devuelve un handle awaitable en esta versión
                await self.session.say(mensaje_despedida_manual, allow_interruptions=False)
                # Esperamos un poco para dar tiempo a que se escuche antes de cerrar la sala
                await asyncio.sleep(4.0)
            finally:
                url = f"{self.server_url}/colgar"
                payload = {"nombre_sala": self.room_name}
                try:
                    async with aiohttp.ClientSession() as sess:
                        await sess.post(url, timeout=5, json=payload)
                except: pass
                
        asyncio.create_task(process_goodbye_and_hangup())
        return "Llamada finalizada."


# ============================================================================
# FUNCIÓN PARA OBTENER LA CONFIGURACIÓN DEL AGENTE DESDE LA API
# ============================================================================
async def fetch_agent_config(survey_id: str) -> dict:
    """Consulta la API local para obtener la configuración del agente asignado a esta encuesta."""
    server_url = (
        os.getenv("BRIDGE_SERVER_URL_INTERNAL")
        or os.getenv("BRIDGE_SERVER_URL")
        or "http://127.0.0.1:8001"
    ).rstrip("/")
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

@server.rtc_session(agent_name=os.getenv("AGENT_NAME_DISPATCH", "default_agent"))
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
        survey_id = parts[-1] if parts else "0"
        if not survey_id.isdigit() and len(parts) >= 2:
            survey_id = parts[-2]
    except:
        survey_id = "0"

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

        # --- PASO 3: Cargar config ---
        vad_task = asyncio.to_thread(silero.VAD.load, min_silence_duration=0.5)
        config_task = fetch_agent_config(survey_id)
        
        vad_model, agent_config = await asyncio.gather(vad_task, config_task)
        logger.info(f"✅ [{job_id}] VAD y configuración cargados.")

        # --- PASO 4: Crear el asistente ---
        agent_instance = DynamicAgent(room_name=room_name, agent_config=agent_config)
        
        llm_model = agent_config.get("llm_model", "llama-3.3-70b-versatile")
        voice_id = agent_config.get("voice_id", "cefcb124-080b-4655-b31f-932f3ee743de")
        language = agent_config.get("language", "es")
        stt_provider = agent_config.get("stt_provider", "deepgram")
        
        logger.info(f"🤖 [{job_id}] Config: LLM='{llm_model}', Voice='{voice_id}', Lang='{language}', STT='{stt_provider}'")

        if language in ["eu", "gl"] or stt_provider == "openai":
            stt_plugin = openai.STT(language=language)
            logger.info("🎙️ Usando STT: OpenAI Whisper")
        else:
            stt_plugin = deepgram.STT(model="nova-3", language=language)
            logger.info("🎙️ Usando STT: Deepgram Nova-3")

        # --- Crear sesión del agente (AgentSession, compatible con versión instalada) ---
        session = AgentSession(
            vad=vad_model,
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
        )

        # La sesión se asocia automáticamente al arrancar
        # agent_instance.session = session  <- Esto fallaba porque session es property sin setter
        
        await session.start(
            room=ctx.room,
            agent=agent_instance,
        )
        
        # NOTA: on_enter() del DynamicAgent se encarga del saludo.
        # NO llamamos a say_greeting() por separado para evitar doble saludo.
        
        # --- EVENTOS ---
        finished = asyncio.Event()

        @ctx.room.on("disconnected")
        def on_disconnect():
            logger.info(f"🔌 [{job_id}] Desconectado.")
            finished.set()

        @ctx.room.on("participant_disconnected")
        def on_participant_disconnected(participant: rtc.RemoteParticipant):
            if not participant.identity.startswith("agent-"):
                logger.info(f"[{job_id}] Cliente se desconectó. Terminando sala.")
                async def force_hangup_room():
                    url = f"{agent_instance.server_url}/colgar"
                    try:
                         async with aiohttp.ClientSession() as http_sess:
                             await http_sess.post(url, timeout=5, json={"nombre_sala": room_name})
                    except: pass
                asyncio.create_task(force_hangup_room())

        await finished.wait()
    
    except Exception as e:
        handle_error(e)
    
    finally:
        if not is_duplicate:
            logger.info(f"--- 🏁 FIN DE SESIÓN AGENTE (Job: {job_id}, Room: {room_name}, Survey: {survey_id}) ---")
            agent_instance_exists = 'agent_instance' in locals()
            data_saved = getattr(agent_instance, 'data_saved', False) if agent_instance_exists else False
            
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
                if 'session' in locals():
                    # Intentamos obtener la historia de la sesión o del asistente (varía según versión de livekit-agents)
                    chat_ctx = getattr(session, 'chat_ctx', getattr(session, 'chat_context', None))
                    if chat_ctx:
                        for m in chat_ctx.messages:
                            if m.content and m.role in ("user", "assistant"):
                                raw_messages.append({"role": m.role, "content": m.content})
                                role_label = "Cliente" if m.role == "user" else "Agente"
                                transcript += f"{role_label}: {m.content}\n"
                    
                    # Enviar a n8n
                    if agent_instance_exists:
                        try:
                            await asyncio.wait_for(
                                agent_instance.notify_n8n_transcription(survey_id, raw_messages),
                                timeout=5
                            )
                        except Exception as n8n_err:
                            logger.error(f"Error enviando transcripción a n8n: {n8n_err}")
            except Exception as ex:
                logger.error(f"Error procesando historia: {ex}")
                
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
                    transcript_payload = {
                        "id_encuesta": int(survey_id) if str(survey_id).isdigit() else 0,
                        "transcription": transcript,
                        "status": call_disposition,
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
        else:
            logger.info(f"--- 🏁 FIN DE SESIÓN DUPLICADA (Job: {job_id}) - Saliendo sin reportar datos ---")

if __name__ == "__main__":
    cli.run_app(server)