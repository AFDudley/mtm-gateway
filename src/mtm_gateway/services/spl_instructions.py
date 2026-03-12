"""SPL Token instruction builders using solders.

The `spl` Python package is no longer maintained as a standalone dependency.
These helpers build SPL Token Program instructions directly using solders,
matching the on-chain instruction layout.

Reference: https://github.com/solana-labs/solana-program-library/blob/master/token/program/src/instruction.rs
"""

from __future__ import annotations

import struct

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)

# SPL Token instruction discriminators
_TRANSFER_CHECKED = 12


def get_associated_token_address(wallet: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive the associated token account (ATA) address for a wallet+mint pair."""
    seeds = [bytes(wallet), bytes(TOKEN_PROGRAM_ID), bytes(mint)]
    ata, _bump = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
    return ata


def transfer_checked(
    source: Pubkey,
    mint: Pubkey,
    dest: Pubkey,
    owner: Pubkey,
    amount: int,
    decimals: int,
) -> Instruction:
    """Build a TransferChecked instruction for the SPL Token Program.

    TransferChecked verifies the mint and decimals match, preventing
    accidental transfers to wrong token accounts.

    Instruction layout (little-endian):
        u8  instruction discriminator (12 = TransferChecked)
        u64 amount
        u8  decimals

    Accounts:
        0. [writable] source token account
        1. []         mint
        2. [writable] destination token account
        3. [signer]   source account owner
    """
    data = struct.pack("<BQB", _TRANSFER_CHECKED, amount, decimals)

    keys = [
        AccountMeta(pubkey=source, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=dest, is_signer=False, is_writable=True),
        AccountMeta(pubkey=owner, is_signer=True, is_writable=False),
    ]

    return Instruction(program_id=TOKEN_PROGRAM_ID, accounts=keys, data=data)
