"""E2E tests for signal endpoints — payment gating."""

import httpx
import pytest


@pytest.mark.asyncio
async def test_signals_buys_without_payment_returns_402(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/signals/buys")
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_signals_shorts_without_payment_returns_402(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/signals/shorts")
    assert resp.status_code == 402
