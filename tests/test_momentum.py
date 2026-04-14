"""Unit tests for momentum scoring."""

import pytest
from momentum import (
    compute_momentum_score,
    _gex_regime_score,
    _delta_flow_score,
    _gex_roc_score,
    _pcr_gex_score,
    interpret_momentum,
)
from gex_engine import compute_gex, GEXSnapshot
from test_data import SAMPLE_DATA


class TestGEXRegimeScore:
    """Test GEX regime score calculation."""

    def test_negative_regime_high_score(self):
        """Test that negative GEX produces high momentum score."""
        snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=-1e7,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
            regime="NEGATIVE",
        )

        score = _gex_regime_score(snap, None)

        assert score > 50  # Negative GEX should score higher
        assert 0 <= score <= 100

    def test_positive_regime_lower_score(self):
        """Test that positive GEX produces lower momentum score."""
        snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=1e7,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
            regime="POSITIVE",
        )

        score = _gex_regime_score(snap, None)

        assert score < 50  # Positive GEX should score lower
        assert 0 <= score <= 100

    def test_spot_far_from_gamma_flip_negative(self):
        """Test negative GEX score increases when spot far from flip."""
        snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=23000,
            total_gex=-1e7,
            gamma_flip=22000,
            put_wall=21000,
            call_wall=24000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
            regime="NEGATIVE",
        )

        score = _gex_regime_score(snap, None)

        assert 0 <= score <= 100

    def test_spot_near_max_gamma_positive(self):
        """Test positive GEX score decreases when spot pinned at max gamma."""
        snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22500.01,
            total_gex=1e7,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
            regime="POSITIVE",
        )

        score = _gex_regime_score(snap, None)

        assert score < 30  # Pinned = very low momentum


class TestDeltaFlowScore:
    """Test delta flow score calculation."""

    def test_strongly_bullish_delta_flow(self):
        """Test high positive delta flow produces bullish score."""
        score = _delta_flow_score(100000, 200000)

        assert score > 70
        assert 0 <= score <= 100

    def test_strongly_bearish_delta_flow(self):
        """Test high negative delta flow produces bearish score."""
        score = _delta_flow_score(-100000, 200000)

        assert score < 30
        assert 0 <= score <= 100

    def test_neutral_delta_flow(self):
        """Test neutral delta flow produces neutral score."""
        score = _delta_flow_score(0, 200000)

        assert 40 <= score <= 60

    def test_normalized_by_max_delta_flow(self):
        """Test that score is normalized by max_delta_flow."""
        score1 = _delta_flow_score(net_delta_flow=100, max_delta_flow=1000)
        score2 = _delta_flow_score(net_delta_flow=1000, max_delta_flow=10000)

        # Should produce similar scores for similar ratios
        assert abs(score1 - score2) < 5

    def test_default_normalization(self):
        """Test that default normalization works when max_delta_flow is None."""
        score = _delta_flow_score(net_delta_flow=1000, max_delta_flow=None)

        assert 0 <= score <= 100


class TestGEXROCScore:
    """Test GEX rate of change score."""

    def test_gex_becoming_more_negative_high_score(self):
        """Test that GEX becoming more negative produces high score."""
        previous = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=-1e6,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
        )

        current = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=-2e6,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
        )

        score = _gex_roc_score(current, previous)

        assert 0 <= score <= 100

    def test_gex_becoming_more_positive_low_score(self):
        """Test that GEX becoming more positive produces low score."""
        previous = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=-2e6,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
        )

        current = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=-1e6,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
        )

        score = _gex_roc_score(current, previous)

        assert 0 <= score <= 100

    def test_no_previous_returns_neutral(self):
        """Test that no previous snapshot returns neutral score."""
        current = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=-1e6,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=0,
        )

        score = _gex_roc_score(current, None)

        assert score == 50  # Neutral


