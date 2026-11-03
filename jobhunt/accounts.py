"""People who can sign in to Job Hunt HQ, and invite codes.

Each person has their own folder under data/users/<id>/ with their own database, career details, CV, letters,
settings and private browser-button token – nobody can see anyone else's. The first account (the owner) takes
over the data that was there before accounts existed. Only the owner can create invite codes.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from werkzeug.security import check_password_hash, generate_password_hash

from .config import DATA_DIR, ROOT, as_user, user_dir

ACCOUNTS_DB = DATA_DIR / "accounts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'idea',
    page TEXT,
    message TEXT NOT NULL,
    image TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    reply TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    email TEXT,
    pw_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    setup_done INTEGER NOT NULL DEFAULT 0,
    session_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS invites (
    code TEXT PRIMARY KEY,
    note TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_by INTEGER,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS resets (
    code TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
"""
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,29}$")
MIN_PASSWORD = 10


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    c = sqlite3.connect(ACCOUNTS_DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def any_users() -> bool:
    if not ACCOUNTS_DB.exists():
        return False
    with connect() as c:
        return c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def get(user_id) -> dict | None:
    if not user_id:
        return None
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def all_users() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM users ORDER BY id")]


def password_problem(password: str, username: str = "") -> str:
    """Why a password isn't good enough, or ''."""
    if len(password or "") < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if username and username.lower() in password.lower():
        return "Don't include your username in your password."
    if len(set(password)) < 5:
        return "Use a less repetitive password."
    return ""


def username_problem(username: str) -> str:
    if not USERNAME.match(username or ""):
        return "Usernames are 3–30 characters: lower-case letters, numbers, dots, dashes or underscores."
    with connect() as c:
        if c.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            return "That username is taken."
    return ""


def create(username: str, name: str, password: str, email: str = "", is_admin: bool = False) -> int:
    with connect() as c:
        cur = c.execute("INSERT INTO users (username, name, email, pw_hash, is_admin, session_version, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (username.lower(), name.strip(), email.strip(), generate_password_hash(password),
                         1 if is_admin else 0, secrets.token_hex(8), _now()))
        uid = cur.lastrowid
    user_dir(uid)                      # make the private folder
    return uid


def update(user_id: int, **fields):
    if "password" in fields:
        fields["pw_hash"] = generate_password_hash(fields.pop("password"))
        fields["session_version"] = secrets.token_hex(8)     # signs out every other device
    if not fields:
        return
    with connect() as c:
        c.execute(f"UPDATE users SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?", [*fields.values(), user_id])


# ------------------------------------------------------------------ signing in (with a brake on guessing)
_ATTEMPTS: dict[str, list[float]] = {}
WINDOW, LIMIT = 15 * 60, 8


def too_many_attempts(key: str) -> bool:
    now = time.time()
    tries = [t for t in _ATTEMPTS.get(key, []) if now - t < WINDOW]
    _ATTEMPTS[key] = tries
    return len(tries) >= LIMIT


def check_login(username: str, password: str, ip: str = "") -> tuple[dict | None, str]:
    username = (username or "").strip().lower()
    for key in (f"u:{username}", f"ip:{ip}"):
        if too_many_attempts(key):
            return None, "Too many attempts. Wait 15 minutes and try again."
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row and row["active"] and check_password_hash(row["pw_hash"], password or ""):
        _ATTEMPTS.pop(f"u:{username}", None)
        update(row["id"], last_login=_now())
        return dict(row), ""
    if not row:                                   # same time either way, so usernames can't be fished for
        check_password_hash(generate_password_hash("x"), password or "")
    for key in (f"u:{username}", f"ip:{ip}"):
        _ATTEMPTS.setdefault(key, []).append(time.time())
    if row and not row["active"]:
        return None, "This account has been switched off. Ask the owner."
    return None, "That username and password don't match."


# ------------------------------------------------------------------ invites and password resets
def _code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"       # no 0/O or 1/I mix-ups
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def create_invite(created_by: int, note: str = "", days: int = 14) -> str:
    code = _code()
    with connect() as c:
        c.execute("INSERT INTO invites (code, note, created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                  (code, note.strip()[:80], created_by, _now(), (datetime.now() + timedelta(days=days)).isoformat()))
    return code


def invites() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT i.*, u.username AS used_by_name FROM invites i LEFT JOIN users u ON u.id = i.used_by "
            "ORDER BY i.created_at DESC LIMIT 50")]


