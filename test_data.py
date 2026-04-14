"""Sample option chain data for testing without live Upstox connection."""

from __future__ import annotations


def _strike(
    strike: float,
    call_oi: int,
    call_vol: int,
    call_ltp: float,
    call_delta: float,
    call_gamma: float,
    call_iv: float,
    put_oi: int,
    put_vol: int,
    put_ltp: float,
    put_delta: float,
    put_gamma: float,
    put_iv: float,
) -> dict:
    """Helper to build a strike dict matching Upstox response format."""
    return {
        "strike_price": strike,
        "underlying_spot_price": 22450,
        "underlying_key": "NSE_INDEX|Nifty 50",
        "expiry": "2026-04-16",
        "pcr": round(put_oi / call_oi, 2) if call_oi else 0,
        "call_options": {
            "instrument_key": f"NSE_FO|NIFTY26APR{int(strike)}CE",
            "market_data": {
                "ltp": call_ltp,
                "volume": call_vol,
                "oi": call_oi,
                "close_price": call_ltp * 0.97,
                "bid_price": call_ltp - 0.5,
                "bid_qty": 1500,
                "ask_price": call_ltp + 0.5,
                "ask_qty": 1200,
                "prev_oi": int(call_oi * 0.95),
            },
            "option_greeks": {
                "delta": call_delta,
                "gamma": call_gamma,
                "theta": -(15 - abs(call_delta - 0.5) * 20),
                "vega": 8.0 + call_gamma * 10000,
                "iv": call_iv,
                "pop": round(call_delta * 100, 1),
            },
        },
        "put_options": {
            "instrument_key": f"NSE_FO|NIFTY26APR{int(strike)}PE",
            "market_data": {
                "ltp": put_ltp,
                "volume": put_vol,
                "oi": put_oi,
                "close_price": put_ltp * 0.97,
                "bid_price": put_ltp - 0.5,
                "bid_qty": 1100,
                "ask_price": put_ltp + 0.5,
                "ask_qty": 1300,
                "prev_oi": int(put_oi * 0.95),
            },
            "option_greeks": {
                "delta": put_delta,
                "gamma": put_gamma,
                "theta": -(12 - abs(put_delta + 0.5) * 18),
                "vega": 7.5 + put_gamma * 10000,
                "iv": put_iv,
                "pop": round((1 + put_delta) * 100, 1),
            },
        },
    }


# Realistic NIFTY option chain: 21 strikes from 21500 to 23500 (100-pt intervals)
# Spot = 22,450
# OI clusters at round numbers (22000, 22500, 23000)
# Gamma highest near ATM
# IV shows a slight put-side smile
SAMPLE_OPTION_CHAIN_NIFTY: list[dict] = [
    _strike(21500, 320000,  8000,  965, 0.96, 0.00005, 16.5, 180000,  4000,   18, -0.04, 0.00005, 19.8),
    _strike(21600, 280000,  7500,  870, 0.95, 0.00007, 16.2, 200000,  4500,   22, -0.05, 0.00007, 19.2),
    _strike(21700, 350000,  9000,  775, 0.93, 0.00010, 15.8, 250000,  5500,   28, -0.07, 0.00010, 18.6),
    _strike(21800, 420000, 11000,  680, 0.91, 0.00014, 15.5, 380000,  7000,   35, -0.09, 0.00014, 18.1),
    _strike(21900, 480000, 13000,  590, 0.88, 0.00019, 15.1, 450000,  9000,   45, -0.12, 0.00019, 17.5),
    _strike(22000, 1250000, 45000, 505, 0.84, 0.00025, 14.8, 890000, 32000,  58, -0.16, 0.00025, 17.0),
    _strike(22100, 980000, 38000,  425, 0.79, 0.00032, 14.4, 1100000, 41000, 75, -0.21, 0.00032, 16.5),
    _strike(22200, 850000, 42000,  350, 0.73, 0.00040, 14.0, 1350000, 48000, 98, -0.27, 0.00040, 16.0),
    _strike(22300, 720000, 50000,  280, 0.65, 0.00048, 13.6, 1150000, 52000, 128, -0.35, 0.00048, 15.5),
    _strike(22400, 680000, 58000,  218, 0.56, 0.00054, 13.2, 950000,  55000, 165, -0.44, 0.00054, 15.0),
    _strike(22500, 1500000, 72000, 165, 0.47, 0.00056, 12.9, 1800000, 68000, 210, -0.53, 0.00056, 14.8),
    _strike(22600, 920000, 55000,  118, 0.38, 0.00052, 13.0, 780000,  45000, 265, -0.62, 0.00052, 14.5),
    _strike(22700, 1100000, 48000,  82, 0.30, 0.00046, 13.2, 650000,  38000, 328, -0.70, 0.00046, 14.2),
    _strike(22800, 780000, 35000,   55, 0.22, 0.00038, 13.5, 520000,  28000, 400, -0.78, 0.00038, 14.0),
    _strike(22900, 600000, 28000,   35, 0.16, 0.00030, 13.8, 400000,  22000, 480, -0.84, 0.00030, 13.8),
    _strike(23000, 1350000, 52000,  22, 0.11, 0.00022, 14.2, 320000,  15000, 565, -0.89, 0.00022, 13.5),
    _strike(23100, 550000, 20000,   14, 0.07, 0.00016, 14.6, 250000,  11000, 655, -0.93, 0.00016, 13.2),
    _strike(23200, 420000, 15000,    8, 0.05, 0.00011, 15.0, 200000,   8500, 748, -0.95, 0.00011, 13.0),
    _strike(23300, 350000, 11000,    5, 0.03, 0.00007, 15.5, 170000,   6000, 845, -0.97, 0.00007, 12.8),
    _strike(23400, 280000,  8000,    3, 0.02, 0.00005, 16.0, 140000,   4500, 945, -0.98, 0.00005, 12.5),
    _strike(23500, 220000,  6000,    2, 0.01, 0.00003, 16.5, 110000,   3000, 1045, -0.99, 0.00003, 12.2),
]


