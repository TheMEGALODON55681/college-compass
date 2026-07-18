"""Reconciles six real, differently-shaped sources into one clean schema.

This is the file the PRD means when it says "budget for normalization... it
is the unglamorous foundation everything sits on." Recurring messiness
problems get handled here, each verified against the actual downloaded data
rather than assumed:

1. Institute names show up in two different shapes across sources: full
   names ("Indian Institute of Technology Bhubaneswar", the canonical form
   the clean sources use) and abbreviated ("IIT Bhubaneswar", expanded via
   expand_abbreviated_institute_name - checked longest-prefix-first so
   "IIIT " isn't partially matched by the "IIT " rule, plus a small hand-
   verified special-case dict for the handful of GFTIs/IIITs whose short
   names don't fit any prefix pattern).
2. Category/PwD labels are spelled with inconsistent spacing across sources
   ("OPEN(PwD)" vs "OPEN (PwD)"), and gender labels vary between full
   ("Gender-Neutral") and abbreviated ("Neutral") forms.
3. The seat matrix file is header-less with fixed column positions, and mixes
   per-program rows with institute-level "Total Seats" aggregate rows that
   share the same 16-column shape - the aggregates get dropped rather than
   summed alongside the rows they already total, which would double-count.
4. Two sources (full_2021_2022_backfill, snapshot_2023_backfill) were added
   after the regressor's own honest evaluation showed a 2021-2023 NIT/IIIT/GFTI
   gap was forcing 82% of its 2024 test rows into a cold-start path with no
   naive baseline to even compare against. Both were cross-checked against
   NIT Tiruchirappalli's own official published PDFs before being trusted
   (see data_pipeline/sources.py for the verification notes). The remaining
   honest gap: no 2025 closing ranks exist anywhere (only a 2025 seat matrix).
   build_dataset.py prints the full coverage picture plainly.

Program names are matched to the canonical program table by a
punctuation-and-case-stripped key wherever a source doesn't use the clean
sources' exact phrasing, which sidesteps ever needing to reconstruct exact
word spacing - matching on a key that dropped all spaces makes the
reconstruction problem disappear rather than solving it.
"""

import os
import re
import sqlite3

import pandas as pd

from data_pipeline.sources import (
    FULL_2021_2022_MAX_YEAR,
    FULL_2021_2022_MIN_YEAR,
    JOSAA_2024_YEAR,
    PROCESSED_DIR,
    RAW_DIR,
    SEAT_MATRIX_YEAR,
    SNAPSHOT_2023_TABLE,
    SNAPSHOT_2023_YEAR,
)

BRANCH_PATTERN = re.compile(r"^(.*?)\s*\((\d+)\s*Years?,\s*(.*?)\)$")

# The 2023 snapshot source abbreviates institute names ("IIT Bhubaneswar",
# "NIT Trichy") instead of using the full names the clean sources use. Most
# expand via a simple prefix swap (checked longest-prefix-first so "IIIT "
# isn't partially matched by the "IIT " rule); the handful that don't fit
# that pattern - mostly GFTIs with their own idiosyncratic short names - are
# a small, bounded, hand-verified set, not a guess.
ABBREVIATED_PREFIX_EXPANSIONS = [
    ("IIIT", "Indian Institute of Information Technology"),
    ("IIT", "Indian Institute of Technology"),
    ("NIT", "National Institute of Technology"),
]

ABBREVIATED_SPECIAL_CASES = {
    "IIITM Gwalior": "Atal Bihari Vajpayee Indian Institute of Information Technology & Management Gwalior",
    "IIEST Shibpur": "Indian Institute of Engineering Science and Technology, Shibpur",
    "IIIT Design & Manufacturing, Kancheepuram": "Indian Institute of Information Technology, Design & Manufacturing, Kancheepuram",
    "IIIT Kilohrad, Sonepat": "Indian Institute of Information Technology(IIIT) Kilohrad, Sonepat, Haryana",
    "IIIT Vadodara International Campus Diu": "Indian Institute of Information Technology, Vadodara International Campus Diu (IIITVICD)",
}


def expand_abbreviated_institute_name(name):
    if name in ABBREVIATED_SPECIAL_CASES:
        return ABBREVIATED_SPECIAL_CASES[name]
    for abbrev, full in ABBREVIATED_PREFIX_EXPANSIONS:
        if name.startswith(abbrev + " "):
            return full + " " + name[len(abbrev) + 1 :]
    return name


