"""SQLite storage for GEX snapshots and signals."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import config
from gex_engine import GEXSnapshot

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS gex_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    spot_price REAL,
    total_gex REAL,
    gamma_flip REAL,
    put_wall REAL,
    call_wall REAL,
    max_gamma_strike REAL,
    pcr_gex REAL,
    net_delta_flow REAL,
    momentum_score INTEGER,
    regime TEXT
);
"""

_CREATE_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    priority TEXT NOT NULL,
    message TEXT,
    data_json TEXT
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_snap_sym_ts ON gex_snapshots (symbol, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_sig_sym_ts ON signals (symbol, timestamp);",
]


class GEXStore:
    """Thin wrapper around SQLite for GEX data persistence."""

    def __init__(self, db_path: str = "") -> None:
        self.db_path = db_path or config.DB_PATH
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()
        self._purge_old()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.open()
        return self._conn  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_tables(self) -> None:
        cur = self.conn.cursor()
        cur.execute(_CREATE_SNAPSHOTS)
        cur.execute(_CREATE_SIGNALS)
        for idx_sql in _CREATE_INDEXES:
            cur.execute(idx_sql)
        self.conn.commit()
        logger.info("SQLite tables initialized at %s", self.db_path)

    def _purge_old(self) -> None:
        cutoff = (datetime.now(IST) - timedelta(days=config.PURGE_DAYS)).isoformat()
        cur = self.conn.cursor()
        cur.execute("DELETE FROM gex_snapshots WHERE timestamp < ?", (cutoff,))
        cur.execute("DELETE FROM signals WHERE timestamp < ?", (cutoff,))
        deleted = cur.rowcount
        self.conn.commit()
        if deleted:
            logger.info("Purged %d old records (older than %d days)", deleted, config.PURGE_DAYS)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def save_snapshot(self, snap: GEXSnapshot, momentum_score: int = 0) -> None:
        self.conn.execute(
            """INSERT INTO gex_snapshots
               (timestamp, symbol, spot_price, total_gex, gamma_flip,
                put_wall, call_wall, max_gamma_strike, pcr_gex,
                net_delta_flow, momentum_score, regime)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snap.timestamp,
                snap.symbol,
                snap.spot_price,
                snap.total_gex,
                snap.gamma_flip,
                snap.put_wall,
                snap.call_wall,
                snap.max_gamma_strike,
                snap.pcr_gex,
                snap.net_delta_flow,
                momentum_score,
                snap.regime,
            ),
        )
        self.conn.commit()

    def get_previous_snapshot(self, symbol: str) -> GEXSnapshot | None:
        """Return the most recent snapshot for *symbol* before the current one."""
        row = self.conn.execute(
            """SELECT * FROM gex_snapshots
               WHERE symbol = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (symbol,),
        ).fetchone()
        if not row:
            return None
        return GEXSnapshot(
            symbol=row["symbol"],
            spot_price=row["spot_price"],
            total_gex=row["total_gex"],
            gamma_flip=row["gamma_flip"],
            put_wall=row["put_wall"],
            call_wall=row["call_wall"],
            max_gamma_strike=row["max_gamma_strike"],
            pcr_gex=row["pcr_gex"],
            net_delta_flow=row["net_delta_flow"],
            regime=row["regime"],
            timestamp=row["timestamp"],
        )

    def get_recent_snapshots(self, symbol: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM gex_snapshots
               WHERE symbol = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_spot_history(self, symbol: str, limit: int = 20) -> list[float]:
        """Return last N spot prices (most recent first)."""
        rows = self.conn.execute(
            """SELECT spot_price FROM gex_snapshots
               WHERE symbol = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (symbol, limit),
        ).fetchall()
        return [r["spot_price"] for r in rows]

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def save_signal(
        self,
        symbol: str,
        signal_type: str,
        priority: str,
        message: str,
        data: dict,
    ) -> None:
        self.conn.execute(
            """INSERT INTO signals (timestamp, symbol, signal_type, priority, message, data_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(IST).isoformat(),
                symbol,
                signal_type,
                priority,
                message,
                json.dumps(data),
            ),
        )
        self.conn.commit()

    def get_recent_signals(self, symbol: str, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM signals
               WHERE symbol = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_regime_changes(self, symbol: str, limit: int = 5) -> list[dict]:
        """Return last N GAMMA_FLIP signals (regime changes)."""
        rows = self.conn.execute(
            """SELECT * FROM signals
               WHERE symbol = ? AND signal_type = 'GAMMA_FLIP'
               ORDER BY timestamp DESC LIMIT ?""",
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_today_signal_count(self) -> int:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM signals WHERE timestamp LIKE ?",
            (f"{today}%",),
        ).fetchone()
        return row["cnt"] if row else 0
