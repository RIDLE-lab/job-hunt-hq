"""Daily safety copies of everyone's data, kept for 7 days, so a bad update or a broken file can be undone.

They exist only to keep people's data safe. They are never used for anything else, they stay on the same server,
and deleting an account removes that person's folder from every copy straight away."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import date
from pathlib import Path

from .config import DATA_DIR

KEEP_DAYS = 7
ROOT = DATA_DIR / "backups"


def _copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".db":                       # a consistent copy, even while the app is writing
        with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
            a.backup(b)
    else:
        shutil.copy2(src, dst)


def snapshot(today: date | None = None) -> Path | None:
    """Make today's copy if there isn't one yet, then drop copies older than KEEP_DAYS. Returns the new folder."""
    today = today or date.today()
    target = ROOT / today.isoformat()
    made = None
    if not target.exists():
        tmp = ROOT / f".{today.isoformat()}.partial"
        shutil.rmtree(tmp, ignore_errors=True)
        for src in DATA_DIR.rglob("*"):
            rel = src.relative_to(DATA_DIR)
            if not src.is_file() or rel.parts[0] in ("backups", "feedback") or src.suffix in (".log", ".tmp") \
                    or src.name.endswith(("-wal", "-shm", "-journal")):
                continue
            try:
                _copy(src, tmp / rel)
            except (OSError, sqlite3.Error) as e:
                print("[backup] skipped", rel, e)
        if tmp.exists():
            tmp.rename(target)
            made = target
    for old in sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")) if ROOT.exists() else []:
        try:
            if (today - date.fromisoformat(old.name)).days >= KEEP_DAYS:
                shutil.rmtree(old, ignore_errors=True)
        except ValueError:
            pass
    return made


def forget_user(user_id: int):
    """Right to erasure: remove the person's folder from every safety copy too."""
    if not ROOT.exists():
        return
    for day in ROOT.iterdir():
        folder = day / "users" / str(int(user_id))
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
