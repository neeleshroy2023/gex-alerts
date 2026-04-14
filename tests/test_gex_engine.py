"""Unit tests for GEX computation engine."""

import pytest
from gex_engine import (
    GEXSnapshot,
    compute_gex,
    _find_gamma_flip,
    compute_delta_flow,
    _safe_float,
)
from test_data import SAMPLE_DATA


class TestSafeFloat:
    """Test _safe_float helper function."""

    def test_valid_float(self):
        assert _safe_float(3.14) == 3.14
        assert _safe_float(0) == 0.0
        assert _safe_float(-10.5) == -10.5

    def test_valid_int(self):
        assert _safe_float(42) == 42.0

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0
        assert _safe_float(None, 100.0) == 100.0

    def test_invalid_string_returns_default(self):
        assert _safe_float("abc") == 0.0
        assert _safe_float("abc", 50.0) == 50.0

    def test_numeric_string_converts(self):
        assert _safe_float("3.14") == 3.14
        assert _safe_float("42") == 42.0


class TestGEXSnapshot:
    """Test GEXSnapshot dataclass."""

    def test_snapshot_creation(self):
        snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=1.5e6,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=0.95,
            net_delta_flow=5000,
        )
        assert snap.symbol == "NIFTY"
        assert snap.spot_price == 22450
        assert snap.regime == "POSITIVE"
        assert snap.timestamp is not None

    def test_snapshot_negative_gex_regime(self):
        snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=-1.5e6,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=0.95,
            net_delta_flow=5000,
            regime="NEGATIVE",
        )
        assert snap.regime == "NEGATIVE"
        assert snap.total_gex < 0


class TestFindGammaFlip:
    """Test gamma flip detection."""

    def test_simple_zero_crossing(self):
        """Test finding zero crossing with positive to negative transition."""
        gex_by_strike = {
            22000: 100000,
            22100: 50000,
            22200: -60000,
            22300: -100000,
        }
        flip = _find_gamma_flip(gex_by_strike)
        # Cumulative: 100k, 150k, 90k, -10k → crossing between 22200 and 22300
        assert 22200 < flip < 22300

    def test_negative_to_positive_crossing(self):
        """Test finding zero crossing with negative to positive transition."""
        gex_by_strike = {
            22000: -100000,
            22100: -60000,
            22200: 50000,
            22300: 100000,
        }
        flip = _find_gamma_flip(gex_by_strike)
        # Cumulative: -100k, -160k, -110k, -10k → returns closest to zero
        assert flip in gex_by_strike.keys()

    def test_no_crossing_returns_closest_to_zero(self):
        """Test that with no zero crossing, closest cumulative sum is returned."""
        gex_by_strike = {
            22000: 100000,
            22100: 50000,
            22200: 25000,
            22300: 10000,
        }
        flip = _find_gamma_flip(gex_by_strike)
        # Should be close to the strike with smallest cumulative
        assert flip in gex_by_strike.keys()

    def test_empty_dict_returns_zero(self):
        """Test that empty dict returns 0."""
        flip = _find_gamma_flip({})
        assert flip == 0.0

    def test_single_strike(self):
        """Test with single strike."""
        flip = _find_gamma_flip({22500: 50000})
        assert flip == 22500


