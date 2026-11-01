"""Sorts recruitment emails into categories and matches them to applications. Rule-based, no AI."""
from __future__ import annotations

import re

RULES = [
    # A real offer names the job: "offer you the position", "offer of employment", "make you an offer".
    # Plain "job offer(s)" is left out – career coaches, forums and surveys say it all the time.
    ("offer", r"offer (?:you )?(?:the |a |this |our )?(?:position|role|job|post)\b|offer of employment|"
              r"conditional offer of|formal offer of|verbal offer of|your offer letter|offer letter (?:is )?attached|"
              r"your application (?:has been|was) successful\b|you(?:'ve| have) been successful in your application|"
              r"(?:pleased|delighted|happy|thrilled|excited) to (?:make|extend) (?:you )?(?:an |a |the )?(?:formal |"
              r"conditional |verbal )?offer"),
    ("withdrawn", r"withdraw(?:al)? of (?:your |my )?application|(?:proceed to |will )withdraw your application|"
                  r"(?:your |the )?application (?:has been |is now |was )withdrawn|withdrawn your application"),
    ("rejected", r"unfortunately|not been successful|unsuccessful|not (be )?progress|"
                 r"decided (not )?to (move|proceed) forward with other|other candidates|regret to inform|"
                 r"position has (now )?been filled|not been shortlisted|will not be taking your application|"
                 r"decided not to proceed|not (to )?(move|moving) forward with your|won'?t be (moving|taking) (forward|your)|"
                 r"will not be (moving|taking) (forward|your)|pursue other (candidates|applicants)|not been selected|"
                 r"unable to offer you|not able to offer you|no longer (being )?considered"),
    ("second_stage", r"second(.stage|.round)? interview|2nd(.stage|.round)? interview|final(.stage|.round)? interview|"
                     r"(second|2nd|final) (stage|round) of (the )?(interview|recruitment|selection|process)|"
                     r"(invite|invited|inviting|progress|progressed|progressing|through|move|moved|moving) (you )?"
                     r"(on )?(through )?to the (next|second|2nd|final) (stage|round)"),
    ("interview", r"invit\w* (you )?(to|for) (an |a |the )?(face.to.face |in.person |video |teams |final |second |first )?interview|"
                  r"interview invitation|(book|schedule|arrange) (an |your |a )?interview|interview slot|"
                  r"like to (meet|interview) you|shortlisted for (an )?interview|confirm (your|the) interview|"
                  r"your interview (is|has been|will be) (scheduled|booked|confirmed|arranged|held)|"
                  r"interview (confirmation|details|reminder)|invitation to (an |a )?interview"),
    ("assessment", r"assessment centre|online (test|assessment)|psychometric|case study|skills test|"
                   r"complete (an |the |a )?(assessment|task)|video (interview|assessment) via|hirevue|"
                   r"one.way video"),
    ("pre_screen", r"phone screen|screening call|pre.?screen|initial (call|chat|conversation)|"
                   r"introductory (call|chat)|quick (call|chat)|telephone interview|phone interview|"
                   r"short call|availability for a call"),
    ("applied", r"we('ve| have) sent your application|application sent by|copy of application to|"
                r"thank(s| you) for sending (us )?your cv|your cv has been sent"),
    ("acknowledged", r"thank(s| you) for (your )?appl|received your application|application (has been )?"
                     r"(received|submitted)|successfully (applied|submitted)|we('ve| have) got your application|"
                     r"thank(s| you) for your (recent )?application|received your cv|thank(s| you) for (submitting|sending) your application|"
                     r"confirm(ing)? (that )?"
                     r"(we have|we've) received"),
]

