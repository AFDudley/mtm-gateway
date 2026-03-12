"""Health and status endpoints. Free — no x402 payment required."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mtm-gateway"}
