"""Local CSV tracker: load, append, overwrite, update, delete."""

from __future__ import annotations

import csv
import os
from typing import Any

import pandas as pd

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TRACKER_CSV = os.path.join(APP_DIR, "tracker.csv")

# --- Tracker column headers -------------------------------------------------
# Written as the CSV header row, in this exact order.
# >>> To match your Google Sheets tracker, replace this list with your sheet's
# >>> header row and update build_tracker_row() in app.py to map values to it.
TRACKER_COLUMNS = [
    "Date Analyzed",
    "Address",
    "Listing URL",
    "List Price",
    "Beds",
    "Baths",
    "Sqft",
    "Lot Size",
    "Year Built",
    "Days on Market",
    "School Ratings",
    "Price/Sqft",
    "Est. ARV",
    "ARV Comps/Source",
    "Est. Rehab Cost",
    "Purchase Price",
    "Est. Closing Costs",
    "Holding Period (months)",
    "Monthly Carrying Cost",
    "Total Carrying Cost",
    "Selling Costs (7%)",
    "Max Offer (70%)",
    "Max Offer (65%)",
    "Est. Total Profit",
    "Est. ROI %",
    "Red Flags",
    "Agent Claims (Unverified)",
    "Notes",
    "Comps JSON",  # the comps table serialized, so a saved deal can be reloaded with its ARV evidence
]

TEXT_COLUMNS = ["Date Analyzed", "Address", "Listing URL", "Lot Size", "School Ratings", "ARV Comps/Source", "Red Flags", "Agent Claims (Unverified)", "Notes", "Comps JSON"]


def load_tracker(path: str = TRACKER_CSV) -> pd.DataFrame:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=TRACKER_COLUMNS)
    try:
        df = pd.read_csv(path, dtype={c: str for c in TEXT_COLUMNS})
    except Exception:
        return pd.DataFrame(columns=TRACKER_COLUMNS)
    for c in TRACKER_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[TRACKER_COLUMNS]
    for c in TEXT_COLUMNS:
        df[c] = df[c].fillna("")
    return df


def append_tracker_row(row: dict[str, Any], path: str = TRACKER_CSV) -> None:
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRACKER_COLUMNS)
        if new_file:
            w.writeheader()
        w.writerow({c: row.get(c, "") for c in TRACKER_COLUMNS})


def overwrite_tracker(df: pd.DataFrame, path: str = TRACKER_CSV) -> None:
    out = df.copy()
    for c in TRACKER_COLUMNS:
        if c not in out.columns:
            out[c] = ""
    out = out[TRACKER_COLUMNS]
    out.to_csv(path, index=False)


def update_tracker_row(index: int, row: dict[str, Any], path: str = TRACKER_CSV) -> bool:
    df = load_tracker(path)
    if index < 0 or index >= len(df):
        return False
    for c in TRACKER_COLUMNS:
        df.at[index, c] = row.get(c, "")
    overwrite_tracker(df, path)
    return True


def delete_tracker_rows(indices: list[int], path: str = TRACKER_CSV) -> int:
    df = load_tracker(path)
    keep = df.drop(index=[i for i in indices if 0 <= i < len(df)])
    overwrite_tracker(keep.reset_index(drop=True), path)
    return len(df) - len(keep)
