"""Tests de liberación de recursos WebRTC/LiveKit en CallSession."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.dynamic_agent import CallSession


def _make_session(**overrides):
    defaults = dict(
        ctx=SimpleNamespace(room=SimpleNamespace(disconnect=AsyncMock())),
        job_id="job-1",
        room_name="empresa_1_camp_1_call_1",
        survey_id="42",
        agent_config={"empresa_id": 1},
        session=SimpleNamespace(aclose=AsyncMock()),
        agent_instance=SimpleNamespace(_transfer_completed=None),
        language="es",
        voice_id="v1",
        speaking_speed=1.0,
        tts_model="tts",
        call_start_time=0.0,
    )
    defaults.update(overrides)
    return CallSession(**defaults)


@pytest.mark.asyncio
async def test_cleanup_is_idempotent():
    cs = _make_session()
    cs.bg_player = SimpleNamespace(aclose=AsyncMock())
    cs.transcript_event_buffer.append({"role": "user", "content": "hola"})

    with patch("agents.livekit_client.close_livekit_admin_api", new=AsyncMock()):
        await cs.cleanup()
        await cs.cleanup()

    assert cs._cleanup_done is True
    assert cs.bg_player is None
    assert cs.transcript_event_buffer == []
    cs.session.aclose.assert_awaited_once()
    cs.ctx.room.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_cancels_background_tasks():
    cs = _make_session()
    blocker = asyncio.Event()

    async def blocked():
        await blocker.wait()

    cs._tasks.append(asyncio.create_task(blocked()))
    cs._ephemeral_tasks.append(asyncio.create_task(blocked()))

    with patch("agents.livekit_client.close_livekit_admin_api", new=AsyncMock()):
        await cs.cleanup()

    assert cs._tasks == []
    assert cs._ephemeral_tasks == []


@pytest.mark.asyncio
async def test_spawn_ephemeral_tracks_and_untracks_tasks():
    cs = _make_session()

    async def quick():
        return 1

    task = cs._spawn_ephemeral(quick())
    await task
    await asyncio.sleep(0)
    assert task not in cs._ephemeral_tasks


@pytest.mark.asyncio
async def test_livekit_client_singleton_and_close():
    from agents import livekit_client as lk

    lk._client = None
    mock_api = MagicMock()
    mock_api.aclose = AsyncMock()

    with patch("agents.livekit_client.lk_api.LiveKitAPI", return_value=mock_api), patch.dict(
        "os.environ",
        {"LIVEKIT_URL": "wss://x", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s"},
    ):
        first = await lk.get_livekit_admin_api()
        second = await lk.get_livekit_admin_api()
        assert first is second
        await lk.close_livekit_admin_api()
        assert lk._client is None
    mock_api.aclose.assert_awaited_once()
