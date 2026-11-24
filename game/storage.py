"""Хранилище: SQLite, один файл. Забег лежит как JSON — схема не нужна."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from . import engine


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    user_id INTEGER PRIMARY KEY,
                    state   TEXT NOT NULL,
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scores (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name    TEXT NOT NULL,
                    floor   INTEGER NOT NULL,
                    kills   INTEGER NOT NULL,
                    gold    INTEGER NOT NULL,
                    points  INTEGER NOT NULL,
                    daily   INTEGER NOT NULL DEFAULT 0,
                    day     TEXT,
                    won     INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scores_points ON scores(daily, day, points DESC);
                CREATE TABLE IF NOT EXISTS users (
                    user_id  INTEGER PRIMARY KEY,
                    name     TEXT,
                    runs     INTEGER NOT NULL DEFAULT 0,
                    best     INTEGER NOT NULL DEFAULT 0
                );
            """)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    # --- забеги ---------------------------------------------------------
    def load_run(self, user_id: int) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT state FROM runs WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        try:
            return engine.migrate(json.loads(row["state"]))
        except json.JSONDecodeError:
            return None

    def save_run(self, user_id: int, state: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO runs(user_id, state, updated) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET state=excluded.state, updated=excluded.updated",
                (user_id, json.dumps(state, ensure_ascii=False), time.time()),
            )

    def clear_run(self, user_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM runs WHERE user_id=?", (user_id,))

    # --- пользователи и очки --------------------------------------------
    def touch_user(self, user_id: int, name: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR IGNORE INTO users(user_id, name) VALUES(?,?)", (user_id, name))
            c.execute("UPDATE users SET name=? WHERE user_id=?", (name, user_id))

    def add_score(self, user_id: int, name: str, state: dict) -> dict:
        sc = engine.score(state)
        day = state.get("day") or engine.today_key()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO scores(user_id, name, floor, kills, gold, points, daily, day, won, created)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (user_id, name, sc["floor"], sc["kills"], sc["gold"], sc["points"],
                 int(bool(state.get("daily"))), day, int(sc["won"]), time.time()),
            )
            c.execute(
                "INSERT INTO users(user_id, name, runs, best) VALUES(?,?,1,?) "
                "ON CONFLICT(user_id) DO UPDATE SET runs=runs+1, best=MAX(best, excluded.best), name=excluded.name",
                (user_id, name, sc["floor"]),
            )
        return sc

    def top(self, daily: bool = False, day: str | None = None, limit: int = 10) -> list[dict]:
        with self._lock, self._conn() as c:
            if daily:
                rows = c.execute(
                    "SELECT name, floor, kills, gold, points, won FROM scores"
                    " WHERE daily=1 AND day=? ORDER BY points DESC, created ASC LIMIT ?",
                    (day or engine.today_key(), limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT name, MAX(points) AS points, floor, kills, gold, won FROM scores"
                    " GROUP BY user_id ORDER BY points DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def stats(self, user_id: int) -> dict:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT runs, best FROM users WHERE user_id=?", (user_id,)).fetchone()
            best = c.execute(
                "SELECT MAX(points) AS p FROM scores WHERE user_id=?", (user_id,)
            ).fetchone()
        return {"runs": row["runs"] if row else 0,
                "best_floor": row["best"] if row else 0,
                "best_points": (best["p"] or 0) if best else 0}
