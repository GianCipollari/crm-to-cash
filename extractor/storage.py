"""Raw storage: one table per source object, plus a table of cursors.

Each raw table keeps the latest version of every record:
    id          source id (primary key)
    updated_at  last modification time reported by the source (ISO 8601)
    payload     the record exactly as the API returned it (JSON text)
    _loaded_at  when this pipeline wrote it (ISO 8601, UTC)

History of changes is not kept here; dbt snapshots will take care of it.

The SQL is plain enough to run on DuckDB (production) and SQLite (tests).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RawStore:
    def __init__(self, conn):
        self.conn = conn  # any DB-API connection: duckdb.connect(...) or sqlite3.connect(...)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS _extract_state ("
            "stream VARCHAR PRIMARY KEY, cursor_value VARCHAR, updated_at VARCHAR)"
        )

    def _ensure_table(self, table: str) -> None:
        self.conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            "id VARCHAR PRIMARY KEY, updated_at VARCHAR, payload VARCHAR, _loaded_at VARCHAR)"
        )

    def upsert(self, table: str, records: list[dict]) -> dict[str, int]:
        """records = [{"id", "updated_at", "payload"}]. Returns inserted/updated/unchanged counts.

        A record whose updated_at matches the stored one is skipped, so loading the
        same data twice writes nothing (idempotent).
        """
        self._ensure_table(table)
        latest: dict[str, dict] = {}
        for r in records:  # if the same id arrives twice, keep the newest version
            if r["id"] not in latest or r["updated_at"] > latest[r["id"]]["updated_at"]:
                latest[r["id"]] = r
        stored = dict(self.conn.execute(f"SELECT id, updated_at FROM {table}").fetchall())

        counts = {"inserted": 0, "updated": 0, "unchanged": 0}
        rows = []
        loaded_at = utc_now()
        for rid, r in latest.items():
            if rid not in stored:
                counts["inserted"] += 1
            elif r["updated_at"] > (stored[rid] or ""):
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
                continue
            rows.append((rid, r["updated_at"], json.dumps(r["payload"], ensure_ascii=False), loaded_at))
        if rows:
            self.conn.executemany(
                f"INSERT INTO {table} (id, updated_at, payload, _loaded_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET updated_at = excluded.updated_at, "
                "payload = excluded.payload, _loaded_at = excluded._loaded_at",
                rows,
            )
        self._commit()
        return counts

    def _commit(self) -> None:
        try:
            self.conn.commit()
        except Exception as err:  # DuckDB autocommits and complains when nothing is open
            if "no transaction" not in str(err).lower():
                raise

    def count(self, table: str) -> int:
        self._ensure_table(table)
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def get_cursor(self, stream: str) -> str | None:
        row = self.conn.execute(
            "SELECT cursor_value FROM _extract_state WHERE stream = ?", [stream]).fetchone()
        return row[0] if row else None

    def set_cursor(self, stream: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO _extract_state (stream, cursor_value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (stream) DO UPDATE SET cursor_value = excluded.cursor_value, "
            "updated_at = excluded.updated_at",
            [stream, value, utc_now()],
        )
        self._commit()
