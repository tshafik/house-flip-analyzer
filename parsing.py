"""Listing-text parsing, URL slug parsing, best-effort scraping, and comp extraction."""

from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# =============================================================================
# CONSTANTS
# =============================================================================

PRE_YEAR_FLAG = 1980

# Keywords that get flagged when found in the listing text.
FLAG_KEYWORDS = {
    "as-is": r"\bas[\s\-]?is\b",
    "cash only": r"\bcash[\s\-]?only\b",
    "multiple offers": r"\bmultiple offers?\b",
    "highest and best": r"\bhighest\s*(?:and|&)\s*best\b",
    "handyman": r"\bhandy[\s\-]?man\b",
    "TLC": r"\bTLC\b",
    "investor special": r"\binvestors?\s*special\b",
    # extras
    "fixer-upper": r"\bfixer[\s\-]?upper\b",
    "needs work": r"\bneeds?\s+(?:some\s+)?work\b",
    "no repairs": r"\bno\s+repairs?\b",
    "bring your contractor": r"\bbring\s+your\s+contractor\b",
    "estate sale": r"\bestate\s+sale\b",
    "foundation": r"\bfoundation\s+(?:issue|problem|repair|crack)",
    "mold": r"\bmold\b",
    "flood": r"\bflood(?:ed|ing|\s+zone)?\b",
}

SAMPLE_LISTING = """1234 Maple St, Springfield, OH 45503
$189,900
3 bd | 2 ba | 1,450 sqft
Single Family Residence, Built in 1962
Lot: 7,405 sqft
42 days on market

Investor special! Handyman fixer-upper sold AS-IS, cash only preferred.
Needs TLC but solid bones. ARV of approx $310k based on recent sales on the
street. Would rent for $1,800/mo. Seller reviewing multiple offers, submit
highest and best by Friday.

Schools
Kenwood Elementary School  6/10
Roosevelt Middle School  5/10
Springfield High School  7/10

Price/sqft: $131
Zestimate: $201,300

Recently sold homes nearby
$298,000
3 bds 2 ba 1,380 sqft - Sold Jun 14, 2026
1210 Maple St, Springfield, OH 45503
$315,500
4 bds 2 ba 1,610 sqft - Sold May 2, 2026
1187 Oak Ave, Springfield, OH 45503
$305,000
3 bds 2 ba 1,455 sqft - Sold Jul 21, 2026
1302 Maple St, Springfield, OH 45503
$279,900
3 bds 1.5 ba 1,320 sqft - Sold Apr 9, 2026
940 Elm Ct, Springfield, OH 45503
$322,000
3 bds 2.5 ba 1,700 sqft - Sold Aug 3, 2026
1415 Birch Ln, Springfield, OH 45503
$334,900
4 bds 3 ba 2,050 sqft - Sold Feb 28, 2026
1550 Cedar Dr, Springfield, OH 45503
"""

_STREET_SUFFIX = (
    r"(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Blvd|Boulevard|"
    r"Way|Pl|Place|Ter|Terrace|Cir|Circle|Pkwy|Parkway|Hwy|Highway|Trl|Trail|Loop)"
)
_NOT_LETTER = r"(?![A-Za-z])"

# =============================================================================
# BASIC HELPERS
# =============================================================================


def to_number(s: str | None) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("$", "")
    mult = 1.0
    if s.lower().endswith("k"):
        mult, s = 1_000.0, s[:-1]
    elif s.lower().endswith("m"):
        mult, s = 1_000_000.0, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _first(patterns: list[str], text: str, flags=re.I) -> str | None:
    for p in patterns:
        m = re.search(p, text, flags)
        if m:
            return m.group(1)
    return None


def html_to_text(raw: str) -> str:
    if re.search(r"<\s*(html|body|div|span|p|meta|script)\b", raw, re.I):
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text("\n")
    return raw


