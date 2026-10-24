"""The boot-time cutoffs read must return exactly the locked-policy subset the
regressor trains on (Gender-Neutral, 2018 onward), in the same row order,
restricted to the columns the features read. A one-shot SELECT * of the whole
table used to peak near 640 MB at boot; this loader filters in SQL and reads in
chunks, so these tests pin that it still returns the same frame.

Runs against the real college_compass.db, like the other golden tests.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models.regressor_dataset as regressor_dataset
from models.regressor_dataset import SERVING_COLUMNS, load_regressor_training_data, load_serving_cutoffs

SMALL_CHUNK = 1_001


def test_serving_cutoffs_match_training_subset():
    _, filtered = load_regressor_training_data()
    expected = filtered[SERVING_COLUMNS].reset_index(drop=True)
    pd.testing.assert_frame_equal(load_serving_cutoffs(), expected)


def test_serving_cutoffs_survive_all_null_round_chunks(monkeypatch):
    """2023 and 2024 rows have no round, so with a small chunk some chunks are
    all NULL in `round`, which pandas would read as object. The frame must still
    come out identical to the default-chunk read, dtypes included.
    """
    whole = load_serving_cutoffs()
    monkeypatch.setattr(regressor_dataset, "SERVING_CHUNK_ROWS", SMALL_CHUNK)

    chunked = load_serving_cutoffs()

    starts = range(0, len(chunked), SMALL_CHUNK)
    assert any(chunked["round"].iloc[i : i + SMALL_CHUNK].isna().all() for i in starts), "no all-NULL chunk to exercise"
    assert chunked["round"].dtype == "float64"
    pd.testing.assert_frame_equal(chunked, whole)