# A second, source-agnostic layer of naming variants that plain prefix
# expansion or match_key stripping can't reach, found by inspecting exactly
# which institute names failed to join after wiring in the two new backfill
# sources. Two real patterns, both verified against the canonical colleges
# table before adding: several NITs are canonically named after a person
# ("Motilal Nehru National Institute of Technology Allahabad", not just
# "National Institute of Technology Allahabad" - a prefix expansion has no
# way to know the person's name), and several IIITs carry a parenthetical
# "(IIIT)" restating the abbreviation in the middle of the canonical name
# itself, which a plain "IIIT " -> "Indian Institute of..." prefix swap
# doesn't reproduce. Applied as a fallback in _resolve_cutoff_rows after a
# direct match_key lookup fails, so it only ever affects names that would
# otherwise have been dropped, never overrides a name that already matched.
KNOWN_NAME_VARIANTS = {
    "National Institute of Technology Allahabad": "Motilal Nehru National Institute of Technology Allahabad",
    "National Institute of Technology Bhopal": "Maulana Azad National Institute of Technology Bhopal",
    "National Institute of Technology Jaipur": "Malaviya National Institute of Technology Jaipur",
    "National Institute of Technology Jalandhar": "Dr. B R Ambedkar National Institute of Technology, Jalandhar",
    "National Institute of Technology Nagpur": "Visvesvaraya National Institute of Technology, Nagpur",
    "National Institute of Technology Surat": "Sardar Vallabhbhai National Institute of Technology, Surat",
    "Indian Institute of Information Technology Design & Manufacture Jabalpur": "Pt. Dwarka Prasad Mishra Indian Institute of Information Technology, Design & Manufacture Jabalpur",
    "Indian Institute of Information Technology Dharwad": "Indian Institute of Information Technology(IIIT) Dharwad",
    "Indian Institute of Information Technology Kalyani": "Indian Institute of Information Technology(IIIT) Kalyani, West Bengal",
    "Indian Institute of Information Technology Kota": "Indian Institute of Information Technology (IIIT)Kota, Rajasthan",
    "Indian Institute of Information Technology Kottayam": "Indian Institute of Information Technology(IIIT) Kottayam",
    "Indian Institute of Information Technology Kurnool": "Indian Institute of Information Technology Design & Manufacturing Kurnool, Andhra Pradesh",
    "Indian Institute of Information Technology Nagpur": "Indian Institute of Information Technology (IIIT) Nagpur",
    "Indian Institute of Information Technology Pune": "Indian Institute of Information Technology (IIIT) Pune",
    "Indian Institute of Information Technology Raichur": "Indian institute of information technology, Raichur, Karnataka",
    "Indian Institute of Information Technology Ranchi": "Indian Institute of Information Technology (IIIT) Ranchi",
    "Indian Institute of Information Technology Sri City, Chittoor": "Indian Institute of Information Technology (IIIT), Sri City, Chittoor",
    "Indian Institute of Information Technology Una": "Indian Institute of Information Technology(IIIT) Una, Himachal Pradesh",
    "Indian Institute of Information Technology Vadodara, Gujrat": "Indian Institute of Information Technology(IIIT), Vadodara, Gujrat",
    "National Institute of Food Technology, Entrepreneurship and Management (NIFTEM) - Thanjavur": "National Institute of Food Technology Entrepreneurship and Management, Thanjavur",
}


def match_key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def institute_type_from_name(name):
    if "Indian Institute of Technology" in name:
        return "IIT"
    if "National Institute of Technology" in name:
        return "NIT"
    if "Indian Institute of Information Technology" in name:
        return "IIIT"
    return "GFTI"


def parse_rank(raw):
    """Strips a trailing category flag letter (round CSVs mark some PwD ranks like '254P')."""
    if pd.isna(raw):
        return None
    m = re.match(r"^\s*(\d+)", str(raw))
    return int(m.group(1)) if m else None


def normalize_category_label(raw):
    if pd.isna(raw):
        return raw
    label = str(raw).strip()
    label = re.sub(r"\s*\(", " (", label)
    return re.sub(r"\s+", " ", label).strip()


NOT_GENDER_SPLIT_LABEL = "Not gender-split (pre-2018 JoSAA reporting)"