def invite_used(code: str) -> bool:
    with connect() as c:
        row = c.execute("SELECT used_by FROM invites WHERE code = ?", ((code or "").strip().upper(),)).fetchone()
    return bool(row and row["used_by"])


def username_exists(username: str) -> bool:
    with connect() as c:
        return c.execute("SELECT 1 FROM users WHERE username = ?", ((username or "").strip().lower(),)).fetchone() is not None


def invite_ok(code: str) -> bool:
    code = (code or "").strip().upper()
    with connect() as c:
        row = c.execute("SELECT * FROM invites WHERE code = ?", (code,)).fetchone()
    return bool(row and not row["used_by"] and row["expires_at"] > _now())


def claim_invite(code: str) -> bool:
    """Take an invite in one step, so two sign-ups sent at the same moment can't both use it."""
    with connect() as c:
        cur = c.execute("UPDATE invites SET used_by = -1, used_at = ? WHERE code = ? AND used_by IS NULL AND expires_at > ?",
                        (_now(), (code or "").strip().upper(), _now()))
        return cur.rowcount == 1


def release_invite(code: str):
    with connect() as c:
        c.execute("UPDATE invites SET used_by = NULL, used_at = NULL WHERE code = ? AND used_by = -1", ((code or "").strip().upper(),))


def claim_reset(code: str) -> bool:
    with connect() as c:
        cur = c.execute("UPDATE resets SET used_at = ? WHERE code = ? AND used_at IS NULL AND expires_at > ?",
                        (_now(), (code or "").strip().upper(), _now()))
        return cur.rowcount == 1


def use_invite(code: str, user_id: int):
    with connect() as c:
        c.execute("UPDATE invites SET used_by = ?, used_at = ? WHERE code = ?", (user_id, _now(), code.strip().upper()))


def cancel_invite(code: str):
    with connect() as c:
        c.execute("DELETE FROM invites WHERE code = ? AND used_by IS NULL", (code,))


