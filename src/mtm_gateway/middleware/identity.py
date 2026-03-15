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
    """Extract the payer's Solana wallet address from verified x402 payment.

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
            # PaymentPayload has a 'payload' field containing the inner dict
            # which includes the signed transaction
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
                if tx.message.account_keys:
                    return str(tx.message.account_keys[0])
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

        if tx.message.account_keys:
            payer = tx.message.account_keys[0]
            return str(payer)

    except Exception:
        logger.exception("Failed to extract wallet from x402 payment")

    return None
