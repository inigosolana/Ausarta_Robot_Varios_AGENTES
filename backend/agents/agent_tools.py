from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Optional

import aiohttp
from livekit.agents import RunContext, function_tool

from agents.agent_common import (
    BRIDGE_SERVER_URL_INTERNAL,
    _build_inbound_datos_extra,
    _extract_transcript_from_session,
    _is_inbound_agent_config,
    normalize_goodbye_message,
    _normalize_message_text,
)
from config import get_settings
from services.queue_service import (
    enqueue_colgar_sala,
    enqueue_guardar_encuesta,
    enqueue_transfer_briefing,
    enqueue_transfer_to_human,
)

logger = logging.getLogger("agent-dynamic")

if TYPE_CHECKING:
    from utils.workflow_state import WorkflowStateMachine


class AgentToolsMixin:
    if TYPE_CHECKING:
        room_name: str
        survey_id: str
        agent_config: dict[str, Any]
        data_saved: bool
        hangup_started: bool
        _workflow_sm: WorkflowStateMachine | None
        _transfer_completed: asyncio.Event

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

        if _is_inbound_agent_config(self.agent_config):
            base_extra = payload.get("datos_extra") if isinstance(payload.get("datos_extra"), dict) else {}
            payload["datos_extra"] = _build_inbound_datos_extra(
                self.agent_config,
                self.room_name,
                base_extra,
            )

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
        Busca en la base de conocimiento de la empresa Y del agente (documentos internos).
        Úsala SIEMPRE antes de responder sobre servicios, precios, políticas o datos de la empresa.
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

    @function_tool(name="buscar_internet")
    async def _tool_buscar_internet(
        self,
        context: RunContext,
        consulta: str,
    ) -> str:
        """
        Busca información pública en internet cuando la base de conocimiento no basta.
        Solo disponible si el agente tiene activada la búsqueda en internet.
        """
        if not getattr(self, "kb_allow_internet", False):
            return ""

        if not consulta or not consulta.strip():
            return ""

        try:
            from services.web_search_service import search_web

            result = await asyncio.wait_for(
                search_web(consulta.strip()),
                timeout=5,
            )
            return result or ""
        except Exception as e:
            logger.warning(f"⚠️ [{self.room_name}] Error en buscar_internet: {e}")
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

    async def _execute_human_transfer(
        self,
        *,
        motivo: str = "El cliente solicita hablar con una persona",
        extension_number: str = "",
        source: str = "tool",
    ) -> str:
        """
        Encola transferencia a humano (Yeastar) y reproduce aviso TTS.
        Usado por la tool del LLM y por el router semántico.
        """
        survey_id_raw = self.survey_id
        survey_id: int | None = int(survey_id_raw) if str(survey_id_raw).isdigit() else None

        logger.info(
            f"[{self.room_name}] Transferencia solicitada "
            f"(source={source}, survey={survey_id_raw}, motivo: {motivo}, ext: {extension_number or 'auto'})"
        )

        busy_message = "Lo siento, nuestros agentes estan ocupados, puedo tomar nota?"

        try:
            empresa_id_int = int(str(getattr(self, "empresa_id", "0") or "0"))
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
                logger.info(
                    f"[{self.room_name}] Briefing de transferencia encolado para encuesta {survey_id}"
                )
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
                f"(job={job_id}, survey={survey_id_raw}, ext={resolved_extension}, source={source})"
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
        return await self._execute_human_transfer(
            motivo=motivo,
            extension_number=extension_number,
            source="llm_tool",
        )

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
            current_session = getattr(self, "session", None)
            chat_ctx = getattr(current_session, "chat_ctx", getattr(current_session, "chat_context", None))
            if chat_ctx and getattr(chat_ctx, "messages", None):
                for m in reversed(chat_ctx.messages):
                    if getattr(m, "role", "") == "user":
                        latest_user = _normalize_message_text(getattr(m, "content", None)).lower()
                        if latest_user:
                            break

            safe_goodbye = normalize_goodbye_message(mensaje_despedida_manual)
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
                safe_goodbye = normalize_goodbye_message(mensaje_despedida_manual)
                if safe_goodbye != _normalize_message_text(mensaje_despedida_manual):
                    logger.info(f"✂️ [{self.room_name}] Despedida normalizada a formato corto: '{safe_goodbye}'")
                current_session = getattr(self, "session", None)
                if current_session:
                    await current_session.say(safe_goodbye, allow_interruptions=False)

                # Margen corto para evitar silencios largos tras despedida.
                # Si se necesita ajustar, usar AGENT_HANGUP_DELAY_SECONDS en entorno.
                wait_seconds = float(os.getenv("AGENT_HANGUP_DELAY_SECONDS", str(get_settings().agent_hangup_delay)))
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

