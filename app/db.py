"""Local history in SQLite (data/history.db)."""
import json
import os
import sqlite3
from pathlib import Path


def _connect():
    path = Path(os.getenv("RESUME_DB", Path(__file__).resolve().parent.parent / "data" / "history.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            jd_hash TEXT NOT NULL,
            job_title TEXT,
            company TEXT,
            resume_name TEXT,
            total INTEGER NOT NULL,
            jd_json TEXT NOT NULL,
            result_json TEXT NOT NULL
        )"""
    )
    return conn


def save(created_at, jd_hash, job, resume_name, total, result) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO analyses (created_at, jd_hash, job_title, company, resume_name, total, jd_json, result_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (created_at, jd_hash, job["job_title"], job["company"], resume_name, total,
             json.dumps(job), json.dumps(result)),
        )
        return cur.lastrowid


def latest_for_jd(jd_hash):
    """Most recent earlier analysis of the same job description, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE jd_hash=? ORDER BY id DESC LIMIT 1", (jd_hash,)
        ).fetchone()
    return row


def get(analysis_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    if not row:
        return None
    result = json.loads(row["result_json"])
    result["id"] = row["id"]
    return result


def list_all():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, jd_hash, job_title, company, resume_name, total"
            " FROM analyses ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete(analysis_id) -> bool:
    with _connect() as conn:
        return conn.execute("DELETE FROM analyses WHERE id=?", (analysis_id,)).rowcount > 0
