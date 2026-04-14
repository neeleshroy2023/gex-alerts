"""Signal detection: compare GEX snapshots to find actionable changes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import config
from gex_engine import GEXSnapshot

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class Signal:
    type: str       # GAMMA_FLIP, GAMMA_SQUEEZE, MOMENTUM_EXTREME, etc.
    priority: str   # HIGH, MEDIUM, LOW
    symbol: str
    message: str
    data: dict = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(IST).isoformat()


_PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def detect_signals(
    current: GEXSnapshot,
    previous: GEXSnapshot | None,
    spot_history: list[float] | None = None,
    momentum_score: int = 50,
) -> list[Signal]:
    """
    Compare current vs previous GEX snapshot and detect trading signals.
    Returns signals sorted by priority (HIGH first).
    """
    signals: list[Signal] = []
    spot = current.spot_price
    symbol = current.symbol

    # 1. GAMMA FLIP (HIGH) — regime changed sign
    if previous and previous.regime != current.regime:
        signals.append(Signal(
            type="GAMMA_FLIP",
            priority="HIGH",
            symbol=symbol,
            message=(
                f"Regime flipped {previous.regime} -> {current.regime}. "
                f"{'Dealers now SHORT gamma — expect amplified moves' if current.regime == 'NEGATIVE' else 'Dealers now LONG gamma — expect mean reversion'}"
            ),
            data={
                "old_regime": previous.regime,
                "new_regime": current.regime,
                "gamma_flip": current.gamma_flip,
                "total_gex": current.total_gex,
            },
        ))

    # 2. GAMMA SQUEEZE (HIGH) — negative gamma + spot near flip + volume spike
    if current.regime == "NEGATIVE" and previous:
        flip_dist_pct = abs(spot - current.gamma_flip) / spot * 100
        if flip_dist_pct < config.GAMMA_SQUEEZE_PROXIMITY_PCT:
            # Check for volume spike at nearby strikes
            volume_spike = _detect_volume_spike(current, previous)
            if volume_spike:
                signals.append(Signal(
                    type="GAMMA_SQUEEZE",
                    priority="HIGH",
                    symbol=symbol,
                    message=(
                        f"Gamma squeeze forming — negative regime, spot {spot:.0f} "
                        f"within {flip_dist_pct:.1f}% of flip at {current.gamma_flip:.0f}, "
                        f"volume spiking at nearby strikes"
                    ),
                    data={
                        "flip_distance_pct": flip_dist_pct,
                        "gamma_flip": current.gamma_flip,
                        "regime": current.regime,
                    },
                ))

    # 3. MOMENTUM EXTREME (HIGH)
    if momentum_score > 80:
        signals.append(Signal(
            type="MOMENTUM_EXTREME",
            priority="HIGH",
            symbol=symbol,
            message=f"Strong BULLISH momentum — score {momentum_score}/100",
            data={"momentum_score": momentum_score, "direction": "BULLISH"},
        ))
    elif momentum_score < 20:
        signals.append(Signal(
            type="MOMENTUM_EXTREME",
            priority="HIGH",
            symbol=symbol,
            message=f"Strong BEARISH momentum — score {momentum_score}/100",
            data={"momentum_score": momentum_score, "direction": "BEARISH"},
        ))

    # 4. WALL BREACH (MEDIUM)
    if spot > current.call_wall * (1 + config.WALL_BREACH_PROXIMITY_PCT / 100):
        signals.append(Signal(
            type="WALL_BREACH",
            priority="MEDIUM",
            symbol=symbol,
            message=f"BULLISH breakout — spot {spot:.0f} breached call wall at {current.call_wall:.0f}",
            data={"wall": current.call_wall, "direction": "BULLISH", "breach_pct": (spot - current.call_wall) / current.call_wall * 100},
        ))
    if spot < current.put_wall * (1 - config.WALL_BREACH_PROXIMITY_PCT / 100):
        signals.append(Signal(
            type="WALL_BREACH",
            priority="MEDIUM",
            symbol=symbol,
            message=f"BEARISH breakdown — spot {spot:.0f} breached put wall at {current.put_wall:.0f}",
            data={"wall": current.put_wall, "direction": "BEARISH", "breach_pct": (current.put_wall - spot) / current.put_wall * 100},
        ))

    # 5. GEX MAGNITUDE SHIFT (MEDIUM) — total GEX changed > 40%
    if previous and previous.total_gex != 0:
        gex_change_pct = abs(current.total_gex - previous.total_gex) / abs(previous.total_gex) * 100
        if gex_change_pct > config.GEX_MAGNITUDE_SHIFT_PCT:
            signals.append(Signal(
                type="GEX_MAGNITUDE_SHIFT",
                priority="MEDIUM",
                symbol=symbol,
                message=f"GEX shifted {gex_change_pct:.0f}% — rapid dealer repositioning",
                data={"change_pct": gex_change_pct, "old_gex": previous.total_gex, "new_gex": current.total_gex},
            ))

    # 6. GAMMA FLIP PROXIMITY (MEDIUM) — spot within 0.3% of flip
    flip_proximity = abs(spot - current.gamma_flip) / spot * 100
    if flip_proximity < config.GAMMA_FLIP_PROXIMITY_PCT:
        # Don't duplicate if we already have a GAMMA_FLIP signal
        if not any(s.type == "GAMMA_FLIP" for s in signals):
            signals.append(Signal(
                type="GAMMA_FLIP_PROXIMITY",
                priority="MEDIUM",
                symbol=symbol,
                message=f"Spot {spot:.0f} within {flip_proximity:.2f}% of gamma flip at {current.gamma_flip:.0f} — inflection zone",
                data={"gamma_flip": current.gamma_flip, "distance_pct": flip_proximity},
            ))

    # 7. PIN RISK (LOW) — spot within 0.2% of max gamma strike
    pin_proximity = abs(spot - current.max_gamma_strike) / spot * 100
    if pin_proximity < config.PIN_RISK_PROXIMITY_PCT:
        # Extra relevance on expiry day (Thursday)
        is_expiry_day = datetime.now(IST).weekday() == 3  # Thursday
        signals.append(Signal(
            type="PIN_RISK",
            priority="LOW",
            symbol=symbol,
            message=(
                f"Pin risk — spot {spot:.0f} within {pin_proximity:.2f}% of "
                f"max gamma strike {current.max_gamma_strike:.0f}"
                f"{' (EXPIRY DAY)' if is_expiry_day else ''}"
            ),
            data={
                "max_gamma_strike": current.max_gamma_strike,
                "distance_pct": pin_proximity,
                "is_expiry_day": is_expiry_day,
            },
        ))

    for sig in signals:
        logger.info("Signal: [%s] %s %s — %s", sig.priority, sig.type, sig.symbol, sig.message)

    return sorted(signals, key=lambda s: _PRIORITY_ORDER.get(s.priority, 9))


def _detect_volume_spike(current: GEXSnapshot, previous: GEXSnapshot) -> bool:
    """Check if any near-ATM strike has a volume spike vs previous cycle.

    This is a simplified check — we look at whether the GEX distribution
    has shifted significantly, which implies heavy volume at specific strikes.
    """
    if not previous.gex_by_strike or not current.gex_by_strike:
        return False

    spot = current.spot_price
    near_strikes = [
        s for s in current.gex_by_strike
        if abs(s - spot) / spot < 0.02  # within 2% of spot
    ]

    for strike in near_strikes:
        cur_gex = abs(current.gex_by_strike.get(strike, 0))
        prev_gex = abs(previous.gex_by_strike.get(strike, 0))
        if prev_gex > 0 and cur_gex / prev_gex > config.VOLUME_SPIKE_MULTIPLIER:
            return True

    return False
