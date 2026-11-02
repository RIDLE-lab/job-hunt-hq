"""Job Hunt HQ in other languages. The pages are written in English; for someone who chose another language the
finished page is translated on its way out (every label, button, heading and menu in the table), and anything
longer the table doesn't cover is translated by the browser itself, on the person's own device, where it can."""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

LANGS = [("en", "English"), ("fr", "Français"), ("de", "Deutsch"), ("nl", "Nederlands"), ("es", "Español"),
         ("pt", "Português")]
CODES = [c for c, _ in LANGS]
_TABLE: dict[str, dict[str, str]] | None = None


def table() -> dict[str, dict[str, str]]:
    global _TABLE
    if _TABLE is None:
        _TABLE = {c: {} for c in CODES[1:]}
        for line in (Path(__file__).with_name("i18n_table.txt")).read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != len(CODES):
                continue
            for code, text in zip(CODES[1:], parts[1:]):
                _TABLE[code][parts[0]] = text
    return _TABLE


def pick(preferred: str | None, accept: str | None = "") -> str:
    if preferred in CODES:
        return preferred
    for part in (accept or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in CODES:
            return code
    return "en"


SKIP = re.compile(r"(<(script|style|textarea|code|pre)\b.*?</\2>)", re.S | re.I)
TEXT = re.compile(r">(\s*)([^<>]*?[A-Za-z][^<>]*?)(\s*)<")
ATTR = re.compile(r'\b(placeholder|title|aria-label)="([^"]*[A-Za-z][^"]*)"')


def translate(page: str, lang: str) -> str:
    if lang == "en" or lang not in CODES:
        return page
    t = table()[lang]

    def tr(text: str) -> str | None:
        raw = _html.unescape(re.sub(r"\s+", " ", text).strip())
        hit = t.get(raw)
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
            chunk = TEXT.sub(node, chunk)
            out.append(ATTR.sub(attr, chunk))
    page = "".join(out)
    return re.sub(r'<html lang="[^"]*"', f'<html lang="{lang}"', page, count=1)
