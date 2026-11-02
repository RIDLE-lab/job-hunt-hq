"""Interview prep: questions for the job you've been invited to interview for, your answer, a score out of 10 and
what to improve.

Questions come from the advert (what it asks for), the kind of work (every field has its own), and the usual opening,
motivation and closing questions. With an Anthropic key on the server, Claude writes the questions and marks the
answers; without one, a built-in coach marks them on what interviewers listen for: a real example, the STAR shape
(Situation, Task, Action, Result), what *you* did, a result you can measure, the right length and staying on the
question. Suggestions only ever point to things from your own history – nothing is invented.
"""
from __future__ import annotations

import json
import random
import re

import requests

# ---------------------------------------------------------------------------------------------------- the questions
OPENING = [
    ("Tell me about yourself.", "opening",
     "They want a two-minute story: who you are now, what you're good at (with proof), and why this job is the next step."),
    ("Talk me through your CV.", "opening",
     "Pick the parts that matter for this job. Go in time order, briefly, and finish on why you're here today."),
]
MOTIVATION = [
    ("Why do you want this job?", "motivation",
     "Show you know what the role involves, and link it to what you enjoy and what you've done."),
    ("Why do you want to work for {company}?", "motivation",
     "Mention something specific about them – what they do, their values, news, the people they help – and why it matters to you."),
    ("What do you know about {company}?", "motivation",
     "Do your homework: what they do, who for, size, recent news, values. Then say what appeals to you."),
]
STRENGTHS = [
    ("What are your greatest strengths?", "strengths",
     "Give two or three that matter for this job, each with a quick real example."),
    ("What is your biggest weakness?", "weakness",
     "Pick a real but fixable weakness that isn't central to the job, and say what you're doing to improve it."),
    ("Where do you see yourself in five years?", "motivation",
     "Show ambition that fits this job and the organisation – growing skills, taking on more."),
]
CLOSING = [
    ("Do you have any questions for us?", "closing",
     "Always say yes. Ask two or three about the team, what success looks like, training, or what's next for them."),
]

# What the advert asks for → the behavioural ("tell me about a time…") question it usually leads to.
COMPETENCIES = [
    (r"stakeholder|relationship|partner", "Tell me about a time you built a good working relationship with a difficult stakeholder."),
    (r"customer|client|service user|patient|guest|resident", "Tell me about a time you went above and beyond for a customer or client."),
    (r"complain|conflict|difficult|challenging (conversation|situation)|resolve", "Describe a time you dealt with a complaint or a difficult situation. What did you do?"),
    (r"team ?work|team player|collaborat|work with others|colleagues", "Give an example of when you worked well as part of a team."),
    (r"lead|manage (a )?team|supervis|line manag|mentor|coach", "Tell me about a time you led or supported others to get something done."),
    (r"priorit|deadline|pressure|fast[- ]paced|busy|multiple tasks|workload|organis", "Tell me about a time you had several deadlines at once. How did you prioritise?"),
    (r"detail|accura|complian|audit|regulat|policy|procedure|gdpr|data protection", "Describe a time your attention to detail made a difference."),
    (r"problem[- ]solv|analy|investigat|root cause|solution", "Tell me about a problem you solved. How did you work out what to do?"),
    (r"improv|change|initiative|innovat|transform|efficien|process", "Give an example of something you changed or improved at work."),
    (r"communicat|present|written|verbal|explain|influenc|negotiat", "Tell me about a time you had to explain something complicated, or persuade someone."),
    (r"adapt|flexib|change|uncertain", "Describe a time you had to adapt quickly to a change."),
    (r"initiative|proactive|self[- ]motivat|independ|own initiative", "Tell me about a time you used your initiative without being asked."),
    (r"mistake|learn|feedback|develop", "Tell me about a mistake you made. What happened and what did you learn?"),
    (r"safeguard|safety|health and safety|risk|vulnerable", "Tell me about a time you spotted a risk or a safety concern. What did you do?"),
    (r"target|kpi|sales|revenue|perform", "Tell me about a time you hit a difficult target."),
    (r"confidential|sensitive|discret|trust", "Describe a time you handled confidential or sensitive information."),
    (r"equality|diversity|inclusion|edi\b|inclusive", "How have you supported equality, diversity and inclusion at work?"),
    (r"budget|cost|financ|money", "Tell me about a time you managed a budget or saved money."),
]
GENERAL_COMPETENCIES = [
    "Tell me about a time you went above and beyond in your work.",
    "Describe a time you dealt with a difficult situation at work.",
    "Give an example of when you worked well as part of a team.",
    "Tell me about a time you had to work under pressure.",
    "Tell me about something you achieved that you're proud of.",
]

