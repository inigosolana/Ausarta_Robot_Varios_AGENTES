"""Exportación de resultados de campaña."""

from __future__ import annotations

import csv
import io
from typing import Any


def build_campaign_results_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = [
        "id",
        "telefono",
        "fecha",
        "status",
        "seconds_used",
        "comentarios",
        "customer_anger_score",
        "requires_urgent_human_attention",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        extra = row.get("datos_extra") if isinstance(row.get("datos_extra"), dict) else {}
        analysis = {}
        ar = row.get("agent_results")
        if isinstance(ar, dict) and isinstance(ar.get("analysis"), dict):
            analysis = ar["analysis"]
        writer.writerow(
            {
                "id": row.get("id"),
                "telefono": row.get("telefono"),
                "fecha": row.get("fecha"),
                "status": row.get("status"),
                "seconds_used": row.get("seconds_used"),
                "comentarios": (row.get("comentarios") or "")[:500],
                "customer_anger_score": analysis.get("customer_anger_score")
                or extra.get("customer_anger_score"),
                "requires_urgent_human_attention": analysis.get("requires_urgent_human_attention")
                if "requires_urgent_human_attention" in analysis
                else extra.get("requires_urgent_human_attention"),
            }
        )
    return output.getvalue()
