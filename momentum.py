"""Composite momentum score (0-100) from GEX data."""

from __future__ import annotations

import logging

import config
from gex_engine import GEXSnapshot

logger = logging.getLogger(__name__)


def compute_momentum_score(
    gex: GEXSnapshot,
    previous_gex: GEXSnapshot | None = None,
    avg_total_gex: float | None = None,
    max_delta_flow: float | None = None,
) -> int:
    """
    Composite momentum score 0-100.

    Components (each normalized to 0-100, then weighted):
        1. GEX Regime Score    (0.35) — regime + magnitude
        2. Delta Flow Score    (0.30) — net dealer delta
        3. GEX Rate of Change  (0.20) — total_gex change vs previous
        4. PCR GEX Score       (0.15) — put/call GEX ratio

    Returns:
        > 75: Strong bullish momentum
        > 60: Moderate bullish lean
        40-60: Neutral / choppy
        < 40: Moderate bearish lean
        < 25: Strong bearish momentum
    """
    w = config.MOMENTUM_WEIGHTS

    regime_score = _gex_regime_score(gex, avg_total_gex)
    delta_score = _delta_flow_score(gex.net_delta_flow, max_delta_flow)
    roc_score = _gex_roc_score(gex, previous_gex)
    pcr_score = _pcr_gex_score(gex.pcr_gex)

    raw = (
        regime_score * w["gex_regime"]
        + delta_score * w["delta_flow"]
        + roc_score * w["gex_roc"]
        + pcr_score * w["pcr_gex"]
    )

    final = int(max(0, min(100, raw)))

    logger.debug(
        "Momentum %s: regime=%d delta=%d roc=%d pcr=%d => %d",
        gex.symbol,
        regime_score,
        delta_score,
        roc_score,
        pcr_score,
        final,
    )
    return final


def _gex_regime_score(gex: GEXSnapshot, avg_total_gex: float | None) -> float:
    """
    Negative GEX + spot moving away from flip = high momentum potential (80-100).
    Positive GEX + spot near max gamma = low momentum, pinned (10-30).
    """
    spot = gex.spot_price
    flip = gex.gamma_flip
    max_g = gex.max_gamma_strike

    if gex.regime == "NEGATIVE":
        # Negative GEX => amplified moves => higher momentum score
        base = 70

        # If spot is moving away from flip, momentum is building
        flip_dist = abs(spot - flip) / spot * 100
        base += min(20, flip_dist * 10)  # up to +20 for being far from flip

        # Normalize by magnitude relative to average
        if avg_total_gex and avg_total_gex != 0:
            magnitude_ratio = abs(gex.total_gex) / abs(avg_total_gex)
            base += min(10, (magnitude_ratio - 1) * 10)  # bonus for extreme
    else:
        # Positive GEX => mean-reverting => lower momentum score
        base = 35

        # If spot is near max gamma, it's pinned (lower score)
        pin_dist = abs(spot - max_g) / spot * 100
        if pin_dist < 0.3:
            base -= 15  # pinned = very low momentum
        else:
            base += min(15, pin_dist * 5)  # further from pin = slightly higher

    return max(0, min(100, base))


def _delta_flow_score(net_delta_flow: float, max_delta_flow: float | None) -> float:
    """
    Strong positive net delta = bullish (70-100).
    Strong negative net delta = bearish (0-30).
    score = 50 + (net_delta_flow / max_delta_flow) * 50
    """
    if max_delta_flow is None or max_delta_flow == 0:
        # Use a reasonable default normalization
        max_delta_flow = max(abs(net_delta_flow), 1.0) * 2

    ratio = net_delta_flow / abs(max_delta_flow)
    ratio = max(-1.0, min(1.0, ratio))
    return 50 + ratio * 50


def _gex_roc_score(gex: GEXSnapshot, previous: GEXSnapshot | None) -> float:
    """
    Rate of change of total GEX.
    If GEX is rapidly becoming more negative = momentum building.
    """
    if previous is None or previous.total_gex == 0:
        return 50  # neutral

    change = gex.total_gex - previous.total_gex
    ref = abs(previous.total_gex)
    pct_change = change / ref if ref else 0

    # GEX becoming more negative = bullish momentum (dealers hedging aggressively)
    # GEX becoming more positive = bearish momentum (market calming)
    # This is counter-intuitive: negative GEX = amplified moves in EITHER direction
    # We combine with delta flow direction for final directionality

    # Map pct_change to score: large negative change => high score (momentum building)
    # large positive change => low score (momentum fading)
    score = 50 - pct_change * 100  # scaled
    return max(0, min(100, score))


def _pcr_gex_score(pcr_gex: float) -> float:
    """
    PCR > 1.3 = oversold, bullish reversal likely (70-90).
    PCR < 0.7 = overbought, bearish reversal likely (10-30).
    PCR 0.9-1.1 = neutral (40-60).
    """
    if pcr_gex > 1.5:
        return 90
    if pcr_gex > 1.3:
        return 70 + (pcr_gex - 1.3) * 100  # 70-90
    if pcr_gex > 1.1:
        return 60 + (pcr_gex - 1.1) * 50  # 60-70
    if pcr_gex > 0.9:
        return 40 + (pcr_gex - 0.9) * 100  # 40-60
    if pcr_gex > 0.7:
        return 30 + (pcr_gex - 0.7) * 50  # 30-40
    if pcr_gex > 0.5:
        return 10 + (pcr_gex - 0.5) * 100  # 10-30
    return 10


def interpret_momentum(score: int) -> str:
    """Human-readable interpretation of the momentum score."""
    if score >= config.MOMENTUM_STRONG_BULLISH:
        return "Strong Bullish"
    if score >= config.MOMENTUM_MODERATE_BULLISH:
        return "Moderate Bullish"
    if score > config.MOMENTUM_MODERATE_BEARISH:
        return "Neutral"
    if score > config.MOMENTUM_STRONG_BEARISH:
        return "Moderate Bearish"
    return "Strong Bearish"
