"""SQLite command journal and durable event outbox."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any


class Journal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS commands (
                command_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                state TEXT NOT NULL,
                payload TEXT NOT NULL,
                error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS event_outbox (
                event_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                sent_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    def command_state(self, command_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT state FROM commands WHERE command_id = ?", (command_id,)
        ).fetchone()
        return None if row is None else str(row["state"])

    def order_id_for_command(self, command_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT order_id FROM commands WHERE command_id = ?", (command_id,)
        ).fetchone()
        return None if row is None else str(row["order_id"])

    def record_command(self, command_id: str, order_id: str, payload: dict[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO commands(command_id, order_id, state, payload)
                   VALUES (?, ?, 'SUBMITTING', ?)
                   ON CONFLICT(command_id) DO NOTHING""",
                (command_id, order_id, json.dumps(payload, sort_keys=True)),
            )

    def set_command_state(self, command_id: str, state: str, error: str | None = None) -> None:
        with self.connection:
            self.connection.execute(
                """UPDATE commands SET state = ?, error = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE command_id = ?""",
                (state, error, command_id),
            )

    def enqueue_event(self, event: dict[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO event_outbox(event_id, payload) VALUES (?, ?)",
                (event["event_id"], json.dumps(event, separators=(",", ":"), default=str)),
            )

    def pending_events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT payload FROM event_outbox WHERE sent_at IS NULL ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def mark_event_sent(self, event_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE event_outbox SET sent_at = CURRENT_TIMESTAMP WHERE event_id = ?",
                (event_id,),
            )

    def close(self) -> None:
        self.connection.close()
