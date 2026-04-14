"""Unit tests for Upstox API client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from upstox_client import UpstoxClient


class TestUpstoxClientInit:
    """Test UpstoxClient initialization."""

    def test_init_with_provided_credentials(self):
        """Test client initialization with provided credentials."""
        client = UpstoxClient(
            api_key="test_key",
            api_secret="test_secret",
            access_token="test_token",
        )

        assert client.api_key == "test_key"
        assert client.api_secret == "test_secret"
        assert client.access_token == "test_token"

    def test_init_with_empty_credentials(self):
        """Test client initialization with empty credentials."""
        with patch("upstox_client.config") as mock_config:
            mock_config.UPSTOX_API_KEY = ""
            mock_config.UPSTOX_API_SECRET = ""
            mock_config.UPSTOX_ACCESS_TOKEN = ""

            client = UpstoxClient()

            assert client.api_key == ""
            assert client._client is None

    def test_init_loads_from_config(self):
        """Test that client loads credentials from config by default."""
        with patch("upstox_client.config") as mock_config:
            mock_config.UPSTOX_API_KEY = "config_key"
            mock_config.UPSTOX_API_SECRET = "config_secret"
            mock_config.UPSTOX_ACCESS_TOKEN = "config_token"

            client = UpstoxClient()

            assert client.api_key == "config_key"
            assert client.api_secret == "config_secret"
            assert client.access_token == "config_token"


class TestGetAuthUrl:
    """Test OAuth2 auth URL generation."""

    def test_get_auth_url(self):
        """Test that auth URL is generated correctly."""
        with patch("upstox_client.config") as mock_config:
            mock_config.UPSTOX_API_KEY = "test_key"
            mock_config.UPSTOX_REDIRECT_URI = "http://localhost:5000/callback"
            mock_config.UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"

            client = UpstoxClient(api_key="test_key")
            url = client.get_auth_url()

            assert "client_id=test_key" in url
            assert "redirect_uri=http" in url
            assert "response_type=code" in url
            assert url.startswith("https://api.upstox.com/v2/login/authorization/dialog")

    def test_auth_url_format(self):
        """Test that auth URL has proper format."""
        with patch("upstox_client.config") as mock_config:
            mock_config.UPSTOX_API_KEY = "test_key"
            mock_config.UPSTOX_REDIRECT_URI = "http://localhost:5000/callback"
            mock_config.UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"

            client = UpstoxClient(api_key="test_key")
            url = client.get_auth_url()

            assert "?" in url  # Has query parameters
            assert url.count("=") >= 2  # Has at least 2 parameters


class TestExchangeCode:
    """Test authorization code exchange."""

    @pytest.mark.asyncio
    async def test_exchange_code_success(self):
        """Test successful code exchange."""
        with patch("upstox_client.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {"access_token": "new_token"}
            mock_response.raise_for_status.return_value = None

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("upstox_client.config") as mock_config:
                mock_config.UPSTOX_API_KEY = "test_key"
                mock_config.UPSTOX_API_SECRET = "test_secret"
                mock_config.UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
                mock_config.UPSTOX_REDIRECT_URI = "http://localhost:5000/callback"

                client = UpstoxClient(
                    api_key="test_key",
                    api_secret="test_secret",
                )

                token = await client.exchange_code("auth_code_123")

                assert token == "new_token"

    @pytest.mark.asyncio
    async def test_exchange_code_updates_token(self):
        """Test that exchange code updates the client's token."""
        with patch("upstox_client.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {"access_token": "new_token"}
            mock_response.raise_for_status.return_value = None

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("upstox_client.config") as mock_config:
                mock_config.UPSTOX_API_KEY = "test_key"
                mock_config.UPSTOX_API_SECRET = "test_secret"
                mock_config.UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
                mock_config.UPSTOX_REDIRECT_URI = "http://localhost:5000/callback"

                client = UpstoxClient(
                    api_key="test_key",
                    api_secret="test_secret",
                    access_token="old_token",
                )

                await client.exchange_code("auth_code_123")

                assert client.access_token == "new_token"


class TestUpdateToken:
    """Test token update."""

    def test_update_token(self):
        """Test that update_token changes the access token."""
        client = UpstoxClient(
            api_key="test_key",
            access_token="old_token",
        )

        client.update_token("new_token")

        assert client.access_token == "new_token"

    def test_update_token_clears_client(self):
        """Test that update_token clears the HTTP client."""
        client = UpstoxClient(
            api_key="test_key",
            access_token="old_token",
        )
        mock_client = MagicMock()
        mock_client.is_closed = False
        client._client = mock_client

        client.update_token("new_token")

        assert client._client is None


@pytest.mark.asyncio
async def test_close_client():
    """Test that close() closes the HTTP client."""
    mock_client = AsyncMock()
    mock_client.is_closed = False

    client = UpstoxClient(api_key="test_key", access_token="test_token")
    client._client = mock_client

    await client.close()

    mock_client.close.assert_called_once()


class TestGetOptionChain:
    """Test option chain fetching."""

    @pytest.mark.asyncio
    async def test_get_option_chain_nifty(self):
        """Test fetching NIFTY option chain."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {
                "NIFTY": "NSE_INDEX|Nifty 50",
                "BANKNIFTY": "NSE_INDEX|Nifty Bank",
            }

            with patch.object(UpstoxClient, "_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "data": [
                        {"strike_price": 22500, "call_options": {}, "put_options": {}},
                        {"strike_price": 22600, "call_options": {}, "put_options": {}},
                    ]
                }

                client = UpstoxClient(api_key="test_key", access_token="test_token")
                chain = await client.get_option_chain("NIFTY", "2026-04-16")

                assert len(chain) == 2
                assert chain[0]["strike_price"] == 22500

    @pytest.mark.asyncio
    async def test_get_option_chain_invalid_symbol(self):
        """Test that invalid symbol raises ValueError."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {"NIFTY": "NSE_INDEX|Nifty 50"}

            client = UpstoxClient(api_key="test_key", access_token="test_token")

            with pytest.raises(ValueError):
                await client.get_option_chain("INVALID", "2026-04-16")


class TestGetSpotPrice:
    """Test spot price fetching."""

    @pytest.mark.asyncio
    async def test_get_spot_price_nifty(self):
        """Test fetching NIFTY spot price."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {
                "NIFTY": "NSE_INDEX|Nifty 50",
            }

            with patch.object(UpstoxClient, "_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "data": {
                        "NSE_INDEX:Nifty 50": {"last_price": 22450.50}
                    }
                }

                client = UpstoxClient(api_key="test_key", access_token="test_token")
                spot = await client.get_spot_price("NIFTY")

                assert spot == 22450.50

    @pytest.mark.asyncio
    async def test_get_spot_price_with_ltp_fallback(self):
        """Test spot price with ltp fallback."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {
                "NIFTY": "NSE_INDEX|Nifty 50",
            }

            with patch.object(UpstoxClient, "_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "data": {
                        "NSE_INDEX:Nifty 50": {"ltp": 22450.50}
                    }
                }

                client = UpstoxClient(api_key="test_key", access_token="test_token")
                spot = await client.get_spot_price("NIFTY")

                assert spot == 22450.50

    @pytest.mark.asyncio
    async def test_get_spot_price_invalid_symbol(self):
        """Test that invalid symbol raises ValueError."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {"NIFTY": "NSE_INDEX|Nifty 50"}

            client = UpstoxClient(api_key="test_key", access_token="test_token")

            with pytest.raises(ValueError):
                await client.get_spot_price("INVALID")

    @pytest.mark.asyncio
    async def test_get_spot_price_no_data(self):
        """Test that no LTP data raises RuntimeError."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {
                "NIFTY": "NSE_INDEX|Nifty 50",
            }

            with patch.object(UpstoxClient, "_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {"data": {}}

                client = UpstoxClient(api_key="test_key", access_token="test_token")

                with pytest.raises(RuntimeError):
                    await client.get_spot_price("NIFTY")


class TestGetExpiryDates:
    """Test expiry date fetching."""

    @pytest.mark.asyncio
    async def test_get_expiry_dates(self):
        """Test fetching expiry dates."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {
                "NIFTY": "NSE_INDEX|Nifty 50",
            }

            with patch.object(UpstoxClient, "_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "data": [
                        {"expiry": "2026-04-16"},
                        {"expiry": "2026-04-23"},
                        {"expiry": "2026-04-30"},
                    ]
                }

                client = UpstoxClient(api_key="test_key", access_token="test_token")
                expiries = await client.get_expiry_dates("NIFTY")

                assert len(expiries) == 3
                assert "2026-04-16" in expiries

    @pytest.mark.asyncio
    async def test_get_expiry_dates_sorted(self):
        """Test that expiry dates are returned sorted."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {
                "NIFTY": "NSE_INDEX|Nifty 50",
            }

            with patch.object(UpstoxClient, "_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "data": [
                        {"expiry": "2026-04-30"},
                        {"expiry": "2026-04-16"},
                        {"expiry": "2026-04-23"},
                    ]
                }

                client = UpstoxClient(api_key="test_key", access_token="test_token")
                expiries = await client.get_expiry_dates("NIFTY")

                assert expiries == ["2026-04-16", "2026-04-23", "2026-04-30"]


