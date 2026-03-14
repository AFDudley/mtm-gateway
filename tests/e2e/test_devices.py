"""E2E tests for device registration endpoints."""

import pytest
from x402.http.clients.httpx import x402HttpxClient


@pytest.mark.asyncio
async def test_register_device(x402_pay: x402HttpxClient) -> None:
    resp = await x402_pay.post(
        "/devices/register", json={"fcmToken": "test-fcm-token-123"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_unregister_device(x402_pay: x402HttpxClient) -> None:
    resp = await x402_pay.delete(
        "/devices/unregister", json={"fcmToken": "test-fcm-token-123"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
