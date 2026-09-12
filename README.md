# Fix & Flip Property Analyzer

A browser-based underwriting tool for fix-and-flip research. Paste a listing, let the
app pull the facts, research the after-repair value (ARV) with comparable sales, and
export an investor-ready PDF deal summary. Runs locally or hosted on Streamlit
Community Cloud for free so a partner can use it too.

No paid APIs or cloud services are required. Two optional free-tier data sources can
be plugged in with your own keys.

## Run locally

Requires Python 3.9 or newer.

```bash
cd "/Users/talha/House Flipping Analyzer"
pip install -r requirements.txt
streamlit run app.py
```

The app opens at `http://localhost:8501`. Stop it with `Ctrl+C`.

## Host it (share with a partner)

The app is set up for [Streamlit Community Cloud](https://share.streamlit.io), which
is free and deploys straight from a GitHub repo.

1. Push this folder to a GitHub repo (private is fine).
2. Go to https://share.streamlit.io, sign in with GitHub, and click **Create app**.
3. Pick the repo, branch `main`, and main file `app.py`. Click **Deploy**.
4. Optional but recommended: in the app's **Settings > Secrets**, add a password so
   only people with the link *and* the password can open it:

   ```toml
   APP_PASSWORD = "choose-something"
   ```

5. Share the `https://<your-app>.streamlit.app` link.

**Hosted data caveat.** The tracker is a CSV file next to the app. On Streamlit Cloud
that file lives on a temporary disk and is wiped whenever the app redeploys or
restarts. Download the tracker CSV regularly from the Saved Properties tab, and use
**Import rows** there to restore it. Keeping your Google Sheet as the system of
record is the safe pattern.

## URL scraping is best effort only

**Zillow, Redfin, and most major listing sites block automated requests, and scraping
them may violate their Terms of Service.** A Zillow or Redfin URL will usually return
an HTTP 403 or a bot-check page, and the app tells you so.

**The reliable path is the paste box.** Open the listing in your browser, select-all,
copy, and paste the text. The parser is built around that workflow.

When a fetch is blocked the URL is still useful: the app decodes the address from the
link itself (Zillow, Redfin, Realtor.com, Trulia, Homes.com) and pre-fills it, and an
**Open listing** button appears next to Analyze. So the loop for a blocked site is:
paste URL, Analyze, Open listing, select-all + copy, paste, Analyze again.

## Layout

A hero header with a **Show listing input** toggle, then three tabs.

**Listing input** (collapsible). URL field, paste box, and Analyze / Load sample /
Reset / Open listing buttons. It auto-collapses once a listing parses cleanly; flip
the toggle to bring it back.

**Tab 1: Deal Analyzer**

1. *Listing facts.* Address, List Price, Beds, Baths, Sqft, Lot Size, Year Built, Days
   on Market, School Ratings. Auto-filled, all editable.
2. *Underwriting inputs.* Estimated ARV, ARV notes, Rehab Cost, Purchase Price / Offer
   (0 means use the list price), Closing Costs, Holding Period, Monthly Carrying Cost,
   Notes.
3. *Underwriting metrics.* Eight live metric cards: ROI, Total Profit, Max Offer at
   70% and 65%, Price/Sqft, Total Carrying Cost, Selling Costs, Total Cash Deployed.
   ROI and Profit are green above 15% ROI, yellow from 8% to 15%, red below 8%. The
   Max Offer cards are green when the list price is at or below the max offer.
4. *Red flags and agent claims.* Pre-1980 build, listing keywords ("as-is", "cash
   only", "multiple offers", "highest and best", "handyman", "TLC", "investor
   special", plus a few common extras), and any ARV, rent, or cap-rate figures the
   listing itself claims, labeled unverified.
5. *Save and export.* **Save to Tracker** appends a row to `tracker.csv`. When a saved
   row has been loaded for editing, this becomes **Update row** with a **Save as new**
   alternative. **Download PDF report** produces the deal summary described below.

**Tab 2: ARV Research**

- *Comparable sales.* Comps are extracted automatically from a pasted Zillow listing
  page (its "Recently sold homes" strip) and from any sold-comps text you paste in the
  **Add comps** box (a Zillow or Redfin "Sold" search, select-all + copied). Each comp
  needs a price and square footage. The comps table is fully editable: fix a value,
  untick **Use** to exclude a comp, or add rows.
- *ARV estimate.* A price-per-square-foot model. Sold comps are preferred; comps
  within 35% of the subject's size are preferred. ARV point = median $/sqft × subject
  sqft, with a conservative (25th percentile) and optimistic (75th percentile) figure,
  a similarity-weighted variant, a confidence grade based on comp count, and a table
  showing each comp's $/sqft and model weight. One click sets any of the three figures
  as your ARV and writes the method into the ARV notes.
- *Other data points.* Zestimate or Redfin Estimate values found in pasted listing
  text, the agent's ARV claim, and the optional sources below. Shown as context only.
- *Optional free-tier sources.* A [RentCast](https://app.rentcast.io) key (free, 50
  calls a month) fetches an automated valuation plus nearby sold comps into the table.
  A [Census](https://api.census.gov/data/key_signup.html) key (free) fetches ZIP-level
  median home value, median year built, and median rent. Keys live only in the browser
  session. These two integrations have not been exercised against live keys.

**Tab 3: Saved Properties**

Pick a property to **Load / edit** (it fills the analyzer and the save button turns
into Update) or **Delete**. Sort by ROI, Max Offer, Profit, List Price, or date. The
table itself is editable inline, including row deletion, followed by **Save table
changes**. Download the CSV or import one.

## PDF deal report

One-page (sometimes two) letter-size summary: a navy header band with the address and
facts, four headline metrics colored by ROI band, the deal structure side by side with
the profit waterfall, the ARV evidence (model basis, range, confidence, full comps
table with $/sqft), third-party estimates and market context, red flags and agent
claims, property facts, notes, and a disclaimer.

## Formulas

| Metric | Formula |
| --- | --- |
| Price/Sqft | List Price ÷ Sqft |
| Max Offer (70% rule) | ARV × 0.70 − Rehab |
| Max Offer (65% rule) | ARV × 0.65 − Rehab |
| Total Carrying Cost | Holding months × Monthly carrying cost |
| Selling Costs | ARV × 0.07 |
| Total Profit | ARV − Offer − Rehab − Closing − Carrying − Selling |
| Total Cash Deployed | Offer + Rehab + Closing + Carrying |
| ROI % | Profit ÷ Total Cash Deployed |
| ARV (comps model) | median comp $/sqft × subject sqft |

## Tracker CSV columns

Defined once as `TRACKER_COLUMNS` at the top of `storage.py`. To match your Google
Sheets tracker, replace that list with your sheet's header row and adjust
`build_tracker_row()` in `app.py`. Current columns, in order:

```
Date Analyzed, Address, Listing URL, List Price, Beds, Baths, Sqft, Lot Size,
Year Built, Days on Market, School Ratings, Price/Sqft, Est. ARV, ARV Comps/Source,
Est. Rehab Cost, Purchase Price, Est. Closing Costs, Holding Period (months),
Monthly Carrying Cost, Total Carrying Cost, Selling Costs (7%), Max Offer (70%),
Max Offer (65%), Est. Total Profit, Est. ROI %, Red Flags, Agent Claims (Unverified),
Notes
```

Google Sheets: **File > Import > Upload**, pick the CSV, choose "Append to current
sheet."

## Files

- `app.py` — Streamlit UI, calculations, state
- `parsing.py` — listing text parser, comps parser, URL slug decoder, best-effort scraper
- `research.py` — ARV comps model and optional RentCast / Census lookups
- `storage.py` — CSV tracker read / append / update / delete
- `report.py` — PDF deal summary (reportlab)
- `.streamlit/config.toml` — theme
- `requirements.txt`
- `tracker.csv` — created on first save (git-ignored)
