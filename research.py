"""ARV research: comps-based valuation model plus optional free-tier data sources."""

from __future__ import annotations

import re
import statistics
from typing import Any

import requests

# =============================================================================
# COMPS MODEL
# =============================================================================


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def estimate_arv(
    comps: list[dict[str, Any]],
    subject_sqft: float | None,
    subject_beds: float | None = None,
    sqft_tolerance: float = 0.35,
) -> dict[str, Any]:
    """Price-per-sqft comps model.

    1. Keep comps marked 'use' that have a price and sqft.
    2. Prefer SOLD comps; fall back to active/pending only if fewer than 2 solds.
    3. Prefer comps within ±tolerance of the subject's sqft; relax if fewer than 3 remain.
    4. ARV point = median $/sqft × subject sqft. Low/High = 25th / 75th percentile $/sqft.
       A similarity-weighted $/sqft (closer sqft and same bed count weigh more) is shown alongside.
    """
    usable = [c for c in comps if c.get("use", True) and c.get("price") and c.get("sqft")]
    notes: list[str] = []
    if not usable:
        return {"ok": False, "reason": "No usable comps (each comp needs a price and square footage).", "rows": []}

    sold = [c for c in usable if str(c.get("status", "")).lower().startswith("sold")]
    pool = sold if len(sold) >= 2 else usable
    if pool is not sold:
        notes.append("Fewer than 2 sold comps — active / pending listings included (weaker evidence).")

    if subject_sqft:
        tight = [c for c in pool if abs(c["sqft"] - subject_sqft) / subject_sqft <= sqft_tolerance]
        if len(tight) >= 3:
            pool = tight
        else:
            notes.append(f"Fewer than 3 comps within ±{int(sqft_tolerance*100)}% of subject sqft — all comps used.")

    used_ids = {id(c) for c in pool}
    rows = []
    ppsf_list, weights, weighted_sum = [], [], 0.0
    for c in usable:
        ppsf = c["price"] / c["sqft"]
        in_model = id(c) in used_ids
        w = 0.0
        if in_model:
            w = 1.0
            if subject_sqft:
                w *= 1.0 / (1.0 + abs(c["sqft"] - subject_sqft) / subject_sqft * 3)
            if subject_beds and c.get("beds"):
                w *= 1.0 if abs(c["beds"] - subject_beds) < 0.5 else 0.75
            cond = str(c.get("condition") or "").lower()
            if re.search(r"\b(?:poor|dated|fixer|as[\s\-]?is|needs|original|distress(?:ed)?|teardown|rough)\b", cond):
                w *= 0.5
                if "Dated / poor-condition comps were down-weighted (ARV should reflect renovated sales)." not in notes:
                    notes.append("Dated / poor-condition comps were down-weighted (ARV should reflect renovated sales).")
            elif re.search(r"renov|updated|remodel|new|turnkey|flipped|rehab", cond):
                w *= 1.15
            ppsf_list.append(ppsf)
            weights.append(w)
            weighted_sum += ppsf * w
        rows.append({**c, "ppsf": ppsf, "weight": w, "in_model": in_model})

    n = len(ppsf_list)
    median_ppsf = statistics.median(ppsf_list)
    p25, p75 = _pct(ppsf_list, 0.25), _pct(ppsf_list, 0.75)
    weighted_ppsf = weighted_sum / sum(weights) if sum(weights) else median_ppsf

    if subject_sqft:
        point, low, high, wpoint = (median_ppsf * subject_sqft, p25 * subject_sqft, p75 * subject_sqft, weighted_ppsf * subject_sqft)
        basis = f"median ${median_ppsf:,.0f}/sqft × {subject_sqft:,.0f} sqft"
    else:
        prices = [c["price"] for c in pool]
        point, low, high, wpoint = (statistics.median(prices), _pct(prices, 0.25), _pct(prices, 0.75), statistics.median(prices))
        basis = "median comp sale price (subject sqft unknown, so no $/sqft adjustment)"
        notes.append("Subject sqft is missing — estimate is the median comp price, not $/sqft-adjusted.")

    confidence = "Good" if n >= 5 else ("Fair" if n >= 3 else "Weak")
    return {
        "ok": True,
        "n": n,
        "n_sold": len([c for c in pool if str(c.get("status", "")).lower().startswith("sold")]),
        "point": point,
        "low": low,
        "high": high,
        "weighted": wpoint,
        "median_ppsf": median_ppsf,
        "p25_ppsf": p25,
        "p75_ppsf": p75,
        "weighted_ppsf": weighted_ppsf,
        "basis": basis,
        "confidence": confidence,
        "notes": notes,
        "rows": rows,
    }


