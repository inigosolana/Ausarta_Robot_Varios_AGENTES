"""Tests HMAC webhooks (anti-spoofing)."""
from __future__ import annotations

import json
import time

import pytest

from services.webhook_signature import (
    build_outbound_webhook_headers,
    compute_webhook_signature,
    serialize_webhook_json,
    verify_webhook_signature,
    verify_webhook_timestamp,
    webhook_hmac_required,
)


def test_compute_and_verify_signature():
    secret = "test-secret"
    body = b'{"empresa_id":1,"action":"create"}'
    sig = compute_webhook_signature(secret, body)
    assert verify_webhook_signature(secret, body, f"sha256={sig}")
    assert verify_webhook_signature(secret, body, sig)
    assert verify_webhook_signature(secret, body, f"v1={sig}")
    assert not verify_webhook_signature(secret, body, "sha256=deadbeef")
    assert not verify_webhook_signature(secret, body + b"x", f"sha256={sig}")


def test_serialize_webhook_json_is_stable():
    payload = {"b": 2, "a": 1}
    assert serialize_webhook_json(payload) == b'{"a":1,"b":2}'


def test_build_outbound_headers_include_signature():
    body = b'{"email":"a@b.com"}'
    headers = build_outbound_webhook_headers("s3cr3t", body)
    assert headers["X-Signature"].startswith("sha256=")
    assert int(headers["X-Webhook-Timestamp"]) > 0


def test_timestamp_skew_rejected_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("WEBHOOK_REQUIRE_HMAC", raising=False)
    assert webhook_hmac_required() is True
    old_ts = str(int(time.time()) - 600)
    assert verify_webhook_timestamp(old_ts) is False
    assert verify_webhook_timestamp(None) is False


def test_timestamp_optional_in_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert verify_webhook_timestamp(None) is True


@pytest.mark.asyncio
async def test_campaign_webhook_rejects_bad_hmac(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from api import app

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("N8N_PROXY_SECRET", "prod-secret")
    payload = {
        "empresa_id": 1,
        "name": "Test",
        "leads": [{"phone_number": "+34600000000", "customer_name": "Test"}],
    }
    body = json.dumps(payload).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/api/webhook/campaign",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": "sha256=invalid",
                "X-Webhook-Timestamp": str(int(time.time())),
            },
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_campaign_webhook_accepts_valid_hmac(monkeypatch):
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from api import app

    secret = "prod-secret"
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("N8N_PROXY_SECRET", secret)
    payload = {
        "empresa_id": 1,
        "name": "Test",
        "leads": [{"phone_number": "+34600000000", "customer_name": "Test"}],
    }
    body = json.dumps(payload).encode()
    sig = compute_webhook_signature(secret, body)
    with patch(
        "routers.campaign_webhook.process_campaign_webhook",
        new=AsyncMock(return_value={"status": "ok", "campaign_id": 99}),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/webhook/campaign",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": f"sha256={sig}",
                    "X-Webhook-Timestamp": str(int(time.time())),
                },
            )
    assert response.status_code == 200
    assert response.json()["campaign_id"] == 99
