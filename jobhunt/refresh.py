"""One refresh = find new jobs, score them, then read new emails.

Run by the Refresh button, or daily from Windows Task Scheduler:
    python -m jobhunt.refresh
"""
from __future__ import annotations

from .persona import home_label

import re
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

from . import db, sources
from .config import load_config
from .matcher import location_fit, score_job, title_excluded


def cv_text(cfg: dict) -> str:
    from .config import cv_file
    path = cv_file(cfg.get("profile", {}))
    if not path:
        return ""
    try:
        if path.suffix.lower() in (".docx", ".doc"):
            from docx import Document
            return "\n".join(p.text for p in Document(str(path)).paragraphs)
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    except Exception:
        return ""


def add_jobs(conn, cfg: dict, jobs: list[dict]) -> int:
    """Score and store jobs; returns how many were new."""
    search = cfg.get("search", {})
    exclude = search.get("exclude_title_words", [])
    cutoff = (date.today() - timedelta(days=int(search.get("max_age_days", 14)))).isoformat()
    new = 0
    for job in jobs:
        if not job.get("title") or title_excluded(job["title"], exclude):
            continue
        if job.get("posted") and job["posted"] < cutoff:
            continue
        if job.get("closes") and job["closes"] < date.today().isoformat():
            continue
        if job.get("remote") and not search.get("include_remote", True):
            continue
        if search.get("hide_far_jobs", True) and location_fit(job.get("location"), bool(job.get("remote"))) == "far":
            continue
        score, reasons = score_job(job)
        job["score"], job["score_reasons"] = score, " · ".join(reasons)
        _, created = db.upsert_job(conn, job)
        new += int(created)
    return new


def tidy_far_jobs(conn, cfg: dict) -> int:
    """Hide new jobs that turn out to be too far away (e.g. after the place lists improved).
    Jobs you saved yourself are left alone."""
    if not cfg.get("search", {}).get("hide_far_jobs", True):
        return 0
    n = 0
    for r in conn.execute("SELECT id, location FROM jobs WHERE status = 'new'").fetchall():
        if location_fit(r["location"]) == "far":
            db.update_job(conn, r["id"], status="skipped", score_reasons=f"Hidden: too far from {home_label()}")
            n += 1
    return n


def fetch_jobs(cfg: dict, log=print) -> list[dict]:
    src, search = cfg.get("sources", {}), cfg.get("search", {})
    keywords = search.get("keywords", [])
    default_distance = int(search.get("distance_miles", 15))
    # A location is either "London" or {"place": "Southend-on-Sea", "miles": 25}
    locations = [(l, default_distance) if isinstance(l, str) else (l["place"], int(l.get("miles", default_distance)))
                 for l in search.get("locations", ["London"])]
    min_salary = search.get("min_salary")
    found: list[dict] = []
    for kw in keywords:
        for loc, distance in locations:
            if src.get("reed_api_key"):
                try:
                    found += sources.search_reed(src["reed_api_key"], kw, loc, distance, min_salary)
                except Exception as e:
                    log(f"Reed '{kw}' in {loc}: {e}")
            if src.get("adzuna_app_id") and src.get("adzuna_app_key"):
                try:
                    found += sources.search_adzuna(src["adzuna_app_id"], src["adzuna_app_key"], kw, loc,
                                                   distance, min_salary, int(search.get("max_age_days", 14)))
                except Exception as e:
                    log(f"Adzuna '{kw}' in {loc}: {e}")
    if not (src.get("reed_api_key") or src.get("adzuna_app_id")):
        log("No Reed/Adzuna keys in config.yaml yet – add them for more jobs (optional).")
    return found


HR_WORDS = re.compile(r"\b(hr|human resources?|people (advis|partner|operations|officer|coordinator|manager|business)|"
                      r"personnel|recruit|talent|resourcing|learning (and|&) development|l&d|employee relations|"
                      r"payroll|reward|onboarding|hris|organi[sz]ational development)", re.I)


def wants_hr_jobs(cfg: dict) -> bool:
    """The Talent World only lists HR jobs, so it's only searched for people looking for HR work."""
    from . import persona
    if persona.builtin():
        return True
    return any(HR_WORDS.search(k or "") for k in (cfg.get("search", {}).get("keywords") or []))


def fetch_talentworld(conn, cfg: dict, log=print) -> list[dict]:
    if not cfg.get("sources", {}).get("talentworld", True) or not wants_hr_jobs(cfg):
        return []
    known = {r["external_id"] for r in conn.execute("SELECT external_id FROM jobs WHERE source = 'The Talent World'")}
    first_run = not known
    try:
        jobs = sources.search_talentworld(known, max_new=60 if first_run else 40, log=log)
        log(f"The Talent World: read {len(jobs)} new job pages")
        return jobs
    except Exception as e:
        log(f"The Talent World: {e}")
        return []


REFRESH_LOCK = threading.Lock()


def run_refresh(log=print) -> dict:
    """One refresh. If another is already running (e.g. the automatic one), this waits for it instead."""
    if not REFRESH_LOCK.acquire(blocking=False):
        with REFRESH_LOCK:
            pass
        return {"new_jobs": 0, "gmail": None, "messages": ["A refresh had just run – the jobs below are up to date."]}
    try:
        return _run_refresh(log)
    finally:
        REFRESH_LOCK.release()


def _run_refresh(log=print) -> dict:
    cfg = load_config()
    result = {"new_jobs": 0, "gmail": None, "messages": []}
    started = db.now()

    def note(msg):
        result["messages"].append(msg)
        log(msg)

    with db.session() as conn:
        jobs = fetch_jobs(cfg, log=note)
        tw = fetch_talentworld(conn, cfg, log=note)
        # Remember every Talent World page already read, even ones filtered out, so it isn't read again.
        for j in tw:
            if not conn.execute("SELECT 1 FROM jobs WHERE source = 'The Talent World' AND external_id = ?",
                                (j["external_id"],)).fetchone():
                kept = add_jobs(conn, cfg, [j])
                if not kept:
                    db.upsert_job(conn, dict(j, status="skipped", score=None, score_reasons="Filtered out"))
                result["new_jobs"] += kept
        result["new_jobs"] += add_jobs(conn, cfg, jobs)
        note(f"Job boards: {len(jobs)} results checked, {result['new_jobs']} new jobs added")
        hidden = tidy_far_jobs(conn, cfg)
        if hidden:
            note(f"Hid {hidden} jobs that are too far from {home_label()}")
        if cfg.get("gmail", {}).get("enabled"):
            try:
                from .gmail_sync import link_existing, sync
                result["gmail"] = sync(conn, cfg, log=note)
                link_existing(conn, log=note)
            except Exception as e:
                note(f"Gmail: {e}")
        db.set_meta(conn, "last_refresh", db.now())
        conn.commit()
        try:
            from .notify import send_new_jobs
            send_new_jobs(conn, cfg, started, log=note)
        except Exception as e:
            note(f"Email: {e}")
    return result


if __name__ == "__main__":
    out = run_refresh()
    sys.exit(0)
