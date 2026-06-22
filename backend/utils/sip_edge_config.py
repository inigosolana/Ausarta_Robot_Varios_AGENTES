"""Validación de destinos SIP salientes y parseo de configuración anti toll-fraud."""
from __future__ import annotations

import os
import re
from typing import FrozenSet

# Prefijos de tarificación especial (España + genéricos internacionales)
_DEFAULT_PREMIUM_PREFIXES = (
    "803",
    "806",
    "807",
    "901",
    "902",
    "903",
    "905",
    "976",
    "800",  # opcional: algunos 800 son gratuitos inbound; bloquear outbound
    "0900",
    "0906",
    "0907",
    "0908",
    "0909",
)


def _parse_csv_env(name: str, default: str = "") -> frozenset[str]:
    raw = os.getenv(name, default)
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return frozenset(parts)


def allowed_country_codes() -> FrozenSet[str]:
    """Códigos país permitidos sin '+' (ej. 34, 351). Vacío = sin restricción."""
    return _parse_csv_env("SIP_OUTBOUND_ALLOWED_COUNTRY_CODES")


def premium_prefixes() -> tuple[str, ...]:
    custom = os.getenv("SIP_OUTBOUND_BLOCKED_PREFIXES", "").strip()
    if custom:
        return tuple(p.strip() for p in custom.split(",") if p.strip())
    return _DEFAULT_PREMIUM_PREFIXES


def block_premium_numbers() -> bool:
    return os.getenv("SIP_OUTBOUND_BLOCK_PREMIUM", "true").lower() in ("1", "true", "yes")


def outbound_max_per_empresa_minute() -> int:
    try:
        return max(1, int(os.getenv("SIP_OUTBOUND_MAX_PER_EMPRESA_MINUTE", "30")))
    except ValueError:
        return 30


def outbound_max_per_dest_hour() -> int:
    try:
        return max(1, int(os.getenv("SIP_OUTBOUND_MAX_PER_DEST_HOUR", "3")))
    except ValueError:
        return 3


_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_e164(phone: str) -> str:
    """Normaliza a E.164 básico (+ y dígitos)."""
    raw = (phone or "").strip()
    if not raw:
        raise ValueError("Número vacío")
    cleaned = re.sub(r"[^\d+]", "", raw)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif not cleaned.startswith("+"):
        cleaned = "+" + cleaned.lstrip("0")
    if not _E164_RE.match(cleaned):
        raise ValueError(f"Formato E.164 inválido: {phone}")
    return cleaned


def _national_digits(digits: str) -> str:
    """Parte nacional tras código de país (heurística ES + allowed_country_codes)."""
    allowed = allowed_country_codes()
    for code in sorted(allowed, key=len, reverse=True):
        cc = code.lstrip("+")
        if digits.startswith(cc) and len(digits) > len(cc) + 6:
            return digits[len(cc) :]
    if digits.startswith("34") and len(digits) > 9:
        return digits[2:]
    return digits


def validate_outbound_destination(phone: str) -> str:
    """
    Valida número saliente. Lanza ValueError si no cumple política anti toll-fraud.
    """
    normalized = normalize_e164(phone)
    digits = normalized[1:]
    national = _national_digits(digits)

    if block_premium_numbers():
        for prefix in premium_prefixes():
            p = prefix.lstrip("+")
            if digits.startswith(p) or national.startswith(p):
                raise ValueError(f"Prefijo de tarificación especial bloqueado: {prefix}")

    allowed = allowed_country_codes()
    if allowed:
        if not any(digits.startswith(code.lstrip("+")) for code in allowed):
            raise ValueError("País no permitido para llamadas salientes")

    return normalized


def mask_phone(phone: str) -> str:
    """Enmascara teléfono para logs (últimos 4 dígitos)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) <= 4:
        return "****"
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"
