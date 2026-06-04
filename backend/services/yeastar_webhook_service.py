from __future__ import annotations

import json
import logging

from services.supabase_service import supabase, sb_query

logger = logging.getLogger("api-backend")


def normalize_yeastar_webhook_payload(payload: dict) -> tuple[str | None, list[str]]:
    """
    Unifica payloads legacy (action/callid) y P-Series Cloud (type + msg con call_id).
    Evento recomendado en Yeastar: 30011 Call State Changed.
    """
    msg = payload.get("msg")
    if isinstance(msg, str):
        try:
            msg = json.loads(msg)
        except Exception:
            msg = {}
    if not isinstance(msg, dict):
        msg = {}

    call_id = (
        payload.get("callid")
        or payload.get("call_id")
        or msg.get("call_id")
        or msg.get("callid")
    )
    if call_id is not None:
        call_id = str(call_id).strip() or None

    phones: list[str] = []
    for key in (
        "caller", "from", "src", "callernumber",
        "callee", "to", "dst", "calleenumber",
    ):
        val = payload.get(key)
        if val:
            phones.append(str(val))

    members = msg.get("members")
    if isinstance(members, str):
        try:
            members = json.loads(members)
        except Exception:
            members = []
    if isinstance(members, list):
        for member in members:
            if not isinstance(member, dict):
                continue
            for section in ("extension", "inbound", "outbound", "internal"):
                block = member.get(section)
                if not isinstance(block, dict):
                    continue
                for key in ("from", "to", "number"):
                    val = block.get(key)
                    if val:
                        phones.append(str(val))

    return call_id, phones


def extract_yeastar_channel_id(payload: dict) -> str | None:
    """Obtiene el canal de la parte externa a transferir desde el evento 30011."""
    msg = payload.get("msg")
    if isinstance(msg, str):
        try:
            msg = json.loads(msg)
        except Exception:
            msg = {}
    if not isinstance(msg, dict):
        return None

    members = msg.get("members")
    if isinstance(members, str):
        try:
            members = json.loads(members)
        except Exception:
            members = []
    if not isinstance(members, list):
        return None

    for section in ("inbound", "outbound", "extension", "internal"):
        for member in members:
            block = member.get(section) if isinstance(member, dict) else None
            channel_id = block.get("channel_id") if isinstance(block, dict) else None
            if channel_id:
                return str(channel_id)
    return None


def _phone_lookup_values(phone_candidates: list[str]) -> list[str]:
    values: set[str] = set()
    for raw_phone in phone_candidates:
        raw = str(raw_phone or "").strip()
        digits = "".join(c for c in raw if c.isdigit())
        if len(digits) < 6:
            continue

        values.add(raw)
        values.add(digits)

        if len(digits) >= 9:
            tail = digits[-9:]
            values.add(tail)
            values.add(f"+34{tail}")
            values.add(f"34{tail}")

        if raw.startswith("+"):
            values.add(raw.replace(" ", ""))

    return sorted(v for v in values if v)


def _parse_extra(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def process_yeastar_webhook_payload(payload: dict) -> None:
    """
    Procesa eventos Yeastar de forma durable desde ARQ.
    Usa una única consulta a Supabase para cruzar todos los teléfonos candidatos.
    """
    try:
        event_label = payload.get("action") or payload.get("type")
        call_id, phone_candidates = normalize_yeastar_webhook_payload(payload)
        channel_id = extract_yeastar_channel_id(payload)
        logger.info(
            "[Yeastar Worker] Evento %s - callid=%s, telefonos=%d",
            event_label,
            call_id,
            len(phone_candidates),
        )

        if not call_id or not supabase:
            return

        lookup_values = _phone_lookup_values(phone_candidates)
        if not lookup_values:
            logger.info("[Yeastar Worker] Evento sin telefonos utiles para callid=%s", call_id)
            return

        enc_res = await sb_query(
            lambda values=lookup_values: supabase.table("encuestas")
            .select("id, telefono, datos_extra")
            .in_("status", ["initiated", "calling", "in_progress"])
            .in_("telefono", values)
            .order("id", desc=True)
            .execute()
        )
        rows = enc_res.data or []
        if not rows:
            logger.info(
                "[Yeastar Worker] Sin encuesta activa para callid=%s telefonos=%s",
                call_id,
                lookup_values,
            )
            return

        by_phone = {str(row.get("telefono") or ""): row for row in rows}
        row = next((by_phone.get(value) for value in lookup_values if by_phone.get(value)), rows[0])

        extra = _parse_extra(row.get("datos_extra"))
        extra["yeastar_callid"] = str(call_id)
        if channel_id:
            extra["yeastar_channel_id"] = channel_id
        await sb_query(
            lambda eid=row["id"], ex=extra: supabase.table("encuestas")
            .update({"datos_extra": ex})
            .eq("id", eid)
            .execute()
        )
        logger.info(
            "[Yeastar Worker] callid %s vinculado a encuesta %s",
            call_id,
            row["id"],
        )

    except Exception as exc:
        logger.error("[Yeastar Worker] Error procesando webhook: %s", exc)
        raise
