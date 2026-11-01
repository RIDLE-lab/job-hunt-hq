"""Answers for application-form questions the Fill logic doesn't cover.

Order: an answer you gave before for the same question → a safe rule from your profile →
a suggestion written by Claude (only if you added an API key) → ask you.
Remembered and rule answers are filled in by themselves; Claude's suggestions are always shown to you first.
"""
from __future__ import annotations

import re

import requests

from .db import question_key

# Questions only you should answer – never guessed by a rule or by Claude.
PERSONAL = re.compile(r"gender|sex\b|pronoun|ethnic|race|religio|belief|sexual|orientation|disab|health|"
                      r"age (group|range|band)|date of birth|marital|caring|carer|veteran|criminal|convict|"
                      r"\btrans\b|transgender|equal|diversity|consent|agree|privacy|terms|declar|confirm|offen[cs]e|offender|"
                      r"prosecut|rehabilitation|adjustment|visa|immigration|nationality|dbs|barred", re.I)


def match_option(options: list[str], want: str | re.Pattern) -> str | None:
    if not options:
        return None
    if isinstance(want, str):
        w = want.strip().lower()
        for o in options:
            if o.strip().lower() == w:
                return o
        for o in options:
            if o.strip().lower().startswith(w) or (len(w) > 3 and w in o.lower()):
                return o
        return None
    return next((o for o in options if want.search(o)), None)


# Things you've told us are true for you, answered only when the form asks you directly
# ("Do you have…", "Have you ever…", "Is there…", "Will you require…"). Consent / check / policy questions are never
# touched – e.g. "Are you happy to have a criminal record check?" is left for you.
ASKS_YOU = re.compile(r"^\W*(do|have|are|is|will|would|did|has)\b", re.I)
NOT_A_DECLARATION = re.compile(r"consent|agree|willing|happy to|prepared to|check\b|checks\b|dbs|disclos|declare|"
                               r"understand|policy|read |aware|confirm|undergo|apply for|in the future you", re.I)
STATED_NO = [
    ("criminal record", re.compile(r"convict|criminal|offen[cs]e|offender|prosecution|\bcaution", re.I), "No"),
    ("reasonable adjustments", re.compile(r"adjustments?\b|access (needs|requirements)|additional support|"
                                          r"assistance (at|during|for) (the |your )?(interview|assessment|application)", re.I),
     "None, thank you."),
    ("visa", re.compile(r"\b(require|need)\b[^.?]{0,60}\b(visa|work permit)|\b(visa|work permit)\b[^.?]{0,40}\b(require|need)", re.I), "No"),
]


def stated_answer(question: str, kind: str, options: list[str]) -> str | None:
    """'No' to unspent convictions, needing adjustments or needing a visa – only for direct questions."""
    q = " ".join((question or "").split())
    if not ASKS_YOU.search(q) or NOT_A_DECLARATION.search(q):
        return None
    if re.search(r"without[^.?]{0,60}(sponsor|visa)|no need for|not (need|require)|right to work", q, re.I):
        return None                      # "right to work without (the need for) sponsorship?" = Yes, via the normal rules
    for _, pattern, text_answer in STATED_NO:
        if pattern.search(q):
            if options:
                return match_option(options, re.compile(r"^\s*no\b", re.I))   # None if there's no plain "No" to pick
            return text_answer if kind in ("text", "textarea") else "No"
    return None