def normalize_gender_label(raw):
    """2016 and 2017 round CSVs carry a blank Gender field for every row, not a
    parsing artifact - JoSAA's own published data those two years had one row
    per college/branch/category with no gender breakdown at all. The separate
    Female-only supernumerary reporting only starts appearing from 2018
    onward (verified: 2016/2017 files have exactly one row per category,
    2018+ have two - Gender-Neutral and Female-only - per category). Mapping
    the blank to "Gender-Neutral" would silently conflate a combined-gender
    figure with a post-2018 gender-neutral-only figure, which is not the same
    population, so it gets its own explicit label instead.

    Separately, the IIT-only backfill source and the 2023 snapshot source
    both spell this pair as bare "Female"/"Neutral" instead of the clean
    sources' "Female-only (including Supernumerary)"/"Gender-Neutral",
    which would otherwise fragment one real concept into extra categories.
    """
    if pd.isna(raw) or str(raw).strip() == "":
        return NOT_GENDER_SPLIT_LABEL
    label = str(raw).strip()
    if label == "Female":
        return "Female-only (including Supernumerary)"
    if label == "Neutral":
        return "Gender-Neutral"
    return label


def _read_josaa_round_csvs():
    rounds_dir = os.path.join(RAW_DIR, "josaa_rounds")
    frames = []
    for fname in sorted(os.listdir(rounds_dir)):
        df = pd.read_csv(os.path.join(rounds_dir, fname))
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    combined["source_tag"] = "round_csv"
    return combined


def _read_josaa_2024():
    df = pd.read_csv(os.path.join(RAW_DIR, "josaa_2024", "josaa24.csv"))
    df["Year"] = JOSAA_2024_YEAR
    df["Round"] = pd.NA
    df["source_tag"] = "final_2024"
    return df


def _read_full_2021_2022():
    """Same underlying shape as the round-CSV source, different column names
    and ordering (Year/Round come first, "Institutes"/"Academic_Program"
    instead of "Institute"/"Academic Program Name"). Renamed to match so this
    can go through the same _resolve_cutoff_rows path as everything else -
    no parallel loader. The source file repeats 2016-2020 too; only 2021 and
    2022 are taken; those years are already covered by seshaljain's source,
    which was independently verified first and stays the source of truth
    for the years it has.
    """
    path = os.path.join(RAW_DIR, "full_2021_2022", "2016-2023dataa.csv")
    df = pd.read_csv(path)
    df = df.rename(columns={"Institutes": "Institute", "Academic_Program": "Academic Program Name", "Seat_Type": "Seat Type"})
    df = df[(df["Year"] >= FULL_2021_2022_MIN_YEAR) & (df["Year"] <= FULL_2021_2022_MAX_YEAR)].copy()
    df["source_tag"] = "full_2021_2022_backfill"
    return df


def build_colleges_and_programs():
    """Builds canonical colleges and programs tables from the two clean,
    non-concatenated sources, then extends both with what the IIT backfill
    source can and can't match.
    """
    round_df = _read_josaa_round_csvs()
    final_df = _read_josaa_2024()
    clean = pd.concat([round_df[["Institute", "Academic Program Name"]], final_df[["Institute", "Academic Program Name"]]], ignore_index=True)

    college_names = sorted(clean["Institute"].dropna().unique())
    colleges = pd.DataFrame(
        {
            "college_id": [slug(n) for n in college_names],
            "canonical_name": college_names,
            "institute_type": [institute_type_from_name(n) for n in college_names],
            "state": None,
        }
    )

    branch_names = sorted(clean["Academic Program Name"].dropna().unique())
    program_rows = []
    program_match_index = {}
    for full_name in branch_names:
        m = BRANCH_PATTERN.match(full_name)
        if not m:
            continue
        branch, duration, degree = m.group(1), int(m.group(2)), m.group(3)
        program_id = slug(f"{branch}-{degree}-{duration}y")
        key = (match_key(branch + degree), duration)
        program_match_index[key] = program_id
        program_rows.append(
            {
                "program_id": program_id,
                "branch_name": branch,
                "degree_type": degree,
                "duration_years": duration,
                "source_tag": "clean",
            }
        )
    programs = pd.DataFrame(program_rows).drop_duplicates(subset="program_id")

    return colleges, programs, program_match_index


