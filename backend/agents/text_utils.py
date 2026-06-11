"""Re-export de utilidades de texto (compatibilidad con tests y imports legacy)."""

from __future__ import annotations

from agents.agent_common import (
    _count_words,
    _detect_language,
    _is_likely_noise_transcript,
    _normalize_goodbye_message,
    _normalize_message_text,
    anonymize_text,
)

__all__ = [
    "_count_words",
    "_detect_language",
    "_is_likely_noise_transcript",
    "_normalize_goodbye_message",
    "_normalize_message_text",
    "anonymize_text",
]
