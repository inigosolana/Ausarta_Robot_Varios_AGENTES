"""Construye y fusiona agent_results JSON por tipo de agente."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1

# Campos legacy de encuestas que se mapean a agent_results
_LEGACY_SCORE_KEYS = {
    "nota_comercial": ("scores", "comercial"),
    "puntuacion_comercial": ("scores", "comercial"),
    "nota_instalador": ("scores", "instalador"),
    "puntuacion_instalador": ("scores", "instalador"),
    "nota_rapidez": ("scores", "rapidez"),
    "puntuacion_rapidez": ("scores", "rapidez"),
}

_SUPPORT_NOTE_KEYS = (
    "motivo_llamada",
    "resolucion",
    "puntos_clave",
    "motivo_contratacion",
    "detalle_problema",
)

_DATOS_EXTRA_SKIP = frozenset(
    {
        "call_direction",
        "room_name",
        "agent_type",
        "yeastar_callid",
        "yeastar_call_id",
        "yeastar_channel_id",
        "resumen_narrativo",
        "sentimiento_cliente",
        "idioma",
    }
)


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _set_nested(target: dict, path: tuple[str, str], value: Any) -> None:
    if value is None:
        return
    section, field = path
    target.setdefault(section, {})
    if isinstance(target[section], dict):
        target[section][field] = value


def normalize_agent_type(raw: str | None) -> str:
    value = (raw or "").strip().upper()
    return value or "ENCUESTA_NUMERICA"


def build_agent_results(
    agent_type: str | None,
    *,
    nota_comercial: int | None = None,
    nota_instalador: int | None = None,
    nota_rapidez: int | None = None,
    comentarios: str | None = None,
    datos_extra: dict | None = None,
    agent_results: dict | None = None,
) -> dict[str, Any]:
    """Construye payload agent_results desde campos legacy y datos_extra."""
    at = normalize_agent_type(agent_type)
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "agent_type": at,
        "scores": {},
        "notes": {},
        "extracted": {},
    }

    if isinstance(agent_results, dict) and agent_results:
        base = _deep_merge(base, agent_results)

    legacy_map = {
        "nota_comercial": nota_comercial,
        "nota_instalador": nota_instalador,
        "nota_rapidez": nota_rapidez,
    }
    for legacy_key, value in legacy_map.items():
        if value is not None and legacy_key in _LEGACY_SCORE_KEYS:
            _set_nested(base, _LEGACY_SCORE_KEYS[legacy_key], value)

    if comentarios:
        base.setdefault("notes", {})
        base["notes"]["comentarios"] = comentarios

    extra = datos_extra if isinstance(datos_extra, dict) else {}
    for legacy_key, path in _LEGACY_SCORE_KEYS.items():
        if legacy_key in extra:
            _set_nested(base, path, extra.get(legacy_key))

    if at == "SOPORTE_CLIENTE":
        base.setdefault("notes", {})
        for key in _SUPPORT_NOTE_KEYS:
            if extra.get(key):
                base["notes"][key] = extra[key]
    elif at in {"CUALIFICACION_LEAD", "AGENDAMIENTO_CITA", "PREGUNTAS_ABIERTAS"}:
        extracted = {
            k: v
            for k, v in extra.items()
            if k not in _DATOS_EXTRA_SKIP and not k.startswith("yeastar_")
        }
        if extracted:
            base.setdefault("extracted", {})
            base["extracted"] = _deep_merge(base.get("extracted") or {}, extracted)
    else:
        extracted = {
            k: v
            for k, v in extra.items()
            if k not in _DATOS_EXTRA_SKIP
            and k not in {*legacy_map, "comentarios", *_SUPPORT_NOTE_KEYS}
            and not k.startswith("yeastar_")
        }
        if extracted:
            base.setdefault("extracted", {})
            base["extracted"] = _deep_merge(base.get("extracted") or {}, extracted)

    if extra.get("sentimiento_cliente"):
        base.setdefault("analysis", {})
        base["analysis"]["sentimiento"] = extra["sentimiento_cliente"]
    if extra.get("idioma"):
        base.setdefault("analysis", {})
        base["analysis"]["idioma"] = extra["idioma"]
    if extra.get("resumen_narrativo"):
        base.setdefault("analysis", {})
        base["analysis"]["resumen"] = extra["resumen_narrativo"]

    base["agent_type"] = at
    base["schema_version"] = SCHEMA_VERSION
    return base


def merge_agent_results(existing: dict | None, patch: dict | None) -> dict[str, Any]:
    if not isinstance(existing, dict) or not existing:
        return copy.deepcopy(patch or {})
    if not isinstance(patch, dict) or not patch:
        return copy.deepcopy(existing)
    return _deep_merge(existing, patch)


def legacy_columns_from_agent_results(agent_results: dict | None) -> dict[str, Any]:
    """Mantiene columnas legacy sincronizadas para dashboards existentes."""
    if not isinstance(agent_results, dict):
        return {}

    scores = agent_results.get("scores") if isinstance(agent_results.get("scores"), dict) else {}
    notes = agent_results.get("notes") if isinstance(agent_results.get("notes"), dict) else {}
    out: dict[str, Any] = {}

    if scores.get("comercial") is not None:
        out["puntuacion_comercial"] = scores["comercial"]
    if scores.get("instalador") is not None:
        out["puntuacion_instalador"] = scores["instalador"]
    if scores.get("rapidez") is not None:
        out["puntuacion_rapidez"] = scores["rapidez"]
    if notes.get("comentarios"):
        out["comentarios"] = notes["comentarios"]

    return out


def build_encuesta_results_update(
    *,
    agent_type: str | None,
    existing_agent_results: dict | None = None,
    nota_comercial: int | None = None,
    nota_instalador: int | None = None,
    nota_rapidez: int | None = None,
    comentarios: str | None = None,
    datos_extra: dict | None = None,
    agent_results_patch: dict | None = None,
) -> dict[str, Any]:
    """Devuelve campos de UPDATE para encuestas (agent_results + legacy)."""
    patch = build_agent_results(
        agent_type,
        nota_comercial=nota_comercial,
        nota_instalador=nota_instalador,
        nota_rapidez=nota_rapidez,
        comentarios=comentarios,
        datos_extra=datos_extra,
        agent_results=agent_results_patch,
    )
    merged = merge_agent_results(existing_agent_results, patch)
    update: dict[str, Any] = {
        "agent_type": normalize_agent_type(agent_type or merged.get("agent_type")),
        "agent_results": merged,
    }
    update.update(legacy_columns_from_agent_results(merged))
    return update


def prepare_transcription_for_storage(transcription: str | None) -> str | None:
    """
    Sanitiza PII en transcripciones antes de persistir en Supabase (GDPR).
    Punto único de entrada para columnas transcription / previews.
    """
    if transcription is None:
        return None
    from utils.pii_sanitizer import sanitize_transcription_pii

    return sanitize_transcription_pii(transcription).text


def prepare_narrative_text_for_storage(text: str | None) -> str | None:
    """Sanitiza resúmenes/comentarios que puedan contener PII hablada en la llamada."""
    if text is None:
        return None
    from utils.pii_sanitizer import sanitize_free_text_pii

    return sanitize_free_text_pii(text)


@dataclass(frozen=True)
class CallUsageMetrics:
    """Métricas de consumo de una llamada para unit economics."""

    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_model: str
    tts_characters: int
    tts_provider: str
    telephony_seconds: int
    stt_audio_seconds: float = 0.0
    stt_provider: str = "deepgram"

    @property
    def llm_total_tokens(self) -> int:
        return self.llm_prompt_tokens + self.llm_completion_tokens


def extract_call_usage_metrics(
    usage_summary: Any,
    *,
    agent_config: dict[str, Any],
    telephony_seconds: int,
) -> CallUsageMetrics:
    """
    Normaliza métricas de LiveKit UsageCollector/UsageSummary + config del agente.
    """
    llm_model = (agent_config.get("llm_model") or "llama-3.3-70b-versatile").strip()
    tts_provider = (agent_config.get("tts_provider") or "cartesia").strip().lower()
    stt_provider = (agent_config.get("stt_provider") or "deepgram").strip().lower()

    prompt_tokens = int(getattr(usage_summary, "llm_prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage_summary, "llm_completion_tokens", 0) or 0)
    tts_characters = int(getattr(usage_summary, "tts_characters_count", 0) or 0)
    stt_audio_seconds = float(getattr(usage_summary, "stt_audio_duration", 0.0) or 0.0)

    return CallUsageMetrics(
        llm_prompt_tokens=max(0, prompt_tokens),
        llm_completion_tokens=max(0, completion_tokens),
        llm_model=llm_model,
        tts_characters=max(0, tts_characters),
        tts_provider=tts_provider or "cartesia",
        telephony_seconds=max(0, int(telephony_seconds or 0)),
        stt_audio_seconds=max(0.0, stt_audio_seconds),
        stt_provider=stt_provider or "deepgram",
    )


async def record_call_usage_billing(
    tenant_id: int,
    metrics: CallUsageMetrics,
    *,
    encuesta_id: int | None = None,
) -> bool:
    """
    Registra consumo de una llamada en billing_service (Redis + Supabase).

    Idempotente por encuesta_id para evitar doble conteo si finalize se reintenta.
    Devuelve False si ya estaba registrado o tenant_id inválido.
    """
    if tenant_id <= 0:
        return False

    if encuesta_id and encuesta_id > 0:
        if not await _claim_billing_slot(encuesta_id):
            return False

    from services.billing_service import get_billing_service

    billing = get_billing_service()

    if metrics.llm_total_tokens > 0:
        await billing.log_llm_tokens(
            tenant_id,
            metrics.llm_prompt_tokens,
            metrics.llm_completion_tokens,
            metrics.llm_model,
        )

    if metrics.tts_characters > 0:
        await billing.log_tts_characters(
            tenant_id,
            metrics.tts_characters,
            metrics.tts_provider,
        )

    stt_secs = int(metrics.stt_audio_seconds)
    if stt_secs > 0:
        await billing.log_stt_audio_seconds(
            tenant_id,
            stt_secs,
            metrics.stt_provider,
        )

    if metrics.telephony_seconds > 0:
        await billing.log_telephony_seconds(tenant_id, metrics.telephony_seconds)

    return True


async def _claim_billing_slot(encuesta_id: int) -> bool:
    """Marca encuesta como facturada en Redis (SET NX)."""
    try:
        from services.redis_service import get_redis

        redis = await get_redis()
        key = f"ausarta:billing:recorded:encuesta:{encuesta_id}"
        claimed = await redis.set(key, "1", nx=True, ex=90 * 24 * 3600)
        return bool(claimed)
    except Exception:
        # Si Redis falla, preferimos registrar consumo antes que perderlo.
        return True