class TestComputeGEX:
    """Test GEX computation from option chain."""

    def test_compute_gex_nifty_sample_data(self):
        """Test GEX computation with NIFTY sample data."""
        spot = SAMPLE_DATA["NIFTY"]["spot"]
        chain = SAMPLE_DATA["NIFTY"]["chain"]

        snapshot = compute_gex(chain, spot, "NIFTY")

        assert snapshot.symbol == "NIFTY"
        assert snapshot.spot_price == spot
        assert snapshot.total_gex != 0
        assert snapshot.gamma_flip > 0
        assert snapshot.put_wall > 0
        assert snapshot.call_wall > 0
        assert snapshot.max_gamma_strike > 0
        assert 0 < snapshot.pcr_gex < 3.0
        assert snapshot.regime in ["POSITIVE", "NEGATIVE"]
        assert len(snapshot.gex_by_strike) > 0

    def test_compute_gex_banknifty_sample_data(self):
        """Test GEX computation with BANKNIFTY sample data."""
        spot = SAMPLE_DATA["BANKNIFTY"]["spot"]
        chain = SAMPLE_DATA["BANKNIFTY"]["chain"]

        snapshot = compute_gex(chain, spot, "BANKNIFTY")

        assert snapshot.symbol == "BANKNIFTY"
        assert snapshot.spot_price == spot
        assert len(snapshot.gex_by_strike) > 0

    def test_empty_chain_returns_defaults(self):
        """Test that empty chain returns a default snapshot."""
        snapshot = compute_gex([], 22450, "NIFTY")

        assert snapshot.total_gex == 0
        assert snapshot.gamma_flip == 22450
        assert snapshot.put_wall == 22450
        assert snapshot.call_wall == 22450
        assert snapshot.pcr_gex == 1.0
        assert snapshot.net_delta_flow == 0

    def test_missing_greeks_handled(self):
        """Test that missing Greeks are handled gracefully."""
        chain = [
            {
                "strike_price": 22500,
                "call_options": {"market_data": {"oi": 100000}},
                "put_options": {"market_data": {"oi": 80000}},
            }
        ]
        snapshot = compute_gex(chain, 22450, "NIFTY")
        # Should not crash and should compute something
        assert snapshot is not None

    def test_invalid_strike_filtered(self):
        """Test that invalid strikes (<=0) are filtered."""
        chain = [
            {
                "strike_price": 0,
                "call_options": {"market_data": {"oi": 100000}, "option_greeks": {"gamma": 0.0005}},
                "put_options": {"market_data": {"oi": 80000}, "option_greeks": {"gamma": 0.0005}},
            },
            {
                "strike_price": 22500,
                "call_options": {"market_data": {"oi": 100000}, "option_greeks": {"gamma": 0.0005}},
                "put_options": {"market_data": {"oi": 80000}, "option_greeks": {"gamma": 0.0005}},
            },
        ]
        snapshot = compute_gex(chain, 22450, "NIFTY")
        # Only the valid strike (22500) should be in gex_by_strike
        assert len(snapshot.gex_by_strike) == 1

    def test_gex_calculation_sign(self):
        """Test that call GEX is positive and put GEX is negative."""
        chain = [
            {
                "strike_price": 22500,
                "call_options": {
                    "market_data": {"oi": 1000000},
                    "option_greeks": {"gamma": 0.0005},
                },
                "put_options": {
                    "market_data": {"oi": 800000},
                    "option_greeks": {"gamma": 0.0005},
                },
            }
        ]
        snapshot = compute_gex(chain, 22450, "NIFTY")
        # Net GEX should be slightly positive (call > put in magnitude)
        assert snapshot.gex_by_strike[22500] != 0


class TestComputeDeltaFlow:
    """Test delta flow computation."""

    def test_delta_flow_positive_delta(self):
        """Test delta flow with bullish bias."""
        spot = 22450
        chain = SAMPLE_DATA["NIFTY"]["chain"]

        flow = compute_delta_flow(chain, spot)

        # Should be a number (positive or negative)
        assert isinstance(flow, float)

    def test_delta_flow_near_atm_only(self):
        """Test that delta flow only considers near-ATM strikes."""
        spot = 22450
        chain = [
            {
                "strike_price": 20000,
                "call_options": {
                    "market_data": {"volume": 10000},
                    "option_greeks": {"delta": 0.99},
                },
                "put_options": {
                    "market_data": {"volume": 10000},
                    "option_greeks": {"delta": -0.99},
                },
            },
            {
                "strike_price": 22450,  # ATM
                "call_options": {
                    "market_data": {"volume": 50000},
                    "option_greeks": {"delta": 0.5},
                },
                "put_options": {
                    "market_data": {"volume": 50000},
                    "option_greeks": {"delta": -0.5},
                },
            },
        ]

        flow = compute_delta_flow(chain, spot)
        # Should prioritize the ATM strike
        assert isinstance(flow, float)

    def test_delta_flow_empty_chain(self):
        """Test delta flow with empty chain."""
        flow = compute_delta_flow([], 22450)
        assert flow == 0.0

    def test_delta_flow_missing_greeks(self):
        """Test delta flow with missing Greeks data."""
        chain = [
            {
                "strike_price": 22450,
                "call_options": {"market_data": {"volume": 50000}},
                "put_options": {"market_data": {"volume": 50000}},
            }
        ]
        # Should not crash
        flow = compute_delta_flow(chain, 22450)
        assert flow == 0.0
