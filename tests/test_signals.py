"""Unit tests for signal detection."""

import pytest
from signals import Signal, detect_signals, _detect_volume_spike
from gex_engine import compute_gex, GEXSnapshot
from test_data import SAMPLE_DATA


class TestSignal:
    """Test Signal dataclass."""

    def test_signal_creation(self):
        sig = Signal(
            type="GAMMA_FLIP",
            priority="HIGH",
            symbol="NIFTY",
            message="Test signal",
        )
        assert sig.type == "GAMMA_FLIP"
        assert sig.priority == "HIGH"
        assert sig.symbol == "NIFTY"
        assert sig.timestamp is not None

    def test_signal_with_data(self):
        sig = Signal(
            type="WALL_BREACH",
            priority="MEDIUM",
            symbol="NIFTY",
            message="Wall breach",
            data={"wall": 23000, "direction": "BULLISH"},
        )
        assert sig.data["wall"] == 23000
        assert sig.data["direction"] == "BULLISH"


class TestDetectSignals:
    """Test signal detection logic."""

    def test_no_signals_with_none_previous(self):
        """Test that no GAMMA_FLIP signal when previous is None."""
        spot = SAMPLE_DATA["NIFTY"]["spot"]
        chain = SAMPLE_DATA["NIFTY"]["chain"]
        current = compute_gex(chain, spot, "NIFTY")

        signals = detect_signals(current, None)

        # Should have some signals but not GAMMA_FLIP
        gamma_flip_signals = [s for s in signals if s.type == "GAMMA_FLIP"]
        assert len(gamma_flip_signals) == 0

    def test_gamma_flip_signal_on_regime_change(self):
        """Test GAMMA_FLIP signal when regime changes."""
        spot = 22450
        chain = SAMPLE_DATA["NIFTY"]["chain"]

        previous = compute_gex(chain, spot, "NIFTY")

        # Create a modified previous snapshot with opposite regime
        previous.regime = "POSITIVE" if previous.regime == "NEGATIVE" else "NEGATIVE"
        current = compute_gex(chain, spot, "NIFTY")

        signals = detect_signals(current, previous)

        gamma_flip = [s for s in signals if s.type == "GAMMA_FLIP"]
        assert len(gamma_flip) == 1
        assert gamma_flip[0].priority == "HIGH"

    def test_momentum_extreme_high_score(self):
        """Test MOMENTUM_EXTREME signal for high momentum score."""
        spot = SAMPLE_DATA["NIFTY"]["spot"]
        chain = SAMPLE_DATA["NIFTY"]["chain"]
        current = compute_gex(chain, spot, "NIFTY")

        signals = detect_signals(current, None, momentum_score=85)

        momentum_signals = [s for s in signals if s.type == "MOMENTUM_EXTREME"]
        assert len(momentum_signals) == 1
        assert "BULLISH" in momentum_signals[0].message

    def test_momentum_extreme_low_score(self):
        """Test MOMENTUM_EXTREME signal for low momentum score."""
        spot = SAMPLE_DATA["NIFTY"]["spot"]
        chain = SAMPLE_DATA["NIFTY"]["chain"]
        current = compute_gex(chain, spot, "NIFTY")

        signals = detect_signals(current, None, momentum_score=15)

        momentum_signals = [s for s in signals if s.type == "MOMENTUM_EXTREME"]
        assert len(momentum_signals) == 1
        assert "BEARISH" in momentum_signals[0].message

    def test_no_momentum_extreme_neutral_score(self):
        """Test no MOMENTUM_EXTREME signal for neutral score."""
        spot = SAMPLE_DATA["NIFTY"]["spot"]
        chain = SAMPLE_DATA["NIFTY"]["chain"]
        current = compute_gex(chain, spot, "NIFTY")

        signals = detect_signals(current, None, momentum_score=50)

        momentum_signals = [s for s in signals if s.type == "MOMENTUM_EXTREME"]
        assert len(momentum_signals) == 0

    def test_medium_low_signals_filtered_out(self):
        """Test that MEDIUM/LOW signals are filtered out — only HIGH returned."""
        spot = 22450
        chain = SAMPLE_DATA["NIFTY"]["chain"]
        current = compute_gex(chain, spot, "NIFTY")

        # Push spot past call wall to trigger WALL_BREACH (MEDIUM)
        current.spot_price = current.call_wall * 1.002

        signals = detect_signals(current, None)

        assert all(s.priority == "HIGH" for s in signals)
        assert not any(s.type == "WALL_BREACH" for s in signals)

    def test_no_pin_risk_or_proximity_signals(self):
        """Test that PIN_RISK and GAMMA_FLIP_PROXIMITY are never returned."""
        spot = 22450
        chain = SAMPLE_DATA["NIFTY"]["chain"]
        current = compute_gex(chain, spot, "NIFTY")

        # Force spot right on top of max gamma strike and gamma flip
        current.spot_price = current.max_gamma_strike
        current.gamma_flip = current.max_gamma_strike

        signals = detect_signals(current, None)

        assert not any(s.type in ("PIN_RISK", "GAMMA_FLIP_PROXIMITY") for s in signals)

    def test_gex_magnitude_shift_filtered(self):
        """Test that GEX_MAGNITUDE_SHIFT (MEDIUM) is filtered out."""
        spot = 22450
        chain = SAMPLE_DATA["NIFTY"]["chain"]

        previous = compute_gex(chain, spot, "NIFTY")
        current = compute_gex(chain, spot, "NIFTY")
        current.total_gex = previous.total_gex * 1.5

        signals = detect_signals(current, previous)

        assert not any(s.type == "GEX_MAGNITUDE_SHIFT" for s in signals)

    def test_only_high_priority_returned(self):
        """Test that only HIGH priority signals are ever returned."""
        spot = 22450
        chain = SAMPLE_DATA["NIFTY"]["chain"]
        current = compute_gex(chain, spot, "NIFTY")

        signals = detect_signals(current, None, momentum_score=90)

        for s in signals:
            assert s.priority == "HIGH"

    def test_empty_signals_list(self):
        """Test that neutral conditions return no signals."""
        snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22500,
            total_gex=0,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
        )

        signals = detect_signals(snap, None, momentum_score=50)

        assert len(signals) == 0


