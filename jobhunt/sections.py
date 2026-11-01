"""Fills the "My Experience" parts of application forms from your career details:
work experience rows, education rows and skills (Workday and similar systems).

It only fills empty fields, adds rows with the section's own "Add" button, and leaves anything it
isn't sure about for you (those fields then come up as questions in the app).
"""
from __future__ import annotations

import re

from .answers import match_option
from .career import month_year

MAX_ROWS = 10
DEGREE_WORDS = {
    "master": r"master|mba|postgraduate|msc|m\.?a\b",
    "bachelor": r"bachelor|undergraduate|b\.?a\b|bsc|honours",
    "professional": r"professional|diploma|certificat|cipd|other",
    "secondary": r"a.?level|btec|secondary|high school|college|further education|other",
}


def _loc(page, fid):
    return page.locator(f'[data-jhq="{fid}"]')


def _type(page, fid, value) -> bool:
    try:
        loc = _loc(page, fid)
        loc.click(timeout=4000)
        if loc.get_attribute("role") == "spinbutton" or loc.evaluate("e => e.tagName") == "INPUT" and \
                re.fullmatch(r"\d{1,4}", value or ""):
            loc.press("Control+a")
            loc.press_sequentially(value, delay=60)
        else:
            loc.fill(value, timeout=4000)
        loc.press("Tab")
        return True
    except Exception:
        return False


def _pick_from_search(page, fid, value) -> bool:
    """A Workday 'search' box (school, field of study, skills): type, press Enter, choose the match."""
    try:
        loc = _loc(page, fid)
        prompt = loc.evaluate("""e => e.getAttribute('role') === 'combobox' || !!e.getAttribute('aria-haspopup') ||
            /search|type to add/i.test((e.placeholder || '') + ' ' + (e.getAttribute('aria-label') || '')) ||
            !!e.closest('[data-automation-id*=multiselect i], [data-automation-id*=prompt i]')""")
        if not prompt:
            return False          # a plain text box: the caller just types into it
        loc.click(timeout=4000)
        loc.fill("")
        loc.press_sequentially(value, delay=35)
        loc.press("Enter")
        for _ in range(8):
            page.wait_for_timeout(400)
            opts = page.locator("[role=option]:visible, [data-automation-id=promptOption]:visible")
            if opts.count():
                texts = [t.strip() for t in opts.all_inner_texts()]
                want = match_option(texts, value)
                if want is None:
                    page.keyboard.press("Escape")
                    loc.fill("")
                    return False
                opts.nth(texts.index(want)).click(timeout=4000)
                page.wait_for_timeout(300)
                return True
        page.keyboard.press("Escape")
        return False
    except Exception:
        return False


def _choose_listbox(page, fid, pattern) -> bool:
    try:
        _loc(page, fid).click(timeout=4000)
        page.wait_for_timeout(600)
        opts = page.locator("[role=option]:visible")
        texts = [t.strip() for t in opts.all_inner_texts()]
        # "native|fluent|advanced": try each word in order, so the best match wins over the first in the list
        alts = pattern.split("|") if "(" not in pattern else [pattern]
        pick = next((t for a in alts for t in texts if re.search(a, t, re.I)), None)
        if pick is None:
            page.keyboard.press("Escape")
            return False
        opts.nth(texts.index(pick)).click(timeout=4000)
        return True
    except Exception:
        return False


def _ensure_rows(agent, page, title_re, section, wanted) -> list:
    blocks = agent._js(page, "p => JHQ.blocks(p)", title_re)
    tries = 0
    while len(blocks) < wanted and tries < wanted + 1:
        tries += 1
        bid = agent._js(page, "s => JHQ.addButton(s)", section)
        if not bid:
            break
        try:
            _loc(page, bid).click(timeout=5000)
        except Exception:
            break
        page.wait_for_timeout(900)
        blocks = agent._js(page, "p => JHQ.blocks(p)", title_re)
    return blocks


def _fill_dates(page, fields, start, end, current) -> int:
    n = 0
    months = [f for f in fields if re.fullmatch(r"month", f["label"], re.I)]
    years = [f for f in fields if re.fullmatch(r"year", f["label"], re.I)]
    singles = [f for f in fields if re.match(r"(from|start)", f["label"], re.I)], \
              [f for f in fields if re.match(r"(to|end)\b", f["label"], re.I)]
    for i, (when, skip) in enumerate(((start, False), (end, current))):
        if skip or not when:
            continue
        mm, yyyy = month_year(when)
        if i < len(years) and not years[i]["value"]:
            if i < len(months) and mm and not months[i]["value"]:
                n += _type(page, months[i]["id"], mm)
            n += _type(page, years[i]["id"], yyyy)
        elif not years and singles[i] and not singles[i][0]["value"] and singles[i][0]["tag"] == "INPUT":
            n += _type(page, singles[i][0]["id"], f"{mm}/{yyyy}" if mm else yyyy)
    return n


