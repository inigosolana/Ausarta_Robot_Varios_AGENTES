import pytest
from httpx import AsyncClient, ASGITransport
from api import app

@pytest.mark.asyncio
async def test_root():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Ausarta Backend", "database": "Supabase"}

@pytest.mark.asyncio
async def test_dashboard_stats():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/dashboard/stats")
    assert response.status_code == 200
    assert "total_calls" in response.json()
