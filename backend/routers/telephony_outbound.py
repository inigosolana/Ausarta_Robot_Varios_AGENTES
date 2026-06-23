"""Endpoints de llamadas salientes LiveKit SIP."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from models.schemas import TestOutboundCallRequest
from services.auth import require_outbound_auth
from services.telephony_outbound_service import make_outbound_call, test_outbound_call

router = APIRouter(tags=["telephony"])


@router.post("/api/telephony/test-outbound")
async def test_outbound_call_endpoint(payload: TestOutboundCallRequest):
    return await test_outbound_call(payload)


@router.post("/api/calls/outbound")
async def make_outbound_call_endpoint(request: dict, _auth: str = Depends(require_outbound_auth)):
    return await make_outbound_call(request, _auth)
