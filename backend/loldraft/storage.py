from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import cutoff_ts, now_ts


class Store:
    """Only whitelisted match facts persist. No PUUIDs, player names, keys, or raw responses."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "matches.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS matches (
                    match_id TEXT PRIMARY KEY, started_at INTEGER NOT NULL,
                    patch TEXT NOT NULL, region TEXT NOT NULL, queue INTEGER NOT NULL,
                    blue_win INTEGER NOT NULL, payload TEXT NOT NULL, inserted_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS matches_window ON matches(region, queue, started_at);
                CREATE TABLE IF NOT EXISTS downloads (
                    match_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def insert(self, match: dict) -> bool:
        with self.connect() as db:
            cursor = db.execute("INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?,?,?)", (
                match["match_id"], match["started_at"], match["patch"], match["region"], match["queue"],
                int(match["blue_win"]), json.dumps(match, separators=(",", ":")), now_ts(),
            ))
            return cursor.rowcount == 1

    def recent(self, region=None, queue=None, patches=None, limit=None):
        query = "SELECT payload FROM matches WHERE started_at>=? AND started_at<=?"
        args = [cutoff_ts(), now_ts()]
        if region:
            query += " AND region=?"
            args.append(region)
        if queue:
            query += " AND queue=?"
            args.append(queue)
        if patches:
            query += " AND patch IN (" + ",".join("?" for _ in patches) + ")"
            args.extend(patches)
        query += " ORDER BY started_at, match_id"
        if limit:
            query += " LIMIT ?"
            args.append(limit)
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(query, args)]

    def stats(self, region=None, queue=None, patches=None):
        clause = "started_at>=? AND started_at<=?"
        args = [cutoff_ts(), now_ts()]
        if region:
            clause += " AND region=?"
            args.append(region)
        if queue:
            clause += " AND queue=?"
            args.append(queue)
        if patches:
            clause += " AND patch IN (" + ",".join("?" for _ in patches) + ")"
            args.extend(patches)
        with self.connect() as db:
            stored = db.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
            pending = db.execute("SELECT COUNT(*) FROM downloads WHERE status='pending'").fetchone()[0]
            count, oldest, newest = db.execute(
                "SELECT COUNT(*),MIN(started_at),MAX(started_at) FROM matches WHERE " + clause, args
            ).fetchone()
            patch_counts = dict(db.execute("SELECT patch,COUNT(*) FROM matches WHERE " + clause + " GROUP BY patch", args))
        return {
            "matches": count, "stored_total": stored,
            "outside_filter_or_expired": stored - count,
            "patches": patch_counts,
            "oldest": oldest, "newest": newest,
            "last_refresh": self.get_meta("last_refresh"), "pending_downloads": pending,
            "window_days": 30, "cutoff": cutoff_ts(),
        }

    def set_meta(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def get_meta(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def enqueue(self, ids):
        with self.connect() as db:
            db.executemany("INSERT OR IGNORE INTO downloads(match_id) VALUES (?)", ((i,) for i in ids))

    def pending(self, region, limit=100):
        with self.connect() as db:
            return [r[0] for r in db.execute(
                "SELECT match_id FROM downloads WHERE status='pending' AND match_id LIKE ? LIMIT ?",
                (region + "_%", limit),
            )]

    def downloaded(self, match_id, status="done", reason=""):
        with self.connect() as db:
            db.execute("UPDATE downloads SET status=?,reason=? WHERE match_id=?", (status, reason, match_id))