# A few questions for each kind of work (keys match occupations.SECTORS).
SECTOR = {
    "hr": ["How would you handle a manager who wants to dismiss someone without following the process?",
           "How do you keep up to date with employment law?",
           "How would you support an employee raising a grievance?",
           "What makes a good recruitment process?"],
    "admin": ["How do you organise your day when lots of requests come in at once?",
              "Which software and systems are you confident with?",
              "How do you make sure documents and data are accurate?"],
    "accountancy": ["Talk me through how you'd prepare a month-end close.",
                    "How do you make sure your figures are accurate?",
                    "How would you explain a budget overspend to a non-finance manager?"],
    "banking": ["How do you balance helping customers with following regulation?",
                "How would you spot and deal with possible fraud?",
                "What does treating customers fairly mean to you?"],
    "customer_services": ["What does great customer service mean to you?",
                          "How do you stay calm with an angry customer?",
                          "How do you handle a high volume of calls or messages?"],
    "sales": ["Sell me something on this desk.", "How do you handle rejection?",
              "Talk me through how you build a pipeline."],
    "marketing": ["Tell me about a campaign you're proud of and how you measured it.",
                  "How would you grow our audience on a small budget?",
                  "Which channels would you use for this role's audience, and why?"],
    "it": ["Talk me through a technical problem you solved recently.",
           "How do you keep your technical skills up to date?",
           "How would you explain a technical issue to a non-technical colleague?"],
    "design": ["Talk me through your portfolio and one project in detail.",
               "How do you handle feedback on your work?",
               "How do you balance a client's wishes with good design?"],
    "education": ["How do you plan a lesson for a mixed-ability group?",
                  "How do you manage challenging behaviour?",
                  "How do you know your learners are making progress?"],
    "healthcare": ["How do you put patients at the centre of their care?",
                   "What would you do if you were worried about a patient's safety?",
                   "How do you cope with the emotional side of the job?"],
    "care": ["What does person-centred care mean to you?",
             "What would you do if you suspected someone you support was being abused?",
             "How do you protect someone's dignity during personal care?"],
    "legal": ["How do you manage several deadlines on different matters?",
              "How do you keep client information confidential?",
              "Tell me about a legal area you're interested in and why."],
    "hospitality": ["How would you deal with a guest who's unhappy with their meal?",
                    "How do you work when the restaurant or hotel is at its busiest?",
                    "Why do food hygiene and allergen rules matter?"],
    "retail": ["How would you approach a customer who's browsing?",
               "What would you do if you saw someone shoplifting?",
               "How do you keep the shop floor looking right during a busy day?"],
    "warehouse": ["How do you make sure you pick and pack accurately?",
                  "What does working safely in a warehouse look like?",
                  "How do you keep going on a physically demanding shift?"],
    "construction": ["How do you make sure a site stays safe?",
                     "Tell me about a project that ran into problems. What did you do?",
                     "Which qualifications and cards (e.g. CSCS) do you hold?"],
    "engineering": ["Talk me through a project you worked on from start to finish.",
                    "How do you make sure your work meets quality standards?",
                    "Tell me about a time you found the cause of a fault."],
    "automotive": ["How do you diagnose a fault you haven't seen before?",
                   "How do you explain repair work and costs to a customer?"],
    "science": ["Talk me through a method or experiment you've run.",
                "How do you make sure your results are reliable?",
                "How do you keep accurate lab records?"],
    "public_sector": ["Why do you want to work in the public sector?",
                      "How do you make sure your work is fair to everyone?",
                      "Tell me about a time you worked within strict rules or policies."],
    "charity": ["Why does our cause matter to you?",
                "How would you make the most of a limited budget?",
                "How do you work with volunteers?"],
    "security": ["How would you deal with someone being aggressive?",
                 "What would you do if you found an unattended bag?",
                 "How do you stay alert on a long shift?"],
    "cleaning": ["How do you make sure areas are cleaned to the right standard?",
                 "Why does COSHH matter in cleaning?"],
    "leisure": ["How would you make sure a customer has a great experience?",
                "How do you handle safety in a leisure or sports setting?"],
    "aviation": ["How do you stay calm when flights are delayed and passengers are upset?",
                 "Why do security and safety procedures matter so much at an airport?"],
    "property": ["How would you deal with a tenant's repair complaint?",
                 "How do you keep track of lots of properties or cases?"],
    "purchasing": ["How do you get the best value from a supplier?",
                   "Talk me through a negotiation you led."],
    "environmental": ["Why do you want to work in this field?",
                      "How do you balance environmental goals with cost?"],
    "management": ["How do you get the best out of your team?",
                   "Tell me about a project you managed – how did you keep it on track?",
                   "How do you deal with someone who isn't performing?"],
    "beauty": ["How do you make clients feel comfortable?",
               "How do you keep up with new trends and techniques?"],
    "languages": ["How do you deal with a word or phrase that has no direct translation?",
                  "How do you make sure your translations are accurate?"],
}


