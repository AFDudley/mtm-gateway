"""E2E tests for subscription verification endpoint."""

import pytest
from x402.http.clients.httpx import x402HttpxClient


@pytest.mark.asyncio
async def test_verify_receipt_without_jws_returns_error(
    x402_pay: x402HttpxClient,
) -> None:
    resp = await x402_pay.post("/subscriptions/verify-receipt", json={})
    assert resp.status_code == 422
