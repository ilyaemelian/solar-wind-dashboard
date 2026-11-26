"""SQLite log for forecasts and the exact source responses used to produce them."""

import hashlib
import json
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / ".ml-output" / "hybrid.sqlite3"


def save_run(path, forecast, captures, *, unique_target=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        if not unique_target:
            db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS payloads (sha256 TEXT PRIMARY KEY, json_zlib BLOB NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS forecasts (
            id INTEGER PRIMARY KEY, issued_at TEXT NOT NULL, target_start TEXT NOT NULL,
            result TEXT NOT NULL
        )""")
        if unique_target:
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS forecast_by_target ON forecasts(target_start)")
        sources = {}
        for name, capture in captures.items():
            sources[name] = dict(capture["metadata"])
            if capture["data"] is not None:
                blob = json.dumps(capture["data"], separators=(",", ":"), allow_nan=False).encode()
                digest = hashlib.sha256(blob).hexdigest()
                sources[name]["sha256"] = digest
                db.execute("INSERT OR IGNORE INTO payloads VALUES (?, ?)", (digest, zlib.compress(blob)))
        record = {**forecast, "sources": sources}
        statement = "INSERT INTO forecasts (issued_at, target_start, result) VALUES (?, ?, ?)"
        if unique_target:
            statement += " ON CONFLICT(target_start) DO NOTHING"
        inserted = db.execute(
            statement,
            (record["issued_at"], record["target_start"], json.dumps(record, allow_nan=False)),
        )
        if unique_target and inserted.rowcount == 0:
            previous = db.execute("SELECT result FROM forecasts WHERE target_start = ?", (record["target_start"],)).fetchone()
            return json.loads(previous[0])
        return record


def read_runs(path=DEFAULT_DB, *, latest_only=False):
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        query = "SELECT result FROM forecasts ORDER BY issued_at DESC, id DESC"
        if latest_only:
            query += " LIMIT 1"
        return [json.loads(row[0]) for row in db.execute(query)]
