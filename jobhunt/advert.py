"""Reads what an advert actually asks for and matches it to facts from your CV.

No AI involved: it finds the duty and requirement bullet points in the advert, scores each against a
library of true statements from your CV, and returns the best pairs – so letters and answers talk about
what this employer wants, in your real experience.
"""
from __future__ import annotations

import re

# True statements from your CV, with the words in an advert that call for them.
FACTS = [
    ({"onboarding", "offer", "contract", "contracts", "right to work", "new starter", "induction", "hiring", "joiner",
      "pre-employment", "references", "dbs", "vetting"},
     "At Chenai I run recruitment and onboarding from start to finish – Right to Work, DBS and reference checks, "
     "inductions and mandatory training – and keep every staff file audit-ready."),
    ({"employee relations", "disciplinary", "grievance", "investigation", "acas", "employment law", "casework",
      "conduct", "capability", "tribunal", "legislation", "statutory"},
     "I manage investigations, disciplinaries and grievances end to end under ACAS guidance, so I apply UK "
     "employment law and policy every day."),
    ({"absence", "sickness", "performance", "return to work", "wellbeing", "leave", "attendance", "pip"},
     "I lead sickness absence management, return-to-work interviews and Performance Improvement Plans, advising "
     "managers on proportionate next steps."),
    ({"hris", "system", "systems", "rippling", "deel", "workday", "hibob", "bamboo", "data accuracy", "records",
      "employee data", "database", "sap", "successfactors", "itrent", "cezanne", "people hr"},
     "I administer Access Evo as our HRIS and LMS under GDPR, have worked with Workday HCM, HiBob and Teamtailor, "
     "and designed and built a complete HR system myself, so I pick up new HR platforms quickly."),
    ({"report", "reporting", "data", "analytics", "dashboard", "metrics", "kpi", "audit", "audits", "insight",
      "excel", "spreadsheet"},
     "I produce monthly leadership reports on vacancies, open cases and workforce risk, and built monthly L&D "
     "dashboards for leadership at Gallagher Bassett."),
    ({"international", "global", "eor", "employer of record", "countries", "time zones", "us-based", "emea",
      "multi-site", "multi-country", "cross-border", "overseas"},
     "At Gallagher Bassett I supported teams across the UK, US, New Zealand and India, so I'm used to working "
     "across countries and time zones."),
    ({"improve", "improvement", "improvements", "process", "processes", "automate", "automation", "efficiency",
      "workflow", "workflows", "streamline", "scale", "mature"},
     "In every recent role I've improved HR processes and automated manual admin with Excel/VBA and Python, "
     "cutting workload by 30–40%."),
    ({"learning", "training", "development", "l&d", "lms", "coaching", "mentoring", "talent", "programme",
      "programmes", "skills"},
     "At Gallagher Bassett I ran learning needs analyses with senior leaders, coordinated L&D programmes from "
     "scheduling to evaluation, and administered a global LMS with 100% data accuracy."),
    ({"recruitment", "recruiting", "candidates", "interviews", "vacancies", "sourcing", "talent acquisition",
      "hiring managers", "ats", "selection"},
     "I run safer recruitment through to onboarding at Chenai, ran consultant recruitment at Blackmont Consulting, "
     "and built a candidate pipeline tracker that keeps everyone up to date."),
    ({"autonomous", "autonomy", "independently", "self-starter", "own initiative", "from scratch",
      "start-up", "startup", "ownership", "self-motivated"},
     "As volunteer People Systems Lead at Global Social Innovators I designed and delivered a whole HR system "
     "on my own initiative, so I'm comfortable taking ownership and building things from scratch."),
    ({"policy", "policies", "compliance", "compliant", "regulatory", "regulation", "gdpr", "governance", "cqc"},
     "I keep 100% CQC audit compliance across staff files and handle personal data under UK GDPR."),
    ({"stakeholder", "stakeholders", "managers", "leaders", "advise", "advice", "partner", "collaborative",
      "collaborate", "escalate", "queries", "questions"},
     "I advise managers on HR matters day to day and work closely with leadership on people decisions."),
    ({"cipd", "qualified", "qualification", "degree", "hr qualification"},
     "I'm Associate CIPD, have an MBA in Human Resource Management & Development and am completing CIPD Level 7."),
]

