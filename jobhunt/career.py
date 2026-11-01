"""Your career details – work history, education, skills, languages – used to fill the
"My Experience" parts of application forms (Workday and others).

Kept in data/career.json and edited on the app's "My career" page. It starts from your CV and grows
with you: change a job, add a qualification, and every later application uses it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import current_user_id, user_dir

SEED = Path(__file__).resolve().parent / "career_seed.json"
EMPTY = {"summary": "", "experience": [], "education": [], "skills": [], "languages": [], "certifications": [],
         "stories": [], "competencies": []}


def path() -> Path:
    """This person's career details (data/users/<id>/career.json)."""
    return user_dir() / "career.json"


def load() -> dict:
    p = path()
    if p.is_file():
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    elif current_user_id() is None:            # before accounts: the owner's details from their CV
        with open(SEED, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.loads(json.dumps(EMPTY))   # a new person starts with nothing of anyone else's
    for key, default in EMPTY.items():
        data.setdefault(key, json.loads(json.dumps(default)))
    return data


def save(data: dict):
    p = path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def month_year(value: str) -> tuple[str, str]:
    """'05/2024' -> ('05', '2024'); '2019' -> ('', '2019'); '' -> ('', '')."""
    m = re.match(r"\s*(\d{1,2})\s*/\s*(\d{4})", value or "")
    if m:
        return m.group(1).zfill(2), m.group(2)
    m = re.search(r"(\d{4})", value or "")
    return ("", m.group(1)) if m else ("", "")


def from_form(form) -> dict:
    """Rebuild the details from the My career page's form fields."""
    def rows(prefix, keys):
        out, i = [], 0
        idx = sorted({int(k.split("-")[1]) for k in form.keys() if k.startswith(prefix + "-")})
        for i in idx:
            row = {k: (form.get(f"{prefix}-{i}-{k}") or "").strip() for k in keys}
            if any(row.values()):
                out.append(row)
        return out
    split = lambda text: [s.strip() for s in re.split(r"[\n,;]+", text or "") if s.strip()]
    langs = []
    for line in (form.get("languages") or "").splitlines():
        if line.strip():
            name, _, level = line.partition("–") if "–" in line else line.partition("-")
            langs.append({"language": name.strip(), "level": level.strip()})
    def newest(row):
        mm, yyyy = month_year(row.get("start", ""))
        return (int(yyyy or 0), int(mm or 0))
    old = load()
    keep = {k: (form.get(k) if k in form else old.get(k, "")) or "" for k in ("summary", "headline")}
    return {
        **{k: v.strip() for k, v in keep.items()},
        "experience": sorted(rows("exp", ("title", "company", "location", "start", "end", "description", "full_history_only",
                                    "start_date", "end_date", "reason", "agency")), key=newest, reverse=True),
        "education": rows("edu", ("school", "degree", "field", "start", "end", "expected", "kind",
                                    "form_degree", "form_field", "result", "full_history_only",
                                    "start_date", "end_date")),
        "stories": rows("sty", ("title", "tags", "situation", "task", "action", "result", "learned")),
        "competencies": rows("comp", ("name", "tags", "answer")),
        "skills": split(form.get("skills")),
        "certifications": split(form.get("certifications")),
        "languages": langs,
    }
