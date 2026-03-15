"""E2E tests for endpoint access patterns — gated vs free."""

import httpx
import pytest

GATED_ENDPOINTS = [
    "/signals/buys",
    "/signals/shorts",
    "/subscriptions/status",
]

FREE_ENDPOINTS = [
    "/health",
    "/lps/pricing",
    "/wizards",
]


@pytest.mark.asyncio
async def test_gated_endpoints_return_402(client: httpx.AsyncClient) -> None:
    for path in GATED_ENDPOINTS:
        resp = await client.get(path)
        assert resp.status_code == 402, f"{path} returned {resp.status_code}, expected 402"


@pytest.mark.asyncio
async def test_free_endpoints_return_200(client: httpx.AsyncClient) -> None:
    for path in FREE_ENDPOINTS:
        resp = await client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}, expected 200"
