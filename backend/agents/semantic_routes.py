"""Definiciones de rutas semánticas para intents de un solo shot (transferencia humana)."""

from __future__ import annotations

import json
import re
from typing import Any, Final

from config import get_settings

# Frases que anulan una posible solicitud de transferencia.
NEGATIVE_TRANSFER_CUES: Final[tuple[str, ...]] = (
    "no quiero hablar",
    "no necesito hablar",
    "no me pases",
    "no me pase",
    "sin hablar con",
    "no quiero un humano",
    "no quiero una persona",
)

# Tier 0: regex compiladas (español + variantes sin tilde).
TRANSFER_HUMAN_REGEXES: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:quiero|necesito|deseo)\s+(?:hablar|comunicar(?:me)?)\s+con\s+(?:un\s+|una\s+)?(?:humano|persona|agente|operador|representante|alguien)\b",
        r"\b(?:p[aá]same|p[oó]nme|comun[ií]came)\s+con\s+(?:un\s+|una\s+)?(?:humano|persona|agente|operador|representante|alguien)\b",
        r"\b(?:hablar|comunicar(?:me)?)\s+con\s+(?:un\s+|una\s+)?(?:humano|persona real|agente real|operador)\b",
        r"\b(?:transferir(?:me)?|pasar(?:me)?)\s+(?:con\s+)?(?:un\s+|una\s+)?(?:humano|agente|operador|persona)\b",
        r"\b(?:agente|operador|persona)\s+(?:humano|real|de verdad)\b",
        r"\b(?:speak|talk)\s+to\s+(?:a\s+)?(?:human|person|agent|representative)\b",
        r"\b(?:transfer|connect)\s+(?:me\s+)?to\s+(?:a\s+)?(?:human|agent|person)\b",
    )
)

DEFAULT_TRANSFER_PHRASES: Final[tuple[str, ...]] = (
    "quiero hablar con un humano",
    "pásame con un agente",
    "necesito un operador",
    "ponme con una persona",
)


def resolve_semantic_routing_config(agent_config: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Lee flags y frases custom desde agent_config / datos_extra."""
    enabled = get_settings().semantic_routing_enabled

    if agent_config.get("semantic_routing_enabled") is not None:
        enabled = bool(agent_config["semantic_routing_enabled"])

    phrases: list[str] = []
    datos_extra = agent_config.get("datos_extra") or {}
    if isinstance(datos_extra, str):
        try:
            datos_extra = json.loads(datos_extra)
        except json.JSONDecodeError:
            datos_extra = {}

    if isinstance(datos_extra, dict):
        if datos_extra.get("semantic_routing_enabled") is not None:
            enabled = bool(datos_extra["semantic_routing_enabled"])
        custom = datos_extra.get("human_transfer_phrases")
        if isinstance(custom, list):
            phrases.extend(str(item).strip() for item in custom if str(item).strip())

    top_level = agent_config.get("human_transfer_phrases")
    if isinstance(top_level, list):
        phrases.extend(str(item).strip() for item in top_level if str(item).strip())

    return enabled, tuple(phrases)
