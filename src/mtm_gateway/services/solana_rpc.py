"""Solana RPC queries for tier computation.

Queries on-chain SPL transfer history to compute lifetime LPS spend
for a given wallet. The chain is the source of truth — no database needed.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from cachetools import TTLCache
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.signature import Signature

logger = logging.getLogger(__name__)

# Cache tier lookups for 5 minutes. Ephemeral — container restart recomputes.
_tier_cache: TTLCache[str, Decimal] = TTLCache(maxsize=10000, ttl=300)

# LPS has 6 decimals (matching frontend lpsTransfer.ts)
LPS_DECIMALS = 6


def get_lifetime_lps_spend(
    rpc_url: str,
    wallet_address: str,
    service_wallet: str,
    lps_mint: str,
) -> Decimal:
    """Query Solana chain for total LPS transferred from wallet to service wallet.

    Uses getSignaturesForAddress to find all transactions involving the wallet,
    then filters for SPL transfers of the LPS token to the service wallet.

    Results are cached with a 5-minute TTL.
    """
    cache_key = wallet_address
    if cache_key in _tier_cache:
        return _tier_cache[cache_key]

    client = Client(rpc_url)
    total = Decimal("0")

    try:
        wallet_pubkey = Pubkey.from_string(wallet_address)
        service_pubkey = Pubkey.from_string(service_wallet)
        mint_pubkey = Pubkey.from_string(lps_mint)

        # Paginate through all transaction signatures for this wallet
        before = None
        while True:
            resp = client.get_signatures_for_address(
                wallet_pubkey,
                before=before,
                limit=1000,
            )
            signatures = resp.value
            if not signatures:
                break

            for sig_info in signatures:
                if sig_info.err is not None:
                    continue  # Skip failed transactions

                amount = _check_lps_transfer(
                    client, sig_info.signature, wallet_pubkey, service_pubkey, mint_pubkey
                )
                if amount > 0:
                    total += Decimal(str(amount)) / Decimal(10**LPS_DECIMALS)

            # Paginate
            before = signatures[-1].signature

    except Exception:
        logger.exception("Failed to query LPS transfer history for %s", wallet_address)

    _tier_cache[cache_key] = total
    return total


def _check_lps_transfer(
    client: Client,
    signature: Signature,
    from_wallet: Pubkey,
    to_wallet: Pubkey,
    lps_mint: Pubkey,
) -> int:
    """Check if a transaction contains an LPS SPL transfer from wallet to service wallet.

    Returns the transfer amount in raw units (before decimal adjustment), or 0.
    """
    try:
        resp = client.get_transaction(
            signature,
            max_supported_transaction_version=0,
        )
        if resp.value is None:
            return 0

        meta = resp.value.transaction.meta
        if meta is None:
            return 0

        # Check pre/post token balances for LPS transfers
        pre_balances = meta.pre_token_balances or []
        post_balances = meta.post_token_balances or []

        # Build a map of account_index -> (owner, mint, pre_amount, post_amount)
        pre_map: dict[int, tuple[str, str, int]] = {}
        for bal in pre_balances:
            if bal.mint == lps_mint and bal.owner == to_wallet:
                amount = int(bal.ui_token_amount.amount) if bal.ui_token_amount.amount else 0
                pre_map[bal.account_index] = (str(bal.owner), str(bal.mint), amount)

        for bal in post_balances:
            if bal.mint == lps_mint and bal.owner == to_wallet:
                post_amount = int(bal.ui_token_amount.amount) if bal.ui_token_amount.amount else 0
                pre_entry = pre_map.get(bal.account_index)
                pre_amount = pre_entry[2] if pre_entry else 0
                diff = post_amount - pre_amount
                if diff > 0:
                    return diff

    except Exception:
        logger.debug("Failed to parse transaction %s", signature)

    return 0


def invalidate_cache(wallet_address: str) -> None:
    """Remove a wallet from the tier cache (e.g., after a new LPS transfer)."""
    _tier_cache.pop(wallet_address, None)
