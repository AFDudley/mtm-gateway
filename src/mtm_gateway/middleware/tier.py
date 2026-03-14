"""Tier computation middleware.

Determines user tier from on-chain LPS transfer history and enforces
daily quotas. Quotas are in-memory and reset at midnight UTC — not persisted.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

from mtm_gateway.config import TIER_CONFIGS, TIER_THRESHOLDS, Settings, tier_from_spend
from mtm_gateway.models import TierInfo
from mtm_gateway.services.solana_rpc import get_lifetime_lps_spend

logger = logging.getLogger(__name__)

# In-memory daily usage counters: {wallet: {"signals": N, "refreshes": N, "date": "YYYY-MM-DD"}}
_daily_usage: dict[str, dict] = defaultdict(lambda: {"signals": 0, "refreshes": 0, "date": ""})


def _reset_if_new_day(wallet: str) -> None:
    """Reset daily counters if the date has changed."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if _daily_usage[wallet]["date"] != today:
        _daily_usage[wallet] = {"signals": 0, "refreshes": 0, "date": today}


def get_tier_info(wallet_address: str, settings: Settings) -> TierInfo:
    """Compute tier and quota info for a wallet address."""
    lifetime_spend = get_lifetime_lps_spend(
        rpc_url=settings.solana_rpc,
        wallet_address=wallet_address,
        service_wallet=settings.solana_wallet_address,
        lps_mint=settings.lps_mint_address,
    )

    tier = tier_from_spend(lifetime_spend)
    config = TIER_CONFIGS[tier]

    # Find next tier
    next_tier = None
    next_tier_at = None
    tier_names = list(TIER_THRESHOLDS.keys())
    current_idx = tier_names.index(tier)
    if current_idx < len(tier_names) - 1:
        next_tier = tier_names[current_idx + 1]
        next_tier_at = float(TIER_THRESHOLDS[next_tier])

    return TierInfo(
        tier=tier,
        lifetime_spend=float(lifetime_spend),
        next_tier_at=next_tier_at,
        next_tier=next_tier,
        signals_per_day=config.signals_per_day,
        refreshes_per_day=config.refreshes_per_day,
        wizard_follows=config.wizard_follows,
        auto_execute=config.auto_execute,
    )


def check_signal_quota(wallet_address: str, settings: Settings) -> tuple[bool, int]:
    """Check if wallet has remaining signal quota for today.

    Returns (allowed, remaining).
    -1 for unlimited tiers means always allowed.
    """
    _reset_if_new_day(wallet_address)
    tier_info = get_tier_info(wallet_address, settings)
    limit = tier_info.signals_per_day

    if limit == -1:
        return True, -1

    used = _daily_usage[wallet_address]["signals"]
    remaining = max(0, limit - used)
    return remaining > 0, remaining


def record_signal_use(wallet_address: str) -> None:
    """Record that a signal was consumed."""
    _reset_if_new_day(wallet_address)
    _daily_usage[wallet_address]["signals"] += 1


def check_refresh_quota(wallet_address: str, settings: Settings) -> tuple[bool, int]:
    """Check if wallet has remaining refresh quota for today."""
    _reset_if_new_day(wallet_address)
    tier_info = get_tier_info(wallet_address, settings)
    limit = tier_info.refreshes_per_day

    if limit == -1:
        return True, -1

    used = _daily_usage[wallet_address]["refreshes"]
    remaining = max(0, limit - used)
    return remaining > 0, remaining


def record_refresh_use(wallet_address: str) -> None:
    """Record that a refresh was consumed."""
    _reset_if_new_day(wallet_address)
    _daily_usage[wallet_address]["refreshes"] += 1