def _open_section(agent, page, title_re, section) -> bool:
    """A section with rows already, or an optional one that only shows an "Add" button: press it once."""
    if agent._js(page, "p => JHQ.blocks(p)", title_re):
        return True
    bid = agent._js(page, "s => JHQ.addButton(s)", section)
    if not bid:
        return False
    try:
        _loc(page, bid).click(timeout=5000)
        page.wait_for_timeout(900)
    except Exception:
        return False
    return bool(agent._js(page, "p => JHQ.blocks(p)", title_re))


def fill_experience(agent, page, career) -> int:
    # Workday-style "include any relevant roles": leave off jobs you marked as full-history-only.
    rows = [r for r in career.get("experience", []) if not r.get("full_history_only")][:MAX_ROWS]
    if not rows or not _open_section(agent, page, r"^work experience\s*\d+$", "work experience"):
        return 0
    blocks = _ensure_rows(agent, page, r"^work experience\s*\d+$", "work experience", len(rows))
    filled = 0
    for block, row in zip(blocks, rows):
        current = not row.get("end")
        for f in block["fields"]:
            label, empty = f["label"].lower(), not f["value"]
            if f["type"] == "checkbox":
                if current and re.search(r"current", label) and empty:
                    try:
                        _loc(page, f["id"]).check(timeout=3000)
                        filled += 1
                    except Exception:
                        pass
                continue
            if not empty:
                continue
            value = (row["title"] if re.search(r"job title|title|position", label) else
                     row["company"] if re.search(r"company|employer|organi[sz]ation", label) else
                     row.get("location") if re.search(r"location|city", label) else
                     (row.get("description") or row.get("details")) if re.search(r"description|responsibilit|summary|duties", label)
                     else None)
            if value:
                filled += _type(page, f["id"], value)
        page.wait_for_timeout(300)
        block_now = agent._js(page, "p => JHQ.blocks(p)", r"^work experience\s*\d+$")
        fresh = next((b for b in block_now if b["title"] == block["title"]), block)
        filled += _fill_dates(page, fresh["fields"], row.get("start"), row.get("end"), current)
    if filled:
        agent.log(f"Filled {min(len(blocks), len(rows))} work experience entries from your career details")
    return filled


def fill_education(agent, page, career) -> int:
    rows = [r for r in career.get("education", []) if not r.get("full_history_only")][:MAX_ROWS]
    if not rows or not _open_section(agent, page, r"^education\s*\d+$", "education"):
        return 0
    blocks = _ensure_rows(agent, page, r"^education\s*\d+$", "education", len(rows))
    filled = 0
    for block, row in zip(blocks, rows):
        for f in block["fields"]:
            label, empty = f["label"].lower(), not f["value"] or re.match(r"select", f["value"], re.I)
            if not empty:
                continue
            if re.search(r"school|university|institution|college", label):
                filled += bool(_pick_from_search(page, f["id"], row["school"]) or _type(page, f["id"], row["school"]))
            elif re.search(r"degree|qualification", label):
                if f["tag"] == "BUTTON":
                    # the option you chose before on these forms (e.g. "Masters Degree"), else the closest by level
                    choice = row.get("form_degree")
                    ok = choice and _choose_listbox(page, f["id"], r"^\s*" + re.escape(choice).replace(r"\ ", r"[\s’']*") + r"\s*$")
                    filled += bool(ok or _choose_listbox(page, f["id"], DEGREE_WORDS.get(row.get("kind", ""), re.escape(row["degree"]))))
                else:
                    filled += _type(page, f["id"], row["degree"])
            elif re.search(r"field of study|subject|major|discipline", label):
                choice = row.get("form_field")
                filled += bool((choice and _pick_from_search(page, f["id"], choice)) or
                               _pick_from_search(page, f["id"], row["field"]) or _type(page, f["id"], choice or row["field"]))
            elif re.search(r"result|gpa|grade|classification", label) and row.get("result"):
                filled += _type(page, f["id"], row["result"])
        end = row.get("end") or month_year(row.get("expected") or "")[1]     # year boxes: "2027"
        filled += _fill_dates(page, block["fields"], row.get("start"), end, not end)
    if filled:
        agent.log(f"Filled education from your career details ({min(len(blocks), len(rows))} entries)")
    return filled


