import asyncio
import pytest

from services import sip_call_service


@pytest.mark.asyncio
async def test_create_sip_participant_with_retry_succeeds_second_attempt(monkeypatch):
    calls = {"n": 0}

    class FakeSip:
        async def create_sip_participant(self, _request):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("sip busy")
            return {"ok": True}

    class FakeLk:
        sip = FakeSip()

    monkeypatch.setattr(sip_call_service, "sip_retry_max_attempts", lambda: 3)
    monkeypatch.setattr(sip_call_service, "sip_retry_base_delay", lambda: 0.01)

    import services.livekit_service as lk_mod

    monkeypatch.setattr(lk_mod, "lkapi", FakeLk())

    result = await sip_call_service.create_sip_participant_with_retry(
        object(),
        skip_guard=True,
    )
    assert result["ok"] is True
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_create_sip_participant_with_retry_raises_after_max(monkeypatch):
    class FakeSip:
        async def create_sip_participant(self, _request):
            raise RuntimeError("trunk down")

    import services.livekit_service as lk_mod

    monkeypatch.setattr(lk_mod, "lkapi", type("L", (), {"sip": FakeSip()})())
    monkeypatch.setattr(sip_call_service, "sip_retry_max_attempts", lambda: 2)
    monkeypatch.setattr(sip_call_service, "sip_retry_base_delay", lambda: 0.01)

    with pytest.raises(RuntimeError, match="trunk down"):
        await sip_call_service.create_sip_participant_with_retry(object(), skip_guard=True)


def test_sip_retry_max_attempts_default():
    assert sip_call_service.sip_retry_max_attempts() >= 1
