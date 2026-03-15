"""E2E tests for subscription tier status endpoint."""

import pytest
from x402.http.clients.httpx import x402HttpxClient


VALID_TIERS = {"free", "starter", "pro", "elite"}


@pytest.mark.asyncio
async def test_subscription_status_returns_tier(x402_pay: x402HttpxClient) -> None:
    resp = await x402_pay.get("/subscriptions/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "tier" in data
    assert data["tier"] in VALID_TIERS, f"Unknown tier: {data['tier']}"
