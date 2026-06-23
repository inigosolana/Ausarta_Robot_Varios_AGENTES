"""Tests de métricas de detalle de campaña."""

from __future__ import annotations

from services.campaign_ab_service import compute_campaign_ab_stats
from services.campaign_details_service import enrich_campaign_leads, apply_lead_status_summary


def test_enrich_campaign_leads_computes_averages():
    leads = [
        {"id": 1, "status": "completed", "call_id": 10},
        {"id": 2, "status": "pending", "call_id": None},
    ]
    surveys = {
        10: {
            "puntuacion_comercial": 8,
            "puntuacion_instalador": 6,
            "puntuacion_rapidez": 10,
            "comentarios": "ok",
            "transcription": "hola",
        }
    }
    enriched, metrics, status_counts = enrich_campaign_leads(leads, surveys)
    assert len(enriched) == 2
    assert enriched[0]["puntuacion_comercial"] == 8
    assert metrics["avg_comercial"] == 8.0
    assert metrics["avg_instalador"] == 6.0
    assert metrics["avg_rapidez"] == 10.0
    assert status_counts["completed"] == 1
    assert status_counts["pending"] == 1


def test_apply_lead_status_summary():
    campaign: dict = {}
    leads = [{"id": 1}, {"id": 2}, {"id": 3}]
    status_counts = {"pending": 1, "calling": 1, "completed": 1}
    apply_lead_status_summary(campaign, leads, status_counts)
    assert campaign["total_leads"] == 3
    assert campaign["called_leads"] == 1
    assert campaign["pending_leads"] == 2
    assert campaign["completed_leads"] == 1


def test_compute_campaign_ab_stats():
    campaign = {
        "id": 5,
        "agent_id": 1,
        "agent_id_b": 2,
        "ab_test_enabled": True,
        "ab_split_ratio": 0.5,
    }
    rows = [
        {"ab_variant": "A", "status": "completed", "puntuacion_comercial": 8},
        {"ab_variant": "B", "status": "failed", "puntuacion_comercial": 4},
        {"ab_variant": "B", "status": "transferred", "agent_results": {"scores": {"comercial": 6}}},
    ]
    result = compute_campaign_ab_stats(campaign, rows)
    assert result["total_calls"] == 3
    assert result["variants"]["A"]["calls"] == 1
    assert result["variants"]["B"]["calls"] == 2
    assert result["variants"]["A"]["completed"] == 1
    assert result["variants"]["B"]["completed"] == 1
    assert result["variants"]["A"]["avg_score"] == 8.0
    assert result["variants"]["B"]["avg_score"] == 5.0