def _fill(q: str, job: dict) -> str:
    return q.replace("{company}", job.get("company") or "us").replace("{title}", job.get("title") or "this role")


def _why_competency(pat: str, desc: str) -> str:
    m = re.search(pat, desc, re.I)
    return f"The advert mentions “{m.group(0)}”, so expect a question about it." if m else ""


def offline_questions(job: dict, sectors: list[str], n: int = 8, seed: int = 0) -> list[dict]:
    """A balanced set: an opener, why this job, competencies from the advert, questions for your field,
    strengths or weakness, and the closing question."""
    rnd = random.Random(seed)
    desc = f"{job.get('title') or ''} {job.get('description') or ''}"
    out: list[dict] = []

    def add(q, kind, tip, why=""):
        if q not in {x["q"] for x in out}:
            out.append({"q": _fill(q, job), "kind": kind, "tip": tip, "why": why})

    q, kind, tip = OPENING[seed % len(OPENING)]
    add(q, kind, tip)
    q, kind, tip = MOTIVATION[(seed + 1) % 2] if job.get("company") else MOTIVATION[0]
    add(q, kind, tip)
    found = [(pat, q) for pat, q in COMPETENCIES if re.search(pat, desc, re.I)]
    rnd.shuffle(found)
    comp_tip = ("Use STAR: the Situation, your Task, the Action YOU took, and the Result – ideally with a number. "
                "Aim for about two minutes.")
    for pat, q in found[:3]:
        add(q, "competency", comp_tip, _why_competency(pat, job.get("description") or ""))
    for q in rnd.sample(GENERAL_COMPETENCIES, len(GENERAL_COMPETENCIES)):
        if sum(1 for x in out if x["kind"] == "competency") >= 3:
            break
        add(q, "competency", comp_tip)
    pool = [q for s in sectors for q in SECTOR.get(s, [])]
    rnd.shuffle(pool)
    for q in pool[:2]:
        add(q, "technical", "Show you know the job: give the right steps, the reason behind them, and a real example if you have one.",
            "A question for your kind of work.")
    q, kind, tip = STRENGTHS[seed % len(STRENGTHS)]
    add(q, kind, tip)
    out = out[:max(n, 4) - 1]
    add(*CLOSING[0])            # always end on "any questions for us?"
    return out


