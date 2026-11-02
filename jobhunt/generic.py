"""Job scoring, cover letters and form answers for everyone except the original owner – built only from the
person's own settings (what they're looking for, where, salary) and their My career details. Nothing here
invents experience: every sentence about the person comes from what they wrote about themselves."""
from __future__ import annotations

import re

from . import persona

STOP = set("""a an the and or of to in on for with at by from as is are be been being this that these those it its our
your you we they their them his her he she i me my mine us will would can could should may might must shall do does did
have has had not no yes all any each every some such more most other into over under about across per via within
including include includes etc role roles job jobs team teams work working experience years year strong good great
excellent ability able skills skill knowledge understanding responsible responsibilities new well also using use
used ensure ensuring support supporting provide providing key including""".split())


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z+#&./-]{2,}", (text or "").lower()) if w not in STOP}


# ------------------------------------------------------------------ where
def location_fit(location: str, remote: bool = False) -> str:
    """'ok' within the person's chosen distance of one of their places (or remote, if they want remote work),
    'far' for a place outside it, 'unknown' when the advert doesn't say where."""
    from . import geo
    p = persona.get()
    loc = (location or "").lower()
    if remote or re.search(r"remote|home.based|work from home|fully flexible", loc):
        return "ok" if p["include_remote"] else "far"
    homes = [(geo.locate(l.get("place", "")), float(l.get("miles") or 15)) for l in p["locations"]]
    homes = [(pt, r) for pt, r in homes if pt]
    if not homes:
        return "unknown"
    where = geo.job_place(location)
    if not where:
        return "unknown"
    best = min(geo.miles(pt, where) - r for pt, r in homes)
    return "ok" if best <= 3 else "far"           # a few miles' leeway at the edge


def distance_note(location: str) -> str:
    from . import geo
    p = persona.get()
    where = geo.job_place(location)
    if not where or not p["locations"]:
        return ""
    near = []
    for l in p["locations"]:
        pt = geo.locate(l.get("place", ""))
        if pt:
            near.append((geo.miles(pt, where), l.get("place", "")))
    if not near:
        return ""
    d, place = min(near)
    return f"About {round(d)} miles from {place.split(',')[0]}"


# ------------------------------------------------------------------ how good a fit
SENIOR = r"senior|lead\b|principal|manager|head of|director|chief|vp\b|vice president"
JUNIOR = r"junior|graduate|trainee|apprentice|assistant|entry level|intern"
TOP = r"director|head of|chief|vp\b|vice president"


def score_job(job: dict) -> tuple[int, list[str]]:
    p = persona.get()
    title = (job.get("title") or "").lower()
    desc = job.get("description") or ""
    blob = f"{title} {desc.lower()}"
    reasons, score = [], 0

    # 1. Job title vs what they're looking for (up to 40)
    best = 0.0
    tw = words(title)
    for want in p["titles"]:
        ww = words(want)
        if not ww:
            continue
        if want.lower() in title:
            best = 1.0
            break
        best = max(best, len(ww & tw) / len(ww))
    score += round(best * 40)
    if best >= 0.99:
        reasons.append("Exactly the kind of role you're looking for")
    elif best >= 0.5:
        reasons.append("Close to the roles you're looking for")
    elif p["titles"]:
        reasons.append("Not one of the job titles you chose")

    # 2. Their skills in the advert (up to 35)
    found = [s for s in p["skills"] if re.search(rf"(?<![a-z]){re.escape(s.lower())}(?![a-z])", blob)]
    score += min(len(found) * 6, 35)
    if found:
        reasons.append("Uses your skills: " + ", ".join(found[:5]))

    # 3. Level (up to 15)
    level = p["level"]
    if re.search(TOP, title) and level != "senior":
        score -= 15
        reasons.append("Very senior title – likely a big step up")
    elif re.search(SENIOR, title) and level == "entry":
        score += 2
        reasons.append("A step up from your level")
    elif re.search(JUNIOR, title) and level == "senior":
        score += 3
        reasons.append("More junior than you're aiming for")
    else:
        score += 15

    # 4. Salary (up to 5)
    lo, hi = job.get("salary_min"), job.get("salary_max")
    top = hi or lo
    want = p["min_salary"] or 0
    if top and want:
        if top >= want:
            score += 5
            reasons.append(f"Pays at least your £{want:,} minimum")
        elif top < want * 0.9:
            score -= 10
            reasons.append("Pays below your minimum")

    # 5. Location (up to 5)
    where = location_fit(job.get("location"), bool(job.get("remote")))
    if where == "ok":
        score += 5
        note = distance_note(job.get("location"))
        if note:
            reasons.append(note)
    elif where == "far":
        score -= 25
        reasons.append(f"Further than you want to travel from {persona.home_label()}")
    else:
        reasons.append("Check the location")

    # Languages the advert insists on that they don't list
    m = re.search(r"fluent (?:in )?(german|french|spanish|italian|portuguese|mandarin|japanese|polish|arabic|dutch|"
                  r"russian|turkish|hindi|urdu|cantonese|korean)", blob)
    if m and m.group(1) not in " ".join(p["languages"]):
        score = min(score, 15)
        reasons.insert(0, f"Needs fluent {m.group(1).title()}")
    return max(0, min(100, score)), reasons


