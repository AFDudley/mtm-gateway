"""E2E tests for wizard endpoints."""

import httpx
import pytest
from x402.http.clients.httpx import x402HttpxClient


@pytest.mark.asyncio
async def test_list_wizards(client: httpx.AsyncClient) -> None:
    resp = await client.get("/wizards")
    assert resp.status_code == 200
    data = resp.json()
    assert "wizards" in data
    assert isinstance(data["wizards"], list)


@pytest.mark.asyncio
async def test_follow_wizard_free_tier_rejected(x402_pay: x402HttpxClient) -> None:
    """Free-tier wallets (no LPS spend history) get 403 on follow.

    Wizard follows require at least 'starter' tier (29 LPS lifetime spend).
    The test wallet has no prior spend, so it's free tier with wizard_follows=0.
    """
    list_resp = await x402_pay.get("/wizards")
    assert list_resp.status_code == 200
    wizards = list_resp.json()["wizards"]
    assert len(wizards) > 0, "No wizards in registry — seed data missing from test environment"

    wizard_id = wizards[0]["id"]
    resp = await x402_pay.post(f"/wizards/{wizard_id}/follow")
    assert resp.status_code == 403

    data = resp.json()
    detail = data["detail"]
    assert detail["error"] == "tier_required"
    assert detail["requiredTier"] == "starter"


@pytest.mark.asyncio
async def test_unfollow_wizard(x402_pay: x402HttpxClient) -> None:
    # Follow first, then unfollow — test environment must have seed data
    list_resp = await x402_pay.get("/wizards")
    assert list_resp.status_code == 200
    wizards = list_resp.json()["wizards"]
    assert len(wizards) > 0, "No wizards in registry — seed data missing from test environment"

    wizard_id = wizards[0]["id"]
    # Follow attempt gets 403 (free tier) but unfollow has no tier check
    await x402_pay.post(f"/wizards/{wizard_id}/follow")
    resp = await x402_pay.delete(f"/wizards/{wizard_id}/follow")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
