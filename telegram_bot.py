"""Telegram alerts and bot commands for GEX signals."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from momentum import interpret_momentum
from signals import Signal

if TYPE_CHECKING:
    from gex_engine import GEXSnapshot
    from store import GEXStore
    from upstox_client import UpstoxClient

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Emoji mapping for signal types
SIGNAL_EMOJI: dict[str, str] = {
    "GAMMA_FLIP": "\U0001f534",         # Red circle
    "GAMMA_SQUEEZE": "\U0001f7e1",      # Yellow circle
    "MOMENTUM_EXTREME": "\U0001f535",   # Blue circle
    "WALL_BREACH_BULLISH": "\U0001f7e2",  # Green circle
    "WALL_BREACH_BEARISH": "\U0001f53b",  # Down triangle
    "GEX_MAGNITUDE_SHIFT": "\u26a1",    # Lightning
    "GAMMA_FLIP_PROXIMITY": "\U0001f4cd",  # Pin
    "PIN_RISK": "\U0001f4cc",           # Pushpin
}


class TelegramAlertBot:
    """Async Telegram bot for GEX alerts and commands."""

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
    ) -> None:
        self.bot_token = bot_token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.app: Application | None = None

        # Deduplication: {(signal_type, symbol): last_sent_time}
        self._sent: dict[tuple[str, str], datetime] = {}

        # References set by main.py after init
        self.store: GEXStore | None = None
        self.upstox: UpstoxClient | None = None
        self.latest_snapshots: dict[str, GEXSnapshot] = {}
        self.latest_scores: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def build(self) -> Application:
        """Build the telegram Application and register command handlers."""
        self.app = (
            Application.builder()
            .token(self.bot_token)
            .build()
        )
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("levels", self._cmd_levels))
        self.app.add_handler(CommandHandler("score", self._cmd_score))
        self.app.add_handler(CommandHandler("history", self._cmd_history))
        self.app.add_handler(CommandHandler("token", self._cmd_token))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("start", self._cmd_help))
        return self.app

    async def start_polling(self) -> None:
        """Start the bot in polling mode (non-blocking)."""
        if self.app is None:
            self.build()
        assert self.app is not None
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]
        logger.info("Telegram bot polling started")

    async def stop(self) -> None:
        if self.app:
            await self.app.updater.stop()  # type: ignore[union-attr]
            await self.app.stop()
            await self.app.shutdown()

    # ------------------------------------------------------------------
    # Sending messages
    # ------------------------------------------------------------------

    async def send(self, text: str, chat_id: str = "") -> None:
        """Send a plain-text message to the configured chat."""
        if self.app is None:
            self.build()
        assert self.app is not None
        target = chat_id or self.chat_id
        try:
            await self.app.bot.send_message(
                chat_id=target,
                text=text,
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to send Telegram message")

    # ------------------------------------------------------------------
    # Signal alerts
    # ------------------------------------------------------------------

    async def send_signal(self, signal: Signal, snapshot: GEXSnapshot, momentum_score: int) -> None:
        """Format and send a signal alert, respecting deduplication rules."""
        if self._is_suppressed(signal):
            logger.debug("Suppressed duplicate signal: %s %s", signal.type, signal.symbol)
            return

        emoji = self._get_signal_emoji(signal)
        now = datetime.now(IST)
        time_str = now.strftime("%I:%M %p IST | %b %d, %Y")
        interp = interpret_momentum(momentum_score)

        delta_cr = snapshot.net_delta_flow / 1e5  # rough "crore" scaling for display
        delta_sign = "+" if delta_cr >= 0 else ""
        delta_dir = "Bullish" if delta_cr >= 0 else "Bearish"

        trade = _trade_suggestion(signal, snapshot)

        text = (
            f"{emoji} <b>{signal.type.replace('_', ' ')}</b> — {signal.symbol}\n\n"
            f"\u26a1 {signal.message}\n"
            f"\U0001f4b9 <b>Trade Idea:</b> {trade}\n\n"
            f"\U0001f4ca Momentum: {momentum_score}/100 ({interp})\n"
            f"\U0001f4cd Spot: \u20b9{snapshot.spot_price:,.0f}\n\n"
            f"\U0001f3af <b>Key Levels:</b>\n"
            f"   Gamma Flip: {snapshot.gamma_flip:,.0f}\n"
            f"   Put Wall: {snapshot.put_wall:,.0f} (Support)\n"
            f"   Call Wall: {snapshot.call_wall:,.0f} (Resistance)\n"
            f"   Max Gamma: {snapshot.max_gamma_strike:,.0f} (Pin)\n\n"
            f"\U0001f504 Delta Flow: {delta_sign}{delta_cr:,.0f}Cr ({delta_dir})\n"
            f"\U0001f4d0 PCR GEX: {snapshot.pcr_gex:.2f}\n\n"
            f"\u23f0 {time_str}"
        )

        await self.send(text)
        self._mark_sent(signal)

    async def send_summary(self, snapshots: dict[str, GEXSnapshot], scores: dict[str, int]) -> None:
        """Send a periodic multi-symbol summary."""
        now = datetime.now(IST)
        time_str = now.strftime("%I:%M %p IST")

        lines = [f"\U0001f4ca <b>GEX Summary — {time_str}</b>\n"]

        for symbol in config.SYMBOLS:
            snap = snapshots.get(symbol)
            if not snap:
                continue
            score = scores.get(symbol, 50)
            regime_icon = "\u26a1" if snap.regime == "NEGATIVE" else "\U0001f6e1\ufe0f"
            delta_cr = snap.net_delta_flow / 1e5
            delta_sign = "+" if delta_cr >= 0 else ""

            lines.append(
                f"<b>{symbol}</b> (\u20b9{snap.spot_price:,.0f})\n"
                f"  Regime: {snap.regime} {regime_icon} | Score: {score}\n"
                f"  Flip: {snap.gamma_flip:,.0f} | "
                f"Walls: {snap.put_wall:,.0f} / {snap.call_wall:,.0f}\n"
                f"  Delta Flow: {delta_sign}{delta_cr:,.0f}Cr\n"
            )

        await self.send("\n".join(lines))

    async def send_eod_summary(
        self, snapshots: dict[str, GEXSnapshot], scores: dict[str, int], signal_count: int
    ) -> None:
        """End-of-day summary at 3:35 PM."""
        now = datetime.now(IST)
        date_str = now.strftime("%b %d, %Y")

        lines = [f"\U0001f4c8 <b>End-of-Day Summary — {date_str}</b>\n"]
        lines.append(f"Signals today: {signal_count}\n")

        for symbol in config.SYMBOLS:
            snap = snapshots.get(symbol)
            if not snap:
                continue
            score = scores.get(symbol, 50)
            interp = interpret_momentum(score)
            lines.append(
                f"<b>{symbol}</b> — Close: \u20b9{snap.spot_price:,.0f}\n"
                f"  Regime: {snap.regime} | Score: {score} ({interp})\n"
                f"  Flip: {snap.gamma_flip:,.0f} | "
                f"Walls: {snap.put_wall:,.0f} / {snap.call_wall:,.0f}\n"
            )

        await self.send("\n".join(lines))

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _is_suppressed(self, signal: Signal) -> bool:
        if signal.type in config.NEVER_SUPPRESS_SIGNALS:
            return False
        key = (signal.type, signal.symbol)
        last = self._sent.get(key)
        if last is None:
            return False
        elapsed = (datetime.now(IST) - last).total_seconds()
        return elapsed < config.SIGNAL_SUPPRESS_MINUTES * 60

    def _mark_sent(self, signal: Signal) -> None:
        key = (signal.type, signal.symbol)
        self._sent[key] = datetime.now(IST)

    def _get_signal_emoji(self, signal: Signal) -> str:
        if signal.type == "WALL_BREACH":
            direction = signal.data.get("direction", "BULLISH")
            return SIGNAL_EMOJI.get(f"WALL_BREACH_{direction}", "\u26a1")
        return SIGNAL_EMOJI.get(signal.type, "\u26a1")

    # ------------------------------------------------------------------
    # Bot commands
    # ------------------------------------------------------------------

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/status — Full current state for all symbols."""
        if not self.latest_snapshots:
            await update.message.reply_text("No data yet. Market may be closed.")  # type: ignore[union-attr]
            return

        now = datetime.now(IST)
        is_market = _is_market_hours(now)
        suffix = "" if is_market else " (Market Closed)"

        lines = [f"\U0001f4ca <b>Current Status{suffix}</b>\n"]

        for symbol in config.SYMBOLS:
            snap = self.latest_snapshots.get(symbol)
            if not snap:
                continue
            score = self.latest_scores.get(symbol, 50)
            interp = interpret_momentum(score)
            regime_icon = "\u26a1" if snap.regime == "NEGATIVE" else "\U0001f6e1\ufe0f"
            delta_cr = snap.net_delta_flow / 1e5
            delta_sign = "+" if delta_cr >= 0 else ""

            lines.append(
                f"<b>{symbol}</b> (\u20b9{snap.spot_price:,.0f})\n"
                f"  Regime: {snap.regime} {regime_icon}\n"
                f"  Momentum: {score}/100 ({interp})\n"
                f"  Gamma Flip: {snap.gamma_flip:,.0f}\n"
                f"  Put Wall: {snap.put_wall:,.0f} | Call Wall: {snap.call_wall:,.0f}\n"
                f"  Max Gamma: {snap.max_gamma_strike:,.0f}\n"
                f"  Delta Flow: {delta_sign}{delta_cr:,.0f}Cr\n"
                f"  PCR GEX: {snap.pcr_gex:.2f}\n"
                f"  Last update: {snap.timestamp[:19]}\n"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")  # type: ignore[union-attr]

    async def _cmd_levels(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/levels — Key levels, one line per symbol."""
        if not self.latest_snapshots:
            await update.message.reply_text("No data yet.")  # type: ignore[union-attr]
            return
        lines = ["\U0001f3af <b>Key Levels</b>\n"]
        for symbol in config.SYMBOLS:
            snap = self.latest_snapshots.get(symbol)
            if not snap:
                continue
            lines.append(
                f"<b>{symbol}</b> \u20b9{snap.spot_price:,.0f} | "
                f"Flip: {snap.gamma_flip:,.0f} | "
                f"Put: {snap.put_wall:,.0f} | "
                f"Call: {snap.call_wall:,.0f} | "
                f"Pin: {snap.max_gamma_strike:,.0f}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")  # type: ignore[union-attr]

    async def _cmd_score(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/score — Momentum score with component breakdown."""
        if not self.latest_snapshots:
            await update.message.reply_text("No data yet.")  # type: ignore[union-attr]
            return
        lines = ["\U0001f4ca <b>Momentum Scores</b>\n"]
        for symbol in config.SYMBOLS:
            snap = self.latest_snapshots.get(symbol)
            score = self.latest_scores.get(symbol)
            if not snap or score is None:
                continue
            interp = interpret_momentum(score)
            bar = _score_bar(score)
            lines.append(
                f"<b>{symbol}</b>: {score}/100 — {interp}\n"
                f"  {bar}\n"
                f"  Regime: {snap.regime} | PCR: {snap.pcr_gex:.2f}\n"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")  # type: ignore[union-attr]

    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/history — Last 5 regime changes per symbol."""
        if not self.store:
            await update.message.reply_text("Store not initialized.")  # type: ignore[union-attr]
            return
        lines = ["\U0001f4dc <b>Recent Regime Changes</b>\n"]
        for symbol in config.SYMBOLS:
            changes = self.store.get_regime_changes(symbol, limit=5)
            if not changes:
                lines.append(f"<b>{symbol}</b>: No regime changes recorded\n")
                continue
            lines.append(f"<b>{symbol}</b>:")
            for ch in changes:
                ts = ch.get("timestamp", "")[:16].replace("T", " ")
                msg = ch.get("message", "")
                lines.append(f"  {ts} — {msg[:80]}")
            lines.append("")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")  # type: ignore[union-attr]

    async def _cmd_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/token <access_token> — Update Upstox access token."""
        if not context.args:
            await update.message.reply_text(  # type: ignore[union-attr]
                "Usage: /token <your_access_token>"
            )
            return
        new_token = context.args[0]
        if self.upstox:
            self.upstox.update_token(new_token)
            ok = await self.upstox.health_check()
            if ok:
                await update.message.reply_text(  # type: ignore[union-attr]
                    "\u2705 Token updated. Upstox connection verified."
                )
            else:
                await update.message.reply_text(  # type: ignore[union-attr]
                    "\u26a0\ufe0f Token updated but health check failed. "
                    "Verify your token is valid."
                )
        else:
            await update.message.reply_text("\u274c Upstox client not initialized.")  # type: ignore[union-attr]

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/help — List all commands."""
        text = (
            "\U0001f916 <b>GEX Alert Bot — Commands</b>\n\n"
            "/status — Full current state\n"
            "/levels — Key levels (one-liner per symbol)\n"
            "/score — Momentum score with breakdown\n"
            "/history — Last 5 regime changes\n"
            "/token &lt;token&gt; — Update Upstox access token\n"
            "/help — This message"
        )
        await update.message.reply_text(text, parse_mode="HTML")  # type: ignore[union-attr]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _is_market_hours(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    today_str = now.strftime("%Y-%m-%d")
    if today_str in config.NSE_HOLIDAYS:
        return False
    market_open = now.replace(
        hour=config.MARKET_OPEN_HOUR, minute=config.MARKET_OPEN_MINUTE, second=0
    )
    market_close = now.replace(
        hour=config.MARKET_CLOSE_HOUR, minute=config.MARKET_CLOSE_MINUTE, second=0
    )
    return market_open <= now <= market_close


def _score_bar(score: int, width: int = 20) -> str:
    filled = int(score / 100 * width)
    return "[" + "\u2588" * filled + "\u2591" * (width - filled) + "]"


def _trade_suggestion(signal: Signal, snapshot: "GEXSnapshot") -> str:
    """Return a concrete BUY suggestion for the given signal.

    Only HIGH-priority signals reach this function.  All suggestions are
    buy-only (calls, puts, or straddles — never short options).
    Strike is rounded to the nearest standard step so the user can act
    directly without looking up the chain.
    """
    symbol = signal.symbol
    lot = config.LOT_SIZES.get(symbol, 25)
    step = config.STRIKE_STEPS.get(symbol, 50)
    atm = int(round(snapshot.spot_price / step) * step)
    s_type = signal.type

    if s_type == "GAMMA_FLIP":
        new_regime = signal.data.get("new_regime", "")
        if new_regime == "NEGATIVE":
            # Amplified-move regime: go with spot direction confirmed by delta flow
            if snapshot.spot_price >= snapshot.gamma_flip and snapshot.net_delta_flow >= 0:
                return f"BUY {atm} CE | 1 lot ({lot} units) | Hold: intraday"
            elif snapshot.spot_price < snapshot.gamma_flip and snapshot.net_delta_flow <= 0:
                return f"BUY {atm} PE | 1 lot ({lot} units) | Hold: intraday"
            else:
                return f"BUY {atm} CE + {atm} PE (straddle) | 1 lot each | Hold: intraday"
        else:  # POSITIVE — mean-reversion regime, no buy setup
            return "NO TRADE — mean-reversion regime favors option sellers"

    if s_type == "GAMMA_SQUEEZE":
        if snapshot.net_delta_flow > 0:
            return f"BUY {atm} CE | 1 lot ({lot} units) | Hold: 15–45 min"
        elif snapshot.net_delta_flow < 0:
            return f"BUY {atm} PE | 1 lot ({lot} units) | Hold: 15–45 min"
        return f"BUY {atm} CE + {atm} PE (straddle) | 1 lot each | Hold: 15–45 min"

    if s_type == "MOMENTUM_EXTREME":
        direction = signal.data.get("direction", "")
        if direction == "BULLISH":
            return f"BUY {atm} CE | 1 lot ({lot} units) | Hold: intraday"
        return f"BUY {atm} PE | 1 lot ({lot} units) | Hold: intraday"

    return "—"
