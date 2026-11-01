"""Cover letters tailored to each advert.

By default letters are assembled from evidence paragraphs taken from your CV, picking the
ones that best match the advert (free, works offline). If an Anthropic API key is set in
config.yaml, Claude writes the letter instead, using your CV and the advert.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import requests

from .matcher import SKILLS

# Evidence paragraphs from the CV, tagged with the skill groups they prove.
EVIDENCE = [
    ({"employee relations", "absence & performance"},
     "As HR & Recruitment Officer at Chenai Holistic Home Care, a CQC-regulated provider, I manage employee "
     "relations from start to finish: investigations, disciplinaries and grievances under ACAS guidance, "
     "gathering evidence, interviewing and writing investigation reports. I also lead sickness absence "
     "management, return-to-work interviews and Performance Improvement Plans, advising managers on "
     "proportionate next steps."),
    ({"recruitment & onboarding", "compliance & GDPR"},
     "I run safer recruitment end to end – Enhanced DBS, Right to Work and reference checks – and maintain "
     "100% CQC audit compliance across staff files, alongside onboarding and mandatory induction tracking."),
    ({"HR systems", "automation & tech"},
     "HR systems are a particular strength. I administer Access Evo (HRIS and LMS) under GDPR, have worked "
     "with Workday HCM, HiBob and Teamtailor, and as volunteer People Systems Lead at Global Social "
     "Innovators I designed and built GSI HRIS – a complete HR system in Python with an ATS, onboarding, "
     "rota, LMS, pulse surveys, messaging and live dashboards on a 45-table SQL database, with role-based "
     "access and audit logging."),
    ({"data & reporting", "automation & tech"},
     "I turn people data into decisions. I produce monthly leadership metrics on vacancies, open cases and "
     "workforce risk, built monthly L&D dashboards for leadership at Gallagher Bassett, and have automated "
     "manual HR admin in every recent role with Excel/VBA and Python tools, cutting workload by 30–40%."),
    ({"L&D & coaching"},
     "At Gallagher Bassett I administered a global LMS with 100% data accuracy across UK, US, New Zealand "
     "and India teams, ran learning needs analyses with senior leaders, coordinated L&D programmes from "
     "scheduling and levy compliance to evaluation, and coached colleagues one to one on career pathways "
     "and professional qualifications (CIPD, CII)."),
    ({"L&D & coaching", "recruitment & onboarding"},
     "As an Employment Advisor at Reed in Partnership I delivered structured one-to-one coaching – "
     "personalised action plans, CV reviews and mock interviews – helping people from a wide range of "
     "backgrounds into work."),
]

CLOSING = ("I am Associate CIPD with an MBA in Human Resource Management & Development, and I am completing "
           "the CIPD Level 7 Advanced Diploma in Strategic Learning & Development. I am available to start "
           "immediately and would welcome the chance to discuss how I could contribute to {company}.")


# How each skill group reads in a sentence, in order of priority.
FOCUS_WORDS = {
    "employee relations": "employee relations",
    "recruitment & onboarding": "recruitment and onboarding",
    "absence & performance": "absence and performance management",
    "HR systems": "HR systems",
    "data & reporting": "people data and reporting",
    "L&D & coaching": "learning and development",
    "compliance & GDPR": "compliance",
}


def _skills_in(text: str) -> list[str]:
    return [name for name, pat in SKILLS.items() if re.search(pat, text or "", re.I)]


def template_letter(job: dict, profile: dict) -> str:
    from . import persona
    if not persona.builtin():
        from . import generic
        return generic.letter(job, profile)
    company = job.get("company") or "your organisation"
    role = job.get("title") or "this role"
    wanted = set(_skills_in(job.get("description", "")))
    ranked = sorted(EVIDENCE, key=lambda e: len(e[0] & wanted), reverse=True)
    chosen = [p for tags, p in ranked[:3]]
    # Keep the original CV order so the letter reads naturally.
    chosen.sort(key=lambda p: [e[1] for e in EVIDENCE].index(p))
    plain = [FOCUS_WORDS[s] for s in FOCUS_WORDS if s in wanted][:3]
    if len(plain) >= 2:
        focus = ", ".join(plain[:-1]) + " and " + plain[-1]
    else:
        focus = plain[0] if plain else "HR operations and supporting people"
    opening = (f"I am applying for the {role} role at {company}. The role's focus on {focus} matches "
               f"my experience closely, and I would welcome the opportunity to bring it to your team.")
    from .advert import company_hook, matched_paragraph
    desc = job.get("description", "")
    hook = company_hook(desc, job.get("company") or "")
    if hook:
        opening += f" Your advert says: “{hook}” – that is exactly the kind of environment I want to contribute to."
    matched = matched_paragraph(desc, 3)
    if matched:
        # Answer what this advert asks for first, then one broader paragraph from the CV that says something new.
        words = set(re.findall(r"[a-z]{5,}", matched.lower()))
        extra = next((p for _, p in ranked if len(set(re.findall(r"[a-z]{5,}", p.lower())) & words) <
                      0.2 * len(set(re.findall(r"[a-z]{5,}", p.lower())))), chosen[0])
        chosen = [matched, extra]
    name = profile.get("name", "")
    parts = ["Dear Hiring Manager,", opening, *chosen, CLOSING.format(company=company),
             "Yours sincerely,", name]
    return "\n\n".join(parts)


def ai_letter(job: dict, profile: dict, cv_text: str, api_key: str, model: str) -> str:
    prompt = (
        "Write a cover letter in UK English for the job below, using only facts from the CV. "
        "Do not invent experience, numbers or tools. 300–380 words, warm and professional, "
        "no headings or bullet points. Start with 'Dear Hiring Manager,' and end with "
        f"'Yours sincerely,' then '{profile.get('name', '')}'. Mention availability: "
        f"{profile.get('notice_period', 'available immediately')}.\n\n"
        f"JOB TITLE: {job.get('title')}\nCOMPANY: {job.get('company')}\nLOCATION: {job.get('location')}\n"
        f"ADVERT:\n{(job.get('description') or '')[:6000]}\n\nCV:\n{cv_text[:12000]}"
    )
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 1200, "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    resp.raise_for_status()
    return "".join(b.get("text", "") for b in resp.json().get("content", [])).strip()


def write_letter(job: dict, profile: dict, cv_text: str = "", ai_cfg: dict | None = None) -> tuple[str, str]:
    """Returns (letter_text, method)."""
    ai_cfg = ai_cfg or {}
    if ai_cfg.get("anthropic_api_key") and cv_text:
        try:
            return ai_letter(job, profile, cv_text, ai_cfg["anthropic_api_key"],
                             ai_cfg.get("model", "claude-haiku-5-5")), "Claude"
        except Exception:  # fall back to the free writer
            pass
    return template_letter(job, profile), "Built-in"


SKILL_PHRASES = {
    "employee relations": "managing employee relations casework end to end under ACAS guidance",
    "absence & performance": "absence management, return-to-work interviews and Performance Improvement Plans",
    "recruitment & onboarding": "safer recruitment and onboarding with 100% CQC audit compliance",
    "HR systems": "administering and building HR systems (Access Evo, Workday, HiBob, and my own HRIS)",
    "data & reporting": "turning people data into monthly leadership reports and dashboards",
    "L&D & coaching": "coordinating L&D programmes, learning needs analysis and one-to-one coaching",
    "compliance & GDPR": "keeping HR records accurate, audit-ready and GDPR-compliant",
    "automation & tech": "automating HR admin with Excel/VBA and Python, cutting workload by 30–40%",
    "CIPD": "applying CIPD best practice as an Associate CIPD member",
}


def short_answers(job: dict, profile: dict) -> list[tuple[str, str]]:
    """Ready-to-paste answers to the questions most application forms ask. Read and personalise them."""
    from . import persona
    if not persona.builtin():
        from . import generic
        return generic.short_answers(job, profile)
    company = job.get("company") or "your organisation"
    role = job.get("title") or "this role"
    wanted = _skills_in(job.get("description", "")) or ["employee relations", "recruitment & onboarding",
                                                        "HR systems", "data & reporting"]
    top = [SKILL_PHRASES[s] for s in wanted if s in SKILL_PHRASES][:3]
    skills_line = "; ".join(top)
    from .advert import company_hook, matches
    desc = job.get("description", "")
    hook = company_hook(desc, job.get("company") or "")
    from .advert import yours
    pairs = matches(desc, 2)
    asked = yours(pairs[0][1][0].lower() + pairs[0][1][1:]) if pairs else ""
    facts = " ".join(f for _, _, f in pairs)
    return [
        (f"Why do you want this role?",
         (f"You're looking for someone to {asked} – that's the work I do best. {facts} " if asked else
          f"The {role} role brings together the work I enjoy most and do well: {skills_line}. ") +
         f"I'm Associate CIPD, completing CIPD Level 7, and I'm looking for a role where I can take ownership, "
         f"improve how things work and support people properly. This role offers exactly that, and I'm "
         f"available to start immediately."),
        (f"Why do you want to work for {company}?",
         (f"Your advert says “{hook}”, and I'd like to be part of that. " if hook else
          f"[Add one specific thing about {company} – its mission, sector or values.] ") +
         f"I want to join an organisation that values its people and gives HR the chance to make a real "
         f"difference, and I believe I can add value to {company} from day one."),
        ("Summary of relevant experience",
         "I'm an HR & Recruitment Officer at a CQC-regulated care provider, where I manage employee relations "
         "end to end, lead absence and performance processes, run safer recruitment and onboarding, and "
         "administer our HRIS and LMS. Previously, as Talent Development Advisor at Gallagher Bassett, I "
         "administered a global LMS with 100% data accuracy, ran learning needs analyses and produced L&D "
         "dashboards for leadership. I also designed and built a complete HR system (ATS, onboarding, LMS, "
         "dashboards) in Python for a social enterprise, and I automate HR admin wherever I can."),
        ("Key skills",
         "\n".join(f"• {SKILL_PHRASES[s][0].upper() + SKILL_PHRASES[s][1:]}" for s in wanted if s in SKILL_PHRASES)),
        ("Qualifications",
         "Associate CIPD; CIPD Level 7 Advanced Diploma in Strategic Learning & Development (in progress); "
         "MBA Human Resource Management & Development (Middlesex University); BA (Hons) Business Management "
         "& Finance (Middlesex University)."),
    ]


def letter_pdf(letter: str, profile: dict) -> bytes:
    """The cover letter as a one-page PDF (for upload boxes)."""
    from io import BytesIO
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    name = ParagraphStyle("n", fontName="Helvetica-Bold", fontSize=16, leading=20)
    small = ParagraphStyle("s", fontName="Helvetica", fontSize=9.5, leading=13, textColor="#444444")
    body = ParagraphStyle("b", fontName="Helvetica", fontSize=10.5, leading=14.5, spaceAfter=8)
    today = date.today()
    contact = " · ".join(escape(x) for x in [profile.get("address"), profile.get("phone"), profile.get("email")] if x)
    story = [Paragraph(escape(profile.get("name", "")), name), Paragraph(contact, small), Spacer(1, 9 * mm),
             Paragraph(f"{today.day} {today:%B %Y}", body)]
    for para in letter.split("\n\n"):
        para = para.strip()
        if para:
            story.append(Paragraph("<br/>".join(escape(l) for l in para.splitlines()), body))
    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm,
                      bottomMargin=18 * mm, title="Cover letter", author=profile.get("name", "")).build(story)
    return buf.getvalue()


def form_message(job: dict, profile: dict) -> str:
    """A short note for 'Message' boxes on application forms."""
    from . import persona
    if not persona.builtin():
        from . import generic
        return generic.form_message(job, profile)
    return (f"Dear Hiring Team,\n\nPlease find attached my CV and cover letter for the {job.get('title') or 'role'} "
            f"position at {job.get('company') or 'your organisation'}. I am Associate CIPD with experience across "
            f"employee relations, recruitment, HR systems and people data, and I am {(profile.get('notice_period') or 'available immediately').lower()}. "
            f"I would welcome the opportunity to discuss my application.\n\nKind regards,\n{profile.get('name', '')}")


def safe_filename(text: str) -> str:
    return re.sub(r"[^\w\s&()-]", "", text).strip()[:80]


def save_docx(letter: str, job: dict, profile: dict, folder: str | Path, filename: str | None = None) -> Path:
    from docx import Document
    from docx.shared import Pt

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    head = doc.add_paragraph()
    run = head.add_run(profile.get("name", ""))
    run.bold = True
    run.font.size = Pt(16)
    doc.add_paragraph(" · ".join(x for x in [profile.get("address"), profile.get("phone"),
                                               profile.get("email")] if x))
    today = date.today()
    doc.add_paragraph(f"{today.day} {today:%B %Y}")  # %-d isn't supported on Windows
    for para in letter.split("\n\n"):
        doc.add_paragraph(para.strip())
    name = filename or f"{profile.get('name', 'Cover')} Cover Letter - {safe_filename(job.get('company') or job.get('title', 'Job'))}.docx"
    path = folder / name
    doc.save(path)
    return path
