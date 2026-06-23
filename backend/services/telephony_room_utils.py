"""Utilidades de nombres de sala LiveKit y datos_extra de encuestas."""

from __future__ import annotations

import json


def parse_datos_extra(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def extract_encuesta_id_from_room(room_name: str) -> int | None:
    """
    Extrae el encuesta_id del nombre de sala. Soporta:
      - Nuevo:   ..._encuesta_{id}
      - Intermedio: empresa_{id}_camp_{id}_call_{encuesta_id}
      - Legacy: último segmento numérico
    """
    try:
        if "encuesta_" in room_name:
            after_enc = room_name.split("encuesta_")[-1]
            candidate = after_enc.split("_")[0]
            if candidate.isdigit():
                return int(candidate)

        if "call_" in room_name:
            after_call = room_name.split("call_")[-1]
            candidate = after_call.split("_")[0]
            if candidate.isdigit():
                return int(candidate)

        parts = room_name.split("_")
        for segment in reversed(parts):
            if segment.isdigit():
                return int(segment)
        return None
    except Exception:
        return None