def ai_questions(job: dict, career: dict, sectors: list[str], ai_cfg: dict, n: int = 8) -> list[dict] | None:
    key = (ai_cfg or {}).get("anthropic_api_key")
    if not key:
        return None
    prompt = (
        "You are an experienced UK interviewer. Write the interview questions this candidate is most likely to be asked "
        f"for the job below – {n} questions: one opener, one on motivation for this employer, three or four competency "
        "(\"tell me about a time…\") questions based on what the advert asks for, one or two technical questions for this "
        "kind of work, and the closing \"any questions for us?\". UK English. Return ONLY JSON: a list of objects with "
        "keys q (the question), kind (opening|motivation|competency|technical|strengths|weakness|closing), tip (one "
        "sentence on what a good answer covers), why (why they'll ask it, citing the advert where you can).\n\n"
        f"JOB: {job.get('title')} at {job.get('company')}\nFIELD: {', '.join(sectors) or 'unknown'}\nADVERT:\n"
        f"{(job.get('description') or '')[:6000]}\n\nCANDIDATE (for context only):\n{json.dumps(career, ensure_ascii=False)[:4000]}")
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": ai_cfg.get("model", "claude-haiku-5-5"), "max_tokens": 1800,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=60)
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        data = json.loads(text[text.index("["): text.rindex("]") + 1])
        qs = [{"q": str(d["q"])[:400], "kind": str(d.get("kind") or "competency"), "tip": str(d.get("tip") or "")[:400],
               "why": str(d.get("why") or "")[:300]} for d in data if isinstance(d, dict) and d.get("q")]
        return qs or None
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------------- marking
S_CUES = re.compile(r"\b(when i (was|worked)|while (i was )?working|in my (previous |last |current )?(role|job|position)|at (my )?(previous|last|current)|"
                    r"there was|we had|one (time|day|morning|afternoon|evening|shift)|last (year|month|week)|a few (months|years) ago|"
                    r"the situation|recently|a (customer|client|colleague|manager|patient|resident|candidate|guest|member of staff))\b", re.I)
T_CUES = re.compile(r"\b(i needed to|i had to|my (task|job|role|goal|aim|responsibility) was|i was (asked|responsible|tasked)|"
                    r"the (aim|goal|task|challenge|problem) was|i wanted to|it was my job|needed to be)\b", re.I)
A_CUES = re.compile(r"\bi (then )?(decided|spoke|called|phoned|emailed|arranged|set up|created|built|organised|organized|led|trained|listened|"
                    r"explained|reviewed|investigated|worked|prioritised|prioritized|escalated|made|took|used|asked|agreed|contacted|"
                    r"wrote|introduced|checked|supported|helped|met|planned|designed|analysed|analyzed|delivered|coached|negotiated|"
                    r"researched|followed|implemented|updated|calmed|apologised|apologized|offered|managed|handled|resolved|fixed)\b", re.I)
R_CUES = re.compile(r"\b(as a result|the result|which (meant|led)|this (meant|led|resulted|helped)|outcome|in the end|reduced|increased|"
                    r"improved|saved|achieved|resolved|thanked|positive feedback|since then|learn(ed|t)|went on to|was promoted|"
                    r"was praised|happy|satisfied|successful(ly)?)\b", re.I)
NUMBERS = re.compile(r"\d|%|£|percent|half|double|twice|three times")
FILLERS = re.compile(r"\b(um+|uh+|erm+|like,|basically|you know|kind of|sort of|i guess|to be honest|literally)\b", re.I)
HYPOTHETICAL = re.compile(r"\b(i would|i'd|i will|i'll|i'd probably|i would probably)\b", re.I)
STOP = set("the a an and or but to of in on at for with about you your me my i we they it is are was were be been "
           "this that what how why when where who tell describe give example time did do does have has had can could "
           "would should us our their there here from as by into than then so if not any".split())


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", text or "")


