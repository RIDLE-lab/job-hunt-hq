"""Who the app is working for right now, and what they want – read once and cached until their settings change.

builtin() is True for the original owner's account (hand-written letters, answers and job scoring tuned to
their CV). Everyone else gets content built from their own settings and My career details (see generic.py).
"""
from __future__ import annotations

import re

from .config import ROOT, current_user_id, user_dir

_CACHE: dict = {}


def _stamp(uid) -> tuple:
    parts = []
    for p in (user_dir(uid) / "settings.yaml", user_dir(uid) / "career.json", ROOT / "config.yaml"):
        try:
            parts.append(p.stat().st_mtime)
        except OSError:
            parts.append(0)
    return tuple(parts)


def get() -> dict:
    uid = current_user_id()
    stamp = _stamp(uid)
    hit = _CACHE.get(uid)
    if hit and hit[0] == stamp:
        return hit[1]
    from .career import load as load_career
    from .config import load_config
    cfg = load_config()
    career = load_career()
    search, prefs, profile = cfg.get("search", {}), cfg.get("prefs", {}), cfg.get("profile", {})
    skills = [s for s in (prefs.get("skills") or []) if s] + \
             [s.split("–")[0].split("-")[0].strip() for s in career.get("skills", []) if s]
    data = {
        "builtin": bool(cfg.get("builtin")),
        "name": profile.get("name", ""),
        "profile": profile,
        "titles": [k for k in (search.get("keywords") or []) if k],
        "locations": [l if isinstance(l, dict) else {"place": l, "miles": search.get("distance_miles", 15)}
                      for l in (search.get("locations") or [])],
        "include_remote": search.get("include_remote", True),
        "min_salary": search.get("min_salary") or 0,
        "level": prefs.get("level", "mid"),
        "skills": list(dict.fromkeys(s for s in skills if 2 <= len(s) <= 60))[:60],
        "languages": [(l.get("language", "") if isinstance(l, dict) else str(l)).split("–")[0].split("-")[0].strip().lower()
                      for l in career.get("languages", []) if l],
        "career": career,
    }
    _CACHE[uid] = (stamp, data)
    return data


def builtin() -> bool:
    try:
        return get()["builtin"]
    except Exception:
        return current_user_id() is None or bool(load_config_safe().get("builtin"))


def load_config_safe() -> dict:
    try:
        from .config import load_config
        return load_config()
    except Exception:
        return {}


def home_label() -> str:
    """'Southend' / 'Manchester' – where the person searches from, for messages."""
    p = get()
    if p["builtin"]:
        return (get().get("profile") or {}).get("location", "").split(",")[0] or "home"
    loc = (p["profile"].get("location") or (p["locations"][0]["place"] if p["locations"] else "")).strip()
    return re.split(r",", loc)[0] if loc else "your area"
