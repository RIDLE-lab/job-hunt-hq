"""Scores how well a job fits Rashid's CV (0–100) and explains why. No AI needed."""
from __future__ import annotations

import re

# Job-title words and how strongly they suggest a fit.
TITLE_FAMILIES = {
    r"\bhr\b|human resources|people\b|people &|people and": 18,
    r"talent|recruit|resourcing": 14,
    r"learning|l&d|l & d|training|development|capability": 14,
    r"hris|hr systems|people systems|people analytics|workforce (data|analytics|planning)|hr data": 18,
    r"employee relations|\ber\b": 10,
}
LEVEL_GOOD = r"advis|officer|coordinator|partner|generalist|assistant|administrator|executive|analyst|specialist"
LEVEL_STRETCH = r"senior|lead\b|manager|business partner|hrbp"
LEVEL_TOO_HIGH = r"director|head of|chief|vp\b|vice president"

# Skills from the CV, grouped. Each group found in the advert adds points.
SKILLS = {
    "employee relations": r"employee relations|disciplinar|grievance|investigation|acas|capability|\bER\b",
    "absence & performance": r"absence|sickness|return.to.work|performance improvement|\bPIP|probation",
    "recruitment & onboarding": r"recruit|onboard|right to work|dbs|safer recruitment|candidate|ats\b|applicant tracking",
    "HR systems": r"hris|hr system|itrent|workday|hibob|\bbob\b|teamtailor|greenhouse|access evo|cezanne|people ?hr|ciphr|sap",
    "data & reporting": r"report|dashboard|metric|kpi|analytic|power ?bi|excel|data",
    "L&D & coaching": r"learning|l&d|training|lms|coaching|development programme|learning needs",
    "compliance & GDPR": r"complian|gdpr|audit|cqc|regulat|policy|policies",
    "automation & tech": r"automat|python|sql|vba|process improvement|ai\b|digital",
    "CIPD": r"cipd",
}
LANGUAGE_BLOCKERS = r"fluent (in )?(german|french|spanish|italian|portuguese|mandarin|japanese|polish)|" \
                    r"(german|french|spanish|italian|portuguese|mandarin|japanese|polish)[- ]speaking|" \
                    r"native (german|french|spanish|italian)"
# The owner lives in south Essex: anywhere in Essex or Greater London works (furthest: Edgware).
ESSEX = ["essex", "southend", "leigh", "westcliff", "rayleigh", "rochford", "benfleet", "canvey", "hadleigh",
         "shoeburyness", "basildon", "wickford", "billericay", "pitsea", "laindon", "south woodham",
         "chelmsford", "brentwood", "grays", "thurrock", "tilbury", "purfleet", "stanford-le-hope",
         "harlow", "epping", "loughton", "colchester", "braintree", "witham", "maldon", "burnham-on-crouch",
         "stansted", "saffron walden", "clacton", "harwich", "great dunmow", "ongar", "waltham abbey"]
GREATER_LONDON = ["london", "city of london", "westminster", "camden", "islington", "hackney", "tower hamlets",
                  "canary wharf", "stratford", "newham", "barking", "dagenham", "havering", "romford", "redbridge",
                  "ilford", "waltham forest", "walthamstow", "enfield", "barnet", "edgware", "haringey", "harrow",
                  "brent", "wembley", "ealing", "hillingdon", "uxbridge", "heathrow", "hounslow", "richmond",
                  "twickenham", "teddington", "kingston", "merton", "wimbledon", "sutton", "croydon", "bromley",
                  "lewisham", "greenwich", "bexley", "bexleyheath", "southwark", "lambeth", "wandsworth",
                  "hammersmith", "fulham", "kensington", "chelsea", "shoreditch", "borough", "paddington",
                  "kings cross", "holborn", "mayfair", "victoria"]
OUTSIDE = ["kent", "tunbridge", "dartford", "gravesend", "northfleet", "maidstone", "faversham", "canterbury",
           "st albans", "hertford", "watford", "luton", "reading", "slough", "guildford", "crawley", "surrey",
           "oxford", "cambridge", "milton keynes", "brighton", "birmingham", "manchester", "leeds", "bristol"]


ESSEX += ["hockley", "southminster", "ockendon", "south ockendon", "corringham", "chafford hundred", "aveley",
          "ingatestone", "hutton", "west horndon", "hornchurch", "upminster", "rainham", "halstead", "coggeshall"]
GREATER_LONDON += ["greater london", "beckenham", "orpington", "sidcup", "eltham", "woolwich", "chingford", "leyton",
                   "leytonstone", "east ham", "west ham", "poplar", "bow", "mile end", "whitechapel", "aldgate",
                   "liverpool street", "moorgate", "farringdon", "clerkenwell", "euston", "marylebone", "soho",
                   "covent garden", "bloomsbury", "waterloo", "battersea", "clapham", "brixton", "peckham", "deptford",
                   "catford", "sydenham", "dulwich", "streatham", "tooting", "putney", "chiswick", "acton",
                   "shepherds bush", "white city", "notting hill", "kilburn", "hampstead", "finchley", "hendon",
                   "mill hill", "colindale", "kingsbury", "wood green", "tottenham", "edmonton", "southgate",
                   "palmers green", "muswell hill", "highgate", "holloway", "dalston", "bethnal green", "stepney",
                   "limehouse", "wapping", "london bridge", "st pauls", "elephant", "vauxhall", "pimlico",
                   "erith", "welling", "chislehurst", "petts wood", "bromley-by-bow", "silvertown", "royal docks",
                   "beckton", "barkingside", "chadwell heath", "gidea park", "harold wood", "wanstead", "woodford",
                   "south woodford", "walthamstow", "ponders end", "new malden", "surbiton", "morden", "mitcham",
                   "carshalton", "wallington", "purley", "coulsdon", "thornton heath", "norwood", "feltham",
                   "isleworth", "brentford", "southall", "hayes", "northolt", "greenford", "ruislip", "pinner",
                   "stanmore", "wealdstone", "kenton", "neasden", "willesden", "cricklewood", "golders green"]