def normalize_text(text: str) -> str:
    text = html_lib.unescape(text)
    text = text.replace(" ", " ").replace("–", "-").replace("—", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


# =============================================================================
# FIELD PARSERS
# =============================================================================


def parse_address(text: str) -> str | None:
    m = re.search(
        r"(\d{1,6}[A-Za-z]?[ \t]+[A-Za-z0-9.'\- ]{2,60}?,\s*[A-Za-z .'\-]{2,40},\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?)",
        text,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(
        r"(\d{1,6}[A-Za-z]?[ \t]+[A-Za-z0-9.'\- ]{2,60}?" + _STREET_SUFFIX + r"\.?,\s*[A-Za-z .'\-]{2,40},\s*[A-Z]{2}\b)",
        text,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"^(\d{1,6}[A-Za-z]?[ \t]+[A-Za-z0-9.'\- ]{2,60}?" + _STREET_SUFFIX + r"\.?)\s*$", text, re.M)
    if m:
        return m.group(1).strip()
    return None


def parse_zip(address: str | None) -> str | None:
    if not address:
        return None
    m = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", address.strip())
    return m.group(1) if m else None


def parse_list_price(text: str) -> float | None:
    labeled = _first(
        [
            r"(?:list(?:ed|ing)?\s*price|asking\s*price|price|listed\s*(?:for|at))\s*[:\-]?\s*\$\s?([\d,]{5,}(?:\.\d+)?)",
            r"\$\s?([\d,]{5,})\s*(?:list(?:ed|ing)?\s*price|asking)",
        ],
        text,
    )
    if labeled:
        v = to_number(labeled)
        if v and v >= 20_000:
            return v
    for m in re.finditer(r"\$\s?([\d,]{5,}(?:\.\d+)?)(?:\s*(k|K))?", text):
        v = to_number(m.group(1))
        if not v or v < 20_000:
            continue
        after = text[m.end(): m.end() + 14].lower()
        before = text[max(0, m.start() - 40): m.start()].lower()
        if re.match(r"\s*(?:/|per)\s*(?:mo|month|yr|year)", after):
            continue
        if re.search(r"zestimate|estimate|tax|arv|after repair|rent|worth", before):
            continue
        return v
    return None


def parse_beds(text: str) -> float | None:
    v = _first(
        [
            r"(\d+(?:\.\d)?)\s*(?:bd|bds|bed|beds|bedroom|bedrooms)" + _NOT_LETTER,
            r"(?:bedrooms?|beds?)\s*[:\-]\s*(\d+(?:\.\d)?)",
        ],
        text,
    )
    return to_number(v)


def parse_baths(text: str) -> float | None:
    v = _first(
        [
            r"(\d+(?:\.\d+)?)\s*(?:ba|bath|baths|bathroom|bathrooms)" + _NOT_LETTER,
            r"(?:bathrooms?|baths?)\s*[:\-]\s*(\d+(?:\.\d+)?)",
        ],
        text,
    )
    if v is None:
        m = re.search(r"(\d+)\s*full(?:\s*bath)?s?(?:,|\s|and)+\s*(\d+)\s*half", text, re.I)
        if m:
            return float(m.group(1)) + 0.5 * float(m.group(2))
    return to_number(v)


def _is_lot_context(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 30): end + 30].lower()
    return "lot" in window or "acre" in window or "land" in window


def parse_sqft(text: str) -> float | None:
    labeled_patterns = [
        r"(?:total\s+)?(?:interior\s+)?(?:livable|living)\s*area\s*[:\-]?\s*([\d,]{3,})",
        r"(?:square\s*footage|sq\.?\s*ft\.?|sqft|home\s*size|size)\s*[:\-]\s*([\d,]{3,})",
    ]
    for p in labeled_patterns:
        for m in re.finditer(p, text, re.I):
            if _is_lot_context(text, m.start(), m.end()):
                continue
            v = to_number(m.group(1))
            if v and 200 <= v <= 30_000:
                return v
    for m in re.finditer(r"([\d,]{3,})\s*(?:sq\.?\s?ft\.?|sqft|square\s*feet|sf)" + _NOT_LETTER, text, re.I):
        if _is_lot_context(text, m.start(), m.end()):
            continue
        v = to_number(m.group(1))
        if v and 200 <= v <= 30_000:
            return v
    return None


def parse_lot_size(text: str) -> str | None:
    m = re.search(
        r"lot(?:\s*size|\s*area)?\s*[:\-]?\s*([\d,.]+)\s*(acres?|ac|sq\.?\s?ft\.?|sqft|square\s*feet)",
        text,
        re.I,
    )
    if not m:
        m = re.search(r"([\d,.]+)\s*(acres?|ac|sq\.?\s?ft\.?|sqft|square\s*feet)\s*lot", text, re.I)
    if not m:
        m = re.search(r"([\d.]+)\s*(acres?)\b", text, re.I)
    if m:
        num, unit = m.group(1), m.group(2).lower()
        unit = "acres" if unit.startswith("ac") else "sqft"
        return f"{num} {unit}"
    return None


def parse_year_built(text: str) -> int | None:
    v = _first(
        [
            r"(?:year\s*built|built\s*in|built)\s*[:\-]?\s*((?:18|19|20)\d{2})\b",
            r"\b((?:18|19|20)\d{2})\s*(?:build|built)\b",
        ],
        text,
    )
    return int(v) if v else None


def parse_days_on_market(text: str) -> int | None:
    v = _first(
        [
            r"(\d+)\s*days?\s*on\s*(?:the\s*)?(?:market|zillow|redfin|realtor|site)",
            r"(?:days?\s*on\s*(?:market|zillow|redfin)|DOM)\s*[:\-]?\s*(\d+)",
            r"listed\s*(\d+)\s*days?\s*ago",
            r"(\d+)\s*days?\s*(?:listed|ago)",
        ],
        text,
    )
    if v is None:
        if re.search(r"\b(?:listed|on\s*market)\s*(?:today|1\s*day\s*ago)|\b(?:new|just)\s*listed\b", text, re.I):
            return 0
        return None
    return int(v)


_SCHOOL_NAME = (
    r"([A-Z][A-Za-z.'\-& ]{2,60}?"
    r"(?:(?:Elementary|Middle|High|Academy|Prep|Charter|Intermediate|Junior\s+High|Senior\s+High)\s+School"
    r"|School|Elementary|Middle|High|Academy|Prep|Charter))"
)
_SCHOOL_NAME_RE = re.compile(_SCHOOL_NAME + r"\b")
_RATING_RE = re.compile(r"\b(\d{1,2})\s*/\s*10\b")


def _school_line(line: str) -> re.Match | None:
    if re.search(r"greatschools", line, re.I):
        return None
    return _SCHOOL_NAME_RE.search(line)


def parse_school_ratings(text: str) -> str | None:
    found: list[str] = []
    lines = [ln.strip() for ln in text.split("\n")]
    i = 0
    while i < len(lines):
        nm = _school_line(lines[i])
        if nm:
            rt = _RATING_RE.search(lines[i])
            if rt:
                found.append(f"{nm.group(1).strip()}: {rt.group(1)}/10")
            else:
                for j in range(i + 1, min(i + 6, len(lines))):
                    if _school_line(lines[j]):
                        break
                    rt = _RATING_RE.search(lines[j])
                    if rt:
                        found.append(f"{nm.group(1).strip()}: {rt.group(1)}/10")
                        i = j
                        break
        i += 1
    if not found:
        ratings = [r for r in re.findall(r"\b(\d{1,2})\s*/\s*10\b", text) if 1 <= int(r) <= 10]
        if ratings:
            found = [f"{r}/10" for r in ratings[:6]]
    if not found:
        m = re.search(r"GreatSchools\s*(?:rating|score)?\s*[:\-]?\s*(\d{1,2})", text, re.I)
        if m:
            found = [f"GreatSchools {m.group(1)}/10"]
    seen, out = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return "; ".join(out) if out else None


def parse_agent_claims(text: str) -> list[str]:
    """ARV / rent figures the *listing itself* claims. Unverified."""
    claims: list[str] = []
    for m in re.finditer(
        r"\b(?:ARV|after[\s\-]repair(?:ed)?\s*value)\b[^$\d\n]{0,25}\$?\s?([\d,]{2,}(?:\.\d+)?\s?[kKmM]?)", text
    ):
        v = to_number(m.group(1).replace(" ", ""))
        if v and v >= 10_000:
            claims.append(f"ARV claim: ${v:,.0f}")
    for m in re.finditer(
        r"(?:rent(?:s|al|ed)?(?:\s*income)?|cash\s*flow|lease[sd]?)\b[^$\n]{0,30}\$\s?([\d,]{3,}(?:\.\d+)?)", text, re.I
    ):
        v = to_number(m.group(1))
        if v and 200 <= v <= 50_000:
            claims.append(f"Rent claim: ${v:,.0f}/mo")
    for m in re.finditer(r"\$\s?([\d,]{3,})\s*(?:/|per|a)\s*(?:mo|month|mth)\b", text, re.I):
        v = to_number(m.group(1))
        before = text[max(0, m.start() - 60): m.start()].lower()
        if v and 200 <= v <= 50_000 and re.search(r"rent|lease|tenant|income", before):
            claims.append(f"Rent claim: ${v:,.0f}/mo")
    for m in re.finditer(r"\b(?:cap\s*rate)\b[^\d\n]{0,15}(\d{1,2}(?:\.\d+)?)\s*%", text, re.I):
        claims.append(f"Cap rate claim: {m.group(1)}%")
    seen, out = set(), []
    for c in claims:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def parse_avms(text: str) -> list[dict[str, Any]]:
    """Third-party automated valuations printed on the listing page (Zestimate etc.)."""
    out = []
    for label, pat in [
        ("Zestimate", r"zestimate[^$\n]{0,20}\$\s?([\d,]{5,})"),
        ("Redfin Estimate", r"redfin\s*estimate[^$\n]{0,20}\$\s?([\d,]{5,})"),
        ("Realtor.com Estimate", r"(?:realtor\.com|realestimate|estimated\s*(?:home\s*)?value)[^$\n]{0,20}\$\s?([\d,]{5,})"),
    ]:
        m = re.search(pat, text, re.I)
        if m:
            v = to_number(m.group(1))
            if v and v >= 20_000:
                out.append({"source": label, "value": v})
    return out


def parse_keyword_flags(text: str) -> list[str]:
    return [label for label, pattern in FLAG_KEYWORDS.items() if re.search(pattern, text, re.I)]


def parse_listing_text(raw: str) -> dict[str, Any]:
    text = normalize_text(html_to_text(raw))
    fields = {
        "address": parse_address(text),
        "list_price": parse_list_price(text),
        "beds": parse_beds(text),
        "baths": parse_baths(text),
        "sqft": parse_sqft(text),
        "lot_size": parse_lot_size(text),
        "year_built": parse_year_built(text),
        "days_on_market": parse_days_on_market(text),
        "school_ratings": parse_school_ratings(text),
        "agent_claims": parse_agent_claims(text),
        "avms": parse_avms(text),
        "keyword_flags": parse_keyword_flags(text),
        "_text": text,
    }
    fields["comps"] = parse_comps(text, subject_price=fields["list_price"], subject_sqft=fields["sqft"], subject_address=fields["address"])
    return fields


# =============================================================================
# COMPARABLE SALES PARSER
# =============================================================================

_COMP_PRICE_RE = re.compile(r"\$\s?([\d,]{6,})(?!\s*(?:/|per)\s*(?:mo|month))")
_SOLD_DATE_RE = re.compile(
    r"(?:sold|closed)\s*(?:on\s*)?[:\-]?\s*("
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4})",
    re.I,
)
_SKIP_BEFORE = re.compile(
    r"zestimate|estimate|tax|payment|price\s*cut|price\s*change|listed\s*for|list\s*price|assessed|loan|down|/mo|rent|arv",
    re.I,
)


