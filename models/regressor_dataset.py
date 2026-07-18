"""Training-set assembly policy for the cutoff regressor.

Locked policy: the regressor trains on a single consistent schema only.
JoSAA did not gender-split cutoffs until 2018 - 2016 and 2017 have one row
per college/branch/category with no gender breakdown, while 2018 onward has
two (Gender-Neutral and Female-only, see normalize.py's normalize_gender_label).
Mixing both into one training set would teach the model an inconsistency:
gender is a real signal from 2018 on and a placeholder sentinel before it.

So this assembles the regressor's dataset as Gender-Neutral rows, years 2018
onward, only. 2016 and 2017 stay in the database untouched - they're excluded
from this one dataset, not deleted, and remain available for lookups and
completeness elsewhere. The temporal split itself is unchanged by this: still
train-on-earlier-years/test-on-most-recent, applied within the 2018+ window,
never a random split.

This module only assembles and filters the dataset. Training the regressor
itself happens in cutoff_regressor.py.
"""

import pandas as pd

from db.connection import get_database_url, get_engine

MIN_TRAINING_YEAR = 2018
TRAINING_GENDER = "Gender-Neutral"


def load_regressor_training_data(database_url=None):
    """Returns (all_cutoffs, filtered) - the full table and the regressor's
    locked-policy training subset, so callers can report the effect of the
    filter rather than just seeing the end result.
    """
    database_url = database_url or get_database_url()
    engine = get_engine(database_url)
    all_cutoffs = pd.read_sql("SELECT * FROM cutoffs", engine)

    filtered = all_cutoffs[
        (all_cutoffs["gender_seat_type"] == TRAINING_GENDER) & (all_cutoffs["year"] >= MIN_TRAINING_YEAR)
    ].copy()

    return all_cutoffs, filtered


def report(database_url=None):
    all_cutoffs, filtered = load_regressor_training_data(database_url)

    print(f"[regressor_dataset] total cutoff rows in DB: {len(all_cutoffs)}")
    print(
        f"[regressor_dataset] rows after gender=={TRAINING_GENDER!r} and year>={MIN_TRAINING_YEAR} filter: {len(filtered)}"
    )
    print(f"[regressor_dataset] year range in filtered set: {sorted(filtered['year'].unique().tolist())}")
    print(f"[regressor_dataset] gender values in filtered set: {sorted(filtered['gender_seat_type'].unique().tolist())}")

    pre_2018_in_db = all_cutoffs[all_cutoffs["year"].isin([2016, 2017])]
    pre_2018_in_filtered = filtered[filtered["year"].isin([2016, 2017])]
    print(f"[regressor_dataset] 2016/2017 rows still in DB: {len(pre_2018_in_db)} (must be > 0 - confirms not deleted)")
    print(f"[regressor_dataset] 2016/2017 rows in filtered training set: {len(pre_2018_in_filtered)} (must be 0)")

    return filtered


if __name__ == "__main__":
    report()
