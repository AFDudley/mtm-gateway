"""E2E tests for the /health endpoint."""

import httpx
import pytest


@pytest.mark.asyncio
async def test_health_returns_200(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_response_shape(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    data = resp.json()
    assert data["status"] == "ok"