def fill_skills(agent, page, career) -> int:
    skills = career.get("skills", [])
    fid = agent._js(page, """() => {
        const f = JHQ.all('input').find(e => JHQ.visible(e) && /skill/i.test((e.getAttribute('aria-label') || '') + ' ' +
              (e.placeholder || '') + ' ' + ((e.closest('[data-automation-id*=skill i], [class*=skill i], fieldset, section') || {}).innerText || '').slice(0, 80)));
        if (!f) return null;
        f.setAttribute('data-jhq', f.getAttribute('data-jhq') || 'skills-' + Date.now() % 100000);
        return f.getAttribute('data-jhq'); }""")
    if not fid or not skills:
        return 0
    try:
        box = _loc(page, fid).evaluate("e => (e.closest('[data-automation-id*=skill i], fieldset, section') || e.parentElement).innerText")
    except Exception:
        box = ""
    added = 0
    for skill in skills[:15]:
        if skill.lower() in (box or "").lower():
            continue
        if _pick_from_search(page, fid, skill):
            added += 1
    if added:
        agent.log(f"Added {added} skills from your career details")
    return added


LEVELS = [   # your level in My career → words used by forms' proficiency drop-downs, best first
    (r"native|mother", r"native|fluent|expert|advanced|excellent|5"),
    (r"fluent", r"fluent|advanced|expert|excellent|4"),
    (r"good|professional|advanced", r"advanced|good|professional|proficient|intermediate|3"),
    (r"working|intermediate|conversational", r"intermediate|working|conversational|moderate|basic"),
    (r"basic|beginner|elementary", r"basic|beginner|elementary|novice|1"),
]


def fill_languages(agent, page, career) -> int:
    rows = career.get("languages", [])[:MAX_ROWS]
    if not rows or not _open_section(agent, page, r"^languages?\s*\d+$", "languages?"):
        return 0
    blocks = _ensure_rows(agent, page, r"^languages?\s*\d+$", "languages?", len(rows))
    filled = 0
    for block, row in zip(blocks, rows):
        level = (row.get("level") or "").lower()
        want = next((w for k, w in LEVELS if re.search(k, level)), None)
        native = bool(re.search(r"native|mother|fluent", level))
        for f in block["fields"]:
            label, empty = f["label"].lower(), not f["value"] or re.match(r"select", f["value"], re.I)
            if f["type"] == "checkbox":
                if native and re.search(r"fluent|native", label) and empty:
                    try:
                        _loc(page, f["id"]).check(timeout=3000)
                        filled += 1
                    except Exception:
                        pass
                continue
            if not empty:
                continue
            if re.fullmatch(r"\*?\s*language\s*\*?", label) or re.search(r"^language\b(?!.*(level|proficien))", label):
                if f["tag"] == "BUTTON":
                    filled += _choose_listbox(page, f["id"], r"^\s*" + re.escape(row["language"]) + r"\b")
                else:
                    filled += bool(_pick_from_search(page, f["id"], row["language"]) or _type(page, f["id"], row["language"]))
            elif want and re.search(r"proficien|level|reading|writing|speaking|comprehension|overall", label) and f["tag"] == "BUTTON":
                filled += _choose_listbox(page, f["id"], want)
    if filled:
        agent.log(f"Filled {min(len(blocks), len(rows))} languages from your career details")
    return filled


# ---------------------------------------------------------------- "Add more …" pop-up entries (Tesco and similar)
EDU_LEVEL = {   # your level → words on "Education level" drop-downs, best first
    "master": r"master|postgrad|level 7|mba|degree",
    "professional": r"level 7|postgrad|professional|diploma|master|other",
    "bachelor": r"bachelor|undergrad|level 6|degree|honours",
    "secondary": r"btec|a.?level|level 3|college|further|sixth|secondary|other",
}


def _full_date(exact, month_year_value, end=False):
    """dd/mm/yyyy: your exact date if saved, else the 1st (or last day) of the month."""
    if exact and re.fullmatch(r"\d{2}/\d{2}/\d{4}", exact):
        return exact
    mm, yyyy = month_year(month_year_value)
    if not yyyy:
        return ""
    if not mm:
        mm = "06" if end else "09"
    import calendar
    day = calendar.monthrange(int(yyyy), int(mm))[1] if end else 1
    return f"{day:02d}/{mm}/{yyyy}"


