from __future__ import annotations

from datetime import datetime
from typing import Iterable

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def _normalize_forbidden_weekdays(values: Iterable[int] | None) -> set[int]:
    normalized: set[int] = set()
    for raw in values or []:
        try:
            day = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6:
            normalized.add(day)
    return normalized


def is_call_allowed(
    now: datetime,
    timezone_str: str = "Europe/Madrid",
    allowed_hours: tuple = (9, 21),  # 9:00 - 21:00
    forbidden_weekdays: set = {6},  # 0=lunes, 6=domingo
) -> tuple[bool, str]:
    """
    Devuelve (True, "") si se puede llamar ahora en la timezone indicada.
    Si no se puede, devuelve (False, "motivo").
    """
    if now.tzinfo is None:
        return False, "datetime sin timezone"

    if ZoneInfo is None:
        return False, "zoneinfo no disponible"

    try:
        tz = ZoneInfo((timezone_str or "Europe/Madrid").strip())
    except Exception:
        tz = ZoneInfo("Europe/Madrid")
        timezone_str = "Europe/Madrid"

    local_now = now.astimezone(tz)
    weekdays = _normalize_forbidden_weekdays(forbidden_weekdays)

    start_hour_raw, end_hour_raw = allowed_hours if len(allowed_hours) == 2 else (9, 21)
    try:
        start_hour = int(start_hour_raw)
        end_hour = int(end_hour_raw)
    except (TypeError, ValueError):
        start_hour, end_hour = 9, 21

    start_hour = max(0, min(start_hour, 23))
    end_hour = max(1, min(end_hour, 24))

    if local_now.weekday() in weekdays:
        return False, f"weekday bloqueado ({local_now.weekday()}) en {timezone_str}"

    hour_now = local_now.hour
    if hour_now < start_hour or hour_now >= end_hour:
        return False, (
            f"fuera de horario {start_hour:02d}:00-{end_hour:02d}:00 "
            f"({hour_now:02d}:00 local {timezone_str})"
        )

    return True, ""
