"""Pydantic models for gateway requests and responses.

Response shapes match what the MTM frontend expects:
- SignalState shape from src/store/index.ts:18-26
- Subscription shape from src/types/index.ts
- Wizard shape from src/types/index.ts
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


# --- Signal models ---


class SignalState(BaseModel):
    """Signal shape consumed by the frontend store's queueSignal().
    Matches src/store/index.ts:18-26.
    """

    id: str
    asset: str
    action: str  # "BUY" or "SELL"
    confidence: float  # 0.0 - 1.0
    entry: float
    reasoning: str
    channelId: str | None = None


class SignalsResponse(BaseModel):
    signals: list[SignalState]
    count: int
    remaining: int  # signals remaining today for this tier


# --- Upstream backtest models (from k_solana_backtest) ---


class BacktestSignalEntry(BaseModel):
    """Shape returned by k_solana_backtest /api/signals/buys and /shorts."""

    token: str
    strategies_firing: list[str]
    n_strategies: int
    spot_price: float
    as_of_date: str


class BacktestSignalsResponse(BaseModel):
    signals: list[BacktestSignalEntry]
    count: int


# --- Subscription / tier models ---


class TierInfo(BaseModel):
    tier: str
    lifetime_spend: float
    next_tier_at: float | None
    next_tier: str | None
    signals_per_day: int
    refreshes_per_day: int
    wizard_follows: int
    auto_execute: bool


class SubscriptionStatus(BaseModel):
    tier: str
    lifetimeSpend: float
    nextTierAt: float | None
    nextTier: str | None
    signalsPerDay: int
    kolChannels: int
    refreshesPerDay: int
    autoExecute: bool
    txFeePercent: float = 1.0


class LpsPricing(BaseModel):
    signalRefresh: float
    signalExecution: float
    wizardSignalSend: float
    laconicWallet: str


# --- Device registration ---


class DeviceRegisterRequest(BaseModel):
    fcmToken: str
    platform: str = "ios"
    appVersion: str = "1.0.0"


class DeviceUnregisterRequest(BaseModel):
    fcmToken: str


# --- Signal receipt ---


class SignalReceiptRequest(BaseModel):
    signalId: str
    action: str  # "APPROVE" or "REJECT"
    walletAddress: str
    lpsTxSignature: str | None = None
    lpsAmount: float | None = None
    asset: str
    timestamp: int
    execution: dict | None = None


# --- Wizard models ---


class Wizard(BaseModel):
    id: str
    name: str
    handle: str
    avatarUrl: str | None = None
    bio: str | None = None
    winRate: float = 0
    avgReturn: float = 0
    signalsPerMonth: int = 0
    followers: int = 0
    verified: bool = False
    walletAddress: str = ""
    createdAt: str = ""


# --- Apple IAP models ---


class VerifyReceiptRequest(BaseModel):
    """Matches the body sent by iap.ts:56-59 via api.verifyReceipt()."""

    receipt: str  # JWS signed transaction from StoreKit 2
    platform: str  # "ios" or "android"
    productId: str  # e.g. "mtm_starter_monthly"


class VerifyReceiptResponse(BaseModel):
    """Matches the response shape expected by api.ts:156-161."""

    success: bool
    lpsAmount: float
    lpsTxSignature: str
    lifetimeSpend: float
    tier: str


# --- Wizard models ---


class WizardSignalRequest(BaseModel):
    asset: str
    action: str
    confidence: float
    entry: float
    reasoning: str
    duration: str = "15m"
    executionCommands: dict | None = None
