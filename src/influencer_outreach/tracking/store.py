"""SQLite-backed outreach tracker (idempotent, scalable)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from influencer_outreach.models import OutreachLogEntry, SendStatus


def _parse_date(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


class OutreachStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outreach_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    influencer_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    message_generated INTEGER NOT NULL,
                    sent INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    date TEXT NOT NULL,
                    detail TEXT,
                    dedupe_key TEXT UNIQUE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_outreach_influencer
                ON outreach_log(influencer_id)
                """
            )

    def already_sent(self, dedupe_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM outreach_log
                WHERE dedupe_key = ?
                  AND status IN ('sent', 'simulated')
                LIMIT 1
                """,
                (dedupe_key,),
            ).fetchone()
            return row is not None

    def record(self, entry: OutreachLogEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO outreach_log (
                    influencer_id, name, email, message_generated, sent,
                    status, channel, date, detail, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.influencer_id,
                    entry.name,
                    entry.email,
                    int(entry.message_generated),
                    int(entry.sent),
                    entry.status.value,
                    entry.channel,
                    entry.date.isoformat(),
                    entry.detail,
                    entry.dedupe_key,
                ),
            )

    def list_entries(self) -> list[OutreachLogEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM outreach_log ORDER BY id ASC"
            ).fetchall()
        out: list[OutreachLogEntry] = []
        for row in rows:
            out.append(
                OutreachLogEntry(
                    influencer_id=row["influencer_id"],
                    name=row["name"],
                    email=row["email"],
                    message_generated=bool(row["message_generated"]),
                    sent=bool(row["sent"]),
                    status=SendStatus(row["status"]),
                    channel=row["channel"],
                    date=_parse_date(row["date"]),
                    detail=row["detail"] or "",
                    dedupe_key=row["dedupe_key"] or "",
                )
            )
        return out

    def export_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [e.model_dump(mode="json") for e in self.list_entries()]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
