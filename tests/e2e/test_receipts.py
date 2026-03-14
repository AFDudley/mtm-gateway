"""E2E tests for signal receipt endpoint."""

import pytest
from x402.http.clients.httpx import x402HttpxClient


@pytest.mark.asyncio
async def test_post_receipt(x402_pay: x402HttpxClient) -> None:
    resp = await x402_pay.post(
        "/signals/receipt",
        json={
            "signalId": "test-signal-1",
            "action": "APE",
            "asset": "BONK",
            "walletAddress": "test-wallet",
            "timestamp": 1700000000,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