def _date_for(field, exact, my, end=False):
    hint = (field["label"] + " " + field.get("placeholder", "")).lower()
    if exact and re.fullmatch(r"\d{2}/\d{2}/\d{4}", exact):
        my = exact[3:]                      # "22/05/2024" → "05/2024"
    if re.search(r"\bmm\s*/\s*yy\b(?!yy)", hint):
        mm, yyyy = month_year(my or "")    # "E.g. 02/82" → MM/YY
        return f"{mm or ('06' if end else '09')}/{yyyy[2:]}" if yyyy else ""
    if re.search(r"dd|day|/\s*mm\s*/", hint) or field["type"] == "date":
        v = _full_date(exact, my, end)
        if field["type"] == "date" and v:      # browser date box wants yyyy-mm-dd
            d_, m_, y_ = v.split("/")
            v = f"{y_}-{m_}-{d_}"
        return v
    mm, yyyy = month_year(my or "")
    # "mm/yyyy", or an example like "E.g. 02/82" (these forms still want a 4-digit year)
    if yyyy and (re.search(r"mm", hint) or re.search(r"\b\d{2}/\d{2,4}\b", hint)):
        return f"{mm or ('06' if end else '09')}/{yyyy}"
    return yyyy


def _select(page, fid, pattern) -> bool:
    try:
        loc = _loc(page, fid)
        texts = loc.evaluate("e => Array.from(e.options).map(o => o.text.trim())")
        for alt in pattern.split("|"):
            pick = next((t for t in texts if re.search(alt, t, re.I)), None)
            if pick:
                loc.select_option(label=pick, timeout=4000)
                return True
    except Exception:
        pass
    return False


def _editor(page, fid, text) -> bool:
    try:
        loc = _loc(page, fid)
        loc.click(timeout=4000)
        page.keyboard.insert_text(text)
        return True
    except Exception:
        return False


