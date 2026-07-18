"""Downloads every raw source into data/raw/ and extracts NIRF's HTML tables.

Idempotent: re-running skips files already on disk. Every fetch logs its
source, URL, and outcome so a partial or failed pull is visible immediately
instead of silently producing a truncated dataset downstream.
"""

import os
import time

import requests
from bs4 import BeautifulSoup

from data_pipeline.sources import (
    FULL_2021_2022_CSV_URL,
    JOSAA_2024_CSV_URL,
    JOSAA_ROUND_CSV_TEMPLATE,
    JOSAA_ROUND_MAX_ROUND_GUESS,
    JOSAA_ROUND_YEARS,
    NIRF_BAND_SUFFIXES,
    NIRF_URL_TEMPLATE,
    NIRF_YEARS,
    RAW_DIR,
    SEAT_MATRIX_2025_URL,
    SNAPSHOT_2023_SQLITE_URL,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) college-compass-ingest/1.0"}
TIMEOUT = 30


def _get(url):
    return requests.get(url, headers=HEADERS, timeout=TIMEOUT)


def _save(path, content_bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content_bytes)


def fetch_josaa_rounds():
    out_dir = os.path.join(RAW_DIR, "josaa_rounds")
    fetched, skipped_existing, not_found = 0, 0, 0
    for year in JOSAA_ROUND_YEARS:
        for round_no in range(1, JOSAA_ROUND_MAX_ROUND_GUESS + 1):
            dest = os.path.join(out_dir, f"{year}-{round_no}.csv")
            if os.path.exists(dest):
                skipped_existing += 1
                continue
            url = JOSAA_ROUND_CSV_TEMPLATE.format(year=year, round=round_no)
            resp = _get(url)
            if resp.status_code == 200:
                _save(dest, resp.content)
                fetched += 1
                print(f"[josaa_rounds] {year} round {round_no}: OK ({len(resp.content)} bytes)")
            elif resp.status_code == 404:
                not_found += 1
                print(f"[josaa_rounds] {year} round {round_no}: not published (404), skipping")
            else:
                print(f"[josaa_rounds] {year} round {round_no}: unexpected status {resp.status_code}")
    print(f"[josaa_rounds] done: {fetched} fetched, {skipped_existing} already on disk, {not_found} not published")


def fetch_josaa_2024():
    dest = os.path.join(RAW_DIR, "josaa_2024", "josaa24.csv")
    if os.path.exists(dest):
        print("[josaa_2024] already on disk, skipping")
        return
    resp = _get(JOSAA_2024_CSV_URL)
    resp.raise_for_status()
    _save(dest, resp.content)
    print(f"[josaa_2024] OK ({len(resp.content)} bytes)")


def fetch_seat_matrix():
    dest = os.path.join(RAW_DIR, "seat_matrix", "seat_matrix_25.csv")
    if os.path.exists(dest):
        print("[seat_matrix] already on disk, skipping")
        return
    resp = _get(SEAT_MATRIX_2025_URL)
    resp.raise_for_status()
    _save(dest, resp.content)
    print(f"[seat_matrix] OK ({len(resp.content)} bytes)")


def fetch_full_2021_2022():
    dest = os.path.join(RAW_DIR, "full_2021_2022", "2016-2023dataa.csv")
    if os.path.exists(dest):
        print("[full_2021_2022] already on disk, skipping")
        return
    resp = _get(FULL_2021_2022_CSV_URL)
    resp.raise_for_status()
    _save(dest, resp.content)
    print(f"[full_2021_2022] OK ({len(resp.content)} bytes)")


def fetch_snapshot_2023():
    import gzip

    dest = os.path.join(RAW_DIR, "snapshot_2023", "db.sqlite3")
    if os.path.exists(dest):
        print("[snapshot_2023] already on disk, skipping")
        return
    resp = _get(SNAPSHOT_2023_SQLITE_URL)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(gzip.decompress(resp.content))
    print(f"[snapshot_2023] OK ({len(resp.content)} bytes compressed)")


