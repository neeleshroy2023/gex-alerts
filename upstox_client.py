"""Upstox API wrapper: OAuth2 auth, option chain fetch, spot prices."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

import config

logger = logging.getLogger(__name__)

BASE_URL = "https://api.upstox.com/v2"


class UpstoxClient:
    """Thin async wrapper around Upstox REST API v2."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        access_token: str = "",
    ) -> None:
        self.api_key = api_key or config.UPSTOX_API_KEY
        self.api_secret = api_secret or config.UPSTOX_API_SECRET
        self.access_token = access_token or config.UPSTOX_ACCESS_TOKEN
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Accept": "application/json",
                },
                timeout=15.0,
            )
        return self._client

    async def _get(self, path: str, params: dict | None = None) -> dict:
        client = await self._ensure_client()
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.close()

    # ------------------------------------------------------------------
    # OAuth2 helpers
    # ------------------------------------------------------------------

    def get_auth_url(self) -> str:
        """Return the URL the user must open to authorize the app."""
        params = {
            "client_id": self.api_key,
            "redirect_uri": config.UPSTOX_REDIRECT_URI,
            "response_type": "code",
        }
        return f"{config.UPSTOX_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, auth_code: str) -> str:
        """Exchange authorization code for an access token. Returns the token."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                config.UPSTOX_TOKEN_URL,
                data={
                    "code": auth_code,
                    "client_id": self.api_key,
                    "client_secret": self.api_secret,
                    "redirect_uri": config.UPSTOX_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()

        token = data.get("access_token", "")
        if token:
            self.access_token = token
            # Recreate the HTTP client with new token
            await self.close()
        return token

    def update_token(self, token: str) -> None:
        """Hot-swap the access token (e.g. via /token Telegram command)."""
        self.access_token = token
        # Force client recreation on next request
        if self._client and not self._client.is_closed:
            # Can't await here; mark for lazy recreation
            self._client = None

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_option_chain(self, symbol: str, expiry: str) -> list[dict]:
        """
        Fetch full option chain with pre-computed Greeks.

        Endpoint: GET /v2/option/chain
        Params: instrument_key, expiry_date

        Returns list of per-strike dicts with structure:
            {
                "strike_price": float,
                "underlying_spot_price": float,
                "call_options": {"market_data": {oi, volume, ltp, ...},
                                 "option_greeks": {delta, gamma, theta, vega, iv, pop}},
                "put_options": { ... same ... },
                ...
            }
        """
        instrument_key = config.INDEX_INSTRUMENT_KEYS.get(symbol)
        if not instrument_key:
            raise ValueError(f"Unknown symbol: {symbol}")

        data = await self._get(
            "/option/chain",
            params={"instrument_key": instrument_key, "expiry_date": expiry},
        )

        strikes = data.get("data", [])
        logger.debug("Fetched %d strikes for %s exp %s", len(strikes), symbol, expiry)
        return strikes

    async def get_spot_price(self, symbol: str) -> float:
        """Get current LTP for an index."""
        instrument_key = config.INDEX_INSTRUMENT_KEYS.get(symbol)
        if not instrument_key:
            raise ValueError(f"Unknown symbol: {symbol}")

        data = await self._get(
            "/market-quote/ltp",
            params={"instrument_key": instrument_key},
        )

        # Response: {"status":"success","data":{"NSE_INDEX:Nifty 50":{"ltp":22450,...}}}
        quotes = data.get("data", {})
        for _key, quote in quotes.items():
            return float(quote.get("last_price", quote.get("ltp", 0)))
        raise RuntimeError(f"No LTP data for {symbol}")

    async def get_expiry_dates(self, symbol: str) -> list[str]:
        """Get available expiry dates for the symbol (YYYY-MM-DD strings)."""
        instrument_key = config.INDEX_INSTRUMENT_KEYS.get(symbol)
        if not instrument_key:
            raise ValueError(f"Unknown symbol: {symbol}")

        data = await self._get(
            "/option/contract",
            params={"instrument_key": instrument_key},
        )

        contracts = data.get("data", [])
        expiries = sorted({c["expiry"] for c in contracts if "expiry" in c})
        return expiries

    async def get_nearest_expiry(self, symbol: str) -> str:
        """Return the nearest (current-week) expiry date string."""
        expiries = await self.get_expiry_dates(symbol)
        if not expiries:
            raise RuntimeError(f"No expiry dates found for {symbol}")
        return expiries[0]

    async def health_check(self) -> bool:
        """Quick check that our token is valid by hitting a lightweight endpoint."""
        try:
            symbol = config.SYMBOLS[0]
            await self.get_spot_price(symbol)
            return True
        except Exception as exc:
            logger.warning("Upstox health check failed: %s", exc)
            return False
