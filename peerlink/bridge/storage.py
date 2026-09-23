"""Local-only deduplication and backend thread mapping."""

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class BridgeState:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
                    sender TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS thread_map (
                    thread_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    sender TEXT NOT NULL, backend_thread_id TEXT NOT NULL,
                    PRIMARY KEY(thread_id,agent_id,sender)
                );
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def reserve(self, message_id, agent_id, sender):
        with self.connect() as conn:
            result = conn.execute(
                "INSERT OR IGNORE INTO processed_messages VALUES (?,?,?,?,?)",
                (message_id, agent_id, sender, "RUNNING", time.time()),
            )
            return result.rowcount == 1

    def finish(self, message_id, status):
        with self.connect() as conn:
            conn.execute("UPDATE processed_messages SET status=? WHERE message_id=?", (status, message_id))

    def thread(self, thread_id, agent_id, sender):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT backend_thread_id FROM thread_map WHERE thread_id=? AND agent_id=? AND sender=?",
                (thread_id, agent_id, sender),
            ).fetchone()
            return row[0] if row else None

    def map_thread(self, thread_id, agent_id, sender, backend_thread_id):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO thread_map VALUES (?,?,?,?)",
                (thread_id, agent_id, sender, backend_thread_id),
            )