# Emails that mention applications but aren't one (sites, accounts, adverts).
NOT_AN_APPLICATION = re.compile(r"uploading your cv|creat(e|ing|ed) (an |your )?account|password|verify your email|"
                                r"complete (the|your) application for|job alert|newsletter|recommended jobs|"
                                r"jobs (for|near) you|new jobs|don'?t forget to apply|valuemycv|"
                                r"to continue your (job )?application|finish your application|incomplete application|"
                                r"complete your application|webinar|replay|masterclass|\blive\b|bonus|survey|"
                                r"the cipd update|unsubscribe from (these|our) (emails|updates)|\btips\b|"
                                r"\bcourse\b|free (guide|training|class)", re.I)

LINKEDIN_ALERT_SENDERS = ("jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com", "jobs-listings@linkedin.com")
INDEED_ALERT_SENDERS = ("alert@indeed.com", "alerts@indeed.com", "donotreply@match.indeed.com",
                        "jobalerts@indeed.com", "noreply@indeed.com")
ALERT_SENDERS = LINKEDIN_ALERT_SENDERS + INDEED_ALERT_SENDERS

STOP = {"ltd", "limited", "plc", "llp", "group", "the", "uk", "inc", "co", "and", "&", "of", "trust",
        "nhs", "foundation", "university", "london", "hr", "people", "careers", "recruitment", "team",
        "hiring", "talent", "no-reply", "noreply", "mail", "email", "ftc", "month", "months", "position", "role",
        "contract", "temporary", "permanent", "com", "net", "org", "notifications", "system", "jobs", "job",
        "for", "with", "from", "your", "you", "our", "application", "applications", "applying", "applied", "thank",
        "thanks", "update", "new", "dear", "rashid", "idle", "re", "fw", "fwd", "via", "about", "into", "this", "that",
        "learning", "content", "designer", "transformation", "acquisition", "specialist", "coordinator", "co-ordinator",
        "manager", "officer", "advisor", "adviser", "assistant", "administrator", "admin", "partner", "director",
        "operations", "human", "resources", "resource", "senior", "junior", "lead", "head", "associate", "executive",
        "development", "training", "business", "generalist", "analyst", "consultant", "coordinator", "support",
        "services", "service", "interim", "fixed", "term", "ftc", "part", "full", "time", "remote", "hybrid",
        "workday", "hcm", "icims", "autoreply", "recruiting", "candidate", "candidates", "applicant", "your", "here"}


MARKETING_SENDERS = re.compile(r"selfmadeway|glassdoor|convertkit|foundit|monster|community@|newsletters?|"
                               r"newsletters-noreply@linkedin|news@|@news\.|marketing|mailer|digest|substack|medium\.com|"
                               r"eventbrite|@e\.|e\.targetjobs|emails@efinancial|candidatesuccess|invitations@linkedin|"
                               r"messaging-digest|editors?@|insights?@|events?@|webinars?@|academy@|learn@", re.I)
MARKETING_SUBJECT = re.compile(r"\blive\b|masterclass|webinar|replay|\bbonus\b|% off|black friday|deal ends|class access|"
                               r"access expir|last chance|course|steal my|\bclass\b|sunsetting|podcast|newsletter|"
                               r"(top|latest) (news|insights)|beware of fake|counter.?offers?|salary guide|"
                               r"how to (ace|land|get)|\btips?\b|strateg(y|ies)", re.I)


def is_marketing(subject: str, sender: str) -> bool:
    """Career coaches, forums, newsletters and courses – they talk about interviews and offers but aren't yours."""
    return bool(MARKETING_SENDERS.search(sender or "") or MARKETING_SUBJECT.search(subject or ""))


