"""Sesión de llamada LiveKit: transcripción, workflow, AMD y cleanup."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import TYPE_CHECKING, Any

from agents.agent_common import (
    _extract_transcript_from_session,
    _normalize_message_text,
)
from agents.agent_lifecycle import CallSessionLifecycleMixin
from agents.post_call_processor import finalize_call_session
from services.call_results_service import prepare_transcription_for_storage
from services.queue_service import (
    enqueue_colgar_sala,
    enqueue_guardar_encuesta,
    enqueue_transfer_to_human,
)
from utils.prompt_sanitizer import sanitize_untrusted_text
from utils.workflow_state import WorkflowStateMachine

if TYPE_CHECKING:
    from livekit.agents import AgentSession, JobContext

    from agents.dynamic_agent import DynamicAgent

logger = logging.getLogger("agent-dynamic")
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
        call_metadata: dict | None = None,
    ) -> None:
        self.ctx = ctx
        self.job_id = job_id
        self.room_name = room_name
        self.survey_id = survey_id
        self.agent_config = agent_config
        self.call_metadata = call_metadata or {}
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

                    if ntype == "schedule":
                        from services.workflow_schedule_service import schedule_workflow_follow_up

                        survey_id_int = int(self.survey_id) if str(self.survey_id).isdigit() else 0
                        empresa_id = int(
                            self.agent_config.get("empresa_id")
                            or self.call_metadata.get("empresa_id")
                            or 0
                        )
                        lead_raw = (
                            self.call_metadata.get("contacto_id")
                            or self.call_metadata.get("lead_id")
                            or self.call_metadata.get("client_id")
                        )
                        lead_id = int(lead_raw) if lead_raw else None
                        campaign_ctx = {
                            "campaign_id": self.call_metadata.get("campaign_id")
                            or self.call_metadata.get("campana_id"),
                            "empresa_id": empresa_id,
                            "survey_id": survey_id_int,
                        }
                        result = await schedule_workflow_follow_up(
                            survey_id=survey_id_int,
                            empresa_id=empresa_id,
                            campaign_id_ref=next_step.get("campaign_id_ref") or "{{campaign_id}}",
                            lead_id=lead_id,
                            delay_days=int(next_step.get("delay_days") or 1),
                            workflow_variables=wf_sm.get_variables(),
                            call_context=campaign_ctx,
                        )
                        if result.get("ok"):
                            logger.info(
                                f"[{self.job_id}] Workflow schedule: lead {result.get('lead_id')} "
                                f"→ {result.get('retry_at')}"
                            )
                        else:
                            logger.warning(
                                f"[{self.job_id}] Workflow schedule falló: {result.get('error')}"
                            )
                        optional_msg = (next_step.get("content") or "").strip()
                        if optional_msg:
                            try:
                                await self.session.say(optional_msg, allow_interruptions=True)
                            except Exception as say_err:
                                logger.warning(f"[{self.job_id}] Workflow schedule say() error: {say_err}")
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

