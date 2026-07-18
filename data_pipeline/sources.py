"""Source constants for every real dataset the pipeline ingests.

Every URL here was hand-verified reachable without any login or API key.
No Kaggle source is used because bulk download requires an authenticated
API token that isn't available in this environment. JoSAA's own site
(josaa.admissions.nic.in) is a cascading ASP.NET form with no bulk export,
so the round-level cutoff data below comes from public scrapes of that same
official archive instead of the form itself.
"""

JOSAA_ROUND_CSV_TEMPLATE = "https://raw.githubusercontent.com/seshaljain/josaa-scrape/master/data/{year}-{round}.csv"
JOSAA_ROUND_YEARS = range(2016, 2021)
JOSAA_ROUND_MAX_ROUND_GUESS = 7

JOSAA_2024_CSV_URL = "https://raw.githubusercontent.com/Quantum-Codes/JoSAA_2024/main/exported_data/csv/josaa24.csv"
JOSAA_2024_YEAR = 2024

SEAT_MATRIX_2025_URL = "https://raw.githubusercontent.com/Quantum-Codes/JoSAA_2024/main/exported_data/csv/seat_matrix_25.csv"
SEAT_MATRIX_YEAR = 2025

# Closes the 2021-2023 NIT/IIIT/GFTI gap flagged by the regressor's own honest
# evaluation (see models/cutoff_regressor.py). Two more independently sourced,
# hand-verified real files, found after the original four above. These
# supersede and replace an earlier IIT-only 2021-2023 backfill source (since
# removed) that both of these now cover more completely, across all
# institute types rather than IITs alone - keeping both would have silently
# double-counted every IIT row for 2021-2023.
#
# - full_2021_2022: same shape as the round-CSV source (Year, Round, full
#   institute names, real Gender-Neutral/Female-only labels), all institute
#   types, for 2021 and 2022. The file also repeats 2016-2020, which are
#   dropped at normalize time since seshaljain's source already covers those
#   years and is the one already cross-checked into the pipeline.
# - snapshot_2023: a single-round snapshot in the same abbreviated-name schema
#   as Sbrjt's current-year mirror (IIT Bhubaneswar, not the full name; Quota
#   AI/HS/OS/GO/JK/LA; Gender Neutral/Female, not Gender-Neutral/Female-only).
#   No Year/Round column, stamped 2023 at ingest time.
#
# Both were verified before use: NIT Tiruchirappalli's own official
# published PDFs (nitt.edu) for 2021 and 2023 show the same opening ranks
# for Computer Science and Engineering under HS and OS quota that these
# sources report (closing ranks differ by a small amount, consistent with
# comparing a specific round to the institute's own final consolidated
# figure, not a wrong year or corrupted data).
FULL_2021_2022_CSV_URL = "https://raw.githubusercontent.com/blossomedinautumn/JOSAA_DataAnalysis/main/data_analysis/static/data/2016-2023dataa.csv"
FULL_2021_2022_MIN_YEAR = 2021
FULL_2021_2022_MAX_YEAR = 2022

SNAPSHOT_2023_SQLITE_URL = "https://raw.githubusercontent.com/Sbrjt/josaa-cutoffs/7cea8f4615/data.db.gz"
SNAPSHOT_2023_TABLE = "tb"
SNAPSHOT_2023_YEAR = 2023

NIRF_URL_TEMPLATE = "https://www.nirfindia.org/Rankings/{year}/EngineeringRanking{suffix}.html"
NIRF_YEARS = range(2016, 2026)
NIRF_BAND_SUFFIXES = ["", "150", "200", "250", "300", "350", "400", "450", "500"]

RAW_DIR = "data/raw"
PROCESSED_DIR = "data/processed"
