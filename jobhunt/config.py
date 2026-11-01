"""Loads config.yaml (falls back to config.example.yaml) and resolves paths.

With accounts, every request and background job runs "as" one person (see as_user): their database, career
details, letters and settings live in data/users/<id>/, and load_config() gives their own profile, job search
and Gmail settings on top of the server-wide ones in config.yaml."""
from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("JOBHUNT_DATA") or (ROOT / "data"))
DB_PATH = DATA_DIR / "jobhunt.db"          # before accounts existed; the owner's data moves to data/users/1/
GMAIL_CREDENTIALS = ROOT / "credentials.json"
HOSTED = os.environ.get("JOBHUNT_HOSTED") == "1"     # running as a website: no robot, no PC-only features

_UID = contextvars.ContextVar("jobhunt_user", default=None)
PERSONAL_SECTIONS = ("profile", "search", "gmail", "email")


def current_user_id():
    return _UID.get()


def set_user(uid):
    return _UID.set(uid)


def reset_user(token):
    _UID.reset(token)


@contextmanager
def as_user(uid):
    token = _UID.set(uid)
    try:
        yield
    finally:
        _UID.reset(token)


def user_dir(uid=None) -> Path:
    """The signed-in person's private folder (or data/ itself before any accounts exist)."""
    uid = uid if uid is not None else _UID.get()
    if uid is None:
        DATA_DIR.mkdir(exist_ok=True)
        return DATA_DIR
    d = DATA_DIR / "users" / str(int(uid))
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return user_dir() / "jobhunt.db"


def gmail_token() -> Path:
    return user_dir() / "gmail_token.json"


GMAIL_TOKEN = DATA_DIR / "gmail_token.json"    # kept for old imports; use gmail_token()


def access_token() -> str:
    """Private key built into your browser buttons, so other websites can't read your details from the app."""
    import secrets
    path = user_dir() / "access_token.txt"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(24))
    return path.read_text().strip()


def load_config() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    path = Path(os.environ["JOBHUNT_CONFIG"]) if os.environ.get("JOBHUNT_CONFIG") else ROOT / "config.yaml"
    if not path.exists():
        path = ROOT / "config.example.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    uid = _UID.get()
    if uid is not None:
        # Each person's own details – never anyone else's, even if config.yaml has some.
        settings_file = user_dir(uid) / "settings.yaml"
        mine = {}
        if settings_file.exists():
            with open(settings_file, encoding="utf-8") as f:
                mine = yaml.safe_load(f) or {}
        for k in PERSONAL_SECTIONS:
            cfg[k] = dict(mine.get(k) or {})
        cfg["builtin"] = bool(mine.get("builtin"))
        cfg["prefs"] = dict(mine.get("prefs") or {})
        cfg["user_id"] = uid
    else:
        cfg["builtin"] = True                 # before accounts: the original single-person set-up
        cfg.setdefault("prefs", {})
    cfg.setdefault("profile", {})
    cfg.setdefault("search", {})
    cfg.setdefault("sources", {})
    cfg.setdefault("gmail", {})
    cfg.setdefault("ai", {})
    cfg.setdefault("app", {})
    cfg["_config_file"] = path.name
    return cfg


def cv_file(profile: dict) -> Path | None:
    """Your CV, read fresh every time: the file in cv_path (Documents/Rashid Idle CV.pdf). Save a new version over
    it and the next application uses it. If you've saved it as Word instead ("Rashid Idle CV.docx"), that's used;
    if both a PDF and a Word version exist, the one you changed most recently wins."""
    raw = (profile or {}).get("cv_path", "")
    if not raw:
        return None
    base = Path(raw)
    found = [q for q in (base, *(base.with_suffix(e) for e in (".pdf", ".docx", ".doc"))) if q.is_file()]
    if not found:
        return None
    return max(dict.fromkeys(found), key=lambda q: (q.stat().st_mtime, q.suffix.lower() == ".pdf"))