def classify(subject: str, body: str, sender: str = "") -> str:
    if any(s in (sender or "").lower() for s in ALERT_SENDERS):
        return "job_alert"
    if is_marketing(subject, sender):
        return "other"
    if re.search(r"(here'?s|here is) a copy of your application|copy of your application data", body or "", re.I):
        return "acknowledged"     # Workable etc. send back your own answers – they can mention anything
    if re.search(r"your application (for .{2,80} )?(has been|was) sent|application (has been |was )?sent to", subject or "", re.I):
        return "applied"
    text = f"{subject}\n{(body or '')[:3000]}".lower().replace("’", "'").replace("‘", "'")
    # "we are not able to offer you a position" is a rejection, and a blank template ("the position of with") isn't an offer
    no_offer = re.search(r"(unable|not able|cannot|can't|won't be able|not be able|not in a position|regret(?:fully)?)"
                         r"[^.]{0,30}\boffer|position of (with|,|\.)", text)
    # A rejection often says "thank you for applying" too, so order matters.
    for category, pattern in RULES:
        if category == "offer" and no_offer:
            continue
        if re.search(pattern, text):
            return category
    return "other"


def _tokens(name: str) -> set[str]:
    words = re.findall(r"[^\W_]+", (name or "").lower())
    return {w for w in words if w not in STOP and len(w) > 2}


# Everyday business words: sharing one of these isn't enough to say an email is about an employer.
COMMON = {"apply", "pack", "digital", "solutions", "services", "global", "international", "business", "partners",
          "partnership", "consulting", "consultants", "resourcing", "search", "select", "first", "group", "holdings",
          "hotel", "hotels", "house", "housing", "care", "health", "healthcare", "energy", "media", "capital", "water",
          "light", "systems", "technology", "technologies", "tech", "labs", "studio", "studios", "network", "direct",
          "general", "national", "british", "united", "london", "city", "council", "college", "school", "academy",
          "insurance", "bank", "finance", "financial", "property", "properties", "retail", "foods", "food", "logistics",
          "engineering", "construction", "management", "associates", "agency", "online", "community", "company",
          "trading", "brands", "beauty", "fashion", "home", "homes", "new", "one", "plus", "pro", "smart", "life",
          "impact", "connect", "connected", "point", "place", "works", "world", "service", "support", "advisor",
          "employment", "personnel", "staffing", "jobs", "careers", "update", "application", "indeed"}


def generic_only(tokens) -> bool:
    return bool(tokens) and all(t in COMMON for t in tokens)


# Job boards and mail services: their name in the sender says nothing about the employer.
PLATFORM_SENDER = re.compile(r"reed\.co\.uk|indeed\.|totaljobs|cv-?library|adzuna|linkedin\.com|broadbean|idibu|jobsite|"
                             r"glassdoor|monster|guardianjobs|charityjob|welcometothejungle|otta\.com|jobserve|"
                             r"workablemail|ashbyhq|greenhouse|smartrecruiters|myworkday|successfactors|icims|lever\.co|"
                             r"tal\.net|teamtailor|pinpoint|occupop|comeet|people-first|connectats|hibob|deel\.com", re.I)


