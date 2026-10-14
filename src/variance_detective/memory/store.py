"""Investigation memory.

A tiny SQLite store (stdlib only — no server to run) that remembers what was found for each
KPI × node × period. This is what lets the agent say *"this is the third month the same
store/category pair explains the shortfall — the explanation given last time was 'one-off
markdown'; it is no longer one-off."*

Swap for Postgres by re-implementing the four public methods; nothing else depends on SQLite.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  kpi TEXT NOT NULL,
  period TEXT NOT NULL,
  actual_version TEXT NOT NULL,
  compare_version TEXT NOT NULL,
  source TEXT NOT NULL,
  variance REAL NOT NULL,
  headline TEXT,
  summary TEXT
);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  kpi TEXT NOT NULL,
  period TEXT NOT NULL,
  node_key TEXT NOT NULL,
  label TEXT NOT NULL,
  depth INTEGER NOT NULL,
  variance REAL NOT NULL,
  share_of_root REAL,
  explanation TEXT,
  tags TEXT
);
CREATE INDEX IF NOT EXISTS ix_findings_node ON findings(kpi, node_key, period);
"""


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open()

    def _open(self) -> sqlite3.Connection:
        """Open the database and create the schema. Filesystems without file locking (synced folders,
        some network/virtual mounts) make SQLite's default journal fail with 'disk I/O error'; on that
        error we reopen with an in-memory journal, which works everywhere at the cost of crash-safety."""
        last: Exception | None = None
        for pragmas in ((), ("PRAGMA journal_mode=MEMORY",)):
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            try:
                for pragma in pragmas:
                    conn.execute(pragma)
                conn.executescript(_SCHEMA)
                return conn
            except sqlite3.OperationalError as e:
                last = e
                conn.close()
                self._clear_stale_journal()
        raise sqlite3.OperationalError(f"Cannot open memory database at {self.path}: {last}")

    def _clear_stale_journal(self) -> None:
        """A failed first write can leave a hot '-journal' file that blocks every later open on
        lock-less filesystems. Remove it (or move it aside if removal is not permitted)."""
        journal = self.path.with_name(self.path.name + "-journal")
        if journal.exists():
            try:
                journal.unlink()
            except OSError:
                journal.rename(journal.with_name(journal.name + f".stale-{int(time.time())}"))

    # ---- write -----------------------------------------------------------------------
    def remember(self, *, investigation_id: str, kpi: str, period: str, actual_version: str, compare_version: str, source: str, variance: float, headline: str, summary: str, findings: list[dict[str, Any]]) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._conn:
            self._conn.execute("DELETE FROM investigations WHERE id = ?", (investigation_id,))
            self._conn.execute(
                "INSERT INTO investigations VALUES (?,?,?,?,?,?,?,?,?,?)",
                (investigation_id, now, kpi, period, actual_version, compare_version, source, variance, headline, summary),
            )
            self._conn.executemany(
                "INSERT INTO findings (investigation_id, created_at, kpi, period, node_key, label, depth, variance, share_of_root, explanation, tags) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (investigation_id, now, kpi, period, f["node_key"], f["label"], f["depth"], f["variance"], f.get("share_of_root"), f.get("explanation"), json.dumps(f.get("tags", [])))
                    for f in findings
                ],
            )

    # ---- read ------------------------------------------------------------------------
    def recall(self, *, kpi: str, node_key: str, exclude_period: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT f.period, f.variance, f.share_of_root, f.explanation, f.created_at, i.actual_version, i.compare_version "
            "FROM findings f JOIN investigations i ON i.id = f.investigation_id "
            "WHERE f.kpi = ? AND f.node_key = ? AND (? IS NULL OR f.period != ?) ORDER BY f.period DESC LIMIT ?",
            (kpi, node_key, exclude_period, exclude_period, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_investigations(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM investigations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def clear(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM findings")
            self._conn.execute("DELETE FROM investigations")

    def close(self) -> None:
        self._conn.close()