# Words that say where a job is in general, not which town.
VAGUE = re.compile(r"^(united kingdom|uk|england|great britain|gb|britain|multiple locations?|various|nationwide|"
                   r"hybrid|flexible|on-?site|office|south east|east of england|eastern|anywhere)?$")


def location_fit(location: str, remote: bool = False) -> str:
    """'ok' (Essex/Greater London or remote), 'far' (a named place outside them), or 'unknown'.
    Other people: within the distance they chose of their own places (see generic.py)."""
    from . import persona
    if not persona.builtin():
        from . import generic
        return generic.location_fit(location, remote)
    loc = (location or "").lower()
    if remote or re.search(r"remote|home.based|work from home", loc):
        return "ok"
    if re.search(r"upon-avon|north yorkshire|richmond, (north )?yorks", loc):
        return "far"   # same names as London places, elsewhere
    if any(re.search(rf"\b{re.escape(p)}\b", loc) for p in ESSEX + GREATER_LONDON):
        return "ok"
    if re.search(r"\b(e|ec|n|nw|se|sw|w|wc|ss|cm|rm|ig|co|en|ha|ub|tw|kt|cr|br|sm)\d{1,2}[a-z]?\b", loc):
        return "ok"   # a London or Essex postcode
    if any(re.search(rf"\b{re.escape(p)}\b", loc) for p in OUTSIDE):
        return "far"
    # A named town that isn't in Essex or London (Grantham, Ilkeston, Birmingham AL…) is too far.
    parts = [p.strip(" .()") for p in re.split(r"[,/|;]| - ", loc) if p.strip(" .()")]
    if parts and not all(VAGUE.match(p) for p in parts):
        return "far"
    return "unknown"


def _years_required(text: str) -> int | None:
    nums = [int(n) for n in re.findall(r"(\d{1,2})\+?\s*(?:or more\s*)?years", text.lower())]
    nums = [n for n in nums if n <= 20]
    return max(nums) if nums else None


def score_job(job: dict) -> tuple[int, list[str]]:
    from . import persona
    if not persona.builtin():
        from . import generic
        return generic.score_job(job)
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "")
    blob = f"{title} {desc.lower()}"
    reasons: list[str] = []
    score = 0

    # 1. Title (up to 40)
    t = sum(w for pat, w in TITLE_FAMILIES.items() if re.search(pat, title))
    t = min(t, 32)
    if re.search(LEVEL_GOOD, title):
        t += 8
    score += min(t, 40)
    if t >= 26:
        reasons.append("Job title matches your HR / people background")
    elif t == 0:
        reasons.append("Job title isn't an HR role")

    # 2. Skills in the advert (up to 35)
    found = [name for name, pat in SKILLS.items() if re.search(pat, desc, re.I)]
    score += min(len(found) * 5, 35)
    if found:
        reasons.append("Uses your skills: " + ", ".join(found[:5]))

    # 3. Level (up to 15)
    if re.search(LEVEL_TOO_HIGH, title):
        score -= 20
        reasons.append("Very senior title – likely out of reach for now")
    elif re.search(LEVEL_STRETCH, title):
        score += 5
        reasons.append("A step up – worth applying as a stretch")
    else:
        score += 15
    years = _years_required(desc)
    if years and years >= 6:
        score -= 10
        reasons.append(f"Asks for {years}+ years' experience")

    # 4. Salary (up to 5) – your expectation is £32–34k
    lo, hi = job.get("salary_min"), job.get("salary_max")
    top = hi or lo
    if top:
        if top >= 30000:
            score += 5
        if top < 26000:
            score -= 10
            reasons.append("Pays below your expectation")
        elif top >= 32000:
            reasons.append("Salary meets your £32–34k expectation")

    # 5. Location (up to 5) – Essex or Greater London from home
    where = location_fit(job.get("location"), bool(job.get("remote")))
    if where == "ok":
        score += 5
    elif where == "far":
        score -= 25
        reasons.append("Outside Essex / Greater London – too far from home")
    else:
        reasons.append("Check the location")

    # Hard blockers
    if re.search(LANGUAGE_BLOCKERS, blob):
        score = min(score, 15)
        reasons.insert(0, "Needs a language you don't have to a fluent level")

    return max(0, min(100, score)), reasons


def fit_label(score: int | None) -> str:
    if score is None:
        return "Not scored"
    if score >= 70:
        return "Strong fit"
    if score >= 50:
        return "Good fit"
    if score >= 30:
        return "Stretch"
    return "Weak fit"


def title_excluded(title: str, words: list[str]) -> bool:
    t = (title or "").lower()
    return any(w.lower() in t for w in words or [])
