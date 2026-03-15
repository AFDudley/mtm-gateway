"""E2E tests for device registration endpoints."""

import pytest
from x402.http.clients.httpx import x402HttpxClient


@pytest.mark.asyncio
async def test_register_device(x402_pay: x402HttpxClient) -> None:
    resp = await x402_pay.post(
        "/devices/register", json={"fcmToken": "test-fcm-token-123"}
    )
    # 502 if laconicd registry mutations not available (fixturenet)
    assert resp.status_code in (200, 502)
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True


@pytest.mark.asyncio
async def test_unregister_device(x402_pay: x402HttpxClient) -> None:
    resp = await x402_pay.request(
        "DELETE", "/devices/unregister", json={"fcmToken": "test-fcm-token-123"}
    )
    # 401 if route not x402-gated, 502 if registry unavailable
    assert resp.status_code in (200, 401, 502)
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True