def match_application(subject: str, body: str, sender: str, applications: list[dict]) -> dict | None:
    """Best application for an email: company name in sender, subject or body."""
    if PLATFORM_SENDER.search(sender or ""):
        m = re.match(r'\s*"?([^"<]*?)"?\s*<', sender or "")
        name = m.group(1) if m else ""
        sender = "" if (not name or PLATFORM_SENDER.search(name.replace(" ", "") + ".") or
                        re.search(r"reed|indeed|workday|workable|no.?reply|ashby|greenhouse", name, re.I)) else name
    hay_strong = f"{sender} {subject}".lower()
    hay_body = (body or "")[:3000].lower()
    if PLATFORM_SENDER.search(sender_addr := (sender or "")) or not sender:
        # the job board's own name in its footer and links isn't the employer
        hay_body = re.sub(r"reed(?:\.co\.uk)?|indeed(?:\.com)?|totaljobs|cv-?library|adzuna|linkedin|workable|ashby|"
                          r"greenhouse|smartrecruiters|workday|icims|broadbean", " ", hay_body)
    best, best_score = None, 0
    for app in applications:
        toks = _tokens(app["company"])
        if not toks:
            continue
        hit_strong = [t for t in toks if re.search(rf"\b{re.escape(t)}\b", hay_strong)]
        strong = len(hit_strong)
        weak = sum(1 for t in toks if re.search(rf"\b{re.escape(t)}\b", hay_body))
        if len(toks) > 1 and generic_only(hit_strong) and strong < len(toks):
            strong = 0                     # "Indeed Apply" is not "Apply Digital"
        joined = "".join(w for w in re.findall(r"[a-z0-9]+", app["company"].lower()) if w not in ("ltd", "limited", "plc", "uk", "the"))
        in_address = len(joined) > 4 and joined in hay_strong.replace("-", "").replace(" ", "")
        if generic_only(toks) and not in_address:
            continue
        if not strong and in_address:          # "Quilombo UK" ↔ hr@quilombouk.com
            strong = len(toks)
        role_hit = 1 if app.get("role") and app["role"].lower() in f"{hay_strong} {hay_body}" else 0
        if strong:                      # company named in sender or subject
            score = strong * 3 + weak + role_hit * 2
        elif weak == len(toks):         # full company name in the body
            score = 2 + role_hit * 2
        else:
            score = 0
        if score > best_score:
            best, best_score = app, score
    return best if best_score >= 2 else None


DATE_PAT = re.compile(
    r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+\d{1,2}(st|nd|rd|th)?\s+[a-z]+(\s+\d{4})?"
    r"(\s+at\s+\d{1,2}([:.]\d{2})?\s*(am|pm)?)?|\b\d{1,2}/\d{1,2}/\d{2,4}(\s+at\s+\d{1,2}[:.]\d{2})?",
    re.I)


def find_date(text: str) -> str | None:
    m = DATE_PAT.search(text or "")
    return m.group(0).strip() if m else None


ALERT_LINKS = {
    "LinkedIn": (re.compile(r"https://(?:[a-z]+\.)?linkedin\.com/(?:comm/)?jobs/view/(\d+)"),
                 "https://www.linkedin.com/jobs/view/{}/"),
    "Indeed": (re.compile(r"https://(?:[a-z]+\.)?indeed\.com/[^\s\"'>]*?[?&](?:jk|vjk)=([0-9a-f]{16})"),
               "https://uk.indeed.com/viewjob?jk={}"),
}
_SKIP_LINE = ("view job", "http", "-", "apply", "easily apply", "new", "just posted", "£", "salary",
              "responsive employer", "urgently hiring", "see all", "posted")


def parse_alert(text: str, site: str) -> list[dict]:
    """Jobs from a LinkedIn or Indeed job-alert email (plain-text part).
    Each job is a link with its title, company and location on the lines just above it."""
    pattern, url_fmt = ALERT_LINKS[site]
    jobs = []
    lines = [l.strip() for l in (text or "").splitlines()]
    for i, line in enumerate(lines):
        m = pattern.search(line)
        if not m or any(j["external_id"] == m.group(1) for j in jobs):
            continue
        before = []
        for l in reversed(lines[max(0, i - 8):i]):
            if not l:
                if before:
                    break      # stop at the blank line above this job's block
                continue
            if l.lower().startswith(_SKIP_LINE) or pattern.search(l):
                continue
            before.insert(0, l)
        if len(before) < 2:
            continue
        block = before[-3:]
        title, company = block[0], block[1]
        location = block[2] if len(block) >= 3 else ""
        jobs.append({"external_id": m.group(1), "title": title, "company": company, "location": location,
                     "url": url_fmt.format(m.group(1))})
    return jobs


def parse_linkedin_alert(text: str) -> list[dict]:
    return parse_alert(text, "LinkedIn")


def alert_site(sender: str) -> str | None:
    s = (sender or "").lower()
    if any(a in s for a in LINKEDIN_ALERT_SENDERS):
        return "LinkedIn"
    if any(a in s for a in INDEED_ALERT_SENDERS):
        return "Indeed"
    return None