def _status_of(chunk: str) -> str | None:
    if re.search(r"\bsold\b|\bclosed\b", chunk, re.I):
        return "Sold"
    if re.search(r"\bpending\b|under\s*contract", chunk, re.I):
        return "Pending"
    if re.search(r"\bfor\s*sale\b|\bactive\b", chunk, re.I):
        return "Active"
    return None


def _parse_comp_window(after: str, before: str) -> dict[str, Any]:
    # Look in the text *after* the price first; the 'before' window can overlap the previous comp.
    date_m = _SOLD_DATE_RE.search(after) or _SOLD_DATE_RE.search(before)
    dist_m = re.search(r"([\d.]+)\s*mi\b", after) or re.search(r"([\d.]+)\s*mi\b", before)
    return {
        "beds": parse_beds(after) or parse_beds(before),
        "baths": parse_baths(after) or parse_baths(before),
        "sqft": parse_sqft(after) or parse_sqft(before),
        "year_built": parse_year_built(after),
        "status": _status_of(after) or _status_of(before) or "Active",
        "sold_date": date_m.group(1) if date_m else "",
        "distance_mi": to_number(dist_m.group(1)) if dist_m else None,
    }


def parse_comps(
    text: str,
    subject_price: float | None = None,
    subject_sqft: float | None = None,
    subject_address: str | None = None,
) -> list[dict[str, Any]]:
    """Extract comparable sales from pasted text (Zillow 'recently sold', Redfin sold search, etc.).

    Each comp needs a price and a square footage to be usable in the $/sqft model.
    """
    text = normalize_text(html_to_text(text))
    matches = list(_COMP_PRICE_RE.finditer(text))
    candidates = []
    for i, m in enumerate(matches):
        price = to_number(m.group(1))
        if not price or price < 20_000:
            continue
        label_before = text[max(0, m.start() - 45): m.start()]
        if _SKIP_BEFORE.search(label_before):
            continue
        prev_end = matches[i - 1].end() if i > 0 else 0
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        before = text[max(prev_end, m.start() - 220): m.start()]
        after = text[m.end(): min(next_start, m.end() + 320)]
        candidates.append((price, before, after))

    # Decide whether addresses sit before or after the price line in this paste
    votes_after = sum(1 for _, b, a in candidates if parse_address(a))
    votes_before = sum(1 for _, b, a in candidates if parse_address(b))
    addr_after = votes_after >= votes_before

    comps: list[dict[str, Any]] = []
    seen = set()
    for price, before, after in candidates:
        info = _parse_comp_window(after, before)
        addr = parse_address(after) if addr_after else parse_address(before)
        if not addr:
            addr = parse_address(before) if addr_after else parse_address(after)
        if not info["sqft"]:
            continue
        # Skip the subject property itself
        if subject_price and abs(price - subject_price) < 1 and (not subject_sqft or abs((info["sqft"] or 0) - subject_sqft) < 1):
            continue
        if subject_address and addr and addr.lower() == subject_address.lower():
            continue
        key = (addr or "", price, info["sqft"])
        if key in seen:
            continue
        seen.add(key)
        comps.append({
            "use": True,
            "address": addr or "(address not found)",
            "status": info["status"],
            "sold_date": info["sold_date"],
            "price": price,
            "sqft": info["sqft"],
            "beds": info["beds"],
            "baths": info["baths"],
            "year_built": info["year_built"],
            "distance_mi": info["distance_mi"],
            "condition": "",
            "source": "Pasted text",
        })
    return comps