def _fill_panel(page, panel, row, kind) -> int:
    n = 0
    current = not (row.get("end") or row.get("end_date"))
    seen_sel = []
    for f in panel["fields"]:
        label = f["label"].lower()
        if f["type"] == "radio":
            q = (f.get("question") or "").lower()
            if re.search(r"still (employed|work)|currently (employed|work|study)|current (job|employer|role)|still (studying|at)", q):
                if re.match(r"\s*(yes|no)\b", f.get("option", ""), re.I) and \
                        f["option"].lower().startswith("yes" if current else "no") and not f["value"]:
                    try:
                        n += bool(page.evaluate("id => JHQ.pickRadio(id)", f["id"]))
                    except Exception:
                        pass
            continue
        if f["type"] == "checkbox":
            if current and re.search(r"current", label) and not f["value"]:
                try:
                    _loc(page, f["id"]).check(timeout=3000)
                    n += 1
                except Exception:
                    pass
            continue
        if f["value"] and not (f["tag"] == "SELECT" and re.match(r"(please )?select|choose|--|month|year", f["value"], re.I)):
            continue
        value = None
        opts = " ".join(f.get("options") or []).lower()
        if f["tag"] == "SELECT" and ("january" in opts or re.search(r"\b(19|20)\d{2}\b", opts)):
            kind_sel = "month" if "january" in opts else "year"
            if re.search(r"start|from|\bend\b|\bto\b|finish|leav|until", label):
                is_end = bool(re.search(r"\bend\b|\bto\b|finish|leav|until", label))
            else:                                         # plain "Month"/"Year" boxes: the first pair is the start
                is_end = seen_sel.count(kind_sel) >= 1
            seen_sel.append(kind_sel)
            if is_end and current:
                continue
            exact, my = (row.get("end_date"), row.get("end") or row.get("expected")) if is_end else (row.get("start_date"), row.get("start"))
            if exact and re.fullmatch(r"\d{2}/\d{2}/\d{4}", exact):
                my = exact[3:]
            mm, yyyy = month_year(my or "")
            if "january" in opts and mm:
                import calendar
                n += _select(page, f["id"], "^" + calendar.month_name[int(mm)])
            elif yyyy:
                n += _select(page, f["id"], "^" + yyyy + "$")
            continue
        if kind == "qual":
            if re.search(r"obtained|awarded|achieved|date", label):
                value = _date_for(f, row.get("end_date"), row.get("end") or row.get("expected"), end=True)
            elif re.search(r"type|level", label):
                if f["tag"] == "SELECT":
                    n += _select(page, f["id"], EDU_LEVEL.get(row.get("kind", ""), "other"))
                    continue
                value = QUAL_TYPE.get(row.get("kind", ""), "Other")
            elif re.search(r"result|grade|class", label):
                value = row.get("result") or ("In progress" if current else "")
            elif re.search(r"name|qualification|title|subject", label):
                value = f"{row.get('degree')} – {row.get('field')}" if row.get("field") else row.get("degree")
        elif re.search(r"reason.*leav|why .*leave", label):
            value = row.get("reason") or ("Still employed here." if current else "")
        elif re.search(r"start|from", label):
            value = _date_for(f, row.get("start_date"), row.get("start"))
        elif re.search(r"\bend\b|\bto\b|finish|leav", label):
            if current and kind == "edu" and row.get("expected"):
                value = _date_for(f, "", row["expected"], end=True)
            elif not current:
                value = _date_for(f, row.get("end_date"), row.get("end"), end=True)
        elif kind == "qual":
            pass
        elif kind == "edu":
            if f["tag"] == "SELECT" and re.search(r"level|type|qualification", label):
                n += _select(page, f["id"], EDU_LEVEL.get(row.get("kind", ""), "other"))
                continue
            if re.search(r"school|college|uni|institution|establishment", label):
                value = row.get("school")
            elif re.search(r"qualification|degree|course|award", label):
                value = f"{row.get('degree')} – {row.get('field')}" if row.get("field") else row.get("degree")
            elif re.search(r"subject|field", label):
                value = row.get("field")
            elif re.search(r"grade|result|classification", label):
                value = row.get("result") or ("In progress" if current else "")
            elif re.search(r"summary|description|detail", label):
                value = f"{row.get('degree')}, {row.get('field')}" + (f" – {row['result']}" if row.get("result") else "")
        else:
            if re.search(r"job title|position|role|title", label):
                value = row.get("title")
            elif re.search(r"employer|company|organi[sz]ation", label):
                value = row.get("company") + (f" (via {row['agency']})" if row.get("agency") else "")
            elif re.search(r"location|city|town", label):
                value = row.get("location")
            elif re.search(r"summary|description|duties|responsibilit|detail", label):
                value = row.get("description") or row.get("details")
        if not value:
            continue
        if f["tag"] == "EDITOR":
            n += _editor(page, f["id"], value)
        elif f["tag"] == "SELECT":
            n += _select(page, f["id"], re.escape(value))
        else:
            n += _type(page, f["id"], value)
    return n


QUAL_TYPE = {"master": "Postgraduate (Masters)", "bachelor": "Degree", "professional": "Professional qualification",
             "secondary": "BTEC Level 3"}


def fill_inline(agent, page, career) -> int:
    """Entry forms already on the page with an "Add Employment / Add Education / Add Qualification" button.
    Two kinds of site:
      • repeating blocks (each entry stays on the page with Remove/Add buttons): fill the first blank block, and
        only press Add when another blank block is needed – so no empty entries are left behind;
      • a single form the button saves and clears: fill it, press the button, repeat."""
    total = 0
    exp = career.get("experience", [])[:MAX_ROWS + 2]          # these forms want your full history
    edu = career.get("education", [])[:MAX_ROWS]
    names = dict(exp="employment", edu="education", qual="qualification")
    for kind, button_re, rows, key in (
            ("exp", r"^\W*add (employment|work|job|position|experience|work experience|employment history)\W*$", exp,
             lambda r: [r["company"], r["title"]]),
            ("edu", r"^\W*add (education|school|education history)\W*$", edu,
             lambda r: [r["school"], _date_for({"label": "mm/yyyy", "type": "text"}, r.get("start_date"), r.get("start"))]),
            ("qual", r"^\W*add (qualifications?|certificates?)\W*$", edu,
             lambda r: [r.get("degree") or "zzzz"])):
        blocks = agent._js(page, "p => JHQ.entryBlocks(p)", button_re)
        if not blocks:
            continue
        repeating = any(b["remove"] for b in blocks) or len(blocks) > 1
        added = 0
        for row in rows:
            blocks = agent._js(page, "p => JHQ.entryBlocks(p)", button_re)
            seen = " ".join(b["values"] for b in blocks) + " " + agent._js(page, "() => document.body.innerText")
            if all(k and k in seen for k in key(row)):
                continue                                     # already on the form
            target = next((b for b in blocks if b["empty"]), None)
            if target is None and repeating and blocks:
                try:
                    _loc(page, blocks[-1]["add"]).click(timeout=5000)
                    page.wait_for_timeout(1000)
                except Exception:
                    break
                blocks = agent._js(page, "p => JHQ.entryBlocks(p)", button_re)
                target = next((b for b in blocks if b["empty"]), None)
            if target is None or not _fill_panel(page, {"fields": target["fields"]}, row, kind):
                break
            added += 1
            if not repeating:                                # the button saves the entry and clears the form
                try:
                    _loc(page, target["add"]).click(timeout=5000)
                    page.wait_for_timeout(1000)
                except Exception:
                    break
        if added:
            agent.log(f"Added {added} {names[kind]} entries from your career details")
        total += added
    return total