def summarize_research(res: dict[str, Any]) -> str:
    """One-line description suitable for the tracker's ARV Comps/Source column."""
    if not res.get("ok"):
        return ""
    return (
        f"{res['n']} comps ({res['n_sold']} sold): {res['basis']} = ${res['point']:,.0f} "
        f"(range ${res['low']:,.0f}–${res['high']:,.0f}, confidence {res['confidence']})"
    )


# =============================================================================
# OPTIONAL FREE-TIER SOURCES (need a key the user creates themselves)
# =============================================================================


def fetch_rentcast(address: str, api_key: str, sqft: float | None = None, beds: float | None = None, baths: float | None = None) -> dict[str, Any]:
    """RentCast AVM + comparables. Free tier: 50 requests / month with a free account.
    Docs: https://developers.rentcast.io/reference/value-estimate
    """
    params: dict[str, Any] = {"address": address, "compCount": 10}
    if sqft:
        params["squareFootage"] = int(sqft)
    if beds:
        params["bedrooms"] = beds
    if baths:
        params["bathrooms"] = baths
    try:
        r = requests.get(
            "https://api.rentcast.io/v1/avm/value",
            params=params,
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException as e:
        return {"ok": False, "error": f"Request failed: {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"RentCast returned HTTP {r.status_code}: {r.text[:200]}"}
    try:
        data = r.json()
    except ValueError:
        return {"ok": False, "error": "RentCast returned non-JSON."}
    comps = []
    for c in data.get("comparables", []) or []:
        price, sqft_c = c.get("price"), c.get("squareFootage")
        if not price or not sqft_c:
            continue
        comps.append({
            "use": True,
            "address": c.get("formattedAddress") or c.get("addressLine1") or "(RentCast comp)",
            "status": "Sold" if c.get("lastSeenDate") or c.get("removedDate") else str(c.get("status") or "Sold"),
            "sold_date": str(c.get("lastSeenDate") or c.get("listedDate") or "")[:10],
            "price": float(price),
            "sqft": float(sqft_c),
            "beds": c.get("bedrooms"),
            "baths": c.get("bathrooms"),
            "year_built": c.get("yearBuilt"),
            "distance_mi": c.get("distance"),
            "condition": "",
            "source": "RentCast",
        })
    return {
        "ok": True,
        "value": data.get("price"),
        "low": data.get("priceRangeLow"),
        "high": data.get("priceRangeHigh"),
        "comps": comps,
    }


def fetch_census_zip(zip_code: str, api_key: str, year: int = 2023) -> dict[str, Any]:
    """ACS 5-year ZIP-level context: median owner-occupied home value, median year built, median gross rent.
    Free key: https://api.census.gov/data/key_signup.html
    """
    url = f"https://api.census.gov/data/{year}/acs/acs5"
    params = {
        "get": "NAME,B25077_001E,B25035_001E,B25064_001E",
        "for": f"zip code tabulation area:{zip_code}",
        "key": api_key,
    }
    try:
        r = requests.get(url, params=params, timeout=20)
    except requests.RequestException as e:
        return {"ok": False, "error": f"Request failed: {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"Census returned HTTP {r.status_code}: {r.text[:200]}"}
    try:
        rows = r.json()
        header, vals = rows[0], rows[1]
        rec = dict(zip(header, vals))
    except (ValueError, IndexError):
        return {"ok": False, "error": "Census returned no data for that ZIP."}

    def _num(v):
        try:
            f = float(v)
            return None if f < 0 else f
        except (TypeError, ValueError):
            return None

    return {
        "ok": True,
        "name": rec.get("NAME"),
        "median_home_value": _num(rec.get("B25077_001E")),
        "median_year_built": _num(rec.get("B25035_001E")),
        "median_gross_rent": _num(rec.get("B25064_001E")),
        "vintage": f"ACS 5-year {year}",
    }