def _parse_nirf_table(html):
    """Extracts (institute_id, name, city, state, score, rank) from NIRF's tbl_overall table.

    Each real institute row is followed by two detail rows (a repeated
    sub-score header and its values, used for the site's expandable
    "More Details" panel) - those have far fewer cells and are skipped.
    The name cell also contains a nested hidden div with the "More Details"
    toggle and a PDF/graph link, so only the leading text node is taken
    rather than get_text(), which would glue the toggle text onto the name.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="tbl_overall")
    if table is None:
        return []
    records = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 10:
            continue
        first_cell_text = cells[0].get_text(strip=True)
        if first_cell_text in ("", "Institute ID"):
            continue
        name = next(cells[1].stripped_strings, "").strip()
        city = cells[-4].get_text(strip=True)
        state = cells[-3].get_text(strip=True)
        score = cells[-2].get_text(strip=True)
        rank = cells[-1].get_text(strip=True)
        if not name or not rank:
            continue
        records.append(
            {
                "institute_id": first_cell_text,
                "name": name,
                "city": city,
                "state": state,
                "score": score,
                "rank": rank,
            }
        )
    return records


def _parse_nirf_band_table(html):
    """Band pages beyond the first ~100-200 institutes (suffixes like 150,
    200, 300) use a different, plainer table: no id="tbl_overall", just a
    3-column Name/City/State list with no rank or score at all - NIRF simply
    doesn't publish full component scores for these lower bands. Missed
    entirely by _parse_nirf_table, which only looks for tbl_overall - found
    while tracking down why several real, well-known institutes had no NIRF
    state despite clearly appearing on NIRF's own site. Used only to backfill
    college state/city; rank and score stay null for these rows since NIRF
    genuinely doesn't publish them here, not because of a parsing gap.
    """
    soup = BeautifulSoup(html, "lxml")
    records = []
    for table in soup.find_all("table"):
        if table.get("id") == "tbl_overall":
            continue
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        if header_cells != ["name", "city", "state"]:
            continue
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) != 3:
                continue
            name, city, state = (c.get_text(strip=True) for c in cells)
            if not name:
                continue
            records.append({"institute_id": None, "name": name, "city": city, "state": state, "score": None, "rank": None})
    return records


def fetch_nirf():
    out_dir = os.path.join(RAW_DIR, "nirf")
    os.makedirs(out_dir, exist_ok=True)
    for year in NIRF_YEARS:
        dest_csv = os.path.join(out_dir, f"{year}.csv")
        if os.path.exists(dest_csv):
            print(f"[nirf] {year}: already on disk, skipping")
            continue
        seen_keys = set()
        rows = []
        found_any_page = False
        for suffix in NIRF_BAND_SUFFIXES:
            url = NIRF_URL_TEMPLATE.format(year=year, suffix=suffix)
            resp = _get(url)
            if resp.status_code != 200:
                continue
            # tbl_overall (ranked, scored) and the plain band table (name/
            # city/state only, no rank) are mutually exclusive per page, but
            # try both rather than assume which one a given year/suffix uses.
            page_records = _parse_nirf_table(resp.text) or _parse_nirf_band_table(resp.text)
            if not page_records:
                continue
            found_any_page = True
            new_count = 0
            for rec in page_records:
                key = rec["institute_id"] or rec["name"]
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                rec["year"] = year
                rows.append(rec)
                new_count += 1
            print(f"[nirf] {year} band '{suffix or 'top'}': {new_count} new institutes")
            time.sleep(0.2)
        if not found_any_page:
            print(f"[nirf] {year}: no live ranking page found, skipping year")
            continue
        import csv

        with open(dest_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["institute_id", "name", "city", "state", "score", "rank", "year"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"[nirf] {year}: {len(rows)} institutes written to {dest_csv}")


def main():
    print("=== ingest: JoSAA round CSVs 2016-2020 ===")
    fetch_josaa_rounds()
    print("=== ingest: JoSAA 2024 final-round snapshot ===")
    fetch_josaa_2024()
    print("=== ingest: 2025 seat matrix ===")
    fetch_seat_matrix()
    print("=== ingest: 2021-2022 all-institute-type backfill ===")
    fetch_full_2021_2022()
    print("=== ingest: 2023 all-institute-type snapshot ===")
    fetch_snapshot_2023()
    print("=== ingest: NIRF engineering rankings ===")
    fetch_nirf()
    print("=== ingest complete ===")


if __name__ == "__main__":
    main()
