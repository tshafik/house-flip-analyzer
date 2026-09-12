"""
Fix & Flip Property Analyzer
----------------------------
Run locally:   streamlit run app.py
Hosted:        Streamlit Community Cloud (see README)

Modules: parsing.py (listing + comps parsing), research.py (ARV model),
storage.py (CSV tracker), report.py (PDF).
"""

from __future__ import annotations

import html as html_lib
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from parsing import (
    PRE_YEAR_FLAG,
    SAMPLE_LISTING,
    address_from_url,
    parse_comps,
    parse_listing_text,
    parse_zip,
    scrape_url,
    to_number,
)
from report import build_pdf
from research import estimate_arv, fetch_census_zip, fetch_rentcast, summarize_research
from storage import (
    TRACKER_COLUMNS,
    TRACKER_CSV,
    append_tracker_row,
    delete_tracker_rows,
    load_tracker,
    overwrite_tracker,
    update_tracker_row,
)

SELLING_COST_PCT = 0.07
ROI_GREEN = 15.0
ROI_YELLOW = 8.0

# =============================================================================
# STYLE
# =============================================================================

STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [data-testid="stAppViewContainer"] *:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded):not([class*="material"]) { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
#MainMenu, footer, header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1240px; }
.hero { background: linear-gradient(120deg, #0B1F3A 0%, #0F3D5E 55%, #0F766E 100%); color: white; border-radius: 18px;
        padding: 24px 28px; margin-bottom: 10px; box-shadow: 0 10px 30px rgba(11,31,58,.18); }
.hero h1 { color: white; font-size: 1.65rem; font-weight: 800; margin: 0 0 4px 0; letter-spacing: -.01em; }
.hero p { color: #CBD5E1; margin: 0; font-size: .93rem; }
.hero .chip { display:inline-block; background: rgba(255,255,255,.13); border: 1px solid rgba(255,255,255,.25); color: white;
              padding: 4px 11px; border-radius: 999px; font-size: .78rem; margin-top: 12px; margin-right: 6px; }
.sec { display:flex; align-items:baseline; gap:10px; margin: 20px 0 4px 0; }
.sec .num { background:#0F766E; color:white; border-radius:8px; min-width:26px; height:26px; display:inline-flex;
            align-items:center; justify-content:center; font-size:.8rem; font-weight:700; }
.sec h3 { margin:0; font-size:1.08rem; font-weight:700; color:#0B1F3A; }
.sec .cap { color:#6B7280; font-size:.84rem; }
.metric { background:white; border:1px solid #E5E7EB; border-top: 4px solid var(--accent); border-radius:14px; padding:14px 16px;
          margin-bottom:12px; min-height:106px; box-shadow: 0 1px 3px rgba(16,24,40,.05); }
.metric .lbl { font-size:.72rem; color:#6B7280; text-transform:uppercase; letter-spacing:.06em; font-weight:600; }
.metric .val { font-size:1.7rem; font-weight:800; color: var(--accent); line-height:1.25; margin-top:2px; letter-spacing:-.01em; }
.metric .sub { font-size:.78rem; color:#6B7280; margin-top:4px; }
.flag  { background:#FFF7ED; border:1px solid #FED7AA; color:#9A3412; border-radius:10px; padding:8px 12px; margin-bottom:6px; font-size:.9rem; }
.claim { background:#EFF6FF; border:1px solid #BFDBFE; color:#1E3A8A; border-radius:10px; padding:8px 12px; margin-bottom:6px; font-size:.9rem; }
.ok    { background:#ECFDF5; border:1px solid #A7F3D0; color:#065F46; border-radius:10px; padding:8px 12px; font-size:.9rem; }
.muted { color:#6B7280; font-size:.85rem; }
.evidence { background:white; border:1px solid #E5E7EB; border-radius:14px; padding:14px 18px; margin-bottom:10px; }
.evidence b { color:#0B1F3A; }
div[data-testid="stTabs"] button[role="tab"] { font-weight:600; font-size:.95rem; }
.stButton > button, .stDownloadButton > button, .stLinkButton > a { border-radius: 10px; font-weight: 600; }
</style>
"""

ACCENT = {"green": "#15803D", "yellow": "#B45309", "red": "#B91C1C", "neutral": "#0B1F3A"}


def section(num: str, title: str, caption: str = "") -> None:
    cap = f'<span class="cap">{html_lib.escape(caption)}</span>' if caption else ""
    st.markdown(f'<div class="sec"><span class="num">{num}</span><h3>{html_lib.escape(title)}</h3>{cap}</div>', unsafe_allow_html=True)


def metric_card(label: str, value: str, band: str = "neutral", sub: str = "") -> str:
    sub_html = f'<div class="sub">{html_lib.escape(sub)}</div>' if sub else ""
    return (
        f'<div class="metric" style="--accent:{ACCENT[band]}"><div class="lbl">{html_lib.escape(label)}</div>'
        f'<div class="val">{html_lib.escape(value)}</div>{sub_html}</div>'
    )


def fmt_money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:,.1f}%"


# =============================================================================
# CALCULATIONS
# =============================================================================


def compute_metrics(list_price, sqft, arv, rehab, purchase_price, closing, months, monthly_carry) -> dict[str, Any]:
    price_per_sqft = (list_price / sqft) if list_price and sqft else None
    max_offer_70 = arv * 0.70 - rehab if arv else None
    max_offer_65 = arv * 0.65 - rehab if arv else None
    carrying_total = months * monthly_carry
    selling = arv * SELLING_COST_PCT if arv else 0.0
    offer = purchase_price if purchase_price else list_price
    profit = (arv - offer - rehab - closing - carrying_total - selling) if arv else None
    cash_deployed = offer + rehab + closing + carrying_total
    roi = (profit / cash_deployed * 100.0) if (profit is not None and cash_deployed > 0) else None
    return {
        "price_per_sqft": price_per_sqft, "max_offer_70": max_offer_70, "max_offer_65": max_offer_65,
        "carrying_total": carrying_total, "selling": selling, "offer_used": offer, "profit": profit,
        "cash_deployed": cash_deployed, "roi": roi,
    }


def roi_band(roi: float | None) -> str:
    if roi is None:
        return "neutral"
    return "green" if roi > ROI_GREEN else ("yellow" if roi >= ROI_YELLOW else "red")


def offer_band(max_offer: float | None, list_price: float) -> str:
    if max_offer is None or not list_price:
        return "neutral"
    return "green" if list_price <= max_offer else ("yellow" if list_price <= max_offer * 1.10 else "red")


# =============================================================================
# STATE
# =============================================================================

FIELD_DEFAULTS: dict[str, Any] = {
    "url": "", "raw_text": "",
    "address": "", "list_price": 0.0, "beds": 0.0, "baths": 0.0, "sqft": 0.0, "lot_size": "",
    "year_built": 0, "dom": 0, "schools": "",
    "arv": 0.0, "arv_notes": "", "rehab": 0.0, "purchase_price": 0.0, "closing": 0.0, "months": 6, "monthly_carry": 0.0,
    "notes": "",
    "keyword_flags": [], "agent_claims": [], "avms": [], "comps": [], "listing_text": "",
    "market_context": None, "rentcast": None,
    "analyzed": False, "missing": [], "scrape_msg": None, "editing_index": None,
}


def _r(v, nd: int = 0):
    if v is None or v == "":
        return ""
    try:
        v = round(float(v), nd)
    except (TypeError, ValueError):
        return v
    return int(v) if v == int(v) else v


def init_state() -> None:
    ss = st.session_state
    for k, v in FIELD_DEFAULTS.items():
        ss.setdefault(k, v)
    ss.setdefault("show_input", True)
    pending = ss.pop("_pending", None)
    if not pending:
        return
    action = pending.get("action")
    if action == "reset":
        for k, v in FIELD_DEFAULTS.items():
            ss[k] = v
        ss["url_w"], ss["raw_text_w"] = "", ""
        ss["show_input"] = True
    elif action == "sample":
        ss["raw_text"], ss["url"] = SAMPLE_LISTING, ""
        ss["raw_text_w"], ss["url_w"] = SAMPLE_LISTING, ""
        ss["show_input"] = True
    elif action == "collapse":
        ss["show_input"] = False
    elif action == "set_arv":
        ss["arv"] = float(pending["arv"])
        if pending.get("notes"):
            ss["arv_notes"] = pending["notes"]
    elif action == "load_row":
        row_to_state(pending["row"])
        ss["editing_index"] = pending["index"]
        ss["show_input"] = False


def _persist(wkey: str, skey: str) -> None:
    st.session_state[skey] = st.session_state[wkey]


def apply_parsed(fields: dict[str, Any], url: str) -> int:
    """Write parsed values into session state. Returns number of core fields found."""
    ss = st.session_state
    ss["address"] = fields.get("address") or ""
    ss["list_price"] = float(fields.get("list_price") or 0.0)
    ss["beds"] = float(fields.get("beds") or 0.0)
    ss["baths"] = float(fields.get("baths") or 0.0)
    ss["sqft"] = float(fields.get("sqft") or 0.0)
    ss["lot_size"] = fields.get("lot_size") or ""
    ss["year_built"] = int(fields.get("year_built") or 0)
    ss["dom"] = int(fields.get("days_on_market") or 0)
    ss["schools"] = fields.get("school_ratings") or ""
    ss["keyword_flags"] = fields.get("keyword_flags") or []
    ss["agent_claims"] = fields.get("agent_claims") or []
    ss["avms"] = fields.get("avms") or []
    ss["comps"] = fields.get("comps") or []
    ss["listing_text"] = fields.get("_text") or ""
    ss["purchase_price"] = 0.0
    ss["editing_index"] = None
    ss["market_context"], ss["rentcast"] = None, None
    ss["analyzed"] = True
    labels = [("address", "Address"), ("list_price", "List Price"), ("beds", "Beds"), ("baths", "Baths"), ("sqft", "Sqft"),
              ("lot_size", "Lot Size"), ("year_built", "Year Built"), ("days_on_market", "Days on Market"), ("school_ratings", "School Ratings")]
    ss["missing"] = [label for key, label in labels if not fields.get(key)]
    return sum(1 for key, _ in labels if fields.get(key))


def build_tracker_row(s: dict[str, Any], m: dict[str, Any], flags: list[str], claims: list[str], research_summary: str) -> dict[str, Any]:
    return {
        "Date Analyzed": datetime.now().strftime("%Y-%m-%d"),
        "Address": s["address"], "Listing URL": s["url"], "List Price": _r(s["list_price"]),
        "Beds": _r(s["beds"], 1) if s["beds"] else "", "Baths": _r(s["baths"], 1) if s["baths"] else "",
        "Sqft": _r(s["sqft"]), "Lot Size": s["lot_size"], "Year Built": s["year_built"] if s["year_built"] else "",
        "Days on Market": s["dom"], "School Ratings": s["schools"], "Price/Sqft": _r(m["price_per_sqft"], 2),
        "Est. ARV": _r(s["arv"]), "ARV Comps/Source": s["arv_notes"] or research_summary,
        "Est. Rehab Cost": _r(s["rehab"]), "Purchase Price": _r(m["offer_used"]), "Est. Closing Costs": _r(s["closing"]),
        "Holding Period (months)": s["months"], "Monthly Carrying Cost": _r(s["monthly_carry"]),
        "Total Carrying Cost": _r(m["carrying_total"]), "Selling Costs (7%)": _r(m["selling"]),
        "Max Offer (70%)": _r(m["max_offer_70"]), "Max Offer (65%)": _r(m["max_offer_65"]),
        "Est. Total Profit": _r(m["profit"]), "Est. ROI %": _r(m["roi"], 2),
        "Red Flags": "; ".join(flags), "Agent Claims (Unverified)": "; ".join(claims), "Notes": s["notes"],
    }


def row_to_state(row: dict[str, Any]) -> None:
    """Load a saved tracker row back into the analyzer form."""
    ss = st.session_state
    num = lambda k: float(to_number(str(row.get(k, ""))) or 0.0)  # noqa: E731
    txt = lambda k: "" if pd.isna(row.get(k, "")) else str(row.get(k, ""))  # noqa: E731
    ss["address"] = txt("Address")
    ss["url"] = txt("Listing URL")
    ss["url_w"] = ss["url"]
    ss["list_price"] = num("List Price")
    ss["beds"] = num("Beds")
    ss["baths"] = num("Baths")
    ss["sqft"] = num("Sqft")
    ss["lot_size"] = txt("Lot Size")
    ss["year_built"] = int(num("Year Built"))
    ss["dom"] = int(num("Days on Market"))
    ss["schools"] = txt("School Ratings")
    ss["arv"] = num("Est. ARV")
    ss["arv_notes"] = txt("ARV Comps/Source")
    ss["rehab"] = num("Est. Rehab Cost")
    ss["purchase_price"] = num("Purchase Price") if num("Purchase Price") != num("List Price") else 0.0
    ss["closing"] = num("Est. Closing Costs")
    ss["months"] = int(num("Holding Period (months)"))
    ss["monthly_carry"] = num("Monthly Carrying Cost")
    ss["notes"] = txt("Notes")
    flags = [f for f in txt("Red Flags").split("; ") if f]
    ss["keyword_flags"] = [f.split('"')[1] for f in flags if f.startswith("Listing says")]
    ss["agent_claims"] = [c for c in txt("Agent Claims (Unverified)").split("; ") if c]
    ss["avms"], ss["comps"], ss["market_context"], ss["rentcast"] = [], [], None, None
    ss["analyzed"], ss["missing"], ss["scrape_msg"] = True, [], None


# =============================================================================
# PASSWORD GATE (hosted deployments: set APP_PASSWORD in Streamlit secrets)
# =============================================================================


def password_gate() -> None:
    try:
        required = str(st.secrets.get("APP_PASSWORD", "")) if hasattr(st, "secrets") else ""
    except Exception:
        required = ""
    if not required or st.session_state.get("authed"):
        return
    st.markdown(STYLE, unsafe_allow_html=True)
    st.markdown('<div class="hero"><h1>🏚️ Fix & Flip Analyzer</h1><p>This deal room is private. Enter the access password to continue.</p></div>', unsafe_allow_html=True)
    pw = st.text_input("Password", type="password")
    if st.button("Enter", type="primary"):
        if pw == required:
            st.session_state["authed"] = True
            st.rerun()
        st.error("Incorrect password.")
    st.stop()


# =============================================================================
# UI PIECES
# =============================================================================


def render_hero() -> None:
    left, right = st.columns([5, 1.4])
    with left:
        st.markdown(
            '<div class="hero"><h1>🏚️ Fix &amp; Flip Property Analyzer</h1>'
            "<p>Underwrite a deal in minutes: pull the listing, research the ARV with comps, and export an investor-ready summary.</p>"
            '<span class="chip">70% / 65% rule</span><span class="chip">Comps-based ARV</span><span class="chip">PDF deal report</span><span class="chip">CSV tracker</span></div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown("<div style='height:22px'></div>", unsafe_allow_html=True)
        st.toggle("Show listing input", key="show_input", help="Hide the URL / paste box once a property is loaded to keep the page clean.")
        if st.session_state["address"]:
            st.markdown(f'<div class="muted">Loaded: <b>{html_lib.escape(st.session_state["address"])}</b></div>', unsafe_allow_html=True)
        if st.session_state["editing_index"] is not None:
            st.markdown(f'<div class="muted">Editing saved row #{st.session_state["editing_index"] + 1}</div>', unsafe_allow_html=True)


def render_input_section() -> None:
    ss = st.session_state
    section("1", "Listing input", "URL is best effort (Zillow / Redfin block bots). Pasting the listing page text is the reliable path.")
    ss.setdefault("url_w", ss["url"])
    ss.setdefault("raw_text_w", ss["raw_text"])
    st.text_input("Listing URL", key="url_w", on_change=_persist, args=("url_w", "url"), placeholder="https://www.zillow.com/homedetails/...")
    st.text_area(
        "Paste the listing text / HTML (open the listing, select-all, copy, paste here)",
        key="raw_text_w", on_change=_persist, args=("raw_text_w", "raw_text"), height=200,
        placeholder="1234 Maple St, Springfield, OH 45503\n$189,900\n3 bd | 2 ba | 1,450 sqft ...\n\nTip: Zillow pages include a 'Recently sold homes' section — paste it too and comps are extracted automatically.",
    )
    c1, c2, c3, c4, _ = st.columns([1, 1, 1, 1.2, 3.8])
    analyze = c1.button("🔎 Analyze", type="primary", width="stretch")
    if c2.button("Load sample", width="stretch"):
        ss["_pending"] = {"action": "sample"}
        st.rerun()
    if c3.button("Reset", width="stretch"):
        ss["_pending"] = {"action": "reset"}
        st.rerun()
    url = ss["url_w"].strip()
    if url.startswith("http"):
        c4.link_button("Open listing ↗", url, width="stretch", help="Opens in a new tab so you can select-all + copy the listing")

    if analyze:
        ss["url"], ss["raw_text"] = ss["url_w"], ss["raw_text_w"]
        raw = ss["raw_text"].strip()
        ss["scrape_msg"] = None
        fields: dict[str, Any] | None = None
        if raw:
            fields = parse_listing_text(raw)
            if url:
                ss["scrape_msg"] = ("info", "Pasted text was used (it takes priority over the URL).")
        elif url:
            with st.spinner("Fetching listing page..."):
                fields, _page_text, err = scrape_url(url)
            if err:
                ss["scrape_msg"] = ("warning" if fields else "error", err)
        else:
            ss["scrape_msg"] = ("error", "Enter a URL or paste listing text first.")
        if url and (fields is None or not fields.get("address")):
            slug_addr = address_from_url(url)
            if slug_addr:
                fields = fields or {}
                fields["address"] = slug_addr
                if ss["scrape_msg"] and ss["scrape_msg"][0] == "error":
                    ss["scrape_msg"] = ("warning", ss["scrape_msg"][1] + f"  \n\nAddress pre-filled from the URL: **{slug_addr}**")
        if fields:
            found = apply_parsed(fields, url)
            if found >= 4:
                ss["_pending"] = {"action": "collapse"}
                st.rerun()


def render_extracted_fields() -> None:
    section("2", "Listing facts", "Auto-filled after Analyze. Everything is editable.")
    r1 = st.columns([3, 1.5, 1, 1])
    r1[0].text_input("Address", key="address")
    r1[1].number_input("List Price ($)", key="list_price", min_value=0.0, step=1000.0, format="%.0f")
    r1[2].number_input("Beds", key="beds", min_value=0.0, step=1.0, format="%.0f")
    r1[3].number_input("Baths", key="baths", min_value=0.0, step=0.5, format="%.1f")
    r2 = st.columns([1, 1, 1, 1, 2])
    r2[0].number_input("Sqft", key="sqft", min_value=0.0, step=10.0, format="%.0f")
    r2[1].text_input("Lot Size", key="lot_size", placeholder="e.g. 0.25 acres")
    r2[2].number_input("Year Built", key="year_built", min_value=0, max_value=2100, step=1, format="%d")
    r2[3].number_input("Days on Market", key="dom", min_value=0, step=1, format="%d")
    r2[4].text_input("School Ratings", key="schools", placeholder="e.g. Elem 7/10; Middle 5/10")


def render_manual_inputs() -> None:
    section("3", "Underwriting inputs", "Your numbers. ARV can be filled from the ARV Research tab.")
    m1 = st.columns([1, 2])
    m1[0].number_input("Estimated ARV ($)", key="arv", min_value=0.0, step=5000.0, format="%.0f")
    m1[1].text_input("ARV comps / source notes", key="arv_notes", placeholder="Auto-filled from the comps model when you click 'Use this ARV'")
    m2 = st.columns(5)
    m2[0].number_input("Estimated Rehab Cost ($)", key="rehab", min_value=0.0, step=1000.0, format="%.0f")
    m2[1].number_input("Purchase Price / Offer ($)", key="purchase_price", min_value=0.0, step=1000.0, format="%.0f", help="Used in the profit calc. Leave at 0 to use the List Price.")
    m2[2].number_input("Est. Closing Costs ($)", key="closing", min_value=0.0, step=500.0, format="%.0f")
    m2[3].number_input("Holding Period (months)", key="months", min_value=0, step=1, format="%d")
    m2[4].number_input("Monthly Carrying Cost ($)", key="monthly_carry", min_value=0.0, step=100.0, format="%.0f")
    st.text_input("Notes", key="notes", placeholder="Anything worth remembering about this deal")


def render_metrics(m: dict[str, Any], band: str) -> None:
    ss = st.session_state
    section("4", "Underwriting metrics", "Updates live as you edit.")
    if not ss["arv"]:
        st.info("Enter an Estimated ARV (or run the ARV Research tab) to unlock offer, profit, and ROI.")

    def vs_list(max_offer):
        if max_offer is None or not ss["list_price"]:
            return ""
        diff = ss["list_price"] - max_offer
        return f" · list price is {fmt_money(abs(diff))} {'above' if diff > 0 else 'below'}"

    k = st.columns(4)
    k[0].markdown(metric_card("Est. ROI", fmt_pct(m["roi"]), band, f"Profit ÷ {fmt_money(m['cash_deployed'])} cash deployed"), unsafe_allow_html=True)
    k[1].markdown(metric_card("Est. Total Profit", fmt_money(m["profit"]), band, f"ARV − {fmt_money(m['offer_used'])} offer − rehab − closing − carrying − selling"), unsafe_allow_html=True)
    k[2].markdown(metric_card("Max Offer (70% rule)", fmt_money(m["max_offer_70"]), offer_band(m["max_offer_70"], ss["list_price"]), "ARV × 0.70 − rehab" + vs_list(m["max_offer_70"])), unsafe_allow_html=True)
    k[3].markdown(metric_card("Max Offer (65% rule)", fmt_money(m["max_offer_65"]), offer_band(m["max_offer_65"], ss["list_price"]), "ARV × 0.65 − rehab" + vs_list(m["max_offer_65"])), unsafe_allow_html=True)
    k2 = st.columns(4)
    k2[0].markdown(metric_card("Price / Sqft", f"${m['price_per_sqft']:,.0f}" if m["price_per_sqft"] else "—", "neutral", "List price ÷ sqft"), unsafe_allow_html=True)
    k2[1].markdown(metric_card("Total Carrying Cost", fmt_money(m["carrying_total"]), "neutral", f"{ss['months']} mo × {fmt_money(ss['monthly_carry'])}"), unsafe_allow_html=True)
    k2[2].markdown(metric_card("Selling Costs", fmt_money(m["selling"]), "neutral", f"{SELLING_COST_PCT:.0%} of ARV"), unsafe_allow_html=True)
    k2[3].markdown(metric_card("Total Cash Deployed", fmt_money(m["cash_deployed"]), "neutral", "Offer + rehab + closing + carrying"), unsafe_allow_html=True)
    st.markdown(f'<div class="muted">ROI bands: 🟢 &gt; {ROI_GREEN:.0f}% · 🟡 {ROI_YELLOW:.0f}–{ROI_GREEN:.0f}% · 🔴 &lt; {ROI_YELLOW:.0f}%. Max-offer cards turn green when the list price is at or below the max offer.</div>', unsafe_allow_html=True)


def compute_flags() -> tuple[list[str], list[str]]:
    ss = st.session_state
    flags: list[str] = []
    if ss["year_built"] and ss["year_built"] < PRE_YEAR_FLAG:
        flags.append(f"Built {ss['year_built']} (pre-{PRE_YEAR_FLAG}): budget for plumbing / electrical / possible lead paint or asbestos")
    for kw in ss["keyword_flags"]:
        flags.append(f'Listing says "{kw}"')
    return flags, list(ss["agent_claims"])


def render_flags(flags: list[str], claims: list[str]) -> None:
    ss = st.session_state
    section("5", "Red flags & agent claims")
    fcol, ccol = st.columns(2)
    with fcol:
        st.markdown("**⚠️ Property / listing flags**")
        if flags:
            for f in flags:
                st.markdown(f'<div class="flag">🚩 {html_lib.escape(f)}</div>', unsafe_allow_html=True)
        elif ss["analyzed"]:
            st.markdown('<div class="ok">No red flags detected.</div>', unsafe_allow_html=True)
        else:
            st.caption("Run Analyze to scan the listing.")
    with ccol:
        st.markdown("**🗣️ Figures claimed in the listing** <span class='muted'>(unverified — agent claim)</span>", unsafe_allow_html=True)
        if claims:
            for c in claims:
                st.markdown(f'<div class="claim">{html_lib.escape(c)}</div>', unsafe_allow_html=True)
            if ss["arv"]:
                for c in claims:
                    if c.startswith("ARV"):
                        claimed = to_number(c.split("$")[-1])
                        if claimed:
                            diff = claimed - ss["arv"]
                            st.caption(f"Agent ARV vs. your ARV: {'+' if diff >= 0 else '-'}{fmt_money(abs(diff))}")
        elif ss["analyzed"]:
            st.caption("No ARV / rent figures found in the listing text.")
        else:
            st.caption("Run Analyze to scan the listing.")


def render_save_export(m: dict[str, Any], flags: list[str], claims: list[str], research: dict[str, Any], band: str) -> None:
    ss = st.session_state
    section("6", "Save & export")
    row = build_tracker_row(dict(ss), m, flags, claims, summarize_research(research))
    c = st.columns([1.3, 1.3, 1.5, 3])
    editing = ss["editing_index"]
    if editing is not None:
        if c[0].button(f"💾 Update row #{editing + 1}", type="primary", width="stretch"):
            if update_tracker_row(editing, row):
                st.success(f"Updated saved row #{editing + 1}.")
            else:
                st.error("That row no longer exists. Save as new instead.")
        if c[1].button("Save as new", width="stretch"):
            append_tracker_row(row)
            ss["editing_index"] = None
            st.success("Saved as a new row.")
    else:
        if c[0].button("💾 Save to Tracker", type="primary", width="stretch"):
            if not ss["address"] and not ss["list_price"]:
                st.error("Nothing to save yet — analyze a listing or enter an address / list price.")
            else:
                append_tracker_row(row)
                st.success(f"Saved {ss['address'] or 'property'} to tracker.")
    try:
        pdf = build_pdf(dict(ss), m, flags, claims, research, ss["avms"], band, offer_band(m["max_offer_70"], ss["list_price"]))
        safe = "".join(ch if ch.isalnum() else "_" for ch in (ss["address"] or "property"))[:40]
        c[2].download_button("📄 Download PDF report", data=pdf, file_name=f"deal_summary_{safe}.pdf", mime="application/pdf", width="stretch")
    except Exception as e:  # pragma: no cover
        c[2].error(f"PDF failed: {e}")


# ----------------------------------------------------------------------------- ARV research tab


def comps_dataframe(comps: list[dict[str, Any]]) -> pd.DataFrame:
    cols = ["use", "address", "status", "sold_date", "price", "sqft", "beds", "baths", "year_built", "distance_mi", "source"]
    df = pd.DataFrame(comps, columns=cols) if comps else pd.DataFrame(columns=cols)
    df["use"] = df["use"].fillna(True).astype(bool)
    for c in ["price", "sqft", "beds", "baths", "year_built", "distance_mi"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def render_arv_tab() -> dict[str, Any]:
    ss = st.session_state
    subj = ss["address"] or "No property loaded"
    subj_facts = " · ".join(p for p in [f"{ss['sqft']:,.0f} sqft" if ss["sqft"] else "sqft unknown", f"{ss['beds']:.0f} bd" if ss["beds"] else "", f"{ss['baths']:g} ba" if ss["baths"] else "", f"list {fmt_money(ss['list_price'])}" if ss["list_price"] else ""] if p)
    st.markdown(f'<div class="evidence"><b>Subject:</b> {html_lib.escape(subj)} <span class="muted">· {html_lib.escape(subj_facts)}</span></div>', unsafe_allow_html=True)

    section("A", "Comparable sales", "Evidence for the ARV. Sold comps within ±35% of the subject's sqft drive the model.")
    with st.expander("➕ Add comps from pasted text", expanded=not ss["comps"]):
        st.caption(
            "On Zillow or Redfin, search **Sold** homes near the subject (last 6 months, similar size), select-all, copy, and paste here. "
            "Zillow listing pages also include a 'Recently sold homes' strip — that is extracted automatically when you Analyze."
        )
        comps_text = st.text_area("Sold comps text", key="comps_text", height=140, label_visibility="collapsed", placeholder="$298,000\n3 bds 2 ba 1,380 sqft - Sold Jun 14, 2026\n1210 Maple St, Springfield, OH 45503\n...")
        b1, b2, _ = st.columns([1.2, 1.2, 4])
        if b1.button("Extract comps", type="primary", width="stretch"):
            new = parse_comps(comps_text, subject_price=ss["list_price"], subject_sqft=ss["sqft"], subject_address=ss["address"])
            if new:
                existing = {(c["address"], c["price"], c["sqft"]) for c in ss["comps"]}
                added = [c for c in new if (c["address"], c["price"], c["sqft"]) not in existing]
                ss["comps"] = ss["comps"] + added
                st.success(f"Extracted {len(new)} comps ({len(added)} new).")
                st.rerun()
            else:
                st.warning("No comps found. Each comp needs a price and a square footage in the text.")
        if b2.button("Clear all comps", width="stretch"):
            ss["comps"] = []
            st.rerun()

    with st.expander("🔌 Optional data sources (free-tier API keys)"):
        st.caption("Both services offer a free key. Keys are kept in this browser session only and never saved.")
        k1, k2 = st.columns(2)
        with k1:
            st.text_input("RentCast API key", key="rentcast_key", type="password", help="Free: 50 requests / month at app.rentcast.io. Returns an AVM plus nearby comparable sales.")
            if st.button("Fetch RentCast AVM + comps", width="stretch", disabled=not (ss.get("rentcast_key") and ss["address"])):
                with st.spinner("Calling RentCast..."):
                    res = fetch_rentcast(ss["address"], ss["rentcast_key"], ss["sqft"] or None, ss["beds"] or None, ss["baths"] or None)
                ss["rentcast"] = res
                if res.get("ok"):
                    existing = {(c["address"], c["price"], c["sqft"]) for c in ss["comps"]}
                    ss["comps"] = ss["comps"] + [c for c in res["comps"] if (c["address"], c["price"], c["sqft"]) not in existing]
                    st.rerun()
                else:
                    st.error(res.get("error"))
        with k2:
            st.text_input("Census API key", key="census_key", type="password", help="Free at api.census.gov/data/key_signup.html. Adds ZIP-level median home value, year built, and rent.")
            zipc = parse_zip(ss["address"])
            if st.button("Fetch ZIP market context", width="stretch", disabled=not (ss.get("census_key") and zipc)):
                with st.spinner("Calling Census ACS..."):
                    ss["market_context"] = fetch_census_zip(zipc, ss["census_key"])
                if not ss["market_context"].get("ok"):
                    st.error(ss["market_context"].get("error"))

    # ---- Comps table (editable)
    df = comps_dataframe(ss["comps"])
    if df.empty:
        st.info("No comps yet. Paste sold comps above, or Analyze a Zillow listing page that includes its 'Recently sold homes' section.")
        research: dict[str, Any] = {"ok": False, "rows": []}
    else:
        st.caption("Edit any cell, untick **Use** to exclude a comp, or add rows at the bottom. The model recalculates live.")
        edited = st.data_editor(
            df, num_rows="dynamic", width="stretch", hide_index=True,
            column_config={
                "use": st.column_config.CheckboxColumn("Use", default=True),
                "address": st.column_config.TextColumn("Address", width="large"),
                "status": st.column_config.SelectboxColumn("Status", options=["Sold", "Pending", "Active"]),
                "sold_date": st.column_config.TextColumn("Sold date"),
                "price": st.column_config.NumberColumn("Price", format="$%d"),
                "sqft": st.column_config.NumberColumn("Sqft", format="%d"),
                "beds": st.column_config.NumberColumn("Bd", format="%g"),
                "baths": st.column_config.NumberColumn("Ba", format="%g"),
                "year_built": st.column_config.NumberColumn("Built", format="%d"),
                "distance_mi": st.column_config.NumberColumn("Dist (mi)", format="%.2f"),
                "source": st.column_config.TextColumn("Source"),
            },
        )
        records = edited.where(pd.notna(edited), None).to_dict("records")
        for r in records:
            r["use"] = bool(r.get("use"))
        ss["comps"] = records
        research = estimate_arv(records, ss["sqft"] or None, ss["beds"] or None)

    # ---- Model results
    section("B", "ARV estimate", "Price-per-sqft model built from the comps above.")
    if research.get("ok"):
        conf_band = {"Good": "green", "Fair": "yellow", "Weak": "red"}[research["confidence"]]
        c = st.columns(4)
        c[0].markdown(metric_card("ARV (point)", fmt_money(research["point"]), "neutral", research["basis"]), unsafe_allow_html=True)
        c[1].markdown(metric_card("Conservative (25th pct)", fmt_money(research["low"]), "neutral", f"${research['p25_ppsf']:,.0f}/sqft"), unsafe_allow_html=True)
        c[2].markdown(metric_card("Optimistic (75th pct)", fmt_money(research["high"]), "neutral", f"${research['p75_ppsf']:,.0f}/sqft"), unsafe_allow_html=True)
        c[3].markdown(metric_card("Confidence", research["confidence"], conf_band, f"{research['n']} comps in model · {research['n_sold']} sold"), unsafe_allow_html=True)
        rows = pd.DataFrame(research["rows"])
        show = rows[rows["in_model"]][["address", "status", "sold_date", "price", "sqft", "ppsf", "weight"]].copy()
        show["weight"] = (show["weight"] / show["weight"].sum() * 100) if show["weight"].sum() else 0
        st.markdown(
            f'<div class="evidence"><b>How this was calculated.</b> {research["n"]} comps passed the filters (sold status preferred, ±35% of subject sqft). '
            f'Median $/sqft = <b>${research["median_ppsf"]:,.0f}</b>; similarity-weighted $/sqft = <b>${research["weighted_ppsf"]:,.0f}</b> '
            f'(weighted ARV {fmt_money(research["weighted"])}). Range uses the 25th–75th percentile of $/sqft.'
            + "".join(f'<br><span class="muted">• {html_lib.escape(n)}</span>' for n in research["notes"])
            + "</div>",
            unsafe_allow_html=True,
        )
        st.dataframe(
            show, hide_index=True, width="stretch",
            column_config={
                "address": "Comp", "status": "Status", "sold_date": "Sold",
                "price": st.column_config.NumberColumn("Price", format="$%d"),
                "sqft": st.column_config.NumberColumn("Sqft", format="%d"),
                "ppsf": st.column_config.NumberColumn("$/sqft", format="$%.0f"),
                "weight": st.column_config.ProgressColumn("Model weight", format="%.0f%%", min_value=0, max_value=100),
            },
        )
        u1, u2, u3, _ = st.columns([1.4, 1.4, 1.4, 2])
        summary = summarize_research(research)
        if u1.button(f"Use {fmt_money(research['point'])} as my ARV", type="primary", width="stretch"):
            ss["_pending"] = {"action": "set_arv", "arv": research["point"], "notes": summary}
            st.rerun()
        if u2.button(f"Use conservative {fmt_money(research['low'])}", width="stretch"):
            ss["_pending"] = {"action": "set_arv", "arv": research["low"], "notes": "Conservative (25th pct) — " + summary}
            st.rerun()
        if u3.button(f"Use weighted {fmt_money(research['weighted'])}", width="stretch"):
            ss["_pending"] = {"action": "set_arv", "arv": research["weighted"], "notes": "Similarity-weighted — " + summary}
            st.rerun()
    elif not df.empty:
        st.warning(research.get("reason", "Model could not run."))

    # ---- Other evidence
    section("C", "Other data points", "Context only — not a substitute for comps.")
    items = []
    for a in ss["avms"]:
        items.append(f"<b>{html_lib.escape(a['source'])}</b> (from listing page): {fmt_money(a['value'])}")
    for c in ss["agent_claims"]:
        if c.startswith("ARV"):
            items.append(f"<b>Agent claim</b> (unverified): {html_lib.escape(c)}")
    rc = ss.get("rentcast")
    if rc and rc.get("ok") and rc.get("value"):
        items.append(f"<b>RentCast AVM:</b> {fmt_money(rc['value'])} (range {fmt_money(rc.get('low'))} – {fmt_money(rc.get('high'))})")
    mc = ss.get("market_context")
    if mc and mc.get("ok"):
        bits = [p for p in [
            f"median home value {fmt_money(mc['median_home_value'])}" if mc.get("median_home_value") else "",
            f"median year built {int(mc['median_year_built'])}" if mc.get("median_year_built") else "",
            f"median rent {fmt_money(mc['median_gross_rent'])}/mo" if mc.get("median_gross_rent") else "",
        ] if p]
        items.append(f"<b>ZIP {html_lib.escape(str(mc.get('name')))}</b> ({mc['vintage']}): " + ", ".join(bits))
    if ss["arv"]:
        items.append(f"<b>Your current ARV:</b> {fmt_money(ss['arv'])}" + (f" — {html_lib.escape(ss['arv_notes'])}" if ss["arv_notes"] else ""))
    if items:
        st.markdown('<div class="evidence">' + "<br>".join(items) + "</div>", unsafe_allow_html=True)
    else:
        st.caption("Nothing yet. Zestimate / Redfin Estimate values are picked up automatically from pasted listing text.")
    return research


# ----------------------------------------------------------------------------- Saved properties tab


def render_saved_tab() -> None:
    ss = st.session_state
    df = load_tracker()
    section("🗂", "Saved properties", f"{len(df)} saved · stored in {TRACKER_CSV.split('/')[-1]}")
    if df.empty:
        st.info("No properties saved yet. Analyze a listing and click **Save to Tracker**.")
    else:
        top = st.columns([2.2, 1, 1, 1.4, 1.4])
        options = [f"#{i + 1} · {a or '(no address)'}" for i, a in enumerate(df["Address"].tolist())]
        pick = top[0].selectbox("Property", options, label_visibility="collapsed")
        idx = options.index(pick)
        if top[1].button("✏️ Load / edit", width="stretch", help="Loads this row into the analyzer so you can change numbers and click Update."):
            ss["_pending"] = {"action": "load_row", "index": idx, "row": df.iloc[idx].to_dict()}
            st.rerun()
        if top[2].button("🗑️ Delete", width="stretch"):
            delete_tracker_rows([idx])
            if ss["editing_index"] == idx:
                ss["editing_index"] = None
            st.rerun()
        sort_by = top[3].selectbox("Sort by", ["Date Analyzed", "Est. ROI %", "Max Offer (70%)", "Max Offer (65%)", "Est. Total Profit", "List Price"], label_visibility="collapsed")
        desc = top[4].selectbox("Order", ["Descending", "Ascending"], label_visibility="collapsed") == "Descending"

        view = df.copy()
        key = pd.to_numeric(view[sort_by], errors="coerce") if sort_by != "Date Analyzed" else view[sort_by]
        view = view.loc[key.sort_values(ascending=not desc, na_position="last").index]

        st.caption("Cells are editable inline. Select a row and press Delete (or use the trash icon) to remove it, then click **Save table changes**.")
        edited = st.data_editor(
            view, num_rows="dynamic", width="stretch", hide_index=False,
            column_config={
                "Est. ROI %": st.column_config.NumberColumn(format="%.1f%%"),
                **{c: st.column_config.NumberColumn(format="$%d") for c in ["List Price", "Est. ARV", "Est. Rehab Cost", "Purchase Price", "Est. Closing Costs", "Monthly Carrying Cost", "Total Carrying Cost", "Selling Costs (7%)", "Max Offer (70%)", "Max Offer (65%)", "Est. Total Profit"]},
                "Listing URL": st.column_config.LinkColumn("Listing URL"),
            },
        )
        b = st.columns([1.4, 1.6, 1.6, 3])
        if b[0].button("💾 Save table changes", type="primary", width="stretch"):
            overwrite_tracker(edited.sort_index() if edited.index.is_monotonic_increasing or True else edited)
            ss["editing_index"] = None
            st.success("Tracker updated.")
            st.rerun()
        b[1].download_button("⬇️ Download tracker CSV", data=df.to_csv(index=False).encode("utf-8"), file_name="fix_flip_tracker.csv", mime="text/csv", width="stretch")

    with st.expander("📥 Import rows from a CSV (e.g. a tracker downloaded earlier)"):
        st.caption("Hosted deployments reset their local files on each redeploy, so download the tracker regularly and re-import it here if needed.")
        up = st.file_uploader("Tracker CSV", type=["csv"], label_visibility="collapsed")
        if up is not None and st.button("Append rows", width="stretch"):
            try:
                inc = pd.read_csv(up)
                for c in TRACKER_COLUMNS:
                    if c not in inc.columns:
                        inc[c] = ""
                merged = pd.concat([load_tracker(), inc[TRACKER_COLUMNS]], ignore_index=True)
                overwrite_tracker(merged)
                st.success(f"Imported {len(inc)} rows.")
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    st.set_page_config(page_title="Fix & Flip Analyzer", page_icon="🏚️", layout="wide")
    password_gate()
    st.markdown(STYLE, unsafe_allow_html=True)
    init_state()
    ss = st.session_state

    render_hero()
    if ss["show_input"]:
        render_input_section()
    if ss["scrape_msg"]:
        level, msg = ss["scrape_msg"]
        getattr(st, level)(msg)
    if ss["analyzed"] and ss["missing"] and ss["show_input"]:
        st.warning("Not found in listing — fill in manually: " + ", ".join(ss["missing"]))

    tab_deal, tab_arv, tab_saved = st.tabs(["📋  Deal Analyzer", "🔬  ARV Research", "🗂️  Saved Properties"])

    with tab_deal:
        render_extracted_fields()
        render_manual_inputs()
        m = compute_metrics(ss["list_price"], ss["sqft"], ss["arv"], ss["rehab"], ss["purchase_price"], ss["closing"], ss["months"], ss["monthly_carry"])
        band = roi_band(m["roi"])
        render_metrics(m, band)
        flags, claims = compute_flags()
        render_flags(flags, claims)
        # research from the comps currently in state (recomputed each run, so the PDF always matches the ARV tab)
        research = estimate_arv(ss["comps"], ss["sqft"] or None, ss["beds"] or None) if ss["comps"] else {"ok": False, "rows": []}
        render_save_export(m, flags, claims, research, band)

    with tab_arv:
        render_arv_tab()

    with tab_saved:
        render_saved_tab()


if __name__ == "__main__":
    main()
