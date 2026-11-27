"""Long-term heating data in SQLite (/data/heating.db), outside HA's 10-day recorder.

``samples`` holds one row per value change, plus a heartbeat every ``HEARTBEAT_S`` so a flat line
is still visible: room temperatures, the outdoor temperature, each boiler circuit (open,
heat_request, target) and each room valve. Rows older than ``RAW_DAYS`` are averaged into
``samples_15m``. ``sessions`` holds one row per heating or cooling run of a circuit, per room
(see sessions.py); those are kept for good. Writes are batched and run in a worker thread.
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

HEARTBEAT_S = 600
RAW_DAYS = 120
BUCKET_S = 900

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (ts INTEGER NOT NULL, key TEXT NOT NULL, value REAL);
CREATE INDEX IF NOT EXISTS samples_key_ts ON samples (key, ts);
CREATE TABLE IF NOT EXISTS samples_15m (ts INTEGER NOT NULL, key TEXT NOT NULL, value REAL, PRIMARY KEY (key, ts));
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- heat | cool
    boiler TEXT,
    circuit TEXT NOT NULL,
    room TEXT,
    start INTEGER NOT NULL,
    end INTEGER NOT NULL,
    end_reason TEXT,
    t_start REAL,
    t_end REAL,
    target REAL,
    outdoor REAL,
    n_open_max INTEGER,
    n_open_avg REAL,
    dead_time_min REAL,
    rate_c_per_h REAL,
    reached_min REAL,
    tau_h REAL,
    note TEXT
);
CREATE INDEX IF NOT EXISTS sessions_start ON sessions (start);
CREATE TABLE IF NOT EXISTS estimates (
    circuit TEXT NOT NULL,
    event_start INTEGER NOT NULL,
    room TEXT,
    event_end INTEGER,
    event_summary TEXT,
    target REAL,
    est_start INTEGER,
    lead_min REAL,
    fixed_lead_min REAL,
    computed_at INTEGER,
    confidence TEXT,
    runs INTEGER,
    n_open INTEGER,
    rate REAL,
    dead_min REAL,
    t_now REAL,
    t_at_start REAL,
    outdoor REAL,
    opened_at INTEGER,       -- filled after the event: when the circuit really opened
    t_at_event REAL,         -- room temperature when the event started
    reached_at INTEGER,      -- when the room reached the target
    evaluated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (circuit, event_start)
);
"""
ESTIMATE_COLUMNS = (
    "circuit", "event_start", "room", "event_end", "event_summary", "target", "est_start", "lead_min", "fixed_lead_min",
    "computed_at", "confidence", "runs", "n_open", "rate", "dead_min", "t_now", "t_at_start", "outdoor",
)
EVALUATION_COLUMNS = ("opened_at", "t_at_event", "reached_at", "evaluated")
OPEN_LOOKBACK_S = 12 * 3600
SESSION_COLUMNS = (
    "kind", "boiler", "circuit", "room", "start", "end", "end_reason", "t_start", "t_end", "target", "outdoor",
    "n_open_max", "n_open_avg", "dead_time_min", "rate_c_per_h", "reached_min", "tau_h", "note",
)


class DataLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._pending: list[tuple[int, str, float | None]] = []
        self._last: dict[str, tuple[int, float | None]] = {}
        for key, ts, value in self._db.execute(
            "SELECT key, MAX(ts), value FROM samples GROUP BY key"
        ):
            self._last[key] = (ts, value)

    # ------------------------------------------------------------------ samples
    def record(self, key: str, value: float | None, ts: float | None = None) -> bool:
        """Queue a value if it changed, or if the last one is older than the heartbeat."""
        ts = int(ts if ts is not None else time.time())
        last = self._last.get(key)
        if last and last[1] == value and ts - last[0] < HEARTBEAT_S:
            return False
        self._last[key] = (ts, value)
        self._pending.append((ts, key, value))
        return True

    def last(self, key: str) -> float | None:
        entry = self._last.get(key)
        return entry[1] if entry else None

    def flush_sync(self) -> int:
        rows, self._pending = self._pending, []
        if rows:
            with self._lock:
                self._db.executemany("INSERT INTO samples (ts, key, value) VALUES (?, ?, ?)", rows)
        return len(rows)

    async def flush(self) -> int:
        return await asyncio.to_thread(self.flush_sync)

    def series(self, key: str, start: float, end: float) -> list[tuple[int, float]]:
        """Values of ``key`` in [start, end], led by the last value before ``start`` (step-hold)."""
        self.flush_sync()
        with self._lock:
            before = self._db.execute(
                "SELECT ts, value FROM samples WHERE key = ? AND ts < ? ORDER BY ts DESC LIMIT 1", (key, int(start))
            ).fetchall()
            rows = self._db.execute(
                "SELECT ts, value FROM samples WHERE key = ? AND ts BETWEEN ? AND ? ORDER BY ts", (key, int(start), int(end))
            ).fetchall()
            if not before and not rows:
                rows = self._db.execute(
                    "SELECT ts, value FROM samples_15m WHERE key = ? AND ts BETWEEN ? AND ? ORDER BY ts",
                    (key, int(start), int(end)),
                ).fetchall()
        return [(int(t), v) for t, v in before + rows if v is not None]

    def keys(self) -> list[str]:
        self.flush_sync()
        with self._lock:
            return [k for (k,) in self._db.execute("SELECT DISTINCT key FROM samples ORDER BY key")]

    def prune(self, now: float | None = None) -> int:
        """Average raw rows older than RAW_DAYS into 15-minute buckets, then delete them."""
        cutoff = int((now or time.time()) - RAW_DAYS * 86400)
        with self._lock:
            self._db.execute("BEGIN")
            self._db.execute(
                f"""INSERT OR REPLACE INTO samples_15m (ts, key, value)
                    SELECT (ts / {BUCKET_S}) * {BUCKET_S}, key, AVG(value) FROM samples
                    WHERE ts < ? AND value IS NOT NULL GROUP BY key, ts / {BUCKET_S}""",
                (cutoff,),
            )
            n = self._db.execute("DELETE FROM samples WHERE ts < ?", (cutoff,)).rowcount
            self._db.execute("COMMIT")
        return n

    # ----------------------------------------------------------------- sessions
    def add_session(self, row: dict) -> int:
        cols = [c for c in SESSION_COLUMNS if c in row]
        with self._lock:
            cur = self._db.execute(
                f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                [row[c] for c in cols],
            )
            return int(cur.lastrowid)

    def sessions(self, limit: int = 200, circuit: str | None = None, room: str | None = None, kind: str | None = None) -> list[dict]:
        where, args = [], []
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if circuit:
            where.append("circuit = ?")
            args.append(circuit)
        if room:
            where.append("room = ?")
            args.append(room)
        sql = "SELECT id, " + ", ".join(SESSION_COLUMNS) + " FROM sessions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY start DESC, id DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [dict(zip(("id",) + SESSION_COLUMNS, r)) for r in rows]

    def set_note(self, session_id: int, note: str | None) -> bool:
        with self._lock:
            return self._db.execute("UPDATE sessions SET note = ? WHERE id = ?", (note or None, int(session_id))).rowcount > 0

    # ---------------------------------------------------------------- estimates
    def save_estimate(self, row: dict) -> None:
        """Keep the latest estimate for an event until its estimated start; after that it stays frozen."""
        cols = list(ESTIMATE_COLUMNS)
        update = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in ("circuit", "event_start"))
        with self._lock:
            self._db.execute(
                f"""INSERT INTO estimates ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})
                    ON CONFLICT (circuit, event_start) DO UPDATE SET {update}
                    WHERE estimates.evaluated = 0 AND estimates.est_start > excluded.computed_at""",
                [row.get(c) for c in cols],
            )

    def estimates(self, limit: int = 100) -> list[dict]:
        cols = ESTIMATE_COLUMNS + EVALUATION_COLUMNS
        with self._lock:
            rows = self._db.execute(
                f"SELECT {', '.join(cols)} FROM estimates ORDER BY event_start DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def evaluate_estimates(self, now: float | None = None) -> int:
        """After an event ends, note when its circuit really opened and when the room got warm."""
        now = int(now or time.time())
        with self._lock:
            due = self._db.execute(
                "SELECT circuit, event_start, event_end, room, target FROM estimates WHERE evaluated = 0 AND event_end <= ?",
                (now,),
            ).fetchall()
        for circuit, start, end, room, target in due:
            temps = self.series(f"room:{room}:temp", start - OPEN_LOOKBACK_S, end) if room else []
            on = self.series(f"circuit:{circuit}:on", start - OPEN_LOOKBACK_S, start)
            t_at = next((v for t, v in reversed(temps) if t <= start), None)
            opened = None
            for (_, a), (t, b) in zip(on, on[1:]):
                if a == 0 and b == 1:
                    opened = t
            crossings = [t for (_, a), (t, b) in zip(temps, temps[1:]) if target is not None and a < target <= b]
            if t_at is not None and target is not None and t_at >= target:
                reached = max((t for t in crossings if t <= start), default=temps[0][0] if temps else None)
            else:
                reached = min((t for t in crossings if t > start), default=None)
            with self._lock:
                self._db.execute(
                    "UPDATE estimates SET opened_at = ?, t_at_event = ?, reached_at = ?, evaluated = 1 WHERE circuit = ? AND event_start = ?",
                    (opened, t_at, reached, circuit, start),
                )
        return len(due)

    def close(self) -> None:
        self.flush_sync()
        with self._lock:
            self._db.close()
