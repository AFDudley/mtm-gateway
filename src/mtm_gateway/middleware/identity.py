"""Extract wallet identity from x402 payment transactions.

The x402 payment header contains a signed Solana transaction. The payer's
public key (wallet address) is recovered from the transaction, providing
cryptographic proof of identity on every request — no JWT needed.
"""

from __future__ import annotations

import base64
import json
import logging

from fastapi import Request
from solders.transaction import VersionedTransaction

logger = logging.getLogger(__name__)


def extract_wallet_from_x402(request: Request) -> str | None:
    """Extract the payer's Solana wallet address from the x402 payment header.

    The X-PAYMENT header contains JSON: {"scheme": "exact", "network": "solana", "payload": "<base64 tx>"}
    The payload is a base64-encoded signed Solana transaction. The first signer
    is the payer.

    Returns the base58 wallet address, or None if no payment header present.
    """
    payment_header = request.headers.get("X-PAYMENT")
    if not payment_header:
        return None

    try:
        payment = json.loads(payment_header)
        payload_b64 = payment.get("payload", "")
        if not payload_b64:
            return None

        tx_bytes = base64.b64decode(payload_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)

        # The first signer is the fee payer / transaction initiator
        if tx.message.account_keys:
            payer = tx.message.account_keys[0]
            return str(payer)

    except Exception:
        logger.exception("Failed to extract wallet from x402 payment")

    return None