# =============================================================================
# "MY RESEARCH" TABLE PARSER
# Columns: Property | Sqft | Bed/Bath | Condition | Sold / Final Price Indicator
# Accepts tab-, pipe-, comma-, or multi-space-separated rows (spreadsheet paste works).
# =============================================================================

_RESEARCH_HEADER_WORDS = ("property", "address", "sqft", "bed", "condition", "price", "comp")


def _split_research_line(line: str) -> list[str]:
    if "\t" in line:
        cells = line.split("\t")
    elif "|" in line:
        cells = line.split("|")
    elif re.search(r"\s{2,}", line):
        cells = re.split(r"\s{2,}", line)
    else:
        cells = re.split(r",(?!\s?\d{3}\b)", line)  # commas, but not the thousands separator in $215,000
    return [c.strip() for c in cells]


def _parse_bed_bath(cell: str) -> tuple[float | None, float | None]:
    m = re.search(r"(\d+(?:\.\d)?)\s*(?:/|-|bd|bed[s]?|br)\s*(\d+(?:\.\d)?)", cell, re.I)
    if m:
        return float(m.group(1)), float(m.group(2))
    return parse_beds(cell), parse_baths(cell)


def parse_research_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Do NOT run normalize_text here: it collapses tabs, which are the column separators in a spreadsheet paste.
    text = html_lib.unescape(text).replace(" ", " ").replace("\r", "")
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        cells = _split_research_line(line)
        if len(cells) < 2:
            continue
        first = cells[0].lower()
        if any(first.startswith(w) for w in _RESEARCH_HEADER_WORDS) and not re.match(r"\d", first):
            continue  # header row
        prop = cells[0]
        sqft = to_number(re.sub(r"[^\d.,]", "", cells[1])) if len(cells) > 1 else None
        beds, baths = _parse_bed_bath(cells[2]) if len(cells) > 2 else (None, None)
        condition = cells[3] if len(cells) > 3 else ""
        price_cell = cells[4] if len(cells) > 4 else " ".join(cells[1:])
        pm = re.search(r"\$?\s?([\d,]{3,}(?:\.\d+)?\s?[kKmM]?)", price_cell)
        price = to_number(pm.group(1).replace(" ", "")) if pm else None
        if price and price < 1000:  # "215k" style without $ handled above; guard against sqft-like numbers
            price = None
        status = "Sold"
        if re.search(r"pending|under contract", price_cell, re.I):
            status = "Pending"
        elif re.search(r"active|list(?:ed|ing)?\b|asking|for sale", price_cell, re.I):
            status = "Active"
        date_m = re.search(r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})", price_cell, re.I)
        if not (sqft or price):
            continue
        rows.append({
            "use": True,
            "address": prop,
            "status": status,
            "sold_date": date_m.group(1) if date_m else "",
            "price": price,
            "sqft": sqft,
            "beds": beds,
            "baths": baths,
            "year_built": None,
            "distance_mi": None,
            "condition": condition,
            "source": "My research",
        })
    return rows


