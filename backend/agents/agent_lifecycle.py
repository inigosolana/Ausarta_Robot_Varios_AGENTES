from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from typing import TYPE_CHECKING

from agents.agent_common import (
    _count_words,
    _detect_language,
    _estimate_thinking_complexity,
    _extract_transcript_from_session,
    _is_inbound_agent_config,
    _is_likely_noise_transcript,
    _normalize_message_text,
    anonymize_text,
)
from agents.stt_tts_builder import _build_tts_plugin
from config import settings
from prompts import _LANG_OVERRIDE_MSGS
from agents.livekit_client import remove_room_participant
from services.queue_service import (
    enqueue_colgar_sala,
    enqueue_guardar_encuesta,
    enqueue_transfer_to_human,
)

if TYPE_CHECKING:
    from livekit import rtc
    from livekit.agents import AgentSession, AudioConfig, BackgroundAudioPlayer, BuiltinAudioClip
    from utils.workflow_state import WorkflowStateMachine
else:
    from livekit import rtc
    from livekit.agents import AudioConfig, BackgroundAudioPlayer, BuiltinAudioClip

logger = logging.getLogger("agent-dynamic")


class DynamicAgentLifecycleMixin:
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


class CallSessionLifecycleMixin:
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
    async def run_amd(self) -> None:
        """Monitoriza transcripciones tempranas para detectar contestador automático."""
        if _is_inbound_agent_config(self.agent_config):
            logger.info(f"⏭️ [{self.job_id}] AMD desactivado para llamada inbound")
            return
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
                        await remove_room_participant(self.room_name, identity)
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
        def _on_user_input_transcribed(ev):
            async def _process_user_input_transcribed() -> None:
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
                        self._spawn_ephemeral(self._try_switch_language(content))
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

                            self._spawn_ephemeral(_say_interrupt_ack())
                    self._append_transcript_event("user", content)
                    self.reprompt_state["last_user_at"] = now
                    self.reprompt_state["waiting_user"] = False
                    self.reprompt_state["reprompt_count"] = 0

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

                    wf_sm = getattr(self.agent_instance, "_workflow_sm", None)
                    if wf_sm is not None and not wf_sm.is_finished():
                        await self._handle_workflow_turn(content, wf_sm)
                except Exception as ev_err:
                    logger.debug(f"[{self.job_id}] Error evento user_input_transcribed: {ev_err}")

            self._spawn_ephemeral(_process_user_input_transcribed())

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
                self._spawn_ephemeral(disconnect_tasks())

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

                if self.bg_player is not None:
                    try:
                        await self.bg_player.aclose()
                    except Exception:
                        pass
                    finally:
                        self.bg_player = None

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

