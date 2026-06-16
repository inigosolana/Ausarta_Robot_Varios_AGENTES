import pytest
from httpx import AsyncClient, ASGITransport
from api import app

@pytest.mark.asyncio
async def test_root():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Ausarta Backend v2", "database": "Supabase"}

@pytest.mark.asyncio
async def test_dashboard_stats():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/dashboard/stats")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_get_voices_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/voices")
    assert response.status_code == 401