# =============================================================================
# ADDRESS FROM URL SLUG
# =============================================================================

_SUFFIX_TOKENS = {
    "st", "street", "ave", "avenue", "rd", "road", "dr", "drive", "ln", "lane", "ct", "court",
    "blvd", "boulevard", "way", "pl", "place", "ter", "terrace", "cir", "circle", "pkwy", "parkway",
    "hwy", "highway", "trl", "trail", "loop", "run", "path", "pike", "sq", "square", "cv", "cove",
    "xing", "crossing", "row", "walk", "aly", "alley", "byp", "bypass", "expy", "fm", "cr",
}
_UNIT_TOKENS = {"apt", "unit", "ste", "suite", "fl", "lot", "bldg", "#", "no", "spc", "space", "trlr"}
_KEEP_UPPER = {"n", "s", "e", "w", "ne", "nw", "se", "sw", "fm", "cr", "us", "sr"}


def _tc(tok: str) -> str:
    if any(ch.isdigit() for ch in tok):
        return tok.upper()
    if tok.isupper():
        return tok
    if tok.lower() in _KEEP_UPPER:
        return tok.upper()
    return tok[:1].upper() + tok[1:]


def _assemble(street_tokens: list[str], city_tokens: list[str], state: str, zipc: str) -> str:
    street = " ".join(_tc(t) for t in street_tokens)
    city = " ".join(_tc(t) for t in city_tokens)
    return ", ".join(p for p in [street, city, f"{state.upper()} {zipc}".strip()] if p)