# ------------------------------------------------------------------ the person's own facts
def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+|;\s+|\s+•\s+|^\s*[-•*]\s*", text or "")
    return [s.strip(" -•*\t") for s in parts if s and len(s.strip()) > 20]


def _as_i(sentence: str) -> str:
    """'Managed a team of 5…' → 'managed a team of 5…' (to follow 'I'); keeps sentences that already start 'I'."""
    s = sentence.strip().rstrip(".")
    if re.match(r"^(I|I'm|I've|My)\b", s):
        return s
    return s[:1].lower() + s[1:] if not s[:2].isupper() else s


def facts() -> list[tuple[list[str], str]]:
    """(keywords, sentence) for each thing the person has written about their work – what advert matching uses."""
    career = persona.get()["career"]
    out = []
    for i, e in enumerate(career.get("experience", [])[:6]):
        title, company = e.get("title", ""), e.get("company", "")
        now = not e.get("end")
        for s in _sentences(e.get("description", ""))[:6]:
            body = _as_i(s)
            if body.startswith(("I ", "I'm", "I've", "My ")):
                text = body
            else:
                lead = re.sub(r"^(responsible for|accountable for|in charge of|part of)\b",
                              lambda m: ("I'm " if now else "I was ") + m.group(1), body)
                text = f"As {title} at {company}, " + (lead if lead != body else f"I {body}")
            out.append((sorted(words(s))[:25], text.rstrip(".") + "."))
    for s in career.get("stories", [])[:6]:
        res = s.get("result") or s.get("action") or ""
        if res:
            out.append((sorted(words(res + " " + (s.get("tags") or "")))[:25], _as_i(res).rstrip(".") + "."))
    return out


def top_facts(text: str, limit: int = 3) -> list[str]:
    want = words(text)
    scored = []
    for i, (keys, fact) in enumerate(facts()):
        hits = len(want & set(keys))
        scored.append((hits, -i, fact))
    scored.sort(reverse=True)
    picked = [f for h, _, f in scored if h > 0][:limit]
    if len(picked) < limit:
        picked += [f for h, _, f in scored if f not in picked][: limit - len(picked)]
    return picked


def qualifications_line() -> str:
    career = persona.get()["career"]
    bits = []
    for ed in career.get("education", [])[:3]:
        deg, field, school = ed.get("degree", ""), ed.get("field", ""), ed.get("school", "")
        if not (deg or field):
            continue
        s = deg + (f" in {field}" if field and field.lower() not in deg.lower() else "")
        if ed.get("expected") or (ed.get("end", "") and "present" in ed.get("end", "").lower()):
            s += " (in progress)"
        bits.append(s + (f" ({school})" if school else ""))
    certs = [c for c in career.get("certifications", []) if c][:3]
    return "; ".join(bits + certs)


def _skills_in(text: str) -> list[str]:
    blob = (text or "").lower()
    return [s for s in persona.get()["skills"] if re.search(rf"(?<![a-z]){re.escape(s.lower())}(?![a-z])", blob)]


def _skill_text(s: str) -> str:
    """'Picking and packing' → 'picking and packing' mid-sentence; keeps WMS, Excel, SQL, Python as written."""
    first = s.split(" ")[0]
    if any(c.isupper() for c in first[1:]) or first.isupper() or len(first) <= 3:
        return s
    proper = {"excel", "word", "python", "sap", "salesforce", "google", "microsoft", "canva", "xero", "sage", "english"}
    return s if first.lower() in proper else s[:1].lower() + s[1:]


def _notice(notice: str) -> str:
    n = (notice or "").strip().rstrip(".")
    if not n:
        return ""
    if re.search(r"immediate|now|straight away|right away", n, re.I):
        return "I am available to start immediately"
    if re.match(r"(?i)^(i |my )", n):
        return n
    return f"My notice period is {n[:1].lower() + n[1:]}"


def _flow(sentences: list[str]) -> list[str]:
    """Don't repeat 'As Warehouse Operative at Amazon, …' for every sentence about the same job."""
    out, last = [], None
    for f in sentences:
        m = re.match(r"^As (.+?) at (.+?), I (.*)$", f)
        if m and (m.group(1), m.group(2)) == last:
            f = f"I also {m.group(3)}" if not m.group(3).startswith(("also ", "was ", "'m ")) else f"I {m.group(3)}"
        last = (m.group(1), m.group(2)) if m else last
        out.append(f)
    return out


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


