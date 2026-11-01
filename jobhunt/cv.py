"""Create CV: one set of details (My career + your profile) turned into a polished CV – in a choice of designs,
as PDF or Word, and tailored to a particular job. Also reads an existing CV (PDF or Word) into My career.

Tailoring never adds anything that isn't in your own details: it puts the skills and achievements the advert
asks for first, and leaves the rest in place."""
from __future__ import annotations

import re
from datetime import date

from .generic import words

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DESIGNS = [
    ("classic", "Classic", "One column, clear headings. Suits almost every employer and reads well in recruitment systems."),
    ("modern", "Modern", "A coloured side panel for your contact details, skills and languages."),
    ("compact", "Compact", "Tighter spacing to fit more on a page – good when you have a lot of experience."),
]
ACCENTS = {"navy": "#1f3a5f", "teal": "#0f6e6e", "plum": "#5b2a6e", "forest": "#2f5d3a", "charcoal": "#333333"}


def nice(value: str) -> str:
    """'07/2026' → 'Jul 2026'; '2019' → '2019'; '' → ''."""
    v = (value or "").strip()
    m = re.match(r"^(\d{1,2})\s*/\s*(\d{4})$", v)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{MONTHS[int(m.group(1)) - 1]} {m.group(2)}"
    return v


def dates(start: str, end: str, expected: str = "") -> str:
    s, e = nice(start), nice(end)
    if not e:
        e = f"expected {nice(expected)}" if expected else "Present"
    return f"{s} – {e}" if s else e


def bullets(description: str) -> list[str]:
    parts = re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z])|\s*•\s*|^\s*[-*]\s+", description or "")
    out = []
    for p in parts:
        p = p.strip(" -•*\t").strip()
        if len(p) > 3:
            out.append(p[0].upper() + p[1:] if p else p)
    return out


def build(career: dict, profile: dict, job: dict | None = None) -> dict:
    """Everything a CV needs, in order – optionally tailored to a job advert."""
    contact = [x for x in [profile.get("phone"), profile.get("email"), profile.get("location") or "",
                           (profile.get("linkedin") or "").replace("https://", "").replace("www.", ""),
                           (profile.get("github") or "").replace("https://", "").replace("www.", "")] if x]
    exp = []
    for e in career.get("experience", []):
        if e.get("full_history_only") and len(career.get("experience", [])) > 4:
            continue                      # older side jobs stay off the main CV
        exp.append({"title": e.get("title", ""), "company": e.get("company", ""), "location": e.get("location", ""),
                    "dates": dates(e.get("start", ""), e.get("end", "")), "bullets": bullets(e.get("description", ""))})
    edu = []
    for ed in career.get("education", []):
        if ed.get("full_history_only") and len(career.get("education", [])) > 3:
            continue
        qual = ed.get("degree", "")
        if ed.get("field") and ed["field"].lower() not in qual.lower():
            qual += f" – {ed['field']}" if qual else ed["field"]
        edu.append({"qualification": qual, "school": ed.get("school", ""),
                    "dates": dates(ed.get("start", ""), ed.get("end", ""), ed.get("expected", "")).replace("Present", "").strip(" –"),
                    "result": ed.get("result", "") if ed.get("result", "").lower() not in ("pending", "pass") else ""})
    langs = []
    for l in career.get("languages", []):
        if isinstance(l, dict):
            langs.append(f"{l.get('language', '')}" + (f" ({l['level']})" if l.get("level") else ""))
        elif l:
            langs.append(str(l))
    cv = {
        "name": profile.get("name", ""),
        "headline": career.get("headline") or profile.get("current_title", ""),
        "contact": contact,
        "summary": (career.get("summary") or "").strip(),
        "experience": exp,
        "education": edu,
        "skills": [s for s in career.get("skills", []) if s],
        "languages": langs,
        "certifications": [c for c in career.get("certifications", []) if c],
        "tailored_for": "",
    }
    if job:
        tailor(cv, job)
    return cv