def offline_rate(question: str, kind: str, answer: str, job: dict) -> dict:
    """A score out of 10, what went well and what to improve – on what interviewers actually listen for."""
    words = _words(answer)
    n = len(words)
    low = answer.lower()
    good, better = [], []
    star = {"situation": bool(S_CUES.search(answer)), "task": bool(T_CUES.search(answer)),
            "action": bool(A_CUES.search(answer)), "result": bool(R_CUES.search(answer)) or bool(NUMBERS.search(answer))}
    i_count = len(re.findall(r"\bi\b", low))
    we_count = len(re.findall(r"\bwe\b", low))
    fillers = len(FILLERS.findall(answer))
    q_words = {w.lower() for w in _words(question)} - STOP
    advert_words = {w.lower() for w in _words(job.get("description") or "") if len(w) > 5} - STOP
    stems = {w.lower()[:5] for w in words}
    on_question = len({w[:5] for w in q_words} & stems) / max(1, len(q_words))
    advert_hits = len(advert_words & {w.lower() for w in words})
    score = 0.0
    if n < 15:
        return {"score": 1.0 if n else 0.0, "verdict": "Too short to mark", "good": [],
                "better": ["Write or say a full answer – a strong answer is usually 150–300 words (about two minutes)."],
                "star": star, "words": n, "minutes": round(n / 130, 1)}

    if kind == "competency":
        hyp = len(HYPOTHETICAL.findall(answer))
        past = len(re.findall(r"\b\w+ed\b|\b(was|were|had|did|went|made|took|spoke|told|found|gave|got)\b", low))
        if (hyp >= 1 and hyp * 2 > past) or not (star["situation"] or past >= 4):
            better.append("Give a real example from your past (\"I did…\"), not what you would do. Interviewers mark "
                          "hypothetical answers down.")
        else:
            score += 1
            good.append("You used a real example.")
        score += 1.5 * star["situation"] + 1.0 * star["task"] + 2.5 * star["action"] + 1.5 * star["result"]
        named = [k.title() for k, v in star.items() if v]
        missing = [k for k, v in star.items() if not v]
        if named:
            good.append("STAR: you covered " + ", ".join(named) + ".")
        for k in missing:
            better.append({"situation": "Set the scene in a sentence: where you were and what was going on.",
                           "task": "Say what you needed to achieve, or what your responsibility was.",
                           "action": "Spend most of the answer on what YOU did – the steps you took and why.",
                           "result": "Finish with the result: what changed, what people said, and what you learned."}[k])
        if NUMBERS.search(answer) and star["result"]:
            score += 0.5
            good.append("You backed the result up with a number.")
        elif star["result"]:
            better.append("Put a number on the result if you can (time saved, %, how many people, feedback score).")
        if we_count > i_count:
            better.append(f"You said “we” {we_count} times and “I” {i_count}. Interviewers need to hear what YOU did.")
        elif not star["action"] or i_count < 3:
            pass
        else:
            score += 1
            good.append("You were clear about your own part (“I…”).")
        lo, hi = 150, 380
    elif kind in ("motivation",):
        co = (job.get("company") or "").lower()
        title_words = {w.lower() for w in _words(job.get("title") or "")} - STOP
        if co and co.split()[0] in low:
            score += 2
            good.append("You named the organisation.")
        else:
            better.append("Mention the organisation by name and something specific about it (what they do, values, news).")
        if title_words & {w.lower() for w in words}:
            score += 1.5
            good.append("You linked your answer to the role itself.")
        else:
            better.append("Say what it is about this role that appeals to you.")
        if re.search(r"\b(i have|i've|my experience|in my (role|job)|i (worked|led|built|supported|managed))\b", low):
            score += 2
            good.append("You connected it to your own experience.")
        else:
            better.append("Link it to what you've done – show why you'd be good at it, not just why you want it.")
        if re.search(r"\b(because|values?|mission|purpose|culture|reputation|growth|develop|learn|impact|community|people)\b", low):
            score += 1.5
            good.append("You gave real reasons, not just “it sounds interesting”.")
        else:
            better.append("Give two or three specific reasons.")
        lo, hi = 80, 260
        score += 1
    elif kind == "opening":
        if re.search(r"\b(currently|at the moment|right now|i am an?|i'm an?|i work)\b", low):
            score += 2
            good.append("You started with where you are now.")
        else:
            better.append("Open with who you are now: your current or most recent role.")
        if re.search(r"\b(years?|experience|background|previously|before that|career)\b", low):
            score += 2
            good.append("You summed up your experience.")
        else:
            better.append("Briefly sum up your experience – the highlights, not every job.")
        if NUMBERS.search(answer) or re.search(r"\b(achiev|proud|led|built|improved|award|promot)\w*", low):
            score += 2
            good.append("You included an achievement.")
        else:
            better.append("Add one achievement with proof (a number or a result).")
        if re.search(r"\b(this role|this job|this position|why i('m| am) (here|applying)|next step|looking for|excited|keen)\b", low):
            score += 2
            good.append("You finished by linking to this job.")
        else:
            better.append("End by saying why this job is the right next step for you.")
        lo, hi = 100, 280
    elif kind == "weakness":
        if re.search(r"\b(perfectionist|work too hard|too hard[- ]working|care too much)\b", low):
            better.append("“Perfectionist” and “I work too hard” sound rehearsed. Pick a real, fixable weakness.")
        else:
            score += 2.5
            good.append("You named a believable weakness.")
        if re.search(r"\b(improv|working on|course|learn|practis|practic|training|now i|since then|to help|i've started|i have started)\w*", low):
            score += 3.5
            good.append("You said what you're doing about it.")
        else:
            better.append("Say what you're doing to improve it, and how it's going.")
        score += 1
        lo, hi = 60, 220
    elif kind == "closing":
        qs = answer.count("?")
        if qs >= 2:
            score += 6
            good.append(f"You asked {qs} questions – good.")
        elif qs == 1:
            score += 3.5
            better.append("Have two or three questions ready in case one gets answered during the interview.")
        else:
            better.append("Always ask questions – e.g. what success looks like in six months, about the team, training, next steps.")
        if re.search(r"salary|holiday|leave|pay\b", low) and qs < 3:
            better.append("Save pay and holiday questions for after an offer, unless they bring it up.")
        lo, hi = 15, 150
        score += 1
    else:   # technical / strengths
        if re.search(r"\b(for example|for instance|when i|in my (role|job)|once|at \w+ i)\b", low):
            score += 2.5
            good.append("You backed it up with a real example.")
        else:
            better.append("Back your answer with a real example from your work.")
        if re.search(r"\b(because|so that|which means|this ensures|that way|the reason)\b", low):
            score += 2
            good.append("You explained the reason behind what you do.")
        else:
            better.append("Explain why – the reason behind each step shows you understand the job.")
        if re.search(r"\b(first|then|next|finally|step|after that)\b", low):
            score += 1.5
            good.append("Your answer had a clear order.")
        else:
            better.append("Give your answer a clear order (first… then… finally…).")
        lo, hi = 80, 300
        score += 1

    # length, focus and delivery – for every kind of question
    if n < lo:
        better.append(f"It's a bit short ({n} words). Aim for about {lo}–{hi} words – roughly {round(lo / 130, 1)}–{round(hi / 130, 1)} minutes out loud.")
        score += 0.5
    elif n > hi * 1.4:
        better.append(f"It's long ({n} words, about {round(n / 130, 1)} minutes). Cut it back to the essentials – around {hi} words.")
        score += 0.5
    else:
        score += 1.5
        good.append(f"Good length ({n} words, about {max(0.5, round(n / 130, 1))} minutes).")
    if kind not in ("closing", "opening", "weakness") and q_words and on_question < 0.2:
        topic = re.sub(r"^(tell me about|describe|give (me |us )?an example of|talk me through)\s+(a time |when )?(you |when you )?",
                       "", question.strip().rstrip("?."), flags=re.I)
        better.append(f"Make sure your example clearly fits the question (“{topic}”). Say so in your first sentence – "
                      "e.g. “A time I had to work under pressure was when…”." if "pressure" in question.lower() else
                      f"Make sure your example clearly fits the question (“{topic}”). Say so in your first sentence – "
                      "e.g. “A good example is when I…”.")
        score -= 1.5
    if advert_hits >= 3 and kind != "closing":
        good.append("You used the advert's own language.")
        score += 0.5
    if fillers >= 3:
        better.append(f"Cut filler words (“like”, “basically”, “you know” – {fillers} found). Pause instead.")
        score -= 0.5
    score = max(0.0, min(10.0, round(score, 1)))
    verdict = ("Strong answer" if score >= 8 else "Good – a few tweaks" if score >= 6 else
               "Getting there" if score >= 4 else "Needs work")
    return {"score": score, "verdict": verdict, "good": good, "better": better, "star": star if kind == "competency" else None,
            "words": n, "minutes": round(n / 130, 1)}