def _read_snapshot_2023():
    """Same abbreviated-name, no-Year/Round-column shape as the current-year
    Sbrjt mirror used for other purposes earlier in this pipeline's history -
    this is an older commit of that same repo/schema, predating its update to
    2024 data. Institute names are expanded to the clean sources' full-name
    form before this goes through the same _resolve_cutoff_rows path as
    everything else.
    """
    db_path = os.path.join(RAW_DIR, "snapshot_2023", "db.sqlite3")
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(f"SELECT * FROM {SNAPSHOT_2023_TABLE}", conn)
    conn.close()

    df["Institute"] = df["Institute"].apply(expand_abbreviated_institute_name)
    df = df.rename(columns={"Branch": "Academic Program Name", "Seat": "Seat Type", "Open": "Opening Rank", "Close": "Closing Rank"})
    df["Year"] = SNAPSHOT_2023_YEAR
    df["Round"] = pd.NA
    df["source_tag"] = "snapshot_2023_backfill"
    return df


def _resolve_cutoff_rows(df, colleges, programs, program_match_index, source_tag):
    """Institute names are matched on a stripped key, not an exact string -
    some sources have double spaces, trailing whitespace, or an embedded
    newline in an otherwise-correct name (verified while wiring in the
    2021-2022 backfill source), and match_key is already the tool this
    pipeline uses to make exactly that kind of noise a non-issue.
    """
    name_key_to_id = {match_key(n): cid for n, cid in zip(colleges["canonical_name"], colleges["college_id"])}

    def resolve_institute(raw):
        cid = name_key_to_id.get(match_key(raw))
        if cid is not None:
            return cid
        variant = KNOWN_NAME_VARIANTS.get(raw)
        return name_key_to_id.get(match_key(variant)) if variant else None

    institute_id_map = {raw: resolve_institute(raw) for raw in df["Institute"].dropna().unique()}

    unmatched_institutes = sorted(name for name, cid in institute_id_map.items() if cid is None)
    if unmatched_institutes:
        print(f"[normalize] {source_tag}: {len(unmatched_institutes)} institute name(s) failed to join to a canonical college, rows dropped: {unmatched_institutes}")

    branch_to_program = {}
    for full_name in df["Academic Program Name"].dropna().unique():
        m = BRANCH_PATTERN.match(full_name)
        if not m:
            continue
        branch, duration, degree = m.group(1), int(m.group(2)), m.group(3)
        key = (match_key(branch + degree), duration)
        branch_to_program[full_name] = program_match_index.get(key)

    return pd.DataFrame(
        {
            "college_id": df["Institute"].map(institute_id_map),
            "program_id": df["Academic Program Name"].map(branch_to_program),
            "quota": df["Quota"],
            "category": df["Seat Type"].map(normalize_category_label),
            "gender_seat_type": df["Gender"].map(normalize_gender_label),
            "opening_rank": df["Opening Rank"].apply(parse_rank),
            "closing_rank": df["Closing Rank"].apply(parse_rank),
            "year": df["Year"],
            "round": df["Round"],
            "source_tag": source_tag,
        }
    )


def build_cutoffs(colleges, programs, program_match_index):
    round_df = _read_josaa_round_csvs()
    final_df = _read_josaa_2024()
    full_2021_2022_df = _read_full_2021_2022()
    snapshot_2023_df = _read_snapshot_2023()

    round_cutoffs = _resolve_cutoff_rows(round_df, colleges, programs, program_match_index, "round_csv")
    final_cutoffs = _resolve_cutoff_rows(final_df, colleges, programs, program_match_index, "final_2024")
    full_2021_2022_cutoffs = _resolve_cutoff_rows(full_2021_2022_df, colleges, programs, program_match_index, "full_2021_2022_backfill")
    snapshot_2023_cutoffs = _resolve_cutoff_rows(snapshot_2023_df, colleges, programs, program_match_index, "snapshot_2023_backfill")

    cutoffs = pd.concat(
        [round_cutoffs, final_cutoffs, full_2021_2022_cutoffs, snapshot_2023_cutoffs],
        ignore_index=True,
    )
    before = len(cutoffs)
    cutoffs = cutoffs.dropna(subset=["college_id", "program_id", "closing_rank"])
    dropped = before - len(cutoffs)
    if dropped:
        print(f"[normalize] cutoffs: dropped {dropped} of {before} rows with unresolved college/program/rank")
    cutoffs["cutoff_id"] = range(1, len(cutoffs) + 1)
    return cutoffs, programs


