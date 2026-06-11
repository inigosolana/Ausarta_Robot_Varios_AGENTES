from __future__ import annotations

import logging
import os
import re
from typing import Any

from config import settings

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
_AGENT_CONFIG_CACHE_TTL = settings.agent_config_cache_ttl
_REDIS_URL = settings.redis_url
DISPATCH_AGENT_NAME = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()


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
INBOUND_ROOM_PREFIX = os.getenv("LIVEKIT_INBOUND_ROOM_PREFIX", "yeastar_")
ALLOWED_ROOM_PREFIXES = tuple(
    p for p in {ROOM_PREFIX, INBOUND_ROOM_PREFIX} if p
)


def _room_name_allowed(room_name: str) -> bool:
    return any(room_name.startswith(prefix) for prefix in ALLOWED_ROOM_PREFIXES)


def _is_inbound_agent_config(agent_config: dict) -> bool:
    return str(agent_config.get("call_direction") or "").lower() == "inbound"


def _parse_inbound_caller_from_room(room_name: str) -> str:
    if "__" in room_name:
        tail = room_name.split("__", 1)[1]
        caller = tail.split("_", 1)[0] if tail else ""
        if caller.isdigit():
            return caller
    for part in room_name.split("_"):
        if part.isdigit() and len(part) >= 9:
            return part
    return ""


def _build_inbound_datos_extra(
    agent_config: dict,
    room_name: str,
    base: dict | None = None,
) -> dict:
    extra = dict(base or {})
    extra["call_direction"] = "inbound"
    extra.setdefault("empresa_id", agent_config.get("empresa_id"))
    extra.setdefault("agent_id", agent_config.get("id") or agent_config.get("agent_id"))
    extra.setdefault("telefono", _parse_inbound_caller_from_room(room_name))
    extra.setdefault("room_name", room_name)
    return extra

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

def _is_uuid_like(value: str) -> bool:
    if not value:
        return False
    return bool(
        re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            value.strip(),
        )
    )
