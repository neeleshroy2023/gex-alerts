"""GEX computation from Upstox option chain data (pure arithmetic)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import config

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class GEXSnapshot:
    symbol: str
    spot_price: float
    total_gex: float
    gamma_flip: float
    put_wall: float
    call_wall: float
    max_gamma_strike: float
    pcr_gex: float
    net_delta_flow: float
    gex_by_strike: dict[float, float] = field(default_factory=dict)
    regime: str = "POSITIVE"
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(IST).isoformat()


def _safe_float(val: object, default: float = 0.0) -> float:
    """Extract a float from potentially None / missing values."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def compute_gex(option_chain: list[dict], spot: float, symbol: str = "") -> GEXSnapshot:
    """
    Compute GEX levels from Upstox option chain data.

    For each strike:
        call_gex = call_oi * call_gamma * 100 * spot^2 * 0.01
        put_gex  = put_oi  * put_gamma  * 100 * spot^2 * 0.01 * (-1)
        net_gex  = call_gex + put_gex

    The (-1) for puts reflects that dealers are typically short puts.
    """
    spot_sq = spot * spot
    multiplier = 100 * spot_sq * 0.01  # = spot^2

    gex_by_strike: dict[float, float] = {}
    call_gex_by_strike: dict[float, float] = {}
    put_gex_by_strike: dict[float, float] = {}

    for strike_data in option_chain:
        strike = _safe_float(strike_data.get("strike_price"))
        if strike <= 0:
            continue

        # --- Call side ---
        call_opts = strike_data.get("call_options") or {}
        call_md = call_opts.get("market_data") or {}
        call_greeks = call_opts.get("option_greeks") or {}
        call_oi = _safe_float(call_md.get("oi"))
        call_gamma = _safe_float(call_greeks.get("gamma"))

        call_gex = call_oi * call_gamma * multiplier

        # --- Put side ---
        put_opts = strike_data.get("put_options") or {}
        put_md = put_opts.get("market_data") or {}
        put_greeks = put_opts.get("option_greeks") or {}
        put_oi = _safe_float(put_md.get("oi"))
        put_gamma = _safe_float(put_greeks.get("gamma"))

        put_gex = put_oi * put_gamma * multiplier * (-1)

        net_gex = call_gex + put_gex
        gex_by_strike[strike] = net_gex
        call_gex_by_strike[strike] = call_gex
        put_gex_by_strike[strike] = abs(put_gex)

    if not gex_by_strike:
        return GEXSnapshot(
            symbol=symbol,
            spot_price=spot,
            total_gex=0,
            gamma_flip=spot,
            put_wall=spot,
            call_wall=spot,
            max_gamma_strike=spot,
            pcr_gex=1.0,
            net_delta_flow=0,
        )

    total_gex = sum(gex_by_strike.values())

    # Gamma flip: strike where cumulative GEX (low → high) crosses zero
    gamma_flip = _find_gamma_flip(gex_by_strike)

    # Put wall: strike with highest absolute put-side GEX (support)
    put_wall = max(put_gex_by_strike, key=put_gex_by_strike.get)  # type: ignore[arg-type]

    # Call wall: strike with highest absolute call-side GEX (resistance)
    call_wall = max(call_gex_by_strike, key=call_gex_by_strike.get)  # type: ignore[arg-type]

    # Max gamma: strike with largest absolute net GEX (magnet/pin)
    max_gamma_strike = max(gex_by_strike, key=lambda s: abs(gex_by_strike[s]))

    # PCR GEX ratio
    total_put_gex = sum(put_gex_by_strike.values())
    total_call_gex = sum(call_gex_by_strike.values())
    pcr_gex = total_put_gex / total_call_gex if total_call_gex else 1.0

    # Delta flow
    net_delta_flow = compute_delta_flow(option_chain, spot)

    regime = "POSITIVE" if total_gex > 0 else "NEGATIVE"

    snapshot = GEXSnapshot(
        symbol=symbol,
        spot_price=spot,
        total_gex=total_gex,
        gamma_flip=gamma_flip,
        put_wall=put_wall,
        call_wall=call_wall,
        max_gamma_strike=max_gamma_strike,
        pcr_gex=pcr_gex,
        net_delta_flow=net_delta_flow,
        gex_by_strike=gex_by_strike,
        regime=regime,
    )

    logger.info(
        "GEX %s | spot=%.0f regime=%s total=%.2e flip=%.0f walls=%.0f/%.0f pin=%.0f pcr=%.2f",
        symbol,
        spot,
        regime,
        total_gex,
        gamma_flip,
        put_wall,
        call_wall,
        max_gamma_strike,
        pcr_gex,
    )
    return snapshot


def _find_gamma_flip(gex_by_strike: dict[float, float]) -> float:
    """Find the strike where cumulative GEX (summing low→high) crosses zero.
    Uses linear interpolation between the two straddling strikes."""
    strikes = sorted(gex_by_strike)
    if not strikes:
        return 0.0

    cumulative = 0.0
    prev_cum = 0.0
    prev_strike = strikes[0]

    for strike in strikes:
        prev_cum = cumulative
        cumulative += gex_by_strike[strike]

        if prev_cum != 0 and ((prev_cum > 0) != (cumulative > 0)):
            # Zero crossing between prev_strike and strike
            # Linear interpolation
            if cumulative == prev_cum:
                return strike
            fraction = abs(prev_cum) / abs(cumulative - prev_cum)
            return prev_strike + fraction * (strike - prev_strike)

        prev_strike = strike

    # No crossing found — return the strike closest to zero cumulative
    # Re-compute cumulative series
    cum_series: dict[float, float] = {}
    running = 0.0
    for s in strikes:
        running += gex_by_strike[s]
        cum_series[s] = running

    return min(cum_series, key=lambda s: abs(cum_series[s]))


def compute_delta_flow(option_chain: list[dict], spot: float) -> float:
    """
    Net dealer delta exposure for near-ATM strikes.

    Near-ATM = N strikes above + N strikes below spot (config.NEAR_ATM_STRIKES).
        bullish = sum(call_volume * call_delta)
        bearish = sum(put_volume * abs(put_delta))
        net = bullish - bearish
    """
    n = config.NEAR_ATM_STRIKES

    # Sort strikes by distance from spot
    strikes_with_dist: list[tuple[float, dict]] = []
    for sd in option_chain:
        strike = _safe_float(sd.get("strike_price"))
        if strike > 0:
            strikes_with_dist.append((abs(strike - spot), sd))

    strikes_with_dist.sort(key=lambda x: x[0])
    near_atm = [sd for _, sd in strikes_with_dist[: n * 2]]

    bullish = 0.0
    bearish = 0.0

    for sd in near_atm:
        call_opts = sd.get("call_options") or {}
        call_md = call_opts.get("market_data") or {}
        call_greeks = call_opts.get("option_greeks") or {}

        put_opts = sd.get("put_options") or {}
        put_md = put_opts.get("market_data") or {}
        put_greeks = put_opts.get("option_greeks") or {}

        call_vol = _safe_float(call_md.get("volume"))
        call_delta = _safe_float(call_greeks.get("delta"))
        put_vol = _safe_float(put_md.get("volume"))
        put_delta = _safe_float(put_greeks.get("delta"))

        bullish += call_vol * call_delta
        bearish += put_vol * abs(put_delta)

    return bullish - bearish