def ai_rate(question: str, kind: str, answer: str, job: dict, career: dict, ai_cfg: dict) -> dict | None:
    key = (ai_cfg or {}).get("anthropic_api_key")
    if not key or len(_words(answer)) < 15:
        return None
    prompt = (
        "You are an honest, encouraging UK interview coach. Mark the candidate's answer to this interview question out "
        "of 10 as a real interviewer for this job would. Judge: did they answer the question; a real specific example "
        "(for competency questions, the STAR shape); what THEY did; a measurable result; relevance to the advert; length "
        "(about 2 minutes spoken). Suggestions may only use facts from the candidate's own details – never invent "
        "experience. UK English. Return ONLY JSON with keys: score (number 0-10, one decimal), verdict (3-5 words), "
        "good (list of short points), better (list of short, specific, actionable points), star (object with booleans "
        "situation, task, action, result – or null if not a competency question), improved (a stronger version of THEIR "
        "answer using only what they said plus facts from their details, about 150-250 words).\n\n"
        f"QUESTION ({kind}): {question}\n\nTHEIR ANSWER:\n{answer[:6000]}\n\nJOB: {job.get('title')} at {job.get('company')}\n"
        f"ADVERT:\n{(job.get('description') or '')[:4000]}\n\nTHEIR DETAILS:\n{json.dumps(career, ensure_ascii=False)[:5000]}")
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": ai_cfg.get("model", "claude-haiku-5-5"), "max_tokens": 1500,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=60)
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        d = json.loads(text[text.index("{"): text.rindex("}") + 1])
        n = len(_words(answer))
        return {"score": max(0.0, min(10.0, float(d.get("score", 0)))), "verdict": str(d.get("verdict") or "")[:60],
                "good": [str(x)[:300] for x in d.get("good") or []][:6], "better": [str(x)[:300] for x in d.get("better") or []][:6],
                "star": d.get("star") if kind == "competency" else None, "improved": str(d.get("improved") or "")[:3000],
                "words": n, "minutes": round(n / 130, 1), "by": "ai"}
    except Exception:
        return None


def rate(question: str, kind: str, answer: str, job: dict, career: dict, ai_cfg: dict) -> dict:
    return ai_rate(question, kind, answer, job, career, ai_cfg) or offline_rate(question, kind, answer, job)