def fill_popups(agent, page, career) -> int:
    """Sections where each entry is added through a pop-up: "Add more education history", "Add work history"…"""
    total = 0
    for kind, button_re, rows, key in (
            ("edu", r"^\W*add (more|an?|another|new)\b.*(education|qualification)|^\W*add (education|qualification) (history|details)",
             career.get("education", []), "school"),
            ("exp", r"^\W*add (more|an?|another|new)\b.*(work|employment|job|experience|position)|^\W*add (work|employment) (history|details)",
             career.get("experience", []), "company")):
        heading_re = {"edu": "education|qualifications?", "exp": "experience|work experience|employment|employment history|work history"}[kind]
        opener = lambda: agent._js(page, "p => JHQ.buttonFor(p)", button_re) or agent._js(page, "p => JHQ.sectionAdd(p)", heading_re)
        if not opener():
            continue
        rows = [r for r in rows if not r.get("full_history_only")][:MAX_ROWS]
        added = 0
        for row in rows:
            page_text = agent._js(page, """() => document.body.innerText + " " +
                JHQ.all('input, textarea').map(e => e.value || '').join(' | ')""")
            if row.get(key) and row[key] in page_text and (kind == "exp" or any(
                    row.get(k) and row[k] in page_text for k in ("degree", "form_degree", "field", "form_field"))):
                continue                       # already on the form
            bid = opener()
            if not bid:
                break
            try:
                _loc(page, bid).click(timeout=5000)
            except Exception:
                break
            page.wait_for_timeout(1000)
            panel = agent._js(page, "() => JHQ.panel()")
            if not panel:
                break
            if _fill_panel(page, panel, row, kind):
                try:
                    _loc(page, panel["save"]).click(timeout=5000)
                    page.wait_for_timeout(1200)
                    added += 1
                except Exception:
                    break
        if added:
            agent.log(f"Added {added} {'education' if kind == 'edu' else 'work history'} entries from your career details")
        total += added
    return total


def fill_skill_boxes(agent, page, career) -> int:
    """Plain "Skill:" boxes with an "Add a skill" button (Tesco and similar)."""
    skills = career.get("skills", [])[:15]
    if not skills or not agent._js(page, "p => JHQ.labelled(p)", r"^skills?:?$"):
        return 0
    added = 0
    for skill in skills:
        boxes = agent._js(page, "p => JHQ.labelled(p)", r"^skills?:?$")
        if any(b["value"].lower() == skill.lower() for b in boxes):
            continue
        empty = next((b for b in boxes if not b["value"]), None)
        if empty is None:
            bid = agent._js(page, "p => JHQ.buttonFor(p)", r"^\W*add (a |another )?skill")
            if not bid:
                break
            try:
                _loc(page, bid).click(timeout=4000)
                page.wait_for_timeout(500)
            except Exception:
                break
            boxes = agent._js(page, "p => JHQ.labelled(p)", r"^skills?:?$")
            empty = next((b for b in boxes if not b["value"]), None)
            if empty is None:
                break
        try:
            _loc(page, empty["id"]).fill(skill, timeout=4000)
            added += 1
        except Exception:
            break
    if added:
        agent.log(f"Added {added} skills from your career details")
    return added


def fill_sections(agent, page, career) -> int:
    total = 0
    for fn in (fill_experience, fill_education, fill_languages, fill_skills, fill_inline, fill_popups, fill_skill_boxes):
        try:
            total += fn(agent, page, career)
        except Exception as e:
            if agent._transient(e):
                raise
            agent.log(f"Couldn't finish {fn.__name__.replace('fill_', '')}: {str(e).splitlines()[0][:100]}")
    return total
