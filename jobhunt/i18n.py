"""Job Hunt HQ in other languages. The pages are written in English; for someone who chose another language the
finished page is translated on its way out (every label, button, heading and menu in the table), and anything
longer the table doesn't cover is translated by the browser itself, on the person's own device, where it can."""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

LANGS = [("en", "English"), ("fr", "Français"), ("de", "Deutsch"), ("nl", "Nederlands"), ("es", "Español"),
         ("pt", "Português"), ("ar", "العربية")]
CODES = [c for c, _ in LANGS]
TABLE_COLUMNS = ["en", "fr", "de", "nl", "es", "pt"]     # the columns of i18n_table.txt
RTL = {"ar"}                                              # languages written right to left
_TABLE: dict[str, dict[str, str]] | None = None
_PATTERNS: dict[str, list] = {}


def table() -> dict[str, dict[str, str]]:
    global _TABLE
    if _TABLE is None:
        _TABLE = {c: {} for c in CODES[1:]}
        for line in (Path(__file__).with_name("i18n_table.txt")).read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != len(TABLE_COLUMNS):
                continue
            for code, text in zip(TABLE_COLUMNS[1:], parts[1:]):
                _TABLE[code][parts[0]] = text
        # languages kept in a file of their own: i18n_<code>.txt, one "English|translation" per line
        for code in CODES[1:]:
            extra = Path(__file__).with_name(f"i18n_{code}.txt")
            if not extra.is_file():
                continue
            for line in extra.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#") and line.count("|") == 1:
                    en, tr = (x.strip() for x in line.split("|"))
                    _TABLE[code][en] = tr
    return _TABLE


def patterns(lang: str) -> list:
    """Table rows with gaps ("Applied {date}", "{role}: add a number…") as patterns that match the finished text."""
    if lang not in _PATTERNS:
        out = []
        for en, tr in table().get(lang, {}).items():
            names = re.findall(r"\{(\w+)\}", en)
            if not names or len(set(names)) != len(names):
                continue
            rx = re.escape(en)
            for n in names:
                rx = rx.replace(re.escape("{" + n + "}"), rf"(?P<{n}>\d+)" if n == "n" else rf"(?P<{n}>.+?)", 1)
            out.append((re.compile(rx), tr))
        out.sort(key=lambda p: -len(p[0].pattern))                 # the most specific first
        _PATTERNS[lang] = out
    return _PATTERNS[lang]


