# OK‑Red Meet Live‑Scoring & Line‑up Assistant – Streamlit app
# ------------------------------------------------------------------------
#  Now computes *live conference seed ranks* automatically on each refresh.
#  No need to maintain a SeedRank column in the roster file.
# ------------------------------------------------------------------------

import streamlit as st
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
from io import StringIO

# ----------------------------- Config ------------------------------------
POINTS_TABLE = {1: 10, 2: 8, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}
MAX_EVENTS_PER_ATHLETE = 4
GH_SCHOOL = "Grand Haven"
MEET_URL = "https://www.athletic.net/TrackAndField/meet/572993/results"

st.set_page_config(page_title="OK‑Red Coach Dashboard", layout="centered", page_icon="🏆")

# ----------------------------- Helpers -----------------------------------
@st.cache_data(show_spinner=False)
def read_sheet(f):
    if f.name.endswith(".csv"):
        return pd.read_csv(f)
    return pd.read_excel(f)

@st.cache_data(show_spinner=False)
def scrape_athletic_results(url: str) -> pd.DataFrame:
    """Scrape Athletic.net finals tables -> Event | Place | School."""
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    rows = []
    for blk in soup.select("div.event-results"):
        ev = blk.select_one("h4").get_text(strip=True)
        table = blk.select_one("table")
        if not table or "No Results" in table.text:
            continue
        df = pd.read_html(StringIO(str(table)))[0]
        for _, rw in df.iterrows():
            try:
                plc = int(rw.get("Place", rw.iloc[0]))
            except ValueError:
                continue
            if plc > 8:
                break
            school = rw.get("Team", rw.iloc[3])
            rows.append({"Event": ev, "Place": plc, "School": school})
    return pd.DataFrame(rows)

# Determine if event is field (higher mark better) or track (lower time better)
FIELD_KEYWORDS = ["Jump", "Long", "High", "Vault", "Shot", "Discus", "Pole", "Javelin"]
def ascending_order(event_name: str) -> bool:
    return not any(k.lower() in event_name.lower() for k in FIELD_KEYWORDS)

# ----------------------------- UI ----------------------------------------
st.title("🏆 OK‑Red Championship – Live Coach Dashboard")

st.sidebar.header("🔧 Upload meet data")
roster_file = st.sidebar.file_uploader("Roster & season‑best marks (xlsx/csv)")
lineup_file = st.sidebar.file_uploader("Initial lineup (xlsx/csv)")

fetch = st.sidebar.button("🌐 Fetch latest Athletic.net results")
refresh = st.sidebar.button("🔄 Refresh dashboard")

# -------------------------------------------------------------------------
if not (roster_file and lineup_file):
    st.info("Upload roster and lineup to begin.")
    st.stop()

roster = read_sheet(roster_file)
lineup = read_sheet(lineup_file)
results = pd.DataFrame()

if fetch or refresh:
    with st.spinner("Scraping Athletic.net …"):
        try:
            results = scrape_athletic_results(MEET_URL)
            st.success(f"Fetched {len(results)} rows.")
        except Exception as e:
            st.error(f"Scrape failed: {e}")
            results = pd.DataFrame(columns=["Event", "Place", "School"])

# If no results yet, keep an empty DF
if results.empty:
    results = pd.DataFrame(columns=["Event", "Place", "School"])

# ---------------------- Compute conference ranks -------------------------
roster = roster.copy()
roster["ConfRank"] = np.nan
for ev, grp in roster.groupby("Event"):
    asc = ascending_order(ev)
    grp_sorted = grp.sort_values("Mark", ascending=asc).reset_index()
    roster.loc[grp_sorted["index"], "ConfRank"] = grp_sorted.index + 1

# ---------------------- Live scoreboard ----------------------------------
pts_live = results.copy()
pts_live["Points"] = pts_live["Place"].map(POINTS_TABLE)
team_pts = (pts_live.groupby("School")["Points"]
            .sum()
            .reset_index()
            .sort_values("Points", ascending=False))

st.subheader("Live team scores (scored events only)")
st.dataframe(team_pts, use_container_width=True, height=300)

# ---------------------- Remaining events projection ----------------------
scored = set(results["Event"].unique())
remaining = [ev for ev in lineup["Event"].unique() if ev not in scored]
proj_rows = []
for ev in remaining:
    ev_roster = roster[roster["Event"] == ev].sort_values("ConfRank")[:8]
    ev_roster["ProjPts"] = ev_roster["ConfRank"].map(POINTS_TABLE)
    gh_pts = ev_roster.loc[ev_roster["School"] == GH_SCHOOL, "ProjPts"].sum()
    proj_rows.append({"Event": ev, "GH_expected": gh_pts})
proj_df = pd.DataFrame(proj_rows).sort_values("Event")

st.subheader("Remaining events – Grand Haven projected points")
st.dataframe(proj_df, use_container_width=True, height=300)

# ---------------------- Greedy swap suggestions --------------------------
ath_load = lineup.groupby("Athlete").size().to_dict()
swaps = []
for ev in remaining:
    gh_candidates = roster[(roster["Event"] == ev) & (roster["School"] == GH_SCHOOL)]
    if gh_candidates.empty:
        continue
    current_entries = lineup[(lineup["Event"] == ev) & (lineup["School"] == GH_SCHOOL)]["Athlete"]
    cur_pts = roster[(roster["Event"] == ev) & (roster["Athlete"].isin(current_entries))]["ConfRank"].map(POINTS_TABLE).sum()
    for _, cand in gh_candidates.iterrows():
        ath = cand["Athlete"]
        if ath_load.get(ath, 0) >= MAX_EVENTS_PER_ATHLETE:
            continue
        pot_pts = POINTS_TABLE.get(int(cand["ConfRank"]), 0)
        if pot_pts - cur_pts >= 2:
            swaps.append({"Event": ev, "SwapIn": ath, "Potential": pot_pts, "Current": cur_pts, "Delta": pot_pts - cur_pts})
            break

st.subheader("💡 Suggested GH swaps (≥ 2‑pt gain)")
if swaps:
    st.dataframe(pd.DataFrame(swaps), use_container_width=True)
else:
    st.info("No high‑impact swaps found.")

st.caption("App refresh computes live conference ranks from raw marks—no SeedRank column needed 👍")
