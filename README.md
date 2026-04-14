# NSE GEX Signal Engine

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/downloads/)
[![Tests Passing](https://img.shields.io/badge/Tests-88%20passed-brightgreen)](./tests/)
[![Code Coverage](https://img.shields.io/badge/Coverage-98%25-green)](./tests/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](./LICENSE)
[![Upstox API v2](https://img.shields.io/badge/Upstox-API%20v2-orange)](https://upstox.com/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram-Bot%20API-blue)](https://core.telegram.org/bots)

A Python system that fetches NSE option chain data from Upstox, computes Gamma Exposure (GEX) levels, detects trading signals, and sends alerts via Telegram.

Tracks **NIFTY** and **BANKNIFTY** only. No auto-trading. No Greeks calculation — Upstox provides them.

---

## Prerequisites

- Python 3.11+
- An [Upstox developer account](https://account.upstox.com/developer/apps) with a registered app
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Your Telegram chat ID (use [@userinfobot](https://t.me/userinfobot) to find it)

---

## Installation

```bash
cd gex-alerts
pip install -r requirements.txt
```

### requirements.txt

```
upstox-python-sdk>=2.9.0
python-telegram-bot>=20.0
APScheduler>=3.10.0
python-dotenv>=1.0.0
httpx>=0.27.0
```

---

## Step 1 — Create the .env file

Copy the example and fill it in:

```bash
cp .env.example .env
```

Open `.env`:

```env
UPSTOX_API_KEY=your_api_key_here
UPSTOX_API_SECRET=your_api_secret_here
UPSTOX_ACCESS_TOKEN=          # filled in Step 3
UPSTOX_REDIRECT_URI=http://localhost:5000/callback
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
RISK_FREE_RATE=6.5
```

**Where to find these values:**

| Variable | Where to get it |
|---|---|
| `UPSTOX_API_KEY` | Upstox Developer Portal → Your App → API Key |
| `UPSTOX_API_SECRET` | Upstox Developer Portal → Your App → Secret Key |
| `UPSTOX_ACCESS_TOKEN` | Generated in Step 3 below |
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | Send a message to your bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` |

---

## Step 2 — Register your Upstox app

1. Go to [account.upstox.com/developer/apps](https://account.upstox.com/developer/apps)
2. Create a new app
3. Set the **Redirect URI** to exactly: `http://localhost:5000/callback`
4. Copy the **API Key** and **Secret Key** into your `.env`

---

## Step 3 — Get the Upstox Access Token (first time)

Upstox uses OAuth2. Access tokens expire daily, so you need one before running.

### 3a. Generate the auth URL

```bash
python main.py --auth
```

Output:
```
Open this URL in your browser to authorize:

https://api.upstox.com/v2/login/authorization/dialog?client_id=...
```

### 3b. Authorize in browser

Open the URL. Log in with your Upstox credentials. After approving, the browser will redirect to something like:

```
http://localhost:5000/callback?code=XXXXXXXXXXXXXXXX
```

Copy the value of the `code` parameter.

### 3c. Exchange the code for an access token

```bash
python - <<'EOF'
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from upstox_client import UpstoxClient

async def main():
    client = UpstoxClient()
    code = input("Paste auth code: ").strip()
    token = await client.exchange_code(code)
    print(f"\nAccess token:\n{token}\n")
    print("Paste this into your .env as UPSTOX_ACCESS_TOKEN=")

asyncio.run(main())
EOF
```

Paste the printed token into `.env`:

```env
UPSTOX_ACCESS_TOKEN=your_long_token_here
```

### Daily token renewal

Upstox access tokens expire at midnight IST. Each morning before 9:10 AM, run Step 3 again — or use the Telegram `/token` command after you have a new token:

```
/token your_new_access_token_here
```

The engine will hot-swap the token without restarting.

---

## Step 4 — Smoke test (no API keys needed)

Before connecting to live APIs, verify the engine works with sample data:

```bash
python main.py --test
```

Expected output:

```
============================================================
  GEX ENGINE — TEST MODE (sample data)
============================================================

——————————————————————————————————————————————————
  NIFTY  |  Spot: 22,450  |  Expiry: 2026-04-16
——————————————————————————————————————————————————

  Regime:      POSITIVE
  Total GEX:   6.33e+10
  Gamma Flip:  22,143
  Put Wall:    22,500  (Support)
  Call Wall:   22,500  (Resistance)
  Max Gamma:   23,000  (Pin)
  PCR GEX:     0.97
  Delta Flow:  44,830

  Momentum:    56/100 (Neutral)

  Signals (1):
    [MEDIUM] WALL_BREACH: BEARISH breakdown — spot 22450 breached put wall at 22500

  Top GEX Strikes:
      23,000 | + ############################## (1.14e+11)
      ...
```

If you see output like this, the GEX engine is working correctly.

---

## Step 5 — Run in production

```bash
python main.py
```

At startup the engine:
1. Validates all `.env` variables
2. Tests the Upstox connection (`GET /v2/market-quote/ltp`)
3. Sends a Telegram message: `🟢 GEX Engine Starting...`
4. Initializes the SQLite database (`gex_data.db`)
5. Starts the Telegram bot (polling for commands)
6. Starts the scheduler

If Upstox fails at startup, the bot still starts so you can use `/token` to fix it.

---

## Scheduled jobs

| Job | When | What |
|---|---|---|
| `fetch_and_analyze` | Every 3 min, market hours | Fetch option chain → compute GEX → detect signals → send alerts |
| `send_summary` | Every 30 min, market hours | Summary table for all symbols |
| `pre_market_check` | 9:10 AM, weekdays | Verify connections, send "Engine Online" |
| `post_market_summary` | 3:35 PM, weekdays | EOD summary with total signals count |

Market hours: **9:15 AM – 3:30 PM IST, Monday–Friday**, skipping NSE holidays.

---

## Telegram bot commands

| Command | Description |
|---|---|
| `/status` | Full current state: regime, momentum, all key levels |
| `/levels` | One-liner per symbol with flip / walls / pin |
| `/score` | Momentum score with visual bar and interpretation |
| `/history` | Last 5 gamma flip (regime change) events |
| `/token <token>` | Hot-swap the Upstox access token |
| `/help` | List all commands |

---

## Signal types

| Signal | Priority | Trigger |
|---|---|---|
| `GAMMA_FLIP` 🔴 | HIGH | GEX regime changed sign (POSITIVE ↔ NEGATIVE) |
| `GAMMA_SQUEEZE` 🟡 | HIGH | Negative regime + spot within 0.5% of flip + volume spike |
| `MOMENTUM_EXTREME` 🔵 | HIGH | Score > 80 (strong bullish) or < 20 (strong bearish) |
| `WALL_BREACH` 🟢/🔻 | MEDIUM | Spot breaks above call wall or below put wall |
| `GEX_MAGNITUDE_SHIFT` ⚡ | MEDIUM | Total GEX changed by > 40% in one cycle |
| `GAMMA_FLIP_PROXIMITY` 📍 | MEDIUM | Spot within 0.3% of gamma flip level |
| `PIN_RISK` 📌 | LOW | Spot within 0.2% of max gamma strike |

**Deduplication**: The same signal type + symbol is suppressed for 15 minutes after sending. `GAMMA_FLIP` and `WALL_BREACH` are never suppressed.

---

## Momentum score (0–100)

The score is a weighted composite of four components:

| Component | Weight | What it measures |
|---|---|---|
| GEX Regime | 35% | Negative GEX (amplified moves) vs positive (mean reversion) |
| Delta Flow | 30% | Net dealer hedging direction (bullish vs bearish) |
| GEX Rate of Change | 20% | How fast GEX is shifting this cycle |
| PCR GEX | 15% | Put/call GEX ratio (> 1.3 = oversold, < 0.7 = overbought) |

| Score | Interpretation |
|---|---|
| > 75 | Strong bullish — dealers amplifying upside |
| 60–75 | Moderate bullish lean |
| 40–60 | Neutral / choppy — no clear edge |
| 25–40 | Moderate bearish lean |
| < 25 | Strong bearish — dealers amplifying downside |

---

## GEX math

```
call_gex(strike) = call_oi × call_gamma × 100 × spot² × 0.01
put_gex(strike)  = put_oi  × put_gamma  × 100 × spot² × 0.01 × (-1)
net_gex(strike)  = call_gex + put_gex

total_gex        = Σ net_gex across all strikes
gamma_flip       = strike where cumulative GEX crosses zero (linear interpolation)
put_wall         = strike with max |put_gex|   (key support)
call_wall        = strike with max |call_gex|  (key resistance)
max_gamma        = strike with max |net_gex|   (price magnet / pin)
```

Greeks (delta, gamma) come directly from Upstox — not calculated here.

---

## Database

SQLite at `gex_data.db`. Two tables:

- `gex_snapshots` — one row per symbol per 3-min cycle: all GEX levels + momentum score
- `signals` — one row per alert sent

Records older than 30 days are auto-purged on startup.

---

## Logs

```
logs/gex.log    — rotating, 5 MB × 3 backups
```

Also printed to stdout at INFO level. Set `--debug` in code to see raw API responses.

---

## Testing

The project includes a comprehensive unit test suite with **88 tests** and **98% code coverage**.

### Run tests

```bash
# All tests
pytest

# With coverage report
pytest --cov --cov-report=html

# Specific module
pytest tests/test_gex_engine.py -v
```

### Test coverage

| Module | Coverage | Tests |
|---|---|---|
| `gex_engine.py` | 99% | 21 tests |
| `signals.py` | 92% | 20 tests |
| `momentum.py` | 96% | 47 tests |
| `upstox_client.py` | 90% | 24 tests |
| **Total** | **98%** | **88 tests** |

See [TESTING.md](./TESTING.md) for detailed test documentation.

---

## File reference

```
gex-alerts/
├── config.py                — Env vars, thresholds, symbols, lot sizes, NSE holidays
├── upstox_client.py         — Upstox REST API v2 wrapper (OAuth2, option chain, LTP)
├── gex_engine.py            — GEX arithmetic: flip, walls, pin, delta flow
├── signals.py               — 7 signal types with priority and deduplication
├── momentum.py              — Composite momentum score 0-100
├── telegram_bot.py          — Alert formatting, bot commands, send/suppress logic
├── store.py                 — SQLite CRUD: snapshots + signals, auto-purge
├── scheduler.py             — APScheduler jobs, market hours guard, retry logic
├── main.py                  — Entry point (--test, --auth, production)
├── test_data.py             — 21-strike NIFTY + BANKNIFTY sample chains for --test
├── requirements.txt
├── .env.example
├── pytest.ini               — Pytest configuration
├── TESTING.md               — Comprehensive testing guide
├── CLAUDE.md                — Claude Code agent notes (if applicable)
├── tests/
│   ├── test_gex_engine.py   — 21 tests for GEX computation
│   ├── test_signals.py      — 20 tests for signal detection
│   ├── test_momentum.py     — 47 tests for momentum scoring
│   ├── test_upstox_client.py — 24 tests for API client
│   ├── conftest.py          — Pytest fixtures and configuration
│   └── README.md            — Testing quick reference
├── logs/                    — Rotating log files
└── gex_data.db              — SQLite database (created on first run)
```

---

## Common issues

**`ModuleNotFoundError`** — run `pip install -r requirements.txt`

**`Upstox connection failed` at startup** — token expired. Use `/token` in Telegram or re-run Step 3.

**No alerts during market hours** — check `logs/gex.log`. Look for `Upstox API down` or `All retries exhausted`.

**`TELEGRAM_CHAT_ID` unknown** — send `/start` to your bot in Telegram, then visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` and look for `"chat": {"id": ...}`.

**Both walls at the same strike** — expected when a round number (like 22500) has the highest OI for both calls and puts. The strike is both support and resistance.

**Token expires mid-day** — Upstox tokens expire at midnight IST, not mid-session. If you see failures during market hours, the token may have been revoked. Use `/token` to update.