def build_seat_counts(colleges, programs, program_match_index):
    path = os.path.join(RAW_DIR, "seat_matrix", "seat_matrix_25.csv")
    df = pd.read_csv(path, header=None, dtype=str)
    df.columns = ["institute", "program", "quota", "gender"] + [f"cat_{i}" for i in range(10)] + ["row_total_display", "extra_display"]
    df["institute"] = df["institute"].ffill()

    df = df[df["gender"] != "Total Seats"].copy()

    for i in range(10):
        df[f"cat_{i}"] = pd.to_numeric(df[f"cat_{i}"], errors="coerce").fillna(0)
    df["row_seats"] = df[[f"cat_{i}" for i in range(10)]].sum(axis=1)

    name_to_id = dict(zip(colleges["canonical_name"], colleges["college_id"]))
    df["college_id"] = df["institute"].map(name_to_id)

    branch_to_program = {}
    for full_name in df["program"].dropna().unique():
        m = BRANCH_PATTERN.match(full_name)
        if not m:
            continue
        branch, duration, degree = m.group(1), int(m.group(2)), m.group(3)
        key = (match_key(branch + degree), duration)
        branch_to_program[full_name] = program_match_index.get(key)
    df["program_id"] = df["program"].map(branch_to_program)

    before = len(df)
    df = df.dropna(subset=["college_id", "program_id"])
    dropped = before - len(df)
    if dropped:
        print(f"[normalize] seat_counts: dropped {dropped} of {before} rows with unresolved college/program")

    grouped = df.groupby(["college_id", "program_id"], as_index=False)["row_seats"].sum()
    grouped["year"] = SEAT_MATRIX_YEAR
    grouped["seat_count_id"] = range(1, len(grouped) + 1)
    grouped = grouped.rename(columns={"row_seats": "seat_count"})
    return grouped[["seat_count_id", "college_id", "program_id", "year", "seat_count"]]


def loose_key(s):
    """Same as match_key but folds "&" to "and" first, since NIRF and the
    clean JoSAA sources spell the same institute name with different
    punctuation often enough that plain match_key (which just strips "&"
    to nothing) misses real matches - "Technology & Management" vs
    "Technology and Management" produce different match_key strings but
    are the same institute. Also expands "ISM" to "Indian School of Mines" -
    IIT Dhanbad's own former name, confirmed directly against NIRF's own
    published spelling ("Indian Institute of Technology (Indian School of
    Mines) Dhanbad"), not an assumed abbreviation.
    """
    s = re.sub(r"&", " and ", str(s))
    s = re.sub(r"\bISM\b", "Indian School of Mines", s)
    return match_key(s)


def match_nirf_names_to_colleges(nirf, colleges):
    """Three tiers, safest first, so a fuzzy pass never gets a chance to
    misfire where an exact one would have worked:

    1. Exact match_key - the common case, byte-for-byte-modulo-punctuation
       same name on both sides.
    2. Exact loose_key (& folded to and) - catches punctuation-only
       differences like the one above.
    3. Name containment (one side's loose_key is a substring of the
       other's) validated by city containment too. Containment alone is
       unsafe on its own: multiple real, differently-located campuses can
       share a long common name prefix (three different NIFTEM campuses
       collapsed onto one match on the first attempt at this, verified
       against a live NIRF pull before this safeguard existed). Requiring
       the NIRF row's own city to also appear in the JoSAA name rules that
       out, at the cost of only matching where the JoSAA name happens to
       mention its city - which is common for GFTIs in particular.
    """
    college_names = colleges["canonical_name"].tolist()
    college_ids = colleges["college_id"].tolist()
    exact_index = {match_key(n): cid for n, cid in zip(college_names, college_ids)}
    loose_index = {loose_key(n): cid for n, cid in zip(college_names, college_ids)}
    loose_name_by_id = {cid: loose_key(n) for n, cid in zip(college_names, college_ids)}

    resolved = []
    tier_counts = {"exact": 0, "loose": 0, "city_validated": 0, "unmatched": 0}
    for name, city in zip(nirf["name"], nirf["city"].fillna("")):
        cid = exact_index.get(match_key(name))
        tier = "exact"
        if cid is None:
            nkey = loose_key(name)
            cid = loose_index.get(nkey)
            tier = "loose"
        if cid is None:
            ckey = loose_key(city)
            if len(ckey) > 3:
                for candidate_id, candidate_key in loose_name_by_id.items():
                    if (nkey in candidate_key or candidate_key in nkey) and ckey in candidate_key:
                        cid = candidate_id
                        tier = "city_validated"
                        break
        tier_counts[tier if cid is not None else "unmatched"] += 1
        resolved.append(cid)

    print(f"[normalize] nirf name matching: {tier_counts}")
    return resolved