def pick(preferred: str | None, accept: str | None = "") -> str:
    if preferred in CODES:
        return preferred
    for part in (accept or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in CODES:
            return code
    return "en"


# ---------------------------------------------------------------- whole sentences
# A sentence with a link or bold words in it ("Click <b>Load unpacked</b> and choose the <b>…</b> folder.") is
# translated as ONE sentence, so each language can put the words in its own order. Its key in the table marks the
# inline bits with numbered brackets: "Click [1]Load unpacked[/1] and choose the [2]Job Hunt HQ Assistant[/2] folder."
# The translation uses the same brackets, in whatever order the language needs; the tags themselves are put back.
BLOCK = re.compile(r"<(p|li|h[1-6]|dt|dd|td|th|figcaption|small|label|summary|em)(\s[^>]*)?>"
                   r"((?:(?!</?(?:p|li|div|ul|ol|h[1-6]|section|form|input|select|textarea|button|table|tr|td|svg|img|"
                   r"label|summary|details|dl|dt|dd|nav|header|footer|figure|figcaption)\b)[\s\S])*?)</\1>", re.I)
INLINE = re.compile(r"<(a|b|strong|i|em|span|code|kbd|q)(\s[^>]*)?>([^<]*)</\1>|<br\s*/?>", re.I)
COLLECT = None                     # a path: sentences with no translation yet are written there (for translators)


def _sentence_key(inner: str):
    """'Click <b>X</b> now' → ('Click [1]X[/1] now', [('<b>', '</b>')]), or None if it isn't one simple sentence."""
    tags, parts, pos = [], [], 0
    for m in INLINE.finditer(inner):
        parts.append(inner[pos:m.start()])
        if m.group(0).lower().startswith("<br"):
            parts.append("[br]")
        else:
            tags.append((m.group(0)[:m.start(3) - m.start()], f"</{m.group(1)}>"))
            parts.append(f"[{len(tags)}]{m.group(3)}[/{len(tags)}]")
        pos = m.end()
    parts.append(inner[pos:])
    if not tags or "<" in "".join(p for p in parts if not p.startswith("[")):
        return None
    key = _html.unescape(re.sub(r"\s+", " ", "".join(parts)).strip())
    outside = re.sub(r"\[(\d+)\].*?\[/\1\]|\[br\]", " ", key)
    # only real sentences: words outside the bold or linked bits (a lone wrapped label is left to the word-by-word pass)
    return (key, tags) if re.search(r"[A-Za-z\u0600-\u06FF]{3}", outside) else None


def _rebuild(text: str, tags) -> str | None:
    out, pos = [], 0
    for m in re.finditer(r"\[(\d+)\](.*?)\[/\1\]|\[br\]", text):
        out.append(_html.escape(text[pos:m.start()], quote=False))
        if m.group(0) == "[br]":
            out.append("<br>")
        else:
            k = int(m.group(1)) - 1
            if k >= len(tags):
                return None
            out.append(tags[k][0] + _html.escape(m.group(2), quote=False) + tags[k][1])
        pos = m.end()
    out.append(_html.escape(text[pos:], quote=False))
    return "".join(out)


def sentences(chunk: str, t: dict) -> str:
    def one(m):
        found = _sentence_key(m.group(3))
        if not found:
            return m.group(0)
        key, tags = found
        hit = t.get(key)
        nums = re.findall(r"\d+", re.sub(r"\[/?\d+\]", "", key))
        if hit is None and len(nums) == 1:
            hit = t.get(re.sub(r"(?<!\[)(?<!\[/)\b\d+\b(?!\])", "{n}", key))
            hit = hit.replace("{n}", nums[0]) if hit else None
        if hit is None:
            if COLLECT:
                with open(COLLECT, "a", encoding="utf-8") as f:
                    f.write(key + "\n")
            return m.group(0)
        inner = _rebuild(hit, tags)
        return m.group(0) if inner is None else m.group(0)[:m.start(3) - m.start()] + inner + f"</{m.group(1)}>"
    return BLOCK.sub(one, chunk)


SKIP = re.compile(r"(<(script|style|textarea|code|pre)\b.*?</\2>)", re.S | re.I)
TEXT = re.compile(r">(\s*)([^<>]*?[A-Za-z][^<>]*?)(\s*)<")
ATTR = re.compile(r'\b(placeholder|title|aria-label)="([^"]*[A-Za-z][^"]*)"')


def translate(page: str, lang: str) -> str:
    if lang == "en" or lang not in CODES:
        return page
    t = table()[lang]

    def look(raw: str) -> str | None:
        hit = t.get(raw)
        if hit is not None:
            return hit
        nums = re.findall(r"\d+", raw)
        if len(nums) == 1:                                  # "See all 12 applications" -> "See all {n} applications"
            hit = t.get(re.sub(r"\d+", "{n}", raw))
            if hit is not None:
                return hit.replace("{n}", nums[0])
        head, sep, rest = raw.partition(": ")               # "Ready to submit: <job title>"
        if sep and head in t:
            return f"{t[head]}: {rest}"
        if "{" in raw:
            return None
        for rx, tr_ in patterns(lang):                     # "Applied 14 Oct" -> "Applied {date}"
            m = rx.fullmatch(raw)
            if m:
                try:
                    return tr_.format(**m.groupdict())
                except (KeyError, IndexError, ValueError):
                    return None
        return None

    def tr(text: str) -> str | None:
        raw = _html.unescape(re.sub(r"\s+", " ", text).strip())
        hit = look(raw)
        if hit is None and " · " in raw:                    # reasons and details joined with " · "
            parts = [p for p in raw.split(" · ")]
            done = [look(p) for p in parts]
            if any(d is not None for d in done):
                hit = " · ".join(d if d is not None else p for d, p in zip(done, parts))
        return _html.escape(hit, quote=False) if hit is not None else None

    def node(m):
        new = tr(m.group(2))
        return f">{m.group(1)}{new}{m.group(3)}<" if new is not None else m.group(0)

    def attr(m):
        if m.group(1) == "value" and m.group(2).startswith(("http", "/")):
            return m.group(0)
        new = tr(m.group(2))
        return f'{m.group(1)}="{_html.escape(new)}"' if new is not None else m.group(0)

    out = []
    for i, chunk in enumerate(SKIP.split(page)):
        if chunk is None:
            continue
        if SKIP.fullmatch(chunk or ""):
            out.append(chunk)
        elif re.fullmatch(r"script|style|textarea|code|pre", chunk or "", re.I):
            continue
        else:
            chunk = sentences(chunk, t)                    # whole sentences with links or bold words first
            chunk = TEXT.sub(node, chunk + "<")[:-1]      # text right before a <textarea> ends the chunk
            out.append(ATTR.sub(attr, chunk))
    page = "".join(out)
    return re.sub(r'<html lang="[^"]*"', f'<html lang="{lang}"' + (' dir="rtl"' if lang in RTL else ''), page, count=1)


DAYS = {"fr": "lun mar mer jeu ven sam dim", "de": "Mo Di Mi Do Fr Sa So", "nl": "ma di wo do vr za zo",
        "es": "lun mar mié jue vie sáb dom", "pt": "seg ter qua qui sex sáb dom",
        "ar": "الاثنين الثلاثاء الأربعاء الخميس الجمعة السبت الأحد"}
MONTHS = {"fr": "janv févr mars avr mai juin juil août sept oct nov déc",
          "de": "Jan Feb Mär Apr Mai Jun Jul Aug Sep Okt Nov Dez",
          "nl": "jan feb mrt apr mei jun jul aug sep okt nov dec",
          "es": "ene feb mar abr may jun jul ago sep oct nov dic",
          "pt": "jan fev mar abr mai jun jul ago set out nov dez",
          "ar": "يناير فبراير مارس أبريل مايو يونيو يوليو أغسطس سبتمبر أكتوبر نوفمبر ديسمبر"}


def phrase(text: str, lang: str, **values) -> str:
    """A sentence with gaps in it ("{n} matches to look through"): translated whole, then the gaps filled in."""
    template = table().get(lang, {}).get(text, text) if lang in CODES[1:] else text
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        return text.format(**values)


DE_MONTHS = "Januar Februar März April Mai Juni Juli August September Oktober November Dezember"


def date_label(d, lang: str) -> str:
    """Home's date line, the way each language writes it: 'Tue 3 Nov 2026', 'Di., 3. November 2026'."""
    if lang == "de":
        return f"{DAYS['de'].split()[d.weekday()]}., {d.day}. {DE_MONTHS.split()[d.month - 1]} {d.year}"
    if lang not in DAYS:
        return f"{d:%a} {d.day} {d:%b} {d.year}"
    return f"{DAYS[lang].split()[d.weekday()]} {d.day} {MONTHS[lang].split()[d.month - 1]} {d.year}"