DUTY_HEAD = re.compile(r"what you.?ll (do|be doing)|responsibilit|the role|your role|day[- ]to[- ]day|key duties|"
                       r"you will|in this role", re.I)
NEED_HEAD = re.compile(r"looking for|about you|requirement|you.?ll (have|bring|need)|skills|experience|who you are|"
                       r"essential|desirable|you have|ideal candidate|person specification", re.I)


def bullets(description: str) -> list[tuple[str, str]]:
    """[(kind, text)] – kind is 'duty' or 'need' – for the advert's bullet points (or short lines under a heading)."""
    out, kind = [], "need"
    for raw in (description or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        bare = re.sub(r"^[•\-\*·–▪◦●]\s*|^\d+[.)]\s*", "", line).strip()
        is_bullet = bare != line
        if not is_bullet and len(line) < 70 and not line.endswith("."):
            if DUTY_HEAD.search(line):
                kind = "duty"
            elif NEED_HEAD.search(line):
                kind = "need"
            continue
        if is_bullet and 25 <= len(bare) <= 260:
            out.append((kind, bare.rstrip(".;")))
    return out


def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9&]+", " ", text.lower()) + " "


def _facts():
    from . import persona
    if persona.builtin():
        return FACTS
    from . import generic
    return generic.facts()


def matches(description: str, limit: int = 3) -> list[tuple[str, str, str]]:
    """Best (kind, advert bullet, CV fact) pairs, each fact used once."""
    scored = []
    facts = _facts()
    for kind, b in bullets(description):
        w = _words(b)
        for i, (keys, fact) in enumerate(facts):
            hits = sum(1 for k in keys if f" {k} " in w)
            if hits:
                scored.append((hits + (0.5 if kind == "duty" else 0), i, kind, b, fact))
    scored.sort(key=lambda x: -x[0])
    used_f, used_b, out = set(), set(), []
    for _, i, kind, b, fact in scored:
        if i in used_f or b in used_b:
            continue
        used_f.add(i)
        used_b.add(b)
        out.append((kind, b, fact))
        if len(out) >= limit:
            break
    return out


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


def yours(text: str) -> str:
    """The advert speaks as 'we/our'; in your letter that becomes 'you/your'."""
    for a, b in ((r"\bour\b", "your"), (r"\bOur\b", "Your"), (r"\bwe\b", "you"), (r"\bWe\b", "You"), (r"\bus\b", "you")):
        text = re.sub(a, b, text)
    return text


def matched_paragraph(description: str, limit: int = 3) -> str:
    parts = []
    for n, (kind, b, fact) in enumerate(matches(description, limit)):
        if kind == "duty" and re.match(r"^[A-Z][a-z]+ ", b):
            lead = ("You need someone to ", "You also want someone to ", "And you need someone to ")[min(n, 2)]
        else:
            lead = ("You're looking for ", "You also want ", "And you're looking for ")[min(n, 2)]
        parts.append(f"{lead}{yours(lower_first(b))}. {fact}")
    return " ".join(parts)


def company_hook(description: str, company: str) -> str:
    """A short sentence from the advert about the company itself, to show you read it."""
    if not company:
        return ""
    name = re.escape(company.split()[0])
    for sentence in re.split(r"(?<=[.!?])\s+|\n", description or ""):
        s = sentence.strip()
        if 40 <= len(s) <= 220 and re.match(rf"^(at )?{name}\b|^we('re| are)\b|^our (mission|purpose)", s, re.I) and \
                not re.search(r"equal opportunit|discriminat|cookie|privacy|salary|benefits", s, re.I):
            return s.rstrip(".")
    return ""


def talking_points(description: str, limit: int = 4) -> list[str]:
    """Facts from your CV that answer this advert – prompts for questions you write yourself."""
    return [fact for _, _, fact in matches(description, limit)]