# ------------------------------------------------------------------ letters and answers
def letter(job: dict, profile: dict) -> str:
    from .advert import company_hook
    company = job.get("company") or "your organisation"
    role = job.get("title") or "this role"
    desc = job.get("description", "")
    p = persona.get()
    career = p["career"]
    matched = _skills_in(desc)[:3]
    opening = f"I am applying for the {role} role at {company}."
    if matched:
        opening += f" The role calls for {_join([_skill_text(x) for x in matched])}, which is where my experience lies."
    # Moving into a new kind of work (e.g. customer service → paralegal): say so plainly, and why it carries across.
    exp = career.get("experience", [])
    STOP_T = {"senior", "junior", "assistant", "trainee", "lead", "manager", "officer", "advisor", "adviser",
              "executive", "coordinator", "associate", "and", "of", "the", "&"}
    role_words = {w for w in re.findall(r"[a-z]+", role.lower()) if w not in STOP_T}
    past_words = {w for e in exp for w in re.findall(r"[a-z]+", (e.get("title") or "").lower()) if w not in STOP_T}
    if exp and role_words and not (role_words & past_words):
        last = exp[0]
        opening += (f" I am moving into this kind of work from my role as {last.get('title')}"
                    + (f" at {last['company']}" if last.get("company") else "")
                    + ", and the experience below carries straight across.")
    hook = company_hook(desc, job.get("company") or "")
    if hook:
        opening += f" Your advert says: “{hook}” – that is the kind of place I want to contribute to."
    body = _flow(top_facts(f"{role} {desc}", 3))
    paras = []
    if body:
        paras.append(" ".join(body[:2]))
        if len(body) > 2:
            paras.append(body[2])
    summary = (career.get("summary") or "").strip()
    if summary and not paras:
        paras.append(summary)
    said = " ".join(paras + [opening]).lower()
    extra = [x for x in p["skills"] if x not in matched and x.lower() not in said][:3]
    if extra:
        paras.append(f"I would also bring {_join([_skill_text(x) for x in extra])}.")
    quals = qualifications_line()
    notice = _notice(profile.get("notice_period"))
    closing = (f"My qualifications include {quals}. " if quals else "") + \
        (f"{notice}, and I" if notice else "I") + \
        f" would welcome the chance to discuss how I could contribute to {company}."
    if not paras:
        paras.append("[Add two or three sentences about your most relevant experience – fill in My career and "
                     "future letters will do this for you.]")
    return "\n\n".join(["Dear Hiring Manager,", opening, *paras, closing, "Yours sincerely,", profile.get("name", "")])


def short_answers(job: dict, profile: dict) -> list[tuple[str, str]]:
    from .advert import company_hook
    company = job.get("company") or "your organisation"
    role = job.get("title") or "this role"
    desc = job.get("description", "")
    career = persona.get()["career"]
    matched = _skills_in(desc)[:3]
    facts_ = top_facts(f"{role} {desc}", 2)
    hook = company_hook(desc, job.get("company") or "")
    summary = (career.get("summary") or "").strip()
    latest = (career.get("experience") or [{}])[0]
    about = summary or (f"I'm currently {latest.get('title')} at {latest.get('company')}." if latest.get("title") else "")
    return [
        ("Why do you want this role?",
         (f"The {role} role is a strong match for what I do best" + (f" – {_join(matched)}" if matched else "") + ". ") +
         " ".join(facts_[:1]) + " I'm looking for a role where I can take ownership and keep developing, and this "
         "role offers exactly that."),
        (f"Why do you want to work for {company}?",
         (f"Your advert says “{hook}”, and I'd like to be part of that. " if hook else
          f"[Add one specific thing about {company} – its mission, products or values.] ") +
         f"I believe I can add value to {company} from day one."),
        ("Summary of relevant experience", " ".join([about, *facts_]).strip() or
         "[Add your experience in My career and this will be written for you.]"),
        ("Key skills", "\n".join(f"• {s}" for s in (matched or persona.get()["skills"][:6]))),
        ("Qualifications", qualifications_line() or "[Add your qualifications in My career.]"),
    ]


def experience_answer(question: str, kind: str = "text") -> str:
    """'Do you have experience of X?' → 'Yes. <the person's own sentence about X>' – or '' if nothing fits."""
    want = words(question) - {"experience", "previous", "prior", "relevant", "have", "any", "do", "you"}
    if not want:
        return ""
    best = []
    for keys, fact in facts():
        hits = len(want & set(keys))
        if hits:
            best.append((hits, fact))
    best.sort(key=lambda x: -x[0])
    if not best or best[0][0] < 1:
        return ""
    text = "Yes. " + best[0][1]
    if kind == "textarea" and len(best) > 1:
        text += " " + best[1][1]
    return text


def form_message(job: dict, profile: dict) -> str:
    latest = (persona.get()["career"].get("experience") or [{}])[0]
    me = f" I am currently {latest.get('title')} at {latest.get('company')}," if latest.get("title") else ""
    notice = (profile.get("notice_period") or "available to start soon").strip()
    return (f"Dear Hiring Team,\n\nPlease find attached my CV and cover letter for the {job.get('title') or 'role'} "
            f"position at {job.get('company') or 'your organisation'}.{me} and I am {notice[:1].lower() + notice[1:]}. "
            f"I would welcome the opportunity to discuss my application.\n\nKind regards,\n{profile.get('name', '')}")
