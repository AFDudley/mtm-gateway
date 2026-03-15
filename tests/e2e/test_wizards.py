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
async def test_follow_wizard(x402_pay: x402HttpxClient) -> None:
    # Get a wizard id from the list first
    list_resp = await x402_pay.get("/wizards")
    assert list_resp.status_code == 200
    wizards = list_resp.json()["wizards"]
    if not wizards:
        pytest.skip("No wizards in registry — skipping follow test")

    wizard_id = wizards[0]["id"]
    resp = await x402_pay.post(f"/wizards/{wizard_id}/follow")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_unfollow_wizard(x402_pay: x402HttpxClient) -> None:
    # Get a wizard id from the list first
    list_resp = await x402_pay.get("/wizards")
    assert list_resp.status_code == 200
    wizards = list_resp.json()["wizards"]
    if not wizards:
        pytest.skip("No wizards in registry — skipping unfollow test")

    wizard_id = wizards[0]["id"]
    resp = await x402_pay.delete(f"/wizards/{wizard_id}/follow")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
