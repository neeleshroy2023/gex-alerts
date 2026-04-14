"""APScheduler setup for market-hours job scheduling."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
from gex_engine import compute_gex
from momentum import compute_momentum_score
from signals import detect_signals

if TYPE_CHECKING:
    from store import GEXStore
    from telegram_bot import TelegramAlertBot
    from upstox_client import UpstoxClient

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


class GEXScheduler:
    """Manages all scheduled jobs for the GEX engine."""

    def __init__(
        self,
        upstox: UpstoxClient,
        store: GEXStore,
        bot: TelegramAlertBot,
    ) -> None:
        self.upstox = upstox
        self.store = store
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

    def start(self) -> None:
        """Register all jobs and start the scheduler."""
        # Fetch & analyze every N minutes during market hours (Mon-Fri)
        self.scheduler.add_job(
            self._fetch_and_analyze,
            IntervalTrigger(minutes=config.FETCH_INTERVAL_MINUTES),
            id="fetch_and_analyze",
            misfire_grace_time=60,
        )

        # Periodic summary every 30 min during market hours
        self.scheduler.add_job(
            self._send_summary,
            IntervalTrigger(minutes=config.SUMMARY_INTERVAL_MINUTES),
            id="send_summary",
            misfire_grace_time=120,
        )

        # Pre-market check at 9:10 AM
        self.scheduler.add_job(
            self._pre_market_check,
            CronTrigger(hour=9, minute=10, day_of_week="mon-fri"),
            id="pre_market_check",
            misfire_grace_time=300,
        )

        # Post-market summary at 3:35 PM
        self.scheduler.add_job(
            self._post_market_summary,
            CronTrigger(hour=15, minute=35, day_of_week="mon-fri"),
            id="post_market_summary",
            misfire_grace_time=300,
        )

        self.scheduler.start()
        logger.info("Scheduler started with %d jobs", len(self.scheduler.get_jobs()))

    def stop(self) -> None:
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _is_market_open(self) -> bool:
        now = datetime.now(IST)
        if now.weekday() >= 5:
            return False
        if now.strftime("%Y-%m-%d") in config.NSE_HOLIDAYS:
            return False
        market_open = now.replace(
            hour=config.MARKET_OPEN_HOUR, minute=config.MARKET_OPEN_MINUTE, second=0
        )
        market_close = now.replace(
            hour=config.MARKET_CLOSE_HOUR, minute=config.MARKET_CLOSE_MINUTE, second=0
        )
        return market_open <= now <= market_close

    def _is_holiday(self) -> bool:
        now = datetime.now(IST)
        return (
            now.weekday() >= 5
            or now.strftime("%Y-%m-%d") in config.NSE_HOLIDAYS
        )

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    async def _fetch_and_analyze(self) -> None:
        """Main loop: fetch option chains, compute GEX, detect signals."""
        if not self._is_market_open():
            return

        for symbol in config.SYMBOLS:
            try:
                await self._process_symbol(symbol)
            except Exception:
                logger.exception("Error processing %s", symbol)

    async def _process_symbol(self, symbol: str) -> None:
        """Fetch, compute, detect, store, alert — for one symbol."""
        # Retry with backoff
        chain = await self._fetch_with_retry(symbol)
        if not chain:
            return

        spot = chain[0].get("underlying_spot_price", 0) if chain else 0
        if not spot:
            try:
                spot = await self.upstox.get_spot_price(symbol)
            except Exception:
                logger.error("Cannot get spot price for %s, skipping", symbol)
                return

        # Compute GEX
        snapshot = compute_gex(chain, spot, symbol)

        # Get previous snapshot for comparison
        previous = self.store.get_previous_snapshot(symbol)

        # Compute momentum
        spot_history = self.store.get_spot_history(symbol, limit=20)
        avg_gex = _avg_gex_from_history(self.store, symbol)
        max_delta = _max_delta_from_history(self.store, symbol)
        score = compute_momentum_score(
            snapshot,
            previous_gex=previous,
            avg_total_gex=avg_gex,
            max_delta_flow=max_delta,
        )

        # Store snapshot
        self.store.save_snapshot(snapshot, momentum_score=score)

        # Update latest state on bot
        self.bot.latest_snapshots[symbol] = snapshot
        self.bot.latest_scores[symbol] = score

        # Detect signals
        signals = detect_signals(
            snapshot,
            previous,
            spot_history=spot_history,
            momentum_score=score,
        )

        # Send alerts and store signals
        for sig in signals:
            await self.bot.send_signal(sig, snapshot, score)
            self.store.save_signal(
                symbol=sig.symbol,
                signal_type=sig.type,
                priority=sig.priority,
                message=sig.message,
                data=sig.data,
            )

    async def _fetch_with_retry(self, symbol: str, retries: int = 3) -> list[dict]:
        """Fetch option chain with exponential backoff."""
        for attempt in range(retries):
            try:
                expiry = await self.upstox.get_nearest_expiry(symbol)
                chain = await self.upstox.get_option_chain(symbol, expiry)
                if chain:
                    return chain
            except Exception as exc:
                wait = 2 ** (attempt + 1)
                logger.warning(
                    "Upstox fetch failed for %s (attempt %d/%d): %s — retrying in %ds",
                    symbol, attempt + 1, retries, exc, wait,
                )
                await asyncio.sleep(wait)

        logger.error("All retries exhausted for %s", symbol)
        await self.bot.send(
            f"\u26a0\ufe0f Upstox API down for {symbol} — skipping cycle"
        )
        return []

    async def _send_summary(self) -> None:
        """Send periodic GEX summary during market hours."""
        if not self._is_market_open():
            return
        if not self.bot.latest_snapshots:
            return
        await self.bot.send_summary(
            self.bot.latest_snapshots,
            self.bot.latest_scores,
        )

    async def _pre_market_check(self) -> None:
        """Run at 9:10 AM to verify connections."""
        if self._is_holiday():
            return

        upstox_ok = await self.upstox.health_check()
        status = "\u2705" if upstox_ok else "\u274c"
        await self.bot.send(
            f"\U0001f7e2 <b>GEX Engine Online</b>\n\n"
            f"Upstox: {status}\n"
            f"Symbols: {', '.join(config.SYMBOLS)}\n"
            f"Fetch interval: {config.FETCH_INTERVAL_MINUTES}min"
        )

        if not upstox_ok:
            await self.bot.send(
                "\u274c Upstox connection failed. Use /token to update."
            )

    async def _post_market_summary(self) -> None:
        """End-of-day summary at 3:35 PM."""
        if self._is_holiday():
            return

        signal_count = self.store.get_today_signal_count()
        await self.bot.send_eod_summary(
            self.bot.latest_snapshots,
            self.bot.latest_scores,
            signal_count,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _avg_gex_from_history(store: GEXStore, symbol: str) -> float | None:
    """Compute average total_gex from recent snapshots (for normalization)."""
    rows = store.get_recent_snapshots(symbol, limit=100)
    if not rows:
        return None
    values = [r["total_gex"] for r in rows if r.get("total_gex")]
    return sum(values) / len(values) if values else None


def _max_delta_from_history(store: GEXStore, symbol: str) -> float | None:
    """Compute max absolute delta flow from recent snapshots."""
    rows = store.get_recent_snapshots(symbol, limit=100)
    if not rows:
        return None
    values = [abs(r["net_delta_flow"]) for r in rows if r.get("net_delta_flow")]
    return max(values) if values else None
