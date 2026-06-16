"""Construye y fusiona agent_results JSON por tipo de agente."""
from __future__ import annotations

import copy
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
