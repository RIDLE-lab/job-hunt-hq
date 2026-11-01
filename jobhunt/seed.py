"""Loads the applications made on 14 October 2026 and the remaining saved LinkedIn jobs.
Runs once, the first time the app starts."""
from __future__ import annotations

from . import db
from .matcher import score_job

LI = "https://www.linkedin.com/jobs/view/{}/"

# (company, role, location, salary, linkedin id, status, applied_on, notes)
APPLICATIONS = []   # (company, role, location, salary, linkedin id, status, applied_on, notes)

# Saved jobs still to do: (company, role, location, linkedin id, note)
SAVED = []          # (company, role, location, linkedin id, note)

SKIPPED = [
    ("Carwow", "People Operations Executive (FTC)", "London (Hybrid)", "4470607848", "Needs fluent German"),
]


def add_seed_letters(conn):
    """Tailored letters written earlier (e.g. Ravensbourne, from its recruitment pack)."""
    from pathlib import Path
    for path in (Path(__file__).parent / "seed_letters").glob("*.txt"):
        row = conn.execute("SELECT id, cover_letter FROM jobs WHERE source = 'LinkedIn' AND external_id = ?",
                           (path.stem,)).fetchone()
        if row and not row["cover_letter"]:
            db.update_job(conn, row["id"], cover_letter=path.read_text(encoding="utf-8").strip())


def seed_if_empty(conn) -> bool:
    from . import persona
    if not persona.builtin():
        return False                 # the starter list is Rashid's own history – new accounts start empty
    if not db.get_meta(conn, "seed_letters_v1") and db.get_meta(conn, "seeded"):
        add_seed_letters(conn)
        db.set_meta(conn, "seed_letters_v1", db.now())
    if db.get_meta(conn, "seeded"):
        return False
    for company, role, loc, salary, lid, status, applied_on, notes in APPLICATIONS:
        job = {"source": "LinkedIn", "external_id": lid, "title": role, "company": company, "location": loc,
               "salary_text": salary, "url": LI.format(lid), "description": "",
               "status": "applied" if status == "applied" else "prepared"}
        job_id, _ = db.upsert_job(conn, job)
        db.add_application(conn, job_id=job_id, company=company, role=role, location=loc, salary_text=salary,
                           url=LI.format(lid), applied_on=applied_on, status=status, notes=notes or None)
    for company, role, loc, lid, note in SAVED:
        job = {"source": "LinkedIn", "external_id": lid, "title": role, "company": company, "location": loc,
               "url": LI.format(lid), "description": "", "status": "shortlisted"}
        score, reasons = score_job(job)
        job["score"], job["score_reasons"] = score, " · ".join([note] + reasons)
        db.upsert_job(conn, job)
    for company, role, loc, lid, note in SKIPPED:
        db.upsert_job(conn, {"source": "LinkedIn", "external_id": lid, "title": role, "company": company,
                             "location": loc, "url": LI.format(lid), "description": "",
                             "status": "skipped", "score_reasons": note})
    db.set_meta(conn, "seeded", db.now())
    add_seed_letters(conn)
    db.set_meta(conn, "seed_letters_v1", db.now())
    return True
