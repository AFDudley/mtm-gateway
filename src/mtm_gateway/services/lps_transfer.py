"""LPS token transfer from service wallet to user wallet.

Used after Apple IAP receipt validation to mint/transfer LPS to the buyer.
The gateway wallet must hold sufficient LPS balance.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from solana.rpc.api import Client as SolanaClient
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from mtm_gateway.config import Settings
from mtm_gateway.services.solana_rpc import LPS_DECIMALS
from mtm_gateway.services.spl_instructions import get_associated_token_address, transfer_checked

logger = logging.getLogger(__name__)


def get_lps_balance(settings: Settings) -> Decimal:
    """Check the gateway wallet's LPS token balance.

    Returns the balance in human-readable units (adjusted for decimals).
    """
    client = SolanaClient(settings.solana_rpc)
    mint = Pubkey.from_string(settings.lps_mint_address)
    wallet = Pubkey.from_string(settings.solana_wallet_address)
    ata = get_associated_token_address(wallet, mint)

    try:
        resp = client.get_token_account_balance(ata)
        if resp.value:
            return Decimal(resp.value.ui_amount_string)
    except Exception:
        logger.exception("Failed to check LPS balance")

    return Decimal("0")


def transfer_lps_to_user(
    settings: Settings,
    recipient_wallet: str,
    amount: Decimal,
) -> str:
    """Transfer LPS tokens from the gateway wallet to a user's wallet.

    Args:
        settings: App settings with wallet keys and RPC URL.
        recipient_wallet: Base58 Solana address of the recipient.
        amount: Amount of LPS in human-readable units (e.g., 29.0).

    Returns:
        The transaction signature as a base58 string.

    Raises:
        ValueError: If the gateway wallet has insufficient LPS balance.
        RuntimeError: If the transaction fails.
    """
    if amount <= 0:
        raise ValueError(f"Invalid LPS amount: {amount}")

    # Pre-flight balance check
    balance = get_lps_balance(settings)
    if balance < amount:
        raise ValueError(
            f"Insufficient LPS balance in gateway wallet: " f"have {balance}, need {amount}"
        )

    client = SolanaClient(settings.solana_rpc)
    keypair = Keypair.from_base58_string(settings.solana_wallet_private_key)
    mint = Pubkey.from_string(settings.lps_mint_address)
    recipient = Pubkey.from_string(recipient_wallet)

    source_ata = get_associated_token_address(keypair.pubkey(), mint)
    dest_ata = get_associated_token_address(recipient, mint)

    # Convert human-readable amount to raw token units
    raw_amount = int(amount * Decimal(10**LPS_DECIMALS))

    ix = transfer_checked(
        source=source_ata,
        mint=mint,
        dest=dest_ata,
        owner=keypair.pubkey(),
        amount=raw_amount,
        decimals=LPS_DECIMALS,
    )

    # Build and sign transaction
    blockhash_resp = client.get_latest_blockhash()
    blockhash = blockhash_resp.value.blockhash

    msg = MessageV0.try_compile(
        payer=keypair.pubkey(),
        instructions=[ix],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )
    tx = VersionedTransaction(msg, [keypair])

    # Send and confirm
    resp = client.send_transaction(tx)
    signature = str(resp.value)

    logger.info(
        "LPS transfer: %s → %s, amount=%s, sig=%s",
        settings.solana_wallet_address,
        recipient_wallet,
        amount,
        signature,
    )

    return signature
