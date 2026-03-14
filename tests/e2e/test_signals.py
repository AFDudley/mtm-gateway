"""E2E tests for signal endpoints — x402 payment gating."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from conftest import X402PayFn


@pytest.mark.asyncio
async def test_signals_buys_without_payment_returns_402(
    client: httpx.AsyncClient,
) -> None:
    """Requesting /signals/buys without payment gets a 402."""
    resp = await client.get("/signals/buys")
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_signals_buys_with_payment_returns_signals(
    x402_pay: X402PayFn,
) -> None:
    """Paying for /signals/buys returns signal data."""
    resp = await x402_pay("/signals/buys", "GET")
    assert resp.status_code == 200

    data = resp.json()
    assert "signals" in data
    signals = data["signals"]
    assert isinstance(signals, list)

    if signals:
        sig = signals[0]
        assert "asset" in sig
        assert "action" in sig
        assert "confidence" in sig
        assert "entry" in sig
        assert "reasoning" in sig


@pytest.mark.asyncio
async def test_signals_shorts_with_payment(
    x402_pay: X402PayFn,
) -> None:
    """Paying for /signals/shorts returns at least one signal."""
    resp = await x402_pay("/signals/shorts", "GET")
    assert resp.status_code == 200

    data = resp.json()
    assert "signals" in data
    assert data["count"] >= 1