class TestGetNearestExpiry:
    """Test nearest expiry date fetching."""

    @pytest.mark.asyncio
    async def test_get_nearest_expiry(self):
        """Test fetching nearest expiry date."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {
                "NIFTY": "NSE_INDEX|Nifty 50",
            }

            with patch.object(UpstoxClient, "get_expiry_dates", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = [
                    "2026-04-16",
                    "2026-04-23",
                    "2026-04-30",
                ]

                client = UpstoxClient(api_key="test_key", access_token="test_token")
                expiry = await client.get_nearest_expiry("NIFTY")

                assert expiry == "2026-04-16"

    @pytest.mark.asyncio
    async def test_get_nearest_expiry_no_dates(self):
        """Test that no expiry dates raises RuntimeError."""
        with patch("upstox_client.config") as mock_config:
            mock_config.INDEX_INSTRUMENT_KEYS = {
                "NIFTY": "NSE_INDEX|Nifty 50",
            }

            with patch.object(UpstoxClient, "get_expiry_dates", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = []

                client = UpstoxClient(api_key="test_key", access_token="test_token")

                with pytest.raises(RuntimeError):
                    await client.get_nearest_expiry("NIFTY")


class TestHealthCheck:
    """Test health check."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test successful health check."""
        with patch.object(UpstoxClient, "get_spot_price", new_callable=AsyncMock) as mock_spot:
            mock_spot.return_value = 22450.0

            with patch("upstox_client.config") as mock_config:
                mock_config.SYMBOLS = ["NIFTY", "BANKNIFTY"]

                client = UpstoxClient(api_key="test_key", access_token="test_token")
                result = await client.health_check()

                assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test failed health check."""
        with patch.object(UpstoxClient, "get_spot_price", new_callable=AsyncMock) as mock_spot:
            mock_spot.side_effect = Exception("Connection failed")

            with patch("upstox_client.config") as mock_config:
                mock_config.SYMBOLS = ["NIFTY"]

                client = UpstoxClient(api_key="test_key", access_token="test_token")
                result = await client.health_check()

                assert result is False