# ---------------------------------------------------------------- role and employer from an email
_GENERIC = re.compile(r"no.?reply|do.?not.?reply|\bsystem\b|notification|\balerts?\b|recruit(ing|ment)?\b|hiring|"
                      r"talent|careers?|\bjobs?\b|applications?|candidates?|workable|ashby|greenhouse|lever|"
                      r"smartrecruiters|successfactors|hibob|\bbob\b|broadbean|\breed\b|adzuna|indeed|linkedin|"
                      r"totaljobs|cv.?library|tal\.net|teamtailor|deel|workday|icims|jobvite|pinpoint|eploy|"
                      r"\bhr\b|people team|\bteam\b|^info$|^admin$|portal|support|jobadder|idibu|tribepad|applytojob|"
                      r"hirehive|recruitee|personio|bamboohr|myworkday|oleeo|stonefish|jobtrain|networx|kallidus", re.I)
_PERSON_WORDS = re.compile(r"\b(ltd|limited|group|plc|llp|partners?(hip)?|consult\w*|services|solutions|hotels?|"
                           r"resorts?|insurance|housing|care|health\w*|bank|university|college|council|trust|nhs|"
                           r"agency|international|global|hospitality|uk|london|media|capital|energy|tech\w*|labs?|"
                           r"foundation|association|school|academy|clinic|resourcing|recruitment|engineering)\b", re.I)
_ROLE = [
    r'copy of application to "(?P<role>[^"]{3,80})"',
    r"^indeed application:\s*(?P<role>.{3,80})$",
    r"we have your (?P<role>[^.\n|!]{3,60}?) application",
    r"your application for (?:the )?(?P<role>[^.\n|]{3,80}?)(?: \(\d+\))? (?:with|at|-|–) (?P<company>[^.\n|(]{2,60})",
    r"(?:for|of) the (?:role|position|post|vacancy) of (?P<role>[^.\n,|!]{3,80})",
    r"(?:applying|applied|apply|application|interview|interest|cv) (?:for|in) (?:the |our |a |an |this )?(?P<role>[^.\n|!,]{3,80}?)\s+(?:role|position|post|vacancy|job|opportunity)\b",
    r"(?:role|position|post) of (?P<role>[^.\n,|!]{3,80})",
    r"thank you for applying\s*[-–:]\s*(?P<role>[^|\n]{3,80})",
    r"job application for (?P<role>[^.\n|]{3,80}?)(?: - | – |\s*$)",
    r"application for (?P<role>[^.\n|!]{3,80}?)(?: with | at | - | – |\s*$)",
    r"applied for (?:the )?(?P<role>[^.\n|!,]{3,60}?)(?: at | with |[.!]|$)",
    r"(?:position|role|post|job) as (?:a |an |the )?\*?(?P<role>[^*.\n|!,]{3,80}?)\*?(?: at | with |[.!,]|$)",
    r"(?:application|applying|interview)\s*[-–:]\s*(?P<role>[^|\n–-]{3,80}?)\s*(?:[-–]|$)",
]
_COMPANY = [
    r"sent your application to (?P<company>[^.\n|!]{2,60})",
    r"items were sent to (?P<company>[^.\n|!]{2,60}?)(?:[.!]| please| you |$)",
    r"job opportunity\s*-\s*(?:from )?(?P<company>[^.\n|!]{2,60}?)(?: (?:job application|application|an update|your|thanks?|re:)\b|$)",
    r"thanks? (?:you )?for applying to (?P<company>[^.\n|!]{2,60})",
    r"your application (?:at|to|with) (?P<company>[^.\n|!]{2,60})",
    r"(?:role|position|post|vacancy|opportunity) (?:at|with) (?P<company>(?-i:[A-Z])[^.\n|!,]{1,60}?)(?:[.!,]| and | we |$)",
    r"(?:interest in|interested in) joining (?P<company>(?-i:[A-Z])[^.\n|!,]{1,50}?)(?:[.!,]| and | team|$)",
    r"(?:joining|join) (?:the )?(?P<company>(?-i:[A-Z])[\w&'’ .-]{1,50}?)(?: team| family|[.!,]|$)",
    r"application (?:from|at|with) (?P<company>(?-i:[A-Z])[^.\n|!,]{1,60})",
    r"working (?:at|for|with) (?:us at )?(?P<company>(?-i:[A-Z])[^.\n|!,]{1,50}?)(?:[.!,]| and |$)",
    r"(?:interest in|interested in) (?P<company>(?-i:[A-Z])[\w&'’.-]+(?: (?-i:[A-Z])[\w&'’.-]+){0,3})(?: and|[!.,])",
    r"\bat the (?P<company>(?-i:[A-Z])[\w&'’ -]{3,60}?)(?: \(|[.!,]|$)",
]
_BAD_ROLE = re.compile(r"^(the|your|our|a|an|this|that|you|us|it|position|role|job|application|cv)\b|"
                       r"\b(we|you|your|our|us|please|thank|regards|dear|applying|applied|interest|application)\b|"
                       r"\b(the|to|and|of|a|an)$|\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
                       r"\b\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\b\d{1,2}[:.]\d{2}\b", re.I)


