"""Pytest configuration and fixtures for GEX Alert Engine tests."""

import pytest
import asyncio
import sys


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_gex_snapshot():
    """Fixture providing a sample GEX snapshot for testing."""
    from gex_engine import GEXSnapshot

    return GEXSnapshot(
        symbol="NIFTY",
        spot_price=22450,
        total_gex=1.5e6,
        gamma_flip=22500,
        put_wall=22000,
        call_wall=23000,
        max_gamma_strike=22500,
        pcr_gex=0.95,
        net_delta_flow=5000,
        gex_by_strike={
            22000: -100000,
            22100: -50000,
            22200: 25000,
            22300: 50000,
            22400: 75000,
            22500: 100000,
        },
    )


@pytest.fixture
def sample_option_chain():
    """Fixture providing a minimal sample option chain."""
    return [
        {
            "strike_price": 22500,
            "call_options": {
                "market_data": {"oi": 1000000, "volume": 50000},
                "option_greeks": {"delta": 0.5, "gamma": 0.0005},
            },
            "put_options": {
                "market_data": {"oi": 800000, "volume": 40000},
                "option_greeks": {"delta": -0.5, "gamma": 0.0005},
            },
        },
        {
            "strike_price": 22600,
            "call_options": {
                "market_data": {"oi": 800000, "volume": 40000},
                "option_greeks": {"delta": 0.4, "gamma": 0.0004},
            },
            "put_options": {
                "market_data": {"oi": 1000000, "volume": 50000},
                "option_greeks": {"delta": -0.6, "gamma": 0.0004},
            },
        },
    ]