def build_nirf(colleges):
    nirf_dir = os.path.join(RAW_DIR, "nirf")
    frames = []
    for fname in sorted(os.listdir(nirf_dir)):
        year = int(fname.replace(".csv", ""))
        df = pd.read_csv(os.path.join(nirf_dir, fname))
        df["year"] = year
        frames.append(df)
    nirf = pd.concat(frames, ignore_index=True)

    nirf["college_id"] = match_nirf_names_to_colleges(nirf, colleges)

    unmatched = nirf["college_id"].isna().sum()
    print(f"[normalize] nirf: {unmatched} of {len(nirf)} ranking rows have no matching JoSAA college (not a JoSAA institute or name mismatch), dropped")
    nirf = nirf.dropna(subset=["college_id"])

    nirf["nirf_id"] = range(1, len(nirf) + 1)
    out = nirf[["nirf_id", "college_id", "year", "rank", "score", "city", "state"]].copy()
    out["rank"] = pd.to_numeric(out["rank"], errors="coerce")
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    return out


def attach_states(colleges, nirf):
    """Every state value here traces back to a real NIRF-published city/state
    field, matched to a canonical college by match_nirf_names_to_colleges -
    no hardcoded per-institute overrides. A college with genuinely no NIRF
    match across any of the 10 fetched years (2016-2025, all bands) stays
    null, and that null is reported below by name, not silently dropped or
    guessed.
    """
    latest = nirf.sort_values("year").drop_duplicates(subset="college_id", keep="last")
    state_map = dict(zip(latest["college_id"], latest["state"]))
    colleges = colleges.copy()
    colleges["state"] = colleges["college_id"].map(state_map)

    known = colleges["state"].notna().sum()
    still_null = colleges[colleges["state"].isna()].sort_values("canonical_name")
    print(f"[normalize] states: {known} of {len(colleges)} colleges have a known state, all NIRF-sourced (no hardcoded overrides)")
    print(f"[normalize] states: {len(still_null)} colleges remain without a verified state (not found in any NIRF year/band fetched):")
    for _, row in still_null.iterrows():
        print(f"    - {row['canonical_name']} ({row['institute_type']})")
    return colleges


def run():
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    print("[normalize] building canonical colleges and programs from clean sources...")
    colleges, programs, program_match_index = build_colleges_and_programs()
    print(f"[normalize] {len(colleges)} colleges, {len(programs)} programs from clean sources")

    print("[normalize] building unified cutoffs table (round CSVs + 2024 final + IIT backfill)...")
    cutoffs, programs = build_cutoffs(colleges, programs, program_match_index)
    print(f"[normalize] {len(cutoffs)} total cutoff rows")

    print("[normalize] building seat counts from 2025 seat matrix...")
    seat_counts = build_seat_counts(colleges, programs, program_match_index)
    print(f"[normalize] {len(seat_counts)} seat-count rows")

    print("[normalize] building NIRF rankings table...")
    nirf = build_nirf(colleges)
    print(f"[normalize] {len(nirf)} NIRF ranking rows across {nirf['year'].nunique()} years")

    colleges = attach_states(colleges, nirf)

    colleges.to_parquet(os.path.join(PROCESSED_DIR, "colleges.parquet"), index=False)
    programs.to_parquet(os.path.join(PROCESSED_DIR, "programs.parquet"), index=False)
    cutoffs.to_parquet(os.path.join(PROCESSED_DIR, "cutoffs.parquet"), index=False)
    seat_counts.to_parquet(os.path.join(PROCESSED_DIR, "seat_counts.parquet"), index=False)
    nirf.to_parquet(os.path.join(PROCESSED_DIR, "nirf_rankings.parquet"), index=False)
    print("[normalize] wrote colleges, programs, cutoffs, seat_counts, nirf_rankings to data/processed/")


if __name__ == "__main__":
    run()