def _tidy(t: str) -> str:
    t = re.sub(r"&amp;", "&", t or "")
    t = re.sub(r"&nbsp;|\u00a0|\u200c", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–:|\"'“”‘’.,!")
    return t


def _clean_role(r: str) -> str:
    r = re.sub(r"\((?:ref|id|job ref|req|reference)[^)]*\)|\(\d{5,}\)|\s+(?:ls|ref|req|id)[-: ]?[a-z]*\d[\w-]*$", "", r, flags=re.I)
    r = re.sub(r"\s+[-–]\s+(?:r|ref|req)\d*$|\s+(?:role|position|post|vacancy|job|opportunity)$", "", r, flags=re.I)
    r = re.sub(r"\s+at\s+(?:the\s+)?(?-i:[A-Z]).*$", "", r)
    r = re.sub(r"\s+[-–]\s+\d+\s*(m|months?)\b.*$", "", r, flags=re.I)
    r = re.sub(r"\s+(has been|was|is) (sent|received|submitted|successful|unsuccessful|reviewed).*$", "", r, flags=re.I)
    r = re.sub(r"\s+(which|that|and we|we|i can|has|have)\b.*$", "", r, flags=re.I)
    r = re.sub(r"(?<=[a-z])(position|role|vacancy)$", "", r)        # "Specialistposition"
    return _tidy(r)


def _dedupe_words(c: str) -> str:
    out = []
    for w in c.split():                     # "Oakleaf Partnership Oakleaf", "Handle Recruitment Handle"
        if w.lower() not in (x.lower() for x in out):
            out.append(w)
    return " ".join(out)


_NOT_COMPANY = re.compile(r"\b(ftc|months?|position|contract|vacancy|temporary|permanent|fixed.term|part.time|full.time|"
                          r"hybrid|remote|role|job|application|opportunit\w*)\b|^(uk|london|england|united kingdom|"
                          r"the uk|team|us|you)$", re.I)


def _good_company(c: str) -> bool:
    if _NOT_COMPANY.search(c or ""):
        return False
    words = [w for w in re.split(r"\s+", c) if w]
    if not words or len(words) > 7 or not (2 <= len(c) <= 60) or re.search(r"[’']s\b|\d{4,}|/|,", c):
        return False
    caps = sum(1 for w in words if w[:1].isupper() or w[:1].isdigit() or w in ("&", "and", "of", "the", "for"))
    return caps / len(words) >= 0.75 and not _BAD_ROLE.search(c) and not _GENERIC.fullmatch(c)