def tailor(cv: dict, job: dict):
    """Put what the advert asks for first – skills, and each job's most relevant achievements – without adding
    or removing anything you wrote."""
    want = words(f"{job.get('title', '')} {job.get('description', '')}")

    def rel(text):
        return len(words(text) & want)
    blob = f"{job.get('title', '')} {job.get('description', '')}".lower()
    cv["skills"].sort(key=lambda s: (s.lower() not in blob, -rel(s)))
    for e in cv["experience"]:
        order = sorted(range(len(e["bullets"])), key=lambda i: (-rel(e["bullets"][i]), i))
        e["bullets"] = [e["bullets"][i] for i in order]
    cv["tailored_for"] = f"{job.get('title', '')} – {job.get('company', '')}".strip(" –")


def filename(cv: dict, ext: str, job: dict | None = None) -> str:
    base = re.sub(r"[^\w\s&()-]", "", cv.get("name") or "My") .strip() or "My"
    extra = f" - {re.sub(r'[^\w\s&()-]', '', job.get('company', ''))}" if job and job.get("company") else ""
    return f"{base} CV{extra}.{ext}"


# ------------------------------------------------------------------ reading an existing CV
HEADINGS = {
    "summary": r"(professional |personal )?(profile|summary|statement)|about me|objective|career summary",
    "experience": r"(work |professional |employment |career |relevant )?(experience|history)|employment|work history|career history|"
                  r"employment and volunteering|experience and volunteering|positions held",
    "education": r"education( and training| & training| and qualifications)?|qualifications|academic( background)?",
    "skills": r"(key |core |technical |relevant )?(skills|competencies|competences|strengths)|skills (and|&) (abilities|tools)|tools",
    "languages": r"languages?",
    "certifications": r"certifications?|certificates|courses|training|professional (development|memberships?)|memberships?",
    "other": r"interests|hobbies|references|volunteering|achievements|awards|publications|projects",
}
MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WHEN = rf"(?:{MONTH}\.?\s+\d{{4}}|\d{{1,2}}\s*/\s*\d{{4}}|\d{{4}})"
RANGE = re.compile(rf"(?P<a>{WHEN})\s*(?:–|-|—|to|until)\s*(?P<b>{WHEN}|present|current|now|date|ongoing)\b", re.I)