def _bnf_strike(strike: float, spot: float = 48320) -> dict:
    """Generate a BANKNIFTY strike with realistic values."""
    moneyness = (spot - strike) / spot
    call_delta = max(0.01, min(0.99, 0.5 + moneyness * 8))
    put_delta = call_delta - 1.0
    gamma = max(0.00002, 0.00035 * (1 - abs(moneyness) * 15))

    is_round = strike % 1000 == 0
    oi_mult = 2.5 if is_round else 1.0

    base_call_oi = int(max(50000, 400000 * (1 - abs(moneyness) * 5)) * oi_mult)
    base_put_oi = int(max(50000, 350000 * (1 - abs(moneyness) * 4)) * oi_mult)

    call_iv = 15.0 + abs(moneyness) * 30 + (0.5 if moneyness < 0 else 0)
    put_iv = 15.5 + abs(moneyness) * 28 + (1.0 if moneyness > 0 else 0)

    call_ltp = max(1, spot - strike + 100 * call_iv / 15) if moneyness > 0 else max(1, 50 * (1 - abs(moneyness) * 10))
    put_ltp = max(1, strike - spot + 100 * put_iv / 15) if moneyness < 0 else max(1, 50 * (1 - abs(moneyness) * 10))

    return {
        "strike_price": strike,
        "underlying_spot_price": spot,
        "underlying_key": "NSE_INDEX|Nifty Bank",
        "expiry": "2026-04-16",
        "pcr": round(base_put_oi / base_call_oi, 2) if base_call_oi else 0,
        "call_options": {
            "instrument_key": f"NSE_FO|BANKNIFTY26APR{int(strike)}CE",
            "market_data": {
                "ltp": round(call_ltp, 2),
                "volume": int(base_call_oi * 0.08),
                "oi": base_call_oi,
                "close_price": round(call_ltp * 0.97, 2),
                "bid_price": round(call_ltp - 1, 2),
                "bid_qty": 900,
                "ask_price": round(call_ltp + 1, 2),
                "ask_qty": 750,
                "prev_oi": int(base_call_oi * 0.94),
            },
            "option_greeks": {
                "delta": round(call_delta, 4),
                "gamma": round(gamma, 6),
                "theta": round(-(12 - abs(call_delta - 0.5) * 16), 2),
                "vega": round(10 + gamma * 8000, 2),
                "iv": round(call_iv, 1),
                "pop": round(call_delta * 100, 1),
            },
        },
        "put_options": {
            "instrument_key": f"NSE_FO|BANKNIFTY26APR{int(strike)}PE",
            "market_data": {
                "ltp": round(put_ltp, 2),
                "volume": int(base_put_oi * 0.07),
                "oi": base_put_oi,
                "close_price": round(put_ltp * 0.97, 2),
                "bid_price": round(put_ltp - 1, 2),
                "bid_qty": 800,
                "ask_price": round(put_ltp + 1, 2),
                "ask_qty": 850,
                "prev_oi": int(base_put_oi * 0.94),
            },
            "option_greeks": {
                "delta": round(put_delta, 4),
                "gamma": round(gamma, 6),
                "theta": round(-(10 - abs(put_delta + 0.5) * 14), 2),
                "vega": round(9 + gamma * 7500, 2),
                "iv": round(put_iv, 1),
                "pop": round((1 + put_delta) * 100, 1),
            },
        },
    }


# BANKNIFTY sample: spot = 48,320, strikes from 46500 to 50500 (200-pt intervals)
SAMPLE_OPTION_CHAIN_BANKNIFTY: list[dict] = [
    _bnf_strike(s, 48320)
    for s in range(46500, 50700, 200)
]


SAMPLE_DATA = {
    "NIFTY": {
        "spot": 22450,
        "expiry": "2026-04-16",
        "chain": SAMPLE_OPTION_CHAIN_NIFTY,
    },
    "BANKNIFTY": {
        "spot": 48320,
        "expiry": "2026-04-16",
        "chain": SAMPLE_OPTION_CHAIN_BANKNIFTY,
    },
}
