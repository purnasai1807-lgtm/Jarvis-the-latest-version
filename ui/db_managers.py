import sqlite3
import threading
from pathlib import Path
from datetime import datetime
from loguru import logger

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

class BrainDBManager:
    def __init__(self):
        self._db_path = _DATA_DIR / "brain_usage.db"
        self._lock = threading.Lock()
        self._init_db()
        
    def _conn(self):
        return sqlite3.connect(self._db_path, check_same_thread=False)

    def _init_db(self):
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_calls (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        model TEXT,
                        prompt_tokens INTEGER,
                        completion_tokens INTEGER,
                        cost_usd REAL,
                        latency_ms REAL,
                        tool_names TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS daily_summary (
                        date TEXT PRIMARY KEY,
                        total_cost REAL DEFAULT 0,
                        total_tokens INTEGER DEFAULT 0,
                        total_calls INTEGER DEFAULT 0
                    )
                """)
                conn.commit()

    def log_api_call(self, model: str, prompt_tokens: int, completion_tokens: int, cost_usd: float, latency_ms: float, tool_names: str=""):
        timestamp = datetime.now().isoformat()
        date_str = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    INSERT INTO api_calls (timestamp, model, prompt_tokens, completion_tokens, cost_usd, latency_ms, tool_names)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (timestamp, model, prompt_tokens, completion_tokens, cost_usd, latency_ms, tool_names))
                
                conn.execute("""
                    INSERT INTO daily_summary (date, total_cost, total_tokens, total_calls)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(date) DO UPDATE SET
                    total_cost = total_cost + excluded.total_cost,
                    total_tokens = total_tokens + excluded.total_tokens,
                    total_calls = total_calls + 1
                """, (date_str, cost_usd, prompt_tokens + completion_tokens))
                conn.commit()

    def get_stats_today(self):
        date_str = datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            row = conn.execute("SELECT total_cost, total_tokens, total_calls FROM daily_summary WHERE date = ?", (date_str,)).fetchone()
            if row:
                return {"total_cost": row[0], "total_tokens": row[1], "total_calls": row[2]}
            return {"total_cost": 0, "total_tokens": 0, "total_calls": 0}

    def get_avg_latency(self):
        date_str = datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            row = conn.execute("SELECT AVG(latency_ms) FROM api_calls WHERE timestamp LIKE ?", (f"{date_str}%",)).fetchone()
            if row and row[0]:
                return row[0] / 1000.0
            return 0.0

    def get_cost_over_time(self, days: int = 30):
        with self._conn() as conn:
            rows = conn.execute("SELECT date, total_cost FROM daily_summary ORDER BY date DESC LIMIT ?", (days,)).fetchall()
        return [{"date": r[0], "cost": r[1]} for r in reversed(rows)]
        
    def get_token_breakdown(self, days: int = 7):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT substr(timestamp, 1, 10) as dt, SUM(prompt_tokens), SUM(completion_tokens)
                FROM api_calls
                GROUP BY dt ORDER BY dt DESC LIMIT ?
            """, (days,)).fetchall()
        return [{"date": r[0], "prompt": r[1] or 0, "completion": r[2] or 0} for r in reversed(rows)]

    def get_tool_usage(self, limit: int = 10):
        # We store comma separated tool names. Let's just fetch recent ones and tally in python.
        with self._conn() as conn:
            rows = conn.execute("SELECT tool_names FROM api_calls WHERE tool_names != ''").fetchall()
            
        from collections import Counter
        tally = Counter()
        for r in rows:
            tools = [t.strip() for t in r[0].split(",") if t.strip()]
            tally.update(tools)
        return [{"tool": k, "count": v} for k, v in tally.most_common(limit)]


class VoiceLogManager:
    def __init__(self):
        self._db_path = _DATA_DIR / "voice_log.db"
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self._db_path, check_same_thread=False)

    def _init_db(self):
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS voice_interactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        direction TEXT,
                        text TEXT
                    )
                """)
                conn.commit()

    def log(self, direction: str, text: str):
        timestamp = datetime.now().isoformat()
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    INSERT INTO voice_interactions (timestamp, direction, text)
                    VALUES (?, ?, ?)
                """, (timestamp, direction, text))
                conn.commit()

    def get_today_logs(self):
        date_str = datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            rows = conn.execute("SELECT timestamp, direction, text FROM voice_interactions WHERE timestamp LIKE ? ORDER BY timestamp DESC LIMIT 50", (f"{date_str}%",)).fetchall()
            return [{"timestamp": r[0], "direction": r[1], "text": r[2]} for r in rows]

class MobileDeviceManager:
    """Phase 3 — registry of phone FCM tokens for push notifications."""

    def __init__(self):
        self._db_path = _DATA_DIR / "mobile_devices.db"
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self._db_path, check_same_thread=False)

    def _init_db(self):
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS devices (
                        token TEXT PRIMARY KEY,
                        platform TEXT,
                        label TEXT,
                        registered_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL
                    )
                """)
                conn.commit()

    def register(self, token: str, platform: str = "", label: str = "") -> None:
        now = datetime.now().isoformat()
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    INSERT INTO devices (token, platform, label, registered_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(token) DO UPDATE SET
                        platform = excluded.platform,
                        label = excluded.label,
                        last_seen_at = excluded.last_seen_at
                """, (token, platform, label, now, now))
                conn.commit()

    def unregister(self, token: str) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute("DELETE FROM devices WHERE token = ?", (token,))
                conn.commit()

    def list_active(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT token, platform, label, registered_at, last_seen_at FROM devices"
            ).fetchall()
        return [
            {"token": r[0], "platform": r[1], "label": r[2],
             "registered_at": r[3], "last_seen_at": r[4]}
            for r in rows
        ]


# Global DB singletons
brain_db = BrainDBManager()
voice_db = VoiceLogManager()
device_db = MobileDeviceManager()