def text_of(path: str) -> str:
    p = str(path).lower()
    if p.endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join(pg.extract_text() or "" for pg in PdfReader(path).pages)
    if p.endswith(".docx"):
        from docx import Document
        d = Document(path)
        lines = [para.text for para in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                lines.append(" | ".join(c.text for c in row.cells))
        return "\n".join(lines)
    raise ValueError("Upload a PDF or Word (.docx) file.")


def _mmyyyy(token: str) -> str:
    t = token.strip().lower()
    m = re.match(rf"{MONTH}\.?\s+(\d{{4}})", t)
    if m:
        mon = next(i for i, name in enumerate(MONTHS) if t.startswith(name.lower())) + 1
        return f"{mon:02d}/{t[-4:]}"
    m = re.match(r"(\d{1,2})\s*/\s*(\d{4})", t)
    if m:
        return f"{int(m.group(1)):02d}/{m.group(2)}"
    m = re.search(r"\d{4}", t)
    return m.group(0) if m else ""


def _sections(text: str) -> dict:
    lines = [re.sub(r"\s+", " ", l).strip() for l in (text or "").splitlines()]
    out, current = {"top": []}, "top"
    for l in lines:
        if not l:
            continue
        bare = l.strip(":•-–— ").lower()
        hit = None
        if len(bare) <= 45:
            for key, pat in HEADINGS.items():
                if re.fullmatch(pat, bare, re.I):
                    hit = key
                    break
        if hit:
            current = hit
            out.setdefault(current, [])
            continue
        out.setdefault(current, []).append(l)
    return out


def _split_title_company(text: str) -> tuple[str, str, str]:
    t = re.sub(r"\s{2,}", " ", text.strip(" |,–-—"))
    for sep in (" | ", " – ", " — ", " - ", " at ", ", "):
        if sep in t:
            a, b = t.split(sep, 1)
            loc = ""
            if ", " in b and sep != ", ":
                b, loc = b.split(", ", 1)
            return a.strip(), b.strip(), loc.strip()
    return t, "", ""


def parse(text: str) -> dict:
    """Read CV text into My career's shape. Best effort – always shown to you to check."""
    sec = _sections(text)
    career = {"summary": "", "experience": [], "education": [], "skills": [], "languages": [], "certifications": []}
    if sec.get("summary"):
        career["summary"] = " ".join(sec["summary"])[:1500]
    # experience: each line with a date range starts a job
    lines = sec.get("experience", [])
    jobs, cur = [], None
    for i, l in enumerate(lines):
        m = RANGE.search(l)
        if m:
            rest = (l[:m.start()] + " " + l[m.end():]).strip(" |,–-—()")
            if not rest and i > 0 and cur is not None and cur["description"]:
                # the title/company were the lines just before the dates – take them back from the last job
                rest = cur["description"].pop()
            elif not rest and i > 0 and cur is None:
                rest = lines[i - 1]
            title, company, loc = _split_title_company(rest)
            end = m.group("b")
            end_val = "" if re.match(r"present|current|now|date|ongoing", end or "", re.I) else _mmyyyy(end)
            cur = {"title": title, "company": company, "location": loc, "start": _mmyyyy(m.group("a")),
                   "end": end_val, "description": []}
            jobs.append(cur)
        elif cur is not None:
            if not cur["company"] and len(l) < 70 and not l.endswith(".") and not re.match(r"^[•\-*]", l):
                cur["company"], _, cur["location"] = l.partition(", ")
            else:
                cur["description"].append(l.lstrip("•-* ").strip())
    for j in jobs:
        j["description"] = " ".join(d if d.endswith((".", "!", "?")) else d + "." for d in j["description"] if d)
        career["experience"].append(j)
    # education: lines with a qualification word
    q = re.compile(r"\b(bsc|ba|ma|msc|mba|phd|llb|beng|meng|pgce|hnd|hnc|btec|nvq|diploma|degree|certificate|a.?levels?|"
                   r"gcses?|level \d|bachelor|master|doctorate|foundation|cipd|university|college|school|academy)\b", re.I)
    for l in sec.get("education", []):
        if q.search(l):
            m = RANGE.search(l) or re.search(r"(\d{4})", l)
            years = re.findall(r"\d{4}", l)
            clean = RANGE.sub("", l) if RANGE.search(l) else re.sub(r"\(?\b\d{4}\b\)?", "", l)
            deg, school, _ = _split_title_company(clean)
            if q.search(school) and not re.search(r"university|college|school|academy", deg, re.I) and \
                    re.search(r"university|college|school|academy", school, re.I):
                pass
            elif re.search(r"university|college|school|academy", deg, re.I) and school:
                deg, school = school, deg
            career["education"].append({"school": school.strip(" ,–-"), "degree": deg.strip(" ,–-"), "field": "",
                                        "start": years[0] if len(years) > 1 else "", "end": years[-1] if years else "",
                                        "expected": "", "kind": "", "result": ""})
    for l in sec.get("skills", []):
        for s in re.split(r"[,;|•·]| {2,}|\s-\s", l):
            s = s.strip(" .-–*")
            if 2 <= len(s) <= 50 and s.lower() not in (x.lower() for x in career["skills"]):
                career["skills"].append(s)
    for l in sec.get("languages", []):
        for part in re.split(r"[,;|•]", l):
            part = part.strip()
            if part:
                name, _, level = re.split(r"\s*[–\-:(]\s*", part, maxsplit=1)[0], "", \
                    (re.split(r"\s*[–\-:(]\s*", part, maxsplit=1)[1].rstrip(")") if re.search(r"[–\-:(]", part) else "")
                career["languages"].append({"language": name.strip(), "level": level.strip()})
    for l in sec.get("certifications", []):
        if 3 <= len(l) <= 120:
            career["certifications"].append(l.lstrip("•-* "))
    career["skills"] = career["skills"][:40]
    return career


def ai_parse(text: str, ai_cfg: dict) -> dict | None:
    """With an Anthropic key in config.yaml, Claude reads the CV more reliably (falls back to parse())."""
    key = (ai_cfg or {}).get("anthropic_api_key")
    if not key:
        return None
    import json

    import requests
    prompt = ("Read this CV and return ONLY JSON with these keys: summary (string), headline (string), experience (list of "
              "{title, company, location, start, end, description}), education (list of {school, degree, field, start, end, "
              "result}), skills (list of strings), languages (list of {language, level}), certifications (list of strings). "
              "Dates as MM/YYYY or YYYY; end is empty for a current job. description: the job's bullet points joined as "
              "sentences, copied faithfully – do not add, embellish or summarise anything.\n\nCV:\n" + text[:15000])
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": ai_cfg.get("model", "claude-haiku-5-5"), "max_tokens": 4000,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=60)
        r.raise_for_status()
        out = "".join(b.get("text", "") for b in r.json().get("content", []))
        data = json.loads(out[out.index("{"): out.rindex("}") + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def merge_into(career: dict, found: dict) -> dict:
    """Fill the empty parts of My career from a CV that was read; anything you'd already entered stays."""
    for k in ("summary", "headline"):
        if found.get(k) and not career.get(k):
            career[k] = found[k]
    for k in ("experience", "education", "skills", "languages", "certifications"):
        if found.get(k) and not career.get(k):
            career[k] = found[k]
    for e in career.get("experience", []):
        for k in ("title", "company", "location", "start", "end", "description"):
            e.setdefault(k, "")
    return career


WEAK = re.compile(r"^(responsible for|duties included|tasks included|in charge of|helped (to )?|assisted (with|in) |worked on )", re.I)


def suggestions(career: dict, profile: dict) -> list[tuple[str, str]]:
    """Ways to make the CV stronger – each is something only you can fill in truthfully, so nothing is added for you.
    Returns (step, advice)."""
    out = []
    if not (profile.get("phone") and profile.get("email")):
        out.append(("details", "Add your phone number and email in My settings so employers can reach you."))
    if not career.get("headline") and not profile.get("current_title"):
        out.append(("profile", "Add a headline under your name – the job title you're aiming for."))
    summ = (career.get("summary") or "").strip()
    if not summ:
        out.append(("profile", "Write a short profile (3–4 sentences): who you are, your strongest experience, and what you want next."))
    elif len(summ) > 900:
        out.append(("profile", "Your profile is long – recruiters skim. Aim for 3–4 sentences."))
    exp = career.get("experience", [])
    if not exp:
        out.append(("experience", "Add your work history – paid jobs, placements and volunteering all count."))
    for e in exp:
        name = f"{e.get('title') or 'a job'}{' at ' + e['company'] if e.get('company') else ''}"
        bl = bullets(e.get("description", ""))
        if not e.get("start"):
            out.append(("experience", f"Add the start date for {name}."))
        if not bl:
            out.append(("experience", f"Add 2–5 achievements for {name}."))
            continue
        if any(WEAK.match(b) for b in bl):
            out.append(("experience", f"{name}: start points with an action (\"Managed…\", \"Built…\", \"Cut…\") rather than \"Responsible for…\"."))
        if not any(re.search(r"\d", b) for b in bl):
            out.append(("experience", f"{name}: add a number if you have one – how many, how much, how often, or by what percentage."))
        if any(len(b) > 260 for b in bl):
            out.append(("experience", f"{name}: split long points – one achievement per line reads better."))
    if not career.get("education"):
        out.append(("education", "Add your education – your highest qualification is enough."))
    if len(career.get("skills", [])) < 5:
        out.append(("skills", "List at least 6–10 skills, using the words job adverts use (tools, systems, methods)."))
    return out[:12]


def today_label() -> str:
    d = date.today()
    return f"{d.day} {d:%B %Y}"
