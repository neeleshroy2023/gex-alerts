# GEX Alert Engine - Unit Tests

Comprehensive unit test suite for the GEX Alert Engine.

## Test Structure

- **test_gex_engine.py** - Tests for GEX computation (`compute_gex`, `_find_gamma_flip`, `compute_delta_flow`)
- **test_signals.py** - Tests for signal detection logic
- **test_momentum.py** - Tests for momentum scoring calculations
- **test_upstox_client.py** - Tests for Upstox API client (with HTTP mocking)
- **conftest.py** - Pytest configuration and shared fixtures

## Running Tests

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run all tests
```bash
pytest
```

### Run specific test file
```bash
pytest tests/test_gex_engine.py
```

### Run specific test class
```bash
pytest tests/test_gex_engine.py::TestComputeGEX
```

### Run specific test
```bash
pytest tests/test_gex_engine.py::TestComputeGEX::test_compute_gex_nifty_sample_data
```

### Run with coverage report
```bash
pytest --cov=. --cov-report=html
```

This generates an HTML coverage report in `htmlcov/index.html`

### Run only fast tests (skip async tests if needed)
```bash
pytest -m "not asyncio"
```

### Run with verbose output
```bash
pytest -v
```

## Test Coverage

Current test coverage includes:

### GEX Engine (gex_engine.py)
- `_safe_float()` helper function
- `GEXSnapshot` dataclass creation and properties
- `_find_gamma_flip()` detection with various strike distributions
- `compute_gex()` with real and synthetic option chains
- `compute_delta_flow()` calculation for near-ATM strikes

### Signals (signals.py)
- `Signal` dataclass creation
- `detect_signals()` for all signal types:
  - GAMMA_FLIP (regime changes)
  - GAMMA_SQUEEZE (negative regime + proximity + volume spike)
  - MOMENTUM_EXTREME (bullish/bearish)
  - WALL_BREACH (call/put walls)
  - GEX_MAGNITUDE_SHIFT (rapid repositioning)
  - GAMMA_FLIP_PROXIMITY (inflection zones)
  - PIN_RISK (max gamma proximity)
- Signal priority sorting
- `_detect_volume_spike()` detection

### Momentum (momentum.py)
- Momentum score calculation (0-100)
- Individual component scoring:
  - GEX regime score
  - Delta flow score
  - GEX rate of change score
  - PCR GEX score
- Momentum interpretation (Strong Bullish → Strong Bearish)

### Upstox Client (upstox_client.py)
- Client initialization with config/custom credentials
- OAuth2 URL generation
- Authorization code exchange
- Token updates
- HTTP client lifecycle
- Option chain fetching
- Spot price fetching
- Expiry date fetching
- Health checks
- Error handling and edge cases

## Sample Data

Tests use realistic sample data for NIFTY and BANKNIFTY from `test_data.py`:
- Complete option chain with Greeks
- Strike clustering at support/resistance levels
- Realistic OI, volume, and IV distributions

## Fixtures

Available pytest fixtures in `conftest.py`:

- **event_loop** - Event loop for async tests
- **sample_gex_snapshot** - Pre-built GEX snapshot
- **sample_option_chain** - Minimal option chain sample

## Notes

- Upstox API tests use mocking to avoid external dependencies
- Async tests are automatically detected via `@pytest.mark.asyncio`
- All tests are isolated and can run in any order
- No external API calls are made during test execution
- Configuration is patched to prevent test environment pollution
