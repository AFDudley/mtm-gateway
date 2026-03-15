"""Extract wallet identity from x402 payment transactions.

The x402 payment header contains a signed Solana transaction. The user's
public key (wallet address) is recovered from the transaction, providing
cryptographic proof of identity on every request — no JWT needed.

In x402 ExactSvm, the transaction has two signers:
  account_keys[0] = fee payer (x402 facilitator)
  account_keys[1] = user (the actual wallet holder)
"""

from __future__ import annotations

import base64
import json
import logging

from fastapi import Request
from solders.transaction import VersionedTransaction

logger = logging.getLogger(__name__)


def _extract_user_pubkey(tx: VersionedTransaction) -> str | None:
    """Extract the user's pubkey from an x402 transaction.

    In x402 ExactSvm, account_keys[0] is the facilitator (fee payer)
    and account_keys[1] is the user. If there's only one signer,
    fall back to account_keys[0].
    """
    keys = tx.message.account_keys
    if not keys:
        return None
    num_signers = tx.message.header.num_required_signatures
    if num_signers >= 2 and len(keys) >= 2:
        return str(keys[1])
    return str(keys[0])


def extract_wallet_from_x402(request: Request) -> str | None:
    """Extract the user's Solana wallet address from verified x402 payment.

    Checks two sources in order:
    1. request.state.payment_payload — set by PaymentMiddlewareASGI after
       successful verification via the facilitator.
    2. X-PAYMENT header — parsed directly as a fallback.

    Returns the base58 wallet address, or None if no payment present.
    """
    # Source 1: middleware-verified payment payload (preferred)
    payment_payload = getattr(request.state, "payment_payload", None)
    if payment_payload is not None:
        try:
            inner = payment_payload
            if hasattr(inner, "payload"):
                inner = inner.payload
            if isinstance(inner, dict):
                tx_data = inner.get("transaction") or inner.get("payload", "")
            else:
                tx_data = str(inner)

            if tx_data:
                tx_bytes = base64.b64decode(tx_data)
                tx = VersionedTransaction.from_bytes(tx_bytes)
                return _extract_user_pubkey(tx)
        except Exception:
            logger.debug("Could not extract wallet from payment_payload, trying header")

    # Source 2: raw X-PAYMENT header
    payment_header = request.headers.get("X-PAYMENT") or request.headers.get("payment-signature")
    if not payment_header:
        return None

    try:
        payment = json.loads(payment_header)
        payload_b64 = payment.get("payload", "")
        if not payload_b64:
            return None

        tx_bytes = base64.b64decode(payload_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        return _extract_user_pubkey(tx)

    except Exception:
        logger.exception("Failed to extract wallet from x402 payment")

    return None
