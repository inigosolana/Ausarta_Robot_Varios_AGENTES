"""Asignación A/B de agentes en campañas outbound."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

AbVariant = Literal["A", "B"]


@dataclass(frozen=True, slots=True)
class AbAssignment:
    variant: AbVariant
    agent_id: int
    ab_test_enabled: bool


def is_ab_test_active(campaign: dict[str, Any]) -> bool:
    if not campaign.get("ab_test_enabled"):
        return False
    agent_b = campaign.get("agent_id_b")
    agent_a = campaign.get("agent_id")
    if agent_b is None or agent_a is None:
        return False
    return int(agent_b) != int(agent_a)


def pick_ab_variant(
    *,
    lead_id: int,
    campaign_id: int,
    split_ratio: float = 0.5,
) -> AbVariant:
    """
    Asignación determinista por lead (mismo lead → misma variante en reintentos).
    split_ratio: fracción para variante A (0.5 = 50/50).
    """
    ratio = max(0.0, min(float(split_ratio), 1.0))
    digest = hashlib.sha256(f"{campaign_id}:{lead_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return "A" if bucket < ratio else "B"


def assign_ab_variant(campaign: dict[str, Any], lead_id: int) -> AbAssignment:
    """Resuelve variante y agent_id efectivo para un lead de campaña."""
    agent_a = int(campaign.get("agent_id") or 1)
    if not is_ab_test_active(campaign):
        return AbAssignment(variant="A", agent_id=agent_a, ab_test_enabled=False)

    split_raw = campaign.get("ab_split_ratio")
    split_ratio = 0.5 if split_raw is None else float(split_raw)
    variant = pick_ab_variant(
        lead_id=int(lead_id),
        campaign_id=int(campaign["id"]),
        split_ratio=split_ratio,
    )
    agent_b = int(campaign["agent_id_b"])
    agent_id = agent_a if variant == "A" else agent_b

    logger.info(
        "[AB] campaña=%s lead=%s → variante %s agent_id=%s (split=%.2f)",
        campaign.get("id"),
        lead_id,
        variant,
        agent_id,
        split_ratio,
    )
    return AbAssignment(variant=variant, agent_id=agent_id, ab_test_enabled=True)


def validate_ab_campaign_payload(payload: dict[str, Any]) -> str | None:
    """Devuelve mensaje de error o None si la config A/B es válida."""
    if not payload.get("ab_test_enabled"):
        return None
    agent_a = payload.get("agent_id")
    agent_b = payload.get("agent_id_b")
    if agent_b is None:
        return "agent_id_b es obligatorio cuando ab_test_enabled=true"
    if agent_a is not None and int(agent_a) == int(agent_b):
        return "agent_id_b debe ser distinto de agent_id"
    ratio = payload.get("ab_split_ratio", 0.5)
    try:
        ratio_f = float(ratio)
    except (TypeError, ValueError):
        return "ab_split_ratio debe ser un número entre 0 y 1"
    if not 0.0 <= ratio_f <= 1.0:
        return "ab_split_ratio debe estar entre 0 y 1"
    return None


_COMPLETED_STATUSES = {"completed", "transferred"}


def compute_campaign_ab_stats(campaign: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, dict[str, Any]] = {
        "A": {
            "calls": 0,
            "completed": 0,
            "completion_rate": 0.0,
            "avg_score": None,
            "agent_id": campaign.get("agent_id"),
        },
        "B": {
            "calls": 0,
            "completed": 0,
            "completion_rate": 0.0,
            "avg_score": None,
            "agent_id": campaign.get("agent_id_b"),
        },
    }
    score_sums: dict[str, float] = {"A": 0.0, "B": 0.0}
    score_counts: dict[str, int] = {"A": 0, "B": 0}

    for row in rows:
        variant = (row.get("ab_variant") or "A").upper()
        if variant not in stats:
            variant = "A"
        stats[variant]["calls"] += 1
        status = (row.get("status") or "").lower()
        if status in _COMPLETED_STATUSES:
            stats[variant]["completed"] += 1

        score = row.get("puntuacion_comercial")
        if score is None and isinstance(row.get("agent_results"), dict):
            scores = row["agent_results"].get("scores") or {}
            score = scores.get("comercial")
        if isinstance(score, (int, float)):
            score_sums[variant] += float(score)
            score_counts[variant] += 1

    for variant, data in stats.items():
        calls = data["calls"]
        if calls:
            data["completion_rate"] = round(data["completed"] / calls, 4)
        if score_counts[variant]:
            data["avg_score"] = round(score_sums[variant] / score_counts[variant], 2)

    return {
        "campaign_id": campaign.get("id"),
        "ab_test_enabled": bool(campaign.get("ab_test_enabled")),
        "ab_split_ratio": campaign.get("ab_split_ratio"),
        "variants": stats,
        "total_calls": len(rows),
    }