def _sender_name(sender: str) -> tuple[str, str]:
    m = re.match(r'\s*"?([^"<]*?)"?\s*<([^>]+)>', sender or "")
    name, addr = (m.group(1), m.group(2)) if m else ("", (sender or "").strip())
    name = re.sub(r"\s*\((via [^)]*)\)|\s+via \w[\w ]*$", "", name)
    name = re.sub(r"\b(recruiting|recruitment|hiring|talent( acquisition)?|careers?|people)( team)?$", "", name, flags=re.I)
    name = name.split(":")[0]               # "NiCE: EMEA Talent Acquisition & Sourcing Partner"
    parts = re.split(r"\s+-\s*|\s*-\s+", name, maxsplit=1)
    if len(parts) == 2 and parts[1]:        # "Sophie Kinloch - Flash Pack", "Sinead Canavan -PIMCO"
        name = parts[1]
    return _tidy(name), addr.lower()


ATS_DOMAIN = re.compile(r"people-first|comeet|connectats|myhrtoolkit|engageats|jobs\.ac\.uk|occupop|greenhouse|pinpoint|lever\.co|ashbyhq|workable|smartrecruiters|successfactors|"
                        r"myworkday|workday|teamtailor|recruitee|tal\.net|hibob|bamboohr|personio|jobvite|icims|eploy|"
                        r"applytojob|hirehive|deel\.com|broadbean|idibu|tribepad|jobtrain|oleeo|cvmail|jobadder|"
                        r"talentlink|webitrent|networx|kallidus|hireroad|beapplied|candidate\.|candidates\.", re.I)


def _domain_company(addr: str) -> str:
    dom = addr.split("@")[-1]
    if ATS_DOMAIN.search(dom):                 # e.g. megan@chisholmhunterltd.occupop-mail.com → Chisholmhunter
        first = dom.split(".")[0]
        if len(dom.split(".")) > 2 and not ATS_DOMAIN.search(first) and not _GENERIC.search(first) and first not in ("eu", "us", "uk", "mail", "email", "careers", "jobs", "hire", "apply", "recruit", "app", "www", "jobs-eu"):
            first = re.sub(r"(ltd|limited|plc|careers)$", "", re.sub(r"^careers-", "", first))
            return first[:1].upper() + first[1:]
        return ""
    parts = [p for p in dom.split(".") if p not in ("co", "uk", "com", "org", "net", "io", "gov", "ac", "eu", "careers",
                                                     "mail", "email", "e", "jobs", "talent", "recruitment", "candidates")]
    if not parts:
        return ""
    name = parts[-1]
    if _GENERIC.search(name) or re.fullmatch(r"[0-9a-f-]{16,}", name):
        return ""
    name = re.sub(r"(?<=[a-z]{4})(uk|group|careers|jobs|hr)$", lambda m: " " + (m.group(1).upper() if m.group(1) in ("uk", "hr") else m.group(1).title()), name)
    return name[:1].upper() + name[1:]


