"""PDF deal report built with reportlab."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#0B1F3A")
TEAL = colors.HexColor("#0F766E")
GREEN = colors.HexColor("#15803D")
YELLOW = colors.HexColor("#B45309")
RED = colors.HexColor("#B91C1C")
GRAY = colors.HexColor("#6B7280")
LIGHT = colors.HexColor("#F3F4F6")
LINE = colors.HexColor("#E5E7EB")


def _money(v: float | None) -> str:
    if v is None or v == "":
        return "—"
    v = float(v)
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{float(v):,.1f}%"


def _n(v) -> str:
    """Compact number: 3.0 -> '3', 2.5 -> '2.5', None -> '—'."""
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{int(f)}" if f == int(f) else f"{f:g}"


def _band_color(band: str):
    return {"green": GREEN, "yellow": YELLOW, "red": RED}.get(band, NAVY)


def build_pdf(
    s: dict[str, Any],
    m: dict[str, Any],
    flags: list[str],
    claims: list[str],
    research: dict[str, Any] | None,
    avms: list[dict[str, Any]],
    roi_band: str,
    offer_band_70: str,
    prepared_by: str = "",
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        title=f"Deal Summary - {s.get('address') or 'Property'}", author=prepared_by or "Fix & Flip Analyzer",
    )
    ss = getSampleStyleSheet()
    h_title = ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=colors.white, alignment=TA_LEFT, spaceAfter=0)
    h_sub = ParagraphStyle("s", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5, textColor=colors.HexColor("#CBD5E1"), leading=14)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=NAVY, spaceBefore=14, spaceAfter=6)
    body = ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=colors.HexColor("#1F2937"))
    small = ParagraphStyle("sm", parent=body, fontSize=8, leading=10.5, textColor=GRAY)
    cell = ParagraphStyle("c", parent=body, fontSize=8.5, leading=11)
    cell_b = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold")
    metric_lbl = ParagraphStyle("ml", parent=body, fontSize=7.5, textColor=GRAY, leading=9)

    W = letter[0] - doc.leftMargin - doc.rightMargin
    story: list[Any] = []

    # ---- Header band
    addr = s.get("address") or "Property"
    facts = " · ".join(
        p for p in [
            f"{int(s['beds'])} bd" if s.get("beds") else "",
            f"{s['baths']:g} ba" if s.get("baths") else "",
            f"{s['sqft']:,.0f} sqft" if s.get("sqft") else "",
            f"Built {int(s['year_built'])}" if s.get("year_built") else "",
            f"Lot {s['lot_size']}" if s.get("lot_size") else "",
        ] if p
    )
    head = Table(
        [[Paragraph("FIX &amp; FLIP DEAL SUMMARY", ParagraphStyle("k", parent=h_sub, fontSize=8.5, textColor=colors.HexColor("#99F6E4"), leading=11))],
         [Paragraph(addr, h_title)],
         [Paragraph(facts or " ", h_sub)],
         [Paragraph(f"List price {_money(s.get('list_price'))}  ·  Prepared {datetime.now():%B %d, %Y}" + (f"  ·  {prepared_by}" if prepared_by else ""), h_sub)]],
        colWidths=[W],
    )
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 16), ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, 0), 12), ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
        ("TOPPADDING", (0, 1), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -2), 2),
    ]))
    story += [head, Spacer(1, 12)]

    # ---- Metric grid
    def metric(label: str, value: str, color=NAVY):
        return [Paragraph(label.upper(), metric_lbl), Paragraph(f'<font color="{color.hexval()}"><b>{value}</b></font>', ParagraphStyle("mv", parent=body, fontSize=15, leading=18))]

    roi_c = _band_color(roi_band)
    grid_cells = [
        metric("Est. ROI", _pct(m.get("roi")), roi_c),
        metric("Est. Total Profit", _money(m.get("profit")), roi_c),
        metric("Max Offer (70% rule)", _money(m.get("max_offer_70")), _band_color(offer_band_70)),
        metric("Total Cash Deployed", _money(m.get("cash_deployed"))),
    ]
    grid = Table([[Table([[c[0]], [c[1]]], colWidths=[W / 4 - 8]) for c in grid_cells]], colWidths=[W / 4] * 4)
    grid.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [grid, Spacer(1, 4)]

    # ---- Deal structure (two columns: assumptions | profit waterfall)
    story.append(Paragraph("Deal structure", h2))
    assumptions = [
        ["Purchase price (offer)", _money(m.get("offer_used"))],
        ["Estimated rehab", _money(s.get("rehab"))],
        ["Closing costs", _money(s.get("closing"))],
        ["Holding period", f"{s.get('months', 0)} months × {_money(s.get('monthly_carry'))}/mo"],
        ["Total carrying cost", _money(m.get("carrying_total"))],
        ["Selling costs (7% of ARV)", _money(m.get("selling"))],
        ["Price / sqft (list)", f"${m['price_per_sqft']:,.0f}" if m.get("price_per_sqft") else "—"],
        ["Max offer (65% rule)", _money(m.get("max_offer_65"))],
    ]
    waterfall = [
        ["After-repair value (ARV)", _money(s.get("arv"))],
        ["− Purchase", _money(-(m.get("offer_used") or 0))],
        ["− Rehab", _money(-(s.get("rehab") or 0))],
        ["− Closing", _money(-(s.get("closing") or 0))],
        ["− Carrying", _money(-(m.get("carrying_total") or 0))],
        ["− Selling", _money(-(m.get("selling") or 0))],
        ["= Estimated profit", _money(m.get("profit"))],
        ["ROI on cash deployed", _pct(m.get("roi"))],
    ]

    def kv_table(rows, bold_last=False):
        t = Table([[Paragraph(a, cell), Paragraph(b, cell_b if (bold_last and i >= len(rows) - 2) else cell)] for i, (a, b) in enumerate(rows)], colWidths=[W / 2 * 0.62 - 6, W / 2 * 0.38 - 6])
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]))
        if bold_last:
            t.setStyle(TableStyle([("BACKGROUND", (0, -2), (-1, -1), LIGHT)]))
        return t

    two = Table([[kv_table(assumptions), kv_table(waterfall, bold_last=True)]], colWidths=[W / 2, W / 2])
    two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (-1, 0), (-1, 0), 0)]))
    story.append(two)

    # ---- ARV evidence
    story.append(Paragraph("ARV evidence", h2))
    if research and research.get("ok"):
        story.append(Paragraph(
            f"<b>Comps model:</b> {research['basis']} = <b>{_money(research['point'])}</b> "
            f"(25th–75th percentile range {_money(research['low'])} – {_money(research['high'])}; "
            f"similarity-weighted {_money(research['weighted'])}). "
            f"{research['n']} comps in model, {research['n_sold']} sold. Confidence: <b>{research['confidence']}</b>.",
            body,
        ))
        for n in research.get("notes", []):
            story.append(Paragraph(f"• {n}", small))
        rows = [[Paragraph(h, cell_b) for h in ["Address", "Status / date", "Price", "Sqft", "$/sqft", "Bd/Ba", "In model"]]]
        for r in research["rows"]:
            rows.append([
                Paragraph(str(r.get("address") or ""), cell),
                Paragraph(f"{r.get('status','')} {r.get('sold_date','')}".strip(), cell),
                Paragraph(_money(r.get("price")), cell),
                Paragraph(f"{r['sqft']:,.0f}", cell),
                Paragraph(f"${r['ppsf']:,.0f}", cell),
                Paragraph(f"{_n(r.get('beds'))}/{_n(r.get('baths'))}", cell),
                Paragraph("✓" if r.get("in_model") else "–", cell),
            ])
        ct = Table(rows, colWidths=[W * 0.34, W * 0.17, W * 0.12, W * 0.09, W * 0.09, W * 0.09, W * 0.10], repeatRows=1)
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story += [Spacer(1, 4), ct]
    else:
        story.append(Paragraph("No comparable-sales model was run. ARV shown is a manual estimate.", body))
    if s.get("arv_notes"):
        story.append(Paragraph(f"<b>ARV notes:</b> {s['arv_notes']}", body))
    extra = [f"{a['source']}: {_money(a['value'])}" for a in avms]
    if extra:
        story.append(Paragraph("<b>Third-party automated estimates (context only):</b> " + "; ".join(extra), body))
    ctx = s.get("market_context")
    if ctx and ctx.get("ok"):
        parts = [p for p in [
            f"median home value {_money(ctx['median_home_value'])}" if ctx.get("median_home_value") else "",
            f"median year built {int(ctx['median_year_built'])}" if ctx.get("median_year_built") else "",
            f"median rent {_money(ctx['median_gross_rent'])}/mo" if ctx.get("median_gross_rent") else "",
        ] if p]
        if parts:
            story.append(Paragraph(f"<b>ZIP market context ({ctx.get('vintage')}):</b> " + ", ".join(parts) + ".", body))

    # ---- Risks
    story.append(Paragraph("Risks &amp; red flags", h2))
    if flags:
        for f in flags:
            story.append(Paragraph(f"• {f}", body))
    else:
        story.append(Paragraph("No red flags detected in the listing.", body))
    if claims:
        story.append(Paragraph("<b>Figures claimed in the listing (unverified, agent claims):</b> " + "; ".join(claims), small))

    # ---- Property facts + notes
    story.append(Paragraph("Property facts", h2))
    facts_rows = [
        ["Address", addr], ["List price", _money(s.get("list_price"))],
        ["Beds / Baths", f"{_n(s.get('beds') or None)} / {_n(s.get('baths') or None)}"],
        ["Sqft / Lot", f"{s['sqft']:,.0f}" if s.get("sqft") else "—"], ["Year built", str(int(s["year_built"])) if s.get("year_built") else "—"],
        ["Days on market", str(s.get("dom") or "—")], ["Schools", s.get("schools") or "—"],
    ]
    if s.get("lot_size"):
        facts_rows[3][1] += f" / {s['lot_size']}"
    if s.get("url"):
        facts_rows.append(["Listing", s["url"]])
    ft = Table([[Paragraph(a, cell_b), Paragraph(b, cell)] for a, b in facts_rows], colWidths=[W * 0.22, W * 0.78])
    ft.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(ft)
    if s.get("notes"):
        story += [Spacer(1, 6), Paragraph(f"<b>Notes:</b> {s['notes']}", body)]

    story += [Spacer(1, 14), Paragraph(
        "Estimates only. ARV, rehab, and cost figures are assumptions entered by the preparer or derived from publicly listed comparable sales, "
        "not appraisals. Verify all numbers independently before making an offer.", small)]

    doc.build(story)
    return buf.getvalue()
