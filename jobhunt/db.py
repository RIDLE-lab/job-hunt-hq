"""SQLite storage: jobs found, applications made, and email events."""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_text TEXT,
    url TEXT,
    description TEXT,
    posted TEXT,
    closes TEXT,
    remote INTEGER DEFAULT 0,
    score INTEGER,
    score_reasons TEXT,
    status TEXT NOT NULL DEFAULT 'new',      -- new, shortlisted, prepared, applied, skipped
    cover_letter TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id),
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    location TEXT,
    salary_text TEXT,
    url TEXT,
    applied_on TEXT,
    status TEXT NOT NULL DEFAULT 'applied',  -- ready, applied, acknowledged, pre_screen, assessment, interview, offer, rejected, withdrawn
    next_step TEXT,
    next_date TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    gmail_id TEXT UNIQUE,
    application_id INTEGER REFERENCES applications(id),
    received_at TEXT,
    sender TEXT,
    subject TEXT,
    snippet TEXT,
    category TEXT,          -- rejected, interview, pre_screen, assessment, offer, acknowledged, job_alert, other
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
    key TEXT PRIMARY KEY,          -- the question, simplified
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

APP_STATUSES = [
    ("ready", "Ready to submit"),
    ("applied", "Submitted"),
    ("acknowledged", "Received"),
    ("pre_screen", "Pre-screening"),
    ("assessment", "Assessment"),
    ("interview", "Interview"),
    ("second_stage", "2nd stage"),
    ("offer", "Job offer"),
    ("rejected", "Rejected"),
    ("withdrawn", "Withdrawn"),
]
STATUS_LABELS = dict(APP_STATUSES)
# Email categories that aren't application statuses
EMAIL_LABELS = {**STATUS_LABELS, "job_alert": "Job alert", "other": "Other email", "sent": "You sent"}
ACTIVE_STATUSES = {"applied", "acknowledged", "pre_screen", "assessment", "interview", "second_stage", "offer"}

# When an email arrives, an application only moves "forward" (or to rejected/offer).
STATUS_RANK = {"ready": 0, "applied": 1, "acknowledged": 2, "pre_screen": 3, "assessment": 4,
               "interview": 5, "second_stage": 5.5, "offer": 7, "rejected": 6, "withdrawn": 6}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path(), timeout=60)   # wait for a running refresh instead of failing
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "apply_url" not in cols:   # added later: the employer's real application page
        conn.execute("ALTER TABLE jobs ADD COLUMN apply_url TEXT")
    acols = {r["name"] for r in conn.execute("PRAGMA table_info(applications)")}
    if "source" not in acols:     # added later: 'gmail' when the app found the application in your emails
        conn.execute("ALTER TABLE applications ADD COLUMN source TEXT")
    return conn


@contextmanager
def session(path=None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


def upsert_job(conn, job: dict) -> tuple[int, bool]:
    """Insert a job if new. Returns (id, created)."""
    row = conn.execute("SELECT id FROM jobs WHERE source = ? AND external_id = ?",
                       (job["source"], job["external_id"])).fetchone()
    if row:
        return row["id"], False
    # Same title + company from another source counts as a duplicate.
    if job.get("company"):
        dup = conn.execute("SELECT id FROM jobs WHERE lower(title) = lower(?) AND lower(company) = lower(?)",
                           (job["title"], job["company"])).fetchone()
        if dup:
            return dup["id"], False
    ts = now()
    cols = ["source", "external_id", "title", "company", "location", "salary_min", "salary_max",
            "salary_text", "url", "description", "posted", "closes", "remote", "score", "score_reasons",
            "status"]
    values = [job.get(c) for c in cols]
    values[cols.index("status")] = job.get("status") or "new"
    cur = conn.execute(
        f"INSERT INTO jobs ({', '.join(cols)}, created_at, updated_at) "
        f"VALUES ({', '.join('?' * len(cols))}, ?, ?)", values + [ts, ts])
    return cur.lastrowid, True


def update_job(conn, job_id: int, **fields):
    if not fields:
        return
    fields["updated_at"] = now()
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", list(fields.values()) + [job_id])


def add_application(conn, **fields) -> int:
    fields.setdefault("status", "applied")
    fields["updated_at"] = now()
    cols = list(fields)
    cur = conn.execute(f"INSERT INTO applications ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       [fields[c] for c in cols])
    return cur.lastrowid


def update_application(conn, app_id: int, **fields):
    fields["updated_at"] = now()
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE applications SET {sets} WHERE id = ?", list(fields.values()) + [app_id])


def question_key(question: str) -> str:
    q = re.sub(r"[^a-z0-9 ]+", " ", (question or "").lower().replace("required", ""))
    return re.sub(r"\s+", " ", q).strip()[:200]


def remembered_answers(conn) -> dict:
    return {r["key"]: r["answer"] for r in conn.execute("SELECT key, answer FROM answers")}


def remember_answer(conn, question: str, answer: str):
    key = question_key(question)
    if key and answer:
        conn.execute("INSERT INTO answers (key, question, answer) VALUES (?, ?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET answer = excluded.answer, question = excluded.question, "
                     "updated_at = CURRENT_TIMESTAMP", (key, question[:500], answer))
