"""Tests de simulación y exportación de campañas."""

from services.campaign_export_service import build_campaign_results_csv


def test_build_campaign_results_csv_includes_anger_fields():
    csv_text = build_campaign_results_csv(
        [
            {
                "id": 1,
                "telefono": "+34600",
                "fecha": "2026-06-22T10:00:00Z",
                "status": "completed",
                "seconds_used": 90,
                "comentarios": "ok",
                "agent_results": {
                    "analysis": {
                        "customer_anger_score": 8,
                        "requires_urgent_human_attention": True,
                    }
                },
            }
        ]
    )
    assert "customer_anger_score" in csv_text
    assert ",8," in csv_text or ",8\n" in csv_text
    assert "True" in csv_text
