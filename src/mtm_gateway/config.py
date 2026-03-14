"""Gateway configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class TierConfig:
    signals_per_day: int
    refreshes_per_day: int
    wizard_follows: int
    auto_execute: bool


TIER_THRESHOLDS: dict[str, Decimal] = {
    "free": Decimal("0"),
    "starter": Decimal("29"),
    "pro": Decimal("158"),
    "elite": Decimal("1000"),
}

TIER_CONFIGS: dict[str, TierConfig] = {
    "free": TierConfig(
        signals_per_day=3, refreshes_per_day=0, wizard_follows=0, auto_execute=False
    ),
    "starter": TierConfig(
        signals_per_day=10, refreshes_per_day=1, wizard_follows=1, auto_execute=False
    ),
    "pro": TierConfig(signals_per_day=50, refreshes_per_day=2, wizard_follows=3, auto_execute=True),
    "elite": TierConfig(
        signals_per_day=-1, refreshes_per_day=-1, wizard_follows=-1, auto_execute=True
    ),
}


def tier_from_spend(lifetime_spend: Decimal) -> str:
    """Determine tier from cumulative LPS spend. Tiers never decrease."""
    tier = "free"
    for name, threshold in TIER_THRESHOLDS.items():
        if lifetime_spend >= threshold:
            tier = name
    return tier


@dataclass(frozen=True)
class Settings:
    # Solana
    solana_rpc: str = field(default_factory=lambda: os.environ.get("SOLANA_RPC", ""))
    solana_wallet_address: str = field(
        default_factory=lambda: os.environ.get("SOLANA_WALLET_ADDRESS", "")
    )
    solana_wallet_private_key: str = field(
        default_factory=lambda: os.environ.get("SOLANA_WALLET_PRIVATE_KEY", "")
    )
    lps_mint_address: str = field(default_factory=lambda: os.environ.get("LPS_MINT_ADDRESS", ""))

    # Upstream
    backtest_upstream: str = field(
        default_factory=lambda: os.environ.get("BACKTEST_UPSTREAM", "http://k-solana-backtest:8000")
    )

    # x402
    x402_facilitator_url: str = field(
        default_factory=lambda: os.environ.get(
            "X402_FACILITATOR_URL", "https://api.cdp.coinbase.com/platform/v2/x402"
        )
    )

    # Pricing (LPS)
    signal_price: str = field(default_factory=lambda: os.environ.get("SIGNAL_PRICE", "0.10"))
    refresh_price: str = field(default_factory=lambda: os.environ.get("REFRESH_PRICE", "0.50"))
    receipt_price: str = field(default_factory=lambda: os.environ.get("RECEIPT_PRICE", "0.05"))
    device_register_price: str = field(
        default_factory=lambda: os.environ.get("DEVICE_REGISTER_PRICE", "0.01")
    )
    wizard_follow_price: str = field(
        default_factory=lambda: os.environ.get("WIZARD_FOLLOW_PRICE", "0.10")
    )
    wizard_signal_price: str = field(
        default_factory=lambda: os.environ.get("WIZARD_SIGNAL_PRICE", "2.00")
    )

    # laconicd
    laconicd_gql: str = field(default_factory=lambda: os.environ.get("LACONICD_GQL", ""))
    encryption_key: str = field(default_factory=lambda: os.environ.get("ENCRYPTION_KEY", ""))

    # Firebase
    firebase_service_account: Path = field(
        default_factory=lambda: Path(
            os.environ.get("FIREBASE_SERVICE_ACCOUNT", "/config/service-account.json")
        )
    )

    # Apple IAP (App Store Server API v2)
    apple_key_id: str = field(default_factory=lambda: os.environ.get("APPLE_KEY_ID", ""))
    apple_issuer_id: str = field(default_factory=lambda: os.environ.get("APPLE_ISSUER_ID", ""))
    apple_private_key_path: str = field(
        default_factory=lambda: os.environ.get("APPLE_PRIVATE_KEY_PATH", "/config/apple-key.p8")
    )
    apple_bundle_id: str = field(default_factory=lambda: os.environ.get("APPLE_BUNDLE_ID", ""))
    apple_environment: str = field(
        default_factory=lambda: os.environ.get("APPLE_ENVIRONMENT", "production")
    )

    # Scheduler
    signal_cycle_interval_hours: int = field(
        default_factory=lambda: int(os.environ.get("SIGNAL_CYCLE_INTERVAL_HOURS", "24"))
    )


def get_settings() -> Settings:
    return Settings()