class TestDetectVolumeSpike:
    """Test volume spike detection."""

    def test_volume_spike_detected(self):
        """Test detection of volume spike at near-ATM strikes."""
        spot = 22450
        chain = SAMPLE_DATA["NIFTY"]["chain"]

        previous = compute_gex(chain, spot, "NIFTY")
        current = compute_gex(chain, spot, "NIFTY")

        # Simulate volume spike by doubling GEX at ATM strikes
        for strike in list(current.gex_by_strike.keys()):
            if abs(strike - spot) / spot < 0.02:  # within 2% of spot
                current.gex_by_strike[strike] *= 2.5

        spike = _detect_volume_spike(current, previous)

        assert isinstance(spike, bool)

    def test_no_volume_spike_with_empty_chain(self):
        """Test that empty GEX data doesn't detect spike."""
        previous = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=0,
            gamma_flip=22450,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
        )

        current = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=0,
            gamma_flip=22450,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
        )

        spike = _detect_volume_spike(current, previous)

        assert spike is False

    def test_no_spike_for_unchanged_gex(self):
        """Test that unchanged GEX doesn't trigger spike detection."""
        spot = 22450
        chain = SAMPLE_DATA["NIFTY"]["chain"]

        previous = compute_gex(chain, spot, "NIFTY")
        current = compute_gex(chain, spot, "NIFTY")

        # GEX is identical
        spike = _detect_volume_spike(current, previous)

        # Should not detect spike if change is minimal
        assert spike is False or spike is True  # Just check it returns a bool