def rule_answer(question: str, kind: str, options: list[str], profile: dict, fields: dict) -> str | None:
    q = question.lower()
    yes, no = re.compile(r"^\s*yes\b", re.I), re.compile(r"^\s*no\b", re.I)

    def pick(value):
        if kind in ("text", "textarea"):
            return value if isinstance(value, str) else None
        return match_option(options, value) if options else (value if isinstance(value, str) else None)

    # "Do you have the right to work WITHOUT sponsorship?" = Yes; "Will you REQUIRE sponsorship?" = No.
    if re.search(r"without[^.?]{0,50}sponsor|no need for[^.?]{0,30}sponsor|not (need|require)[^.?]{0,30}sponsor", q):
        return pick(yes) if options else "Yes"
    if re.search(r"sponsor", q):
        return pick(no) if options else "No"
    if re.search(r"\b(require|need)\b[^.?]{0,60}\b(visa|work permit)", q) and not re.search(r"without|no need|not (need|require)|right to work", q):
        return pick(no) if options else "No"
    if re.search(r"right to work|eligib\w* to work|legally (able|entitled|authori[sz]ed|permitted)|permission to work", q):
        return pick(yes) if options else "Yes"
    if re.search(r"(18|eighteen) (years|or over|or older)|over (the age of )?18|at least 18", q):
        return pick(yes) if options else "Yes"
    if re.search(r"phone.*(type|device)|(type|device).*phone", q):
        return pick("Mobile")
    if re.search(r"(country|phone).*(code|prefix)|dial", q):
        return pick(re.compile(r"united kingdom|\+44|^uk\b", re.I))
    if re.search(r"\bcountry\b|country of residence", q):
        return pick(re.compile(r"^(united kingdom|uk|great britain|gb)\b", re.I))
    if re.search(r"\bcounty\b|\bregion\b|\bstate\b|province", q) and options:
        return pick("Essex")
    if re.search(r"notice", q) and profile.get("notice_period"):
        return pick(profile["notice_period"]) if options else profile["notice_period"]
    if re.search(r"salary|pay expectation|expected (pay|compensation)", q) and not re.search(r"current|present", q):
        return profile.get("salary_expectation") if kind in ("text", "textarea") else None
    if re.search(r"\bcity\b|\btown\b", q):
        return pick(fields.get("city", ""))
    if re.search(r"post.?code|postal|zip", q):
        return fields.get("postcode") if kind == "text" else None
    if re.search(r"address", q) and not re.search(r"e-?mail|line 2", q):
        return fields.get("address_line") if kind == "text" else None
    if re.search(r"linkedin", q):
        return profile.get("linkedin") if kind == "text" else None
    if re.search(r"github|portfolio|personal (web)?site|examples of (your )?work", q) and profile.get("github"):
        if kind == "textarea":
            return f"GitHub: {profile['github']}" + (f"\nLinkedIn: {profile['linkedin']}" if profile.get("linkedin") else "")
        return profile["github"] if kind == "text" else None
    if re.search(r"current (job )?title|current (position|role)", q):
        return profile.get("current_title") if kind == "text" else None
    if re.search(r"current (employer|company)", q):
        return profile.get("current_employer") if kind == "text" else None
    return None


def ai_answer(question: str, kind: str, options: list[str], job: dict, profile: dict, cv: str, ai_cfg: dict) -> str:
    key = (ai_cfg or {}).get("anthropic_api_key")
    if not key or PERSONAL.search(question):
        return ""
    if options:
        how = "Reply with exactly one of these options, copied exactly, and nothing else:\n" + "\n".join(options)
    elif kind == "textarea":
        how = "Reply with the answer only: 60–180 words, first person, UK English, no headings."
    else:
        how = "Reply with a short answer only (a few words or one sentence), UK English."
    prompt = (
        "You are filling in a job application form for the candidate below. Answer the question truthfully "
        "using only facts from the CV and profile. Never invent experience, qualifications or numbers. "
        "If the answer can't be known from them, reply with exactly UNKNOWN.\n\n"
        f"QUESTION: {question}\n{how}\n\n"
        f"JOB: {job.get('title')} at {job.get('company')}\nADVERT:\n{(job.get('description') or '')[:4000]}\n\n"
        f"PROFILE: notice {profile.get('notice_period')}; salary expectation {profile.get('salary_expectation')}; "
        f"right to work {profile.get('right_to_work')}; lives in {profile.get('address', '').split(',')[-3:]}\n\n"
        f"CV:\n{cv[:10000]}"
    )
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": ai_cfg.get("model", "claude-haiku-5-5"), "max_tokens": 500,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=40)
        resp.raise_for_status()
        text = "".join(b.get("text", "") for b in resp.json().get("content", [])).strip()
    except Exception:
        return ""
    if not text or text.upper().startswith("UNKNOWN"):
        return ""
    if options:
        return match_option(options, text) or ""
    return text


def suggest(q: dict, remembered: dict, profile: dict, fields: dict, job: dict, cv: str, ai_cfg: dict) -> tuple[str, str]:
    """Returns (answer, source) where source is remembered / rule / ai / ''."""
    label, kind, options = q.get("label", ""), q.get("kind", "text"), q.get("options") or []
    saved = remembered.get(question_key(label))
    if saved:
        if not options or match_option(options, saved):
            return (match_option(options, saved) if options else saved), "remembered"
    if q.get("own_words"):
        return "", "own_words"          # the employer asked for your own words: you write it
    stated = stated_answer(label, kind, options)
    if stated:
        return stated, "rule"
    if PERSONAL.search(label) and not re.search(r"right to work|sponsor", label, re.I):
        return "", ""                   # personal questions are yours to answer: nothing guesses them
    if not PERSONAL.search(label) or re.search(r"right to work|sponsor", label, re.I):
        rule = rule_answer(label, kind, options, profile, fields)
        if rule:
            return rule, "rule"
    if kind in ("text", "textarea") and not options:
        text = experience_answer(label, kind)
        if text:
            return text, "experience"
    if kind == "textarea" and not options and len(label) < 120 and not BEHAVIOURAL.search(label):
        text = competency_answer(label)
        if text:
            return text, "competency"
    if kind == "textarea" and not options and BEHAVIOURAL.search(label):
        text, story, score = story_answer(label + " " + (q.get("hint") or ""), job)
        if text:
            q["story"], q["story_fit"] = story, score
            return text, "story"
    if kind == "textarea" and not options:
        draft = draft_answer(label, job, profile)
        if draft:
            return draft, "draft"
    ai = ai_answer(label, kind, options, job, profile, cv, ai_cfg)
    if ai:
        return ai, "ai"
    return "", ""


