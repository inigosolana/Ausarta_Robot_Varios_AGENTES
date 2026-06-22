"""
Sanitización de PII en transcripciones antes de persistencia (GDPR).

Motor por defecto: regex de alto rendimiento (sin dependencias extra).
Opcional: Presidio si PII_SANITIZER_ENGINE=presidio y paquetes instalados.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Final, Literal

from config import get_settings

logger = logging.getLogger(__name__)

PIIEngine = Literal["regex", "presidio"]

_REDACTION_LABELS: Final[dict[str, str]] = {
    "email": "EMAIL",
    "phone": "PHONE",
    "dni_nie": "DNI_NIE",
    "iban": "IBAN",
    "credit_card": "CREDIT_CARD",
    "ip_address": "IP_ADDRESS",
    "address": "ADDRESS",
    "long_number": "NUMBER",
}

# Orden: patrones más específicos primero.
_REGEX_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "email",
        re.compile(r"[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}", re.IGNORECASE),
    ),
    (
        "iban",
        re.compile(
            r"\b[A-Z]{2}\d{2}[\s]?(?:\d{4}[\s]?){2,5}\d{1,4}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "credit_card",
        re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"),
    ),
    (
        "credit_card",
        re.compile(r"\b\d{13,19}\b"),
    ),
    (
        "dni_nie",
        re.compile(r"\b[XYZ]\d{7}[A-Z]\b", re.IGNORECASE),
    ),
    (
        "dni_nie",
        re.compile(r"\b\d{8}[A-Z]\b", re.IGNORECASE),
    ),
    (
        "phone",
        re.compile(
            r"(?<!\w)(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,4}\)?[\s\-.]?)?\d{3}[\s\-.]?\d{2,3}[\s\-.]?\d{2,3}(?!\w)"
        ),
    ),
    (
        "ip_address",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ),
    (
        "address",
        re.compile(
            r"\b(?:calle|cl\.?|avenida|avda?\.?|plaza|pl\.?|paseo|ps\.?|carretera|ctra\.?|camino|cmno\.?|urbanización|urb\.?)"
            r"\s+[A-Za-zÁÉÍÓÚÑáéíóúñ0-9][A-Za-zÁÉÍÓÚÑáéíóúñ0-9\s\.\'\-]{0,60}?\d{1,4}[A-Za-z]?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "long_number",
        re.compile(r"\b\d{9,}\b"),
    ),
)


@dataclass(frozen=True, slots=True)
class PIISanitizationResult:
    text: str
    redaction_count: int
    redacted_types: tuple[str, ...]
    engine: PIIEngine


def _placeholder(entity_type: str) -> str:
    label = _REDACTION_LABELS.get(entity_type, entity_type.upper())
    return f"[REDACTED_{label}]"


def _sanitize_with_regex(text: str) -> PIISanitizationResult:
    sanitized = text
    redaction_count = 0
    redacted_types: list[str] = []

    for entity_type, pattern in _REGEX_RULES:

        def _repl(match: re.Match[str], et: str = entity_type) -> str:
            nonlocal redaction_count
            redaction_count += 1
            if et not in redacted_types:
                redacted_types.append(et)
            return _placeholder(et)

        sanitized, _ = pattern.subn(_repl, sanitized)

    return PIISanitizationResult(
        text=sanitized,
        redaction_count=redaction_count,
        redacted_types=tuple(redacted_types),
        engine="regex",
    )


def _sanitize_with_presidio(text: str) -> PIISanitizationResult | None:
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
        from presidio_anonymizer.entities import OperatorConfig
    except ImportError:
        return None

    try:
        analyzer = AnalyzerEngine()
        anonymizer = AnonymizerEngine()
        results = analyzer.analyze(text=text, language="es")
        if not results:
            return PIISanitizationResult(
                text=text,
                redaction_count=0,
                redacted_types=(),
                engine="presidio",
            )

        operators = {
            entity.entity_type: OperatorConfig("replace", {"new_value": _placeholder(entity.entity_type.lower())})
            for entity in results
        }
        anonymized = anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=operators,
        )
        redacted_types = tuple(sorted({r.entity_type.lower() for r in results}))
        return PIISanitizationResult(
            text=anonymized.text,
            redaction_count=len(results),
            redacted_types=redacted_types,
            engine="presidio",
        )
    except Exception as exc:
        logger.warning("Presidio PII sanitization failed, falling back to regex: %s", exc)
        return None


def _resolve_engine() -> PIIEngine:
    raw = (os.getenv("PII_SANITIZER_ENGINE") or "regex").strip().lower()
    return "presidio" if raw == "presidio" else "regex"


def sanitize_transcription_pii(
    text: str | None,
    *,
    enabled: bool | None = None,
) -> PIISanitizationResult:
    """Redacta PII en texto de transcripción. No trunca (a diferencia de anonymize_text)."""
    if text is None:
        return PIISanitizationResult(text="", redaction_count=0, redacted_types=(), engine="regex")

    stripped = text.strip()
    if not stripped:
        return PIISanitizationResult(text=text, redaction_count=0, redacted_types=(), engine="regex")

    if enabled is None:
        enabled = get_settings().pii_sanitization_enabled
    if not enabled:
        return PIISanitizationResult(
            text=text,
            redaction_count=0,
            redacted_types=(),
            engine="regex",
        )

    engine = _resolve_engine()
    if engine == "presidio":
        presidio_result = _sanitize_with_presidio(stripped)
        if presidio_result is not None:
            if presidio_result.redaction_count:
                logger.info(
                    "PII sanitization presidio: %s redaction(s) types=%s",
                    presidio_result.redaction_count,
                    presidio_result.redacted_types,
                )
            return PIISanitizationResult(
                text=presidio_result.text,
                redaction_count=presidio_result.redaction_count,
                redacted_types=presidio_result.redacted_types,
                engine="presidio",
            )

    result = _sanitize_with_regex(stripped)
    if result.redaction_count:
        logger.info(
            "PII sanitization regex: %s redaction(s) types=%s",
            result.redaction_count,
            result.redacted_types,
        )
    return result


def sanitize_free_text_pii(text: str | None, *, enabled: bool | None = None) -> str | None:
    """Sanitiza campos narrativos derivados (comentarios, resumen)."""
    if text is None:
        return None
    return sanitize_transcription_pii(text, enabled=enabled).text