def create_reset(user_id: int, hours: int = 48) -> str:
    code = _code()
    with connect() as c:
        c.execute("INSERT INTO resets (code, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                  (code, user_id, _now(), (datetime.now() + timedelta(hours=hours)).isoformat()))
    return code


def reset_user(code: str) -> int | None:
    with connect() as c:
        row = c.execute("SELECT * FROM resets WHERE code = ?", ((code or "").strip().upper(),)).fetchone()
    if row and not row["used_at"] and row["expires_at"] > _now():
        return row["user_id"]
    return None


def use_reset(code: str):
    with connect() as c:
        c.execute("UPDATE resets SET used_at = ? WHERE code = ?", (_now(), code.strip().upper()))


# ------------------------------------------------------------------ the browser buttons' private token
def user_for_token(token: str) -> int | None:
    """Which person a browser-button token belongs to (each person has their own)."""
    import hmac
    if not token:
        return None
    for u in all_users():
        path = user_dir(u["id"]) / "access_token.txt"
        if path.exists() and hmac.compare_digest(path.read_text().strip(), token):
            return u["id"]
    return None


# ------------------------------------------------------------------ the owner takes over the existing data
PERSONAL_SECTIONS = ("profile", "search", "gmail", "email")
MOVE = ("jobhunt.db", "career.json", "letters", "access_token.txt", "gmail_token.json", "browser", "ui.json")


def adopt_existing_data(user_id: int) -> list[str]:
    """Move the data that was there before accounts existed into the owner's folder (a backup copy of the
    database stays behind), and copy their personal settings out of config.yaml."""
    dest = user_dir(user_id)
    moved = []
    db_file = DATA_DIR / "jobhunt.db"
    if db_file.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        shutil.copy2(db_file, DATA_DIR / f"jobhunt-before-accounts-{stamp}.db")
    dest.mkdir(parents=True, exist_ok=True)
    for name in MOVE:
        src, to = DATA_DIR / name, dest / name
        if not src.exists() or to.exists():
            continue
        # Copy first (safe even if Windows still has the file open), then tidy the old one away if possible.
        if name.endswith(".db"):
            a, b = sqlite3.connect(src), sqlite3.connect(to)
            a.backup(b)
            a.close()
            b.close()
        elif src.is_dir():
            try:
                shutil.copytree(src, to, ignore=shutil.ignore_patterns("Singleton*", "*.lock", "lockfile"),
                                ignore_dangling_symlinks=True, dirs_exist_ok=True)
            except (OSError, shutil.Error):
                pass                   # a file the browser has locked – the rest is copied
        else:
            shutil.copy2(src, to)
        try:
            if src.is_dir():
                shutil.rmtree(src)
            else:
                src.unlink()
        except OSError:
            pass                       # still in use – harmless: the app now reads the copy in the account folder
        moved.append(name)
    settings = {}
    for path in (ROOT / "config.yaml", ROOT / "config.example.yaml"):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            settings = {k: cfg.get(k) or {} for k in PERSONAL_SECTIONS}
            break
    settings["builtin"] = True          # keeps the owner's own hand-written letters, answers and job scoring
    if not (dest / "career.json").exists():
        seed = Path(__file__).with_name("career_seed.json")
        if seed.exists():
            shutil.copy2(seed, dest / "career.json")
    save_settings(settings, user_id)
    update(user_id, setup_done=1)
    return moved


# ------------------------------------------------------------------ each person's own settings
def settings_path(user_id=None) -> Path:
    return user_dir(user_id) / "settings.yaml"


def load_settings(user_id=None) -> dict:
    path = settings_path(user_id)
    if not path.exists():
        return {}
    from .secretbox import open_settings
    with open(path, encoding="utf-8") as f:
        return open_settings(yaml.safe_load(f) or {})


def save_settings(data: dict, user_id=None):
    from .secretbox import seal_settings
    path = settings_path(user_id)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(seal_settings(data), f, allow_unicode=True, sort_keys=False)
    tmp.replace(path)


def users_for_background() -> list[int]:
    """Everyone whose job search should keep running in the background."""
    return [u["id"] for u in all_users() if u["active"] and u["setup_done"]]


def run_as_each_user(fn):
    """Run fn() once for each active person, with their data."""
    for uid in users_for_background():
        with as_user(uid):
            try:
                fn()
            except Exception as e:
                print(f"[background] {uid}: {e}")


def export_summary(user_id: int) -> str:
    return json.dumps({k: v for k, v in (get(user_id) or {}).items() if k not in ("pw_hash", "session_version")})


# ------------------------------------------------------------------ moving your data (PC → website)
SKIP_EXPORT = ("browser/", "browser\\")


def export_zip(user_id: int) -> bytes:
    """Everything that's yours – jobs, applications, emails, career, settings, letters, and your CV file – in one zip.
    The robot's browser profile (site sign-ins) is left out: sign in again wherever you use it next."""
    import io
    import zipfile

    from .config import cv_file
    folder = user_dir(user_id)
    settings = load_settings(user_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            rel = p.relative_to(folder).as_posix()
            if p.is_dir() or rel.startswith(SKIP_EXPORT) or rel.endswith(".tmp") or rel == "settings.yaml":
                continue
            if rel.endswith(".db"):                       # a consistent copy, even while the app is running
                import sqlite3
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    snap = Path(td) / "snap.db"
                    src = sqlite3.connect(p)
                    dst = sqlite3.connect(snap)
                    src.backup(dst)
                    src.close()
                    dst.close()
                    z.write(snap, rel)
                continue
            z.write(p, rel)
        cv = cv_file(settings.get("profile") or {})
        if cv and folder not in cv.resolve().parents:
            z.write(cv, f"cv/{cv.name}")
            settings.setdefault("profile", {})["cv_path"] = f"cv/{cv.name}"
        elif cv:
            settings.setdefault("profile", {})["cv_path"] = cv.resolve().relative_to(folder.resolve()).as_posix()
        z.writestr("settings.yaml", yaml.safe_dump(settings, allow_unicode=True, sort_keys=False))
        z.writestr("JOB-HUNT-HQ-EXPORT.txt", "Job Hunt HQ data export. Import it when creating your account on the website.\n")
    return buf.getvalue()


def import_zip(user_id: int, data: bytes) -> int:
    """Unpack an export into this account (only into its own folder). Returns the number of files."""
    import io
    import zipfile
    folder = user_dir(user_id).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if "JOB-HUNT-HQ-EXPORT.txt" not in z.namelist():
            raise ValueError("That isn't a Job Hunt HQ export.")
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or name.startswith(SKIP_EXPORT) or name == "JOB-HUNT-HQ-EXPORT.txt":
                continue
            target = (folder / name).resolve()
            if folder not in target.parents:
                continue                                   # never write outside this account's folder
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                out.write(src.read())
            count += 1
    s = load_settings(user_id)
    cvp = (s.get("profile") or {}).get("cv_path")
    if cvp and not Path(cvp).is_absolute():
        s["profile"]["cv_path"] = str(folder / cvp)
        save_settings(s, user_id)
    update(user_id, setup_done=1)
    return count


# ------------------------------------------------------------------ feedback from the people using it
FEEDBACK_KINDS = [("problem", "Something's wrong"), ("idea", "An idea"), ("question", "A question"), ("praise", "Something I like"),
                  ("report", "Report misuse or a security problem")]
FEEDBACK_STATUS = [("new", "New"), ("planned", "Planned"), ("done", "Done"), ("wont", "Not doing")]
FEEDBACK_DIR = DATA_DIR / "feedback"


def add_feedback(user_id: int, kind: str, message: str, page: str = "", image: tuple[bytes, str] | None = None) -> int:
    kind = kind if kind in dict(FEEDBACK_KINDS) else "idea"
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as c:
        fid = c.execute("INSERT INTO feedback (user_id, kind, page, message, status, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, 'new', ?, ?)", (user_id, kind, (page or "")[:300], message[:5000], now, now)).lastrowid
        if image:
            data, ext = image
            FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
            name = f"{fid}-{secrets.token_hex(6)}{ext}"
            (FEEDBACK_DIR / name).write_bytes(data)
            c.execute("UPDATE feedback SET image = ? WHERE id = ?", (name, fid))
    return fid


def feedback_list(user_id: int | None = None) -> list[dict]:
    """Everyone's feedback (for the owner), or one person's own."""
    q = ("SELECT f.*, u.name AS name, u.username AS username FROM feedback f LEFT JOIN users u ON u.id = f.user_id "
         + ("WHERE f.user_id = ? " if user_id else "") +
         "ORDER BY CASE f.status WHEN 'new' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END, f.created_at DESC")
    with connect() as c:
        return [dict(r) for r in c.execute(q, (user_id,) if user_id else ())]


def get_feedback(fid: int) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM feedback WHERE id = ?", (fid,)).fetchone()
    return dict(r) if r else None


def update_feedback(fid: int, status: str | None = None, reply: str | None = None):
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as c:
        if status in dict(FEEDBACK_STATUS):
            c.execute("UPDATE feedback SET status = ?, updated_at = ? WHERE id = ?", (status, now, fid))
        if reply is not None:
            c.execute("UPDATE feedback SET reply = ?, updated_at = ? WHERE id = ?", (reply.strip()[:3000] or None, now, fid))


def delete_feedback(fid: int):
    f = get_feedback(fid)
    if f and f.get("image"):
        try:
            (FEEDBACK_DIR / f["image"]).unlink()
        except OSError:
            pass
    with connect() as c:
        c.execute("DELETE FROM feedback WHERE id = ?", (fid,))


def new_feedback_count() -> int:
    if not ACCOUNTS_DB.exists():
        return 0
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM feedback WHERE status = 'new'").fetchone()[0]


def owner_contact() -> str:
    """The owner's email, for privacy and data requests."""
    try:
        with connect() as c:
            row = c.execute("SELECT id, email FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1").fetchone()
        if not row:
            return ""
        return (load_settings(row["id"]).get("profile") or {}).get("email") or row["email"] or ""
    except Exception:
        return ""


def delete_user(user_id: int):
    """Right to erasure: remove the person's account and everything stored for them. The owner can't be deleted."""
    u = get(user_id)
    if not u or u["is_admin"]:
        raise ValueError("The owner's account can't be deleted here.")
    for f in feedback_list(user_id):
        delete_feedback(f["id"])                   # their feedback and any screenshots
    folder = user_dir(user_id)
    if folder.exists() and folder.parent.name == "users":
        shutil.rmtree(folder, ignore_errors=True)  # jobs, applications, emails, CV, letters, settings, Gmail link
    with connect() as c:
        c.execute("DELETE FROM resets WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
