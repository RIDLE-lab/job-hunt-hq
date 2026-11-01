"""Turn a CV (from cv.build) into a PDF in one of three designs, or a Word document."""
from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, ListFlowable, ListItem, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from .cv import ACCENTS

FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
_FONTS = None


def _fonts():
    """Use a bundled TTF when one is available (proper £ and – everywhere), else Helvetica."""
    global _FONTS
    if _FONTS:
        return _FONTS
    reg, bold = "Helvetica", "Helvetica-Bold"
    for name in ("DejaVuSans", "Inter", "NotoSans"):
        r, b = FONT_DIR / f"{name}.ttf", FONT_DIR / f"{name}-Bold.ttf"
        if r.exists() and b.exists():
            try:
                pdfmetrics.registerFont(TTFont("CV", str(r)))
                pdfmetrics.registerFont(TTFont("CV-Bold", str(b)))
                reg, bold = "CV", "CV-Bold"
                break
            except Exception:
                pass
    _FONTS = (reg, bold)
    return _FONTS


def esc(t) -> str:
    return (str(t or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles(accent: str, compact: bool, light=False):
    reg, bold = _fonts()
    base = 9.2 if compact else 10
    lead = base * (1.28 if compact else 1.38)
    ink = HexColor("#1d232b")
    soft = HexColor("#5a6470")
    acc = HexColor(accent)
    s = {
        "name": ParagraphStyle("name", fontName=bold, fontSize=22 if not compact else 19, leading=26, textColor=white if light else ink),
        "headline": ParagraphStyle("headline", fontName=reg, fontSize=11.5, leading=15, textColor=white if light else acc),
        "contact": ParagraphStyle("contact", fontName=reg, fontSize=8.8, leading=12, textColor=white if light else soft),
        "h": ParagraphStyle("h", fontName=bold, fontSize=10.5 if not compact else 9.8, leading=13, textColor=acc,
                            spaceBefore=9 if not compact else 6, spaceAfter=3),
        "role": ParagraphStyle("role", fontName=bold, fontSize=base + 0.6, leading=lead, textColor=ink),
        "meta": ParagraphStyle("meta", fontName=reg, fontSize=base - 1, leading=lead - 1, textColor=soft),
        "body": ParagraphStyle("body", fontName=reg, fontSize=base, leading=lead, textColor=ink, alignment=TA_LEFT),
        "side_h": ParagraphStyle("sh", fontName=bold, fontSize=9.6, leading=12, textColor=white, spaceBefore=10, spaceAfter=3),
        "side": ParagraphStyle("sd", fontName=reg, fontSize=8.8, leading=11.6, textColor=white),
    }
    return s


def _heading(text, s, accent, width):
    t = Table([[Paragraph(esc(text).upper(), s["h"])]], colWidths=[width])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.8, HexColor(accent)),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    t.spaceBefore, t.spaceAfter = s["h"].spaceBefore, 4
    t.keepWithNext = True              # never leave a heading alone at the foot of a page
    return t


def _bullets(items, s, compact):
    return ListFlowable([ListItem(Paragraph(esc(b), s["body"]), leftIndent=10, value="•") for b in items],
                        bulletType="bullet", start="•", leftIndent=11, bulletFontSize=9, bulletOffsetY=-0.5,
                        spaceBefore=1, spaceAfter=2 if compact else 4)


def _role_block(e, s, width, compact):
    left = f"<b>{esc(e['title'])}</b>" + (f" · {esc(e['company'])}" if e["company"] else "")
    head = Table([[Paragraph(left, s["role"]), Paragraph(esc(e["dates"]), s["meta"])]],
                 colWidths=[width * 0.72, width * 0.28])
    head.setStyle(TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    s["meta"].alignment = 2
    parts = [head]
    if e.get("location"):
        loc = ParagraphStyle("loc", parent=s["meta"], alignment=0)
        parts.append(Paragraph(esc(e["location"]), loc))
    if e["bullets"]:
        parts.append(_bullets(e["bullets"], s, compact))
    else:
        parts.append(Spacer(1, 4))
    return KeepTogether(parts[:2] + parts[2:]) if len(e["bullets"]) <= 6 else parts


def _main_sections(cv, s, accent, width, compact, include_side_parts=True):
    out = []
    if cv["summary"]:
        out += [_heading("Profile", s, accent, width), Paragraph(esc(cv["summary"]), s["body"])]
    if cv["experience"]:
        out.append(_heading("Experience", s, accent, width))
        for e in cv["experience"]:
            blk = _role_block(e, s, width, compact)
            out += blk if isinstance(blk, list) else [blk]
    if cv["education"]:
        out.append(_heading("Education", s, accent, width))
        for ed in cv["education"]:
            line = f"<b>{esc(ed['qualification'])}</b>" + (f" · {esc(ed['school'])}" if ed["school"] else "")
            if ed["result"]:
                line += f" – {esc(ed['result'])}"
            t = Table([[Paragraph(line, s["body"]), Paragraph(esc(ed["dates"]), s["meta"])]],
                      colWidths=[width * 0.7, width * 0.3])
            t.setStyle(TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
            out.append(t)
    if include_side_parts:
        if cv["skills"]:
            out += [_heading("Skills", s, accent, width), Paragraph(" · ".join(esc(x) for x in cv["skills"]), s["body"])]
        if cv["certifications"]:
            out += [_heading("Certifications", s, accent, width), _bullets(cv["certifications"], s, compact)]
        if cv["languages"]:
            out += [_heading("Languages", s, accent, width), Paragraph(" · ".join(esc(x) for x in cv["languages"]), s["body"])]
    return out


def pdf(cv: dict, design: str = "classic", accent: str = "navy") -> bytes:
    colour = ACCENTS.get(accent, accent if str(accent).startswith("#") else ACCENTS["navy"])
    buf = io.BytesIO()
    W, H = A4
    compact = design == "compact"
    margin = 13 * mm if compact else 16 * mm
    meta = dict(title=f"{cv['name']} CV", author=cv["name"], subject="Curriculum vitae")

    if design == "modern":
        side_w = 64 * mm
        s = _styles(colour, False)
        sl = _styles(colour, False, light=True)

        def paint(c, doc):
            c.saveState()
            c.setFillColor(HexColor(colour))
            c.rect(0, 0, side_w, H, stroke=0, fill=1)
            c.restoreState()
        doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=0, rightMargin=0, topMargin=0, bottomMargin=0, **meta)
        side = Frame(9 * mm, 12 * mm, side_w - 16 * mm, H - 24 * mm, id="side", showBoundary=0,
                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        main_w = W - side_w - 12 * mm - 14 * mm
        main = Frame(side_w + 12 * mm, 12 * mm, main_w, H - 24 * mm, id="main",
                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        later = Frame(side_w + 12 * mm, 12 * mm, main_w, H - 24 * mm, id="later",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates([PageTemplate(id="first", frames=[side, main], onPage=paint),
                              PageTemplate(id="rest", frames=[later], onPage=paint)])
        from reportlab.platypus import FrameBreak, NextPageTemplate
        story = [Paragraph(esc(cv["name"]), ParagraphStyle("n", parent=sl["name"], fontSize=19, leading=23)),
                 Paragraph(esc(cv["headline"]), sl["headline"]), Spacer(1, 6)]
        story.append(Paragraph("CONTACT", sl["side_h"]))
        story += [Paragraph(esc(c), sl["side"]) for c in cv["contact"]]
        if cv["skills"]:
            story.append(Paragraph("SKILLS", sl["side_h"]))
            story += [Paragraph("• " + esc(x), sl["side"]) for x in cv["skills"][:22]]
        if cv["languages"]:
            story.append(Paragraph("LANGUAGES", sl["side_h"]))
            story += [Paragraph(esc(x), sl["side"]) for x in cv["languages"]]
        if cv["certifications"]:
            story.append(Paragraph("CERTIFICATIONS", sl["side_h"]))
            story += [Paragraph("• " + esc(x), sl["side"]) for x in cv["certifications"][:8]]
        story += [NextPageTemplate("rest"), FrameBreak()]
        story += _main_sections(cv, s, colour, main_w, False, include_side_parts=False)
        doc.build(story)
        return buf.getvalue()

    s = _styles(colour, compact)
    if design == "classic":            # a traditional, centred heading in a serif face
        for k in ("name", "headline", "contact"):
            s[k].alignment = 1
        s["name"].fontName, s["name"].fontSize, s["name"].leading = "Times-Bold", 25, 29
        s["h"].fontName, s["h"].fontSize = "Times-Bold", 12
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin,
                          bottomMargin=margin, **meta)
    width = W - 2 * margin
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(margin, margin, width, H - 2 * margin, id="f",
                                                             leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    story = [Paragraph(esc(cv["name"]), s["name"])]
    if cv["headline"]:
        story.append(Paragraph(esc(cv["headline"]), s["headline"]))
    if cv["contact"]:
        story += [Spacer(1, 2), Paragraph("  |  ".join(esc(c) for c in cv["contact"]), s["contact"])]
    story.append(Spacer(1, 4 if compact else 6))
    story += _main_sections(cv, s, colour, width, compact)
    doc.build(story)
    return buf.getvalue()


def docx(cv: dict, accent: str = "navy") -> bytes:
    from docx import Document
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    colour = ACCENTS.get(accent, ACCENTS["navy"]).lstrip("#")
    rgb = RGBColor.from_string(colour.upper())
    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Mm(16))
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10.5)
    st.paragraph_format.space_after = Pt(2)
    right = sec.page_width - sec.left_margin - sec.right_margin

    def para(text="", bold=False, size=None, color=None, after=2, tab=None):
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(after)
        if tab is not None:
            p.paragraph_format.tab_stops.add_tab_stop(right, WD_TAB_ALIGNMENT.RIGHT)
        r = p.add_run(text)
        r.bold = bold
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = color
        return p

    def heading(text):
        p = para(text.upper(), bold=True, size=11, color=rgb, after=3)
        p.paragraph_format.space_before = Pt(9)
        pPr = p._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        b = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", colour)):
            b.set(qn(k), v)
        bdr.append(b)
        pPr.append(bdr)

    para(cv["name"], bold=True, size=22, after=0)
    if cv["headline"]:
        para(cv["headline"], size=12, color=rgb, after=1)
    if cv["contact"]:
        para("  |  ".join(cv["contact"]), size=9, color=RGBColor(0x5A, 0x64, 0x70), after=4)
    if cv["summary"]:
        heading("Profile")
        para(cv["summary"])
    if cv["experience"]:
        heading("Experience")
        for e in cv["experience"]:
            p = para(after=0, tab=True)
            r = p.add_run(e["title"])
            r.bold = True
            if e["company"]:
                p.add_run(f" · {e['company']}")
            p.add_run(f"\t{e['dates']}").font.color.rgb = RGBColor(0x5A, 0x64, 0x70)
            if e.get("location"):
                para(e["location"], size=9, color=RGBColor(0x5A, 0x64, 0x70), after=1)
            for b in e["bullets"]:
                bp = d.add_paragraph(b, style="List Bullet")
                bp.paragraph_format.space_after = Pt(1)
            d.paragraphs[-1].paragraph_format.space_after = Pt(5)
    if cv["education"]:
        heading("Education")
        for ed in cv["education"]:
            p = para(after=2, tab=True)
            p.add_run(ed["qualification"]).bold = True
            if ed["school"]:
                p.add_run(f" · {ed['school']}")
            if ed["result"]:
                p.add_run(f" – {ed['result']}")
            p.add_run(f"\t{ed['dates']}").font.color.rgb = RGBColor(0x5A, 0x64, 0x70)
    if cv["skills"]:
        heading("Skills")
        para(" · ".join(cv["skills"]))
    if cv["certifications"]:
        heading("Certifications")
        for c in cv["certifications"]:
            d.add_paragraph(c, style="List Bullet")
    if cv["languages"]:
        heading("Languages")
        para(" · ".join(cv["languages"]))
    d.core_properties.author = cv["name"]
    d.core_properties.title = f"{cv['name']} CV"
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()