def _split_street_city(tokens: list[str]) -> tuple[list[str], list[str]]:
    last_suffix = max((i for i, t in enumerate(tokens) if t.lower() in _SUFFIX_TOKENS), default=-1)
    if last_suffix < 0:
        cut = 2 if len(tokens) > 2 else 1
        return tokens[:cut], tokens[cut:]
    end = last_suffix + 1
    while end < len(tokens):
        t = tokens[end].lower()
        if any(ch.isdigit() for ch in t) or t in _UNIT_TOKENS:
            end += 1
            if t in _UNIT_TOKENS and end < len(tokens):
                end += 1
        else:
            break
    return tokens[:end], tokens[end:]


def address_from_url(url: str) -> str | None:
    try:
        path = urlparse(url).path
    except Exception:
        return None
    segs = [s for s in path.split("/") if s]
    host = url.lower()
    try:
        if "redfin.com" in host and len(segs) >= 3 and re.fullmatch(r"[A-Za-z]{2}", segs[0]):
            state, city = segs[0], segs[1].replace("-", " ")
            toks = segs[2].split("-")
            zipc = toks.pop() if toks and re.fullmatch(r"\d{5}", toks[-1]) else ""
            return _assemble(toks, city.split(" "), state, zipc)
        if "realtor.com" in host:
            for s in segs:
                parts = s.split("_")
                if len(parts) >= 4 and re.fullmatch(r"[A-Za-z]{2}", parts[2]) and re.fullmatch(r"\d{5}", parts[3]):
                    return _assemble(parts[0].split("-"), parts[1].split("-"), parts[2], parts[3])
        for s in segs:
            toks = s.split("-")
            for i in range(len(toks) - 1, 0, -1):
                if re.fullmatch(r"\d{5}", toks[i]) and re.fullmatch(r"[A-Za-z]{2}", toks[i - 1]):
                    state, zipc = toks[i - 1], toks[i]
                    street, city = _split_street_city(toks[: i - 1])
                    if street and re.match(r"\d", street[0]):
                        return _assemble(street, city, state, zipc)
    except Exception:
        return None
    return None


