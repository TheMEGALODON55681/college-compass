"""Generates db/reference_metadata.csv once, if it doesn't already exist.

None of the five real ingested sources include fees or hostel information -
the PRD's own suggested resolution for data a scrape can't provide is a
small, clearly-labeled, hand-maintained reference table, so that's what this
is. Coverage is intentionally bounded (23 IITs plus the top NIRF-ranked
NITs/IIITs) rather than attempted for all ~130 colleges, and the fee figures
are broad per-institute-type approximations, not scraped per-college figures -
inventing false per-college precision would be worse than being honest about
a coarser number. Anyone using this for a real admission decision should
check the institute's current fee circular; source_note says so on every row.
"""

import os

import pandas as pd

from data_pipeline.sources import PROCESSED_DIR

REFERENCE_CSV_PATH = os.path.join("db", "reference_metadata.csv")

APPROX_ANNUAL_FEES_LAKHS = {
    "IIT": 2.5,
    "NIT": 1.25,
    "IIIT": 1.75,
    "GFTI": 1.0,
}

SOURCE_NOTE = (
    "Manually curated approximate figure by institute-type tier, not scraped per-college. "
    "Verify against the institute's current fee circular before relying on this for a real decision."
)

TOP_NON_IIT_COUNT = 40


def build_reference_metadata():
    colleges = pd.read_parquet(os.path.join(PROCESSED_DIR, "colleges.parquet"))
    nirf = pd.read_parquet(os.path.join(PROCESSED_DIR, "nirf_rankings.parquet"))

    latest_nirf = nirf.sort_values("year").drop_duplicates(subset="college_id", keep="last")
    latest_nirf = latest_nirf.set_index("college_id")

    iits = colleges[colleges["institute_type"] == "IIT"]
    non_iits = colleges[colleges["institute_type"] != "IIT"].copy()
    non_iits["nirf_rank"] = non_iits["college_id"].map(latest_nirf["rank"])
    top_non_iits = non_iits.dropna(subset=["nirf_rank"]).sort_values("nirf_rank").head(TOP_NON_IIT_COUNT)

    selected = pd.concat([iits, top_non_iits], ignore_index=True)

    rows = []
    for _, row in selected.iterrows():
        city = latest_nirf["city"].get(row["college_id"]) if row["college_id"] in latest_nirf.index else None
        rows.append(
            {
                "college_id": row["college_id"],
                "fees_annual_lakhs": APPROX_ANNUAL_FEES_LAKHS.get(row["institute_type"]),
                "hostel_available": 1,
                "location_city": city,
                "location_state": row["state"],
                "source_note": SOURCE_NOTE,
            }
        )

    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(REFERENCE_CSV_PATH), exist_ok=True)
    out.to_csv(REFERENCE_CSV_PATH, index=False)
    print(f"[reference_data] wrote {len(out)} rows to {REFERENCE_CSV_PATH}")
    return out


def load_reference_metadata():
    if not os.path.exists(REFERENCE_CSV_PATH):
        return build_reference_metadata()
    return pd.read_csv(REFERENCE_CSV_PATH)


if __name__ == "__main__":
    build_reference_metadata()