EXPERIENCE_Q = re.compile(r"^\W*(do|have|are) you (got |have |had )?(any |previous |prior |recent |relevant |proven |some )*"
                          r"(experience|worked|work experience|knowledge|been (employed|working))|"
                          r"^\W*(what|describe your|tell us about your) (previous |relevant )?experience", re.I)

# Your experience in a few words, for "Do you have experience of …?" questions. Only true statements from your CV.
EXPERIENCE = [
    (r"\bhr\b|human resources|people advis|people partner|generalist|hr advis|hr officer|hr administrat|personnel",
     "Yes. I'm currently HR & Recruitment Officer at Chenai Holistic Home Care, a generalist HR role covering recruitment "
     "and onboarding, employee relations (investigations, disciplinaries and grievances under ACAS), absence and "
     "performance management, and HRIS administration. Before that I was Talent Development Advisor in the HR/L&D team "
     "at Gallagher Bassett. I'm Associate CIPD with a CIPD-accredited MBA in HRM."),
    (r"employee relations|\ber\b|disciplinar|grievance|investigat|casework|case work",
     "Yes. At Chenai Holistic Home Care I manage investigations, disciplinaries and grievances end to end under the ACAS "
     "Code – gathering evidence, interviewing witnesses, writing investigation reports and advising managers on fair, "
     "proportionate outcomes."),
    (r"recruit|resourcing|talent acquisition|hiring|onboard",
     "Yes. I run end-to-end safer recruitment and onboarding at Chenai Holistic Home Care – adverts, screening, "
     "interviews, offers, Right to Work, DBS and reference checks and inductions – and ran consultant recruitment at "
     "Blackmont Consulting."),
    (r"learning|training|l&d|development|coach",
     "Yes. As Talent Development Advisor at Gallagher Bassett I coordinated L&D programmes and inductions across four "
     "countries, ran learning needs analyses, administered the LMS and coached employees on professional qualifications."),
    (r"hris|system|workday|database|data|excel|report",
     "Yes. I administer Access Evo (HRIS/LMS), have used Workday, HiBob and Teamtailor, build Excel/VBA and Python tools, "
     "and produce monthly HR reports for senior leadership. I also designed and built a complete HR system."),
    (r"absence|attendance|performance|capability",
     "Yes. I lead sickness absence management, return-to-work interviews and Performance Improvement Plans at Chenai "
     "Holistic Home Care, advising managers on next steps."),
    (r"customer|call|phone|email|high volume|queries|enquir",
     "Yes. At NatWest's Fraud Prevention Centre of Excellence I handled 50+ urgent cases and calls a day, and I've been a "
     "first point of contact for HR queries by phone, email and ticketing system at Gallagher Bassett and Chenai."),
    (r"care|health|social care|cqc|safeguard",
     "Yes. I work in HR for a CQC-regulated home care provider, running safer recruitment with Enhanced DBS checks, "
     "keeping staff files 100% compliant and handling safeguarding-related employee relations cases."),
    (r"employment law|legislation|acas",
     "Yes. I apply UK employment law and the ACAS Code of Practice every day in disciplinaries, grievances, absence, "
     "Right to Work and GDPR, and studied it in depth for my CIPD-accredited MBA."),
]


def experience_answer(question: str, kind: str = "text") -> str:
    from . import persona
    if not persona.builtin():
        if not EXPERIENCE_Q.search(question):
            return ""
        from . import generic
        return generic.experience_answer(question, kind)
    return _builtin_experience_answer(question, kind)


def _builtin_experience_answer(question: str, kind: str = "text") -> str:
    """A brief "Yes – …" with your real experience, for open "Do you have experience of …?" questions.
    Empty when nothing on your CV fits – those are left for you."""
    if not EXPERIENCE_Q.search(question):
        return ""
    q = question.lower()
    picks = [text for pattern, text in EXPERIENCE if re.search(pattern, q)]
    if not picks:
        return ""
    answer = picks[0]
    if kind == "textarea" and len(picks) > 1:
        answer += " " + picks[1].removeprefix("Yes. ")
    return answer