# =============================================================================
# URL SCRAPING (best effort)
# =============================================================================

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

BLOCKED_HELP = (
    "Click **Open listing** to view it in your browser, select-all + copy the page, "
    "paste it in the text box, then Analyze again."
)


def _walk_jsonld(obj: Any, out: dict[str, Any]) -> None:
    if isinstance(obj, list):
        for o in obj:
            _walk_jsonld(o, out)
        return
    if not isinstance(obj, dict):
        return
    addr = obj.get("address")
    if isinstance(addr, dict) and not out.get("address"):
        parts = [
            addr.get("streetAddress"),
            addr.get("addressLocality"),
            " ".join(str(x) for x in [addr.get("addressRegion"), addr.get("postalCode")] if x),
        ]
        joined = ", ".join(str(p).strip() for p in parts if p)
        if joined:
            out["address"] = joined
    offers = obj.get("offers")
    if isinstance(offers, dict) and offers.get("price") and not out.get("list_price"):
        out["list_price"] = to_number(str(offers["price"]))
    if obj.get("price") and not out.get("list_price"):
        out["list_price"] = to_number(str(obj["price"]))
    for k_src, k_dst in [("numberOfRooms", "beds"), ("numberOfBedrooms", "beds"), ("numberOfBathroomsTotal", "baths")]:
        if obj.get(k_src) and not out.get(k_dst):
            out[k_dst] = to_number(str(obj[k_src]))
    fs = obj.get("floorSize")
    if isinstance(fs, dict) and fs.get("value") and not out.get("sqft"):
        out["sqft"] = to_number(str(fs["value"]))
    if obj.get("yearBuilt") and not out.get("year_built"):
        try:
            out["year_built"] = int(str(obj["yearBuilt"])[:4])
        except ValueError:
            pass
    for v in obj.values():
        if isinstance(v, (dict, list)):
            _walk_jsonld(v, out)


def scrape_url(url: str) -> tuple[dict[str, Any] | None, str, str | None]:
    """Returns (parsed_fields, page_text, error_message)."""
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
    except requests.RequestException as e:
        return None, "", f"Request failed: {e}"
    if resp.status_code != 200:
        return None, "", f"Site returned HTTP {resp.status_code} (bot-blocked). {BLOCKED_HELP}"
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.get_text(" ") if soup.title else ""
    meta_bits = []
    for prop in ("og:title", "og:description", "description"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            meta_bits.append(tag["content"])
    jsonld_scripts = [s.string or "" for s in soup.find_all("script", attrs={"type": "application/ld+json"})]
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    body_text = soup.get_text("\n")
    page_text = "\n".join([title] + meta_bits + [body_text])
    if re.search(r"captcha|access denied|are you a (?:human|robot)|press\s*&\s*hold|unusual traffic", page_text, re.I) and len(body_text) < 6000:
        return None, "", f"Site served a bot-check / captcha page. {BLOCKED_HELP}"

    fields = parse_listing_text(page_text)
    jsonld: dict[str, Any] = {}
    for s in jsonld_scripts:
        try:
            _walk_jsonld(json.loads(s), jsonld)
        except (json.JSONDecodeError, TypeError):
            continue
    for k, v in jsonld.items():
        if v:
            fields[k] = v
    found = [k for k in ("address", "list_price", "beds", "baths", "sqft") if fields.get(k)]
    if len(found) < 2:
        return fields, page_text, "Page fetched but very little listing data was found. Paste the listing text for better results."
    return fields, page_text, None