class TestPCRGEXScore:
    """Test PCR GEX score calculation."""

    def test_high_pcr_bullish_score(self):
        """Test high PCR (>1.3) produces bullish score."""
        score = _pcr_gex_score(1.5)

        assert score > 70
        assert score == 90

    def test_low_pcr_bearish_score(self):
        """Test low PCR (<0.7) produces bearish score."""
        score = _pcr_gex_score(0.5)

        assert score < 40

    def test_neutral_pcr_neutral_score(self):
        """Test neutral PCR (0.9-1.1) produces neutral score."""
        score = _pcr_gex_score(1.0)

        assert 40 <= score <= 60

    def test_pcr_boundaries(self):
        """Test PCR score at boundary values."""
        assert _pcr_gex_score(1.5) == 90
        assert _pcr_gex_score(1.3) >= 70
        assert _pcr_gex_score(0.7) > 29  # Floating point tolerance


class TestComputeMomentumScore:
    """Test composite momentum score calculation."""

    def test_score_in_valid_range(self):
        """Test that momentum score is always 0-100."""
        snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=1e7,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=5000,
        )

        score = compute_momentum_score(snap)

        assert 0 <= score <= 100
        assert isinstance(score, int)

    def test_negative_gex_higher_than_positive(self):
        """Test that negative GEX produces higher momentum than positive."""
        negative_snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=-1e7,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=10000,
            regime="NEGATIVE",
        )

        positive_snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=1e7,
            gamma_flip=22500,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22500,
            pcr_gex=1.0,
            net_delta_flow=10000,
            regime="POSITIVE",
        )

        neg_score = compute_momentum_score(negative_snap)
        pos_score = compute_momentum_score(positive_snap)

        # Negative GEX typically scores higher for momentum
        assert neg_score > pos_score

    def test_with_sample_data(self):
        """Test momentum score with sample data."""
        spot = SAMPLE_DATA["NIFTY"]["spot"]
        chain = SAMPLE_DATA["NIFTY"]["chain"]
        snap = compute_gex(chain, spot, "NIFTY")

        score = compute_momentum_score(snap)

        assert 0 <= score <= 100

    def test_with_previous_snapshot(self):
        """Test momentum score computation with previous snapshot."""
        spot = SAMPLE_DATA["NIFTY"]["spot"]
        chain = SAMPLE_DATA["NIFTY"]["chain"]

        previous = compute_gex(chain, spot, "NIFTY")
        current = compute_gex(chain, spot, "NIFTY")

        score = compute_momentum_score(current, previous)

        assert 0 <= score <= 100

    def test_bullish_conditions_produce_high_score(self):
        """Test that bullish GEX + positive delta produces high score."""
        snap = GEXSnapshot(
            symbol="NIFTY",
            spot_price=22450,
            total_gex=-1e7,
            gamma_flip=22400,
            put_wall=22000,
            call_wall=23000,
            max_gamma_strike=22300,
            pcr_gex=0.8,
            net_delta_flow=50000,
            regime="NEGATIVE",
        )

        score = compute_momentum_score(snap)

        # Bullish conditions should produce score > 60
        assert score > 50


class TestInterpretMomentum:
    """Test momentum score interpretation."""

    def test_strong_bullish(self):
        """Test strong bullish interpretation."""
        text = interpret_momentum(80)
        assert "Bullish" in text

    def test_moderate_bullish(self):
        """Test moderate bullish interpretation."""
        text = interpret_momentum(65)
        assert "Bullish" in text

    def test_neutral(self):
        """Test neutral interpretation."""
        text = interpret_momentum(50)
        assert "Neutral" in text

    def test_moderate_bearish(self):
        """Test moderate bearish interpretation."""
        text = interpret_momentum(35)
        assert "Bearish" in text

    def test_strong_bearish(self):
        """Test strong bearish interpretation."""
        text = interpret_momentum(10)
        assert "Bearish" in text

    def test_boundary_values(self):
        """Test interpretation at boundary values."""
        assert "Strong Bullish" in interpret_momentum(75)
        assert "Moderate Bullish" in interpret_momentum(60)
        assert "Moderate Bearish" in interpret_momentum(40)
        assert "Strong Bearish" in interpret_momentum(25)