def competency_answer(label: str) -> str:
    """Your saved answer for a competency box such as "Leadership" or "Planning and organising" (My career)."""
    from .career import load
    words = " " + re.sub(r"[^a-z0-9 ]+", " ", label.lower()) + " "
    best, score = "", 0
    for c in load().get("competencies", []):
        terms = [c.get("name", "")] + (c.get("tags") or "").split(",")
        s = max((len(t.strip()) for t in terms
                 if t.strip() and " " + re.sub(r"[^a-z0-9 ]+", " ", t.strip().lower()) + " " in words), default=0)
        if s > score and c.get("answer"):
            best, score = c["answer"], s
    return best


def draft_answer(question: str, job: dict, profile: dict) -> str:
    """A first draft for common written questions, built from the advert and your CV (not AI). Always shown to you."""
    from .letters import short_answers
    q = question.lower()
    answers = dict(short_answers(job, profile))
    keys = list(answers)
    if re.search(r"why .*(us|company|organi[sz]ation|join|work (for|at|here))|interest(s|ed)? .*(in|about) (us|the company|"
                 + re.escape((job.get("company") or "zzzz").lower().split()[0]) + ")|what (interests|attracts|excites|appeals|draws)", q):
        return answers[keys[1]]
    if re.search(r"why .*(role|position|job|apply|applying)|motivat|interest(s|ed)? .*(role|position|job)", q):
        return answers[keys[0]]
    if re.search(r"tell us about|about yourself|relevant experience|summar|background|suitab|why should we|what (would|will|can) you bring", q):
        return answers[keys[2]]
    if re.search(r"cover letter|covering letter|supporting statement|personal statement", q):
        return job.get("cover_letter") or ""
    return ""


BEHAVIOURAL = re.compile(r"describe|an example|a time (when|where|you)|tell us about a|outline your experience|provide (an )?(example|details)|"
                         r"how did you|walk us through|give us|select (an|a) (example|role)|referring (back )?to your cv|"
                         r"your experience (of|in|with)|most (complex|challenging|difficult)", re.I)


def story_answer(question: str, job: dict) -> tuple[str, str, int]:
    """(answer, example title, fit) built from your best-matching example in My career – your real story, in STAR order."""
    from .advert import bullets, lower_first, yours
    from .career import load
    stories = [s for s in load().get("stories", []) if s.get("action") or s.get("situation")]
    if not stories:
        return "", "", 0
    words = " " + re.sub(r"[^a-z0-9& ]+", " ", question.lower()) + " "

    def fit(s):
        tags = [t.strip().lower() for t in (s.get("tags") or "").split(",") if t.strip()]
        score = sum(3 for t in tags if f" {t} " in words or (len(t) > 5 and t in words))
        score += sum(1 for w in re.findall(r"[a-z]{6,}", (s.get("title") or "").lower()) if w in words)
        return score

    from . import persona
    gap = next((g for g in GAPS if re.search(g[0], question, re.I)), None) if persona.builtin() else None
    preferred = [s for s in stories if gap and gap[2] and gap[2] in (s.get("tags") or "").lower()]
    best = max(preferred or stories, key=fit)
    score = fit(best)
    parts = [best.get(k, "").strip() for k in ("situation", "task", "action", "result")]
    if re.search(r"differently|lesson|learn|reflect", question, re.I) and best.get("learned"):
        learned = best["learned"].strip()
        parts.append(("Looking back, I would " + lower_first(learned)) if not re.match(r"(?i)^(i |looking back)", learned)
                     else learned)
    text = " ".join(p for p in parts if p)
    # Be straight about anything your CV doesn't show, then give the closest real experience.
    if gap:
        text = gap[1] + " " + text
    # Tie it to this employer: the advert duty closest to the example.
    tags = set(t.strip().lower() for t in (best.get("tags") or "").split(",") if t.strip())
    ranked = sorted(((sum(1 for t in tags if t in b.lower()), b) for k, b in bullets(job.get("description", ""))
                     if re.match(r"^[A-Z][a-z]+ ", b) and not re.match(r"^(Experience|Knowledge|Ability|Strong|Excellent|Professional)\b", b)),
                    reverse=True)
    if ranked and ranked[0][0] >= 2 and re.match(r"^[A-Z][a-z]+ ", ranked[0][1]) and job.get("company"):
        text += f" It's the approach I'd bring to {job['company']}, where you need someone to {yours(lower_first(ranked[0][1]))}."
    return text, best.get("title", ""), score


# Topics your CV doesn't cover: say so honestly, then use the closest real experience.
GAPS = [
    (r"restructur|redundanc|collective consultation|\btupe\b|business case",
     "I haven't yet led a formal restructure or collective consultation, though through my MBA and CIPD studies I "
     "understand the process – the business case, consultation, fair selection and managing the people risks – and I'd "
     "welcome the chance to apply it. The closest experience I have is leading organisational change.", "change"),
    (r"senior leader|executive|board|director",
     "My CV doesn't describe a specific disagreement with an executive, but advising and challenging managers is part of "
     "my day-to-day role.", ""),
]
