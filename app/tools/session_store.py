from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


DEFAULT_STATE: Dict[str, Any] = {
    "name": "",
    "phone": "",
    "address": "",
    "area": "",
    "pending_items": [],
    "notes": "",
    "last_product_candidates": [],
    "awaiting_qty": False,
    "checkout_flow": "",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    channel_user_id TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get_state(self, channel_user_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT data_json FROM sessions WHERE channel_user_id = ?",
                (channel_user_id,),
            )
            row = cur.fetchone()
        if not row:
            return dict(DEFAULT_STATE)

        try:
            data = json.loads(row[0])
        except Exception:
            data = {}

        state = dict(DEFAULT_STATE)
        state.update(data)
        return state

    def save_state(self, channel_user_id: str, data: Dict[str, Any]) -> None:
        state = dict(DEFAULT_STATE)
        state.update(data)
        payload = json.dumps(state, ensure_ascii=False)
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(channel_user_id, data_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(channel_user_id)
                DO UPDATE SET data_json=excluded.data_json, updated_at=excluded.updated_at
                """,
                (channel_user_id, payload, now),
            )
            conn.commit()
