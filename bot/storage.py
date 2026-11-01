"""SQLite document storage."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .forest import Audience

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    text TEXT NOT NULL,
    audience TEXT NOT NULL,
    source TEXT NOT NULL,            -- archive | user
    uploader_id INTEGER,
    uploader_name TEXT,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,            -- active | pending | replaced | deleted
    replaced_by INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
"""


@dataclass
class Document:
    id: int
    title: str
    filename: str
    text: str
    audience: Audience
    source: str
    uploader_id: int | None
    uploader_name: str | None
    sha256: str
    status: str
    replaced_by: int | None
    created_at: str

    @property
    def from_user(self) -> bool:
        return self.source == "user"


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def _doc(self, row: sqlite3.Row) -> Document:
        data = dict(row)
        data["audience"] = Audience.from_json(data["audience"])
        return Document(**data)

    def add(
        self,
        *,
        title: str,
        filename: str,
        text: str,
        audience: Audience,
        source: str,
        sha256: str,
        status: str,
        uploader_id: int | None = None,
        uploader_name: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO documents (title, filename, text, audience, source, uploader_id, uploader_name,"
            " sha256, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title, filename, text, audience.to_json(), source, uploader_id, uploader_name,
                sha256, status, datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get(self, doc_id: int) -> Document | None:
        row = self.conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return self._doc(row) if row else None

    def active(self) -> list[Document]:
        rows = self.conn.execute("SELECT * FROM documents WHERE status = 'active' ORDER BY id").fetchall()
        return [self._doc(r) for r in rows]

    def by_uploader(self, user_id: int) -> list[Document]:
        rows = self.conn.execute(
            "SELECT * FROM documents WHERE uploader_id = ? AND status IN ('active', 'pending') ORDER BY id",
            (user_id,),
        ).fetchall()
        return [self._doc(r) for r in rows]

    def find_by_sha(self, sha256: str, statuses: tuple[str, ...]) -> Document | None:
        marks = ",".join("?" * len(statuses))
        row = self.conn.execute(
            f"SELECT * FROM documents WHERE sha256 = ? AND status IN ({marks}) LIMIT 1", (sha256, *statuses)
        ).fetchone()
        return self._doc(row) if row else None

    def known_sha(self, sha256: str) -> bool:
        return self.conn.execute("SELECT 1 FROM documents WHERE sha256 = ?", (sha256,)).fetchone() is not None

    def set_audience(self, doc_id: int, audience: Audience) -> None:
        self.conn.execute("UPDATE documents SET audience = ? WHERE id = ?", (audience.to_json(), doc_id))
        self.conn.commit()

    def set_status(self, doc_id: int, status: str, replaced_by: int | None = None) -> None:
        self.conn.execute(
            "UPDATE documents SET status = ?, replaced_by = ? WHERE id = ?", (status, replaced_by, doc_id)
        )
        self.conn.commit()

    def delete(self, doc_id: int) -> Document | None:
        """Deletes a document and brings back the version it replaced, if any; returns that version."""
        row = self.conn.execute(
            "SELECT * FROM documents WHERE replaced_by = ? AND status = 'replaced'", (doc_id,)
        ).fetchone()
        self.set_status(doc_id, "deleted")
        if not row:
            return None
        self.set_status(row["id"], "active")
        return self.get(row["id"])