def parse_application(subject: str, body: str, sender: str = "") -> tuple[str, str]:
    """(role, company) from an application email – either may be '' when the email doesn't say."""
    subject = _tidy(subject)
    text = _tidy(" ".join((body or "")[:2500].split()))
    role = company = ""
    for src in (subject, text):
        for pat in _ROLE:
            for m in re.finditer(pat, src, re.I):
                r = re.sub(r"^.*\b(?:apply|applying|applied) for (?:the |our |a |an )?", "", m.group("role"), flags=re.I)
                r = _clean_role(r)
                if 3 <= len(r) <= 80 and len(r.split()) <= 10 and not _BAD_ROLE.search(r) and r[:1].isupper():
                    role = role or r
                    if "company" in m.groupdict() and m.group("company") and not company and _good_company(_tidy(m.group("company"))):
                        company = _tidy(m.group("company"))
                    break
            if role:
                break
        if role:
            break
    if not company:
        for src in (subject, text):
            for pat in _COMPANY:
                m = re.search(pat, src, re.I)
                if m:
                    c = _company_after_at(_dedupe_words(_tidy(m.group("company"))))
                    c = _tidy(re.split(r"\s+(?:for|regarding|re:|[-–])\s+|\s*\(|:", c)[0])
                    c = re.sub(r"\s+(team|family|careers?|recruitment)$", "", c, flags=re.I)
                    if _good_company(c):
                        company = c
                        break
            if company:
                break
    name, addr = _sender_name(sender)
    if not company and name and not _GENERIC.search(name):
        person = re.fullmatch(r"(?-i:[A-Z][a-z'’-]+)(?: (?-i:[A-Z][a-z'’-]+)){1,2}", name) and not _PERSON_WORDS.search(name)
        if not person and "/" not in name and len(name.split()) <= 6:
            company = _dedupe_words(name)
    if not company:
        company = _domain_company(addr)
    company = re.sub(r"^(job opportunity - from |from )", "", company, flags=re.I)
    if company[:1].islower():
        company = company[:1].upper() + company[1:]
    return role, company


def _company_after_at(c: str) -> str:
    """'Talent Acquisition Associate - 24m FTC at Man Group' → 'Man Group'."""
    m = re.search(r"\bat (?:the )?((?-i:[A-Z])[\w&'’ .-]{1,50})$", c or "")
    return _tidy(m.group(1)) if m else c


NEWS_SENDERS = re.compile(r"comms\.|newsletter|news@|@news\.|marketing|mailer|emails@efinancial|selfmadeway|"
                          r"e\.targetjobs|digest|@e\.|noreply@medium|substack|eventbrite", re.I)
NEWS_WORDS = re.compile(r"deal|black friday|class access|top news|conference|#\w+|expires in|you might have missed|"
                        r"discount|% off|save \d|register now|book your place|podcast|event", re.I)

APP_CATEGORIES = ("applied", "acknowledged", "pre_screen", "assessment", "interview", "second_stage", "offer", "rejected",
                  "withdrawn")


def is_application_email(category: str, subject: str, text: str, sender: str = "") -> bool:
    if category not in APP_CATEGORIES:
        return False
    if NEWS_SENDERS.search(sender or "") or NEWS_WORDS.search(subject or ""):
        return False
    return not NOT_AN_APPLICATION.search(f"{subject} {text[:600]}")


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (t or "").lower()) if len(w) > 2 and w not in ("and", "the", "for", "with")}


def same_role(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return True                       # one side doesn't say: can't tell them apart
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def find_application(subject: str, body: str, sender: str, apps: list[dict], role: str = "",
                     company: str = "") -> dict | None:
    """The application an email is about. Same employer but a different role = a different application."""
    if company:                             # an application already under exactly this employer comes first
        exact = [a for a in apps if a["company"].lower() == company.lower()]
        hit = next((a for a in exact if not role or same_role(role, a.get("role", "")) or
                    str(a.get("role", "")).startswith("Role not named")), None)
        if hit:
            return hit
    app = match_application(subject, body, sender, apps)
    if app and company and app["company"].lower() != company.lower() and \
            company.lower().startswith(app["company"].lower() + " ") and len(company.split()) > len(app["company"].split()):
        app = None                          # "Reed Human Resources" is its own application, not plain "Reed"
    if not app and company:
        same = [a for a in apps if a["company"].lower() == company.lower()]
        app = next((a for a in same if not role or same_role(role, a.get("role", "")) or
                    str(a.get("role", "")).startswith("Role not named")), None)
    known = app.get("role") if app and not str(app.get("role", "")).startswith("Role not named") else ""
    if app and role and known and not same_role(role, known):
        same = [a for a in apps if a["company"].lower() == app["company"].lower() and same_role(role, a.get("role", ""))]
        return same[0] if same else None
    return app
