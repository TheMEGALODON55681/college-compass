"""Runnable checks for models/trend.py's deterministic trend classifier.
Written before the implementation (docs/Rules.md's review gate and this
phase's own task order both call for tests first).

Every fixture below is picked and verified (see docs/BuildLog.md's slope
analysis) against the classifier's actual thresholds, not against a guess at
what they should be.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.trend import (
    DRIFT_MEDIAN_SLOPE,
    INSUFFICIENT_HISTORY,
    LOOSENING,
    MIN_YEARS,
    NEUTRAL_BAND_FRACTION,
    STABLE,
    TIGHTENING,
    classify_trend,
    series_from_history,
)


def test_clearly_tightening_series():
    series = [(2020, 12000), (2021, 9000), (2022, 6000), (2023, 3000)]
    result = classify_trend(series)
    assert result.label == TIGHTENING
    assert result.slope < 0
    assert result.years_used == 4


def test_clearly_loosening_series():
    series = [(2020, 5000), (2021, 7000), (2022, 9000), (2023, 11000)]
    result = classify_trend(series)
    assert result.label == LOOSENING
    assert result.slope > 0
    assert result.years_used == 4


def test_series_moving_with_the_field_is_stable():
    """A series whose own normalized slope roughly matches DRIFT_MEDIAN_SLOPE
    (the system-wide drift) is stable relative to the field, not stable in
    absolute terms - this college's cutoff is moving, just at the same pace
    as everything else, so nothing distinguishes it. That's the case this
    test covers now that classify_trend compares a detrended residual, not
    the raw slope, against NEUTRAL_BAND_FRACTION.
    """
    series = [(2019, 9200), (2020, 9600), (2021, 10000), (2022, 10400)]
    result = classify_trend(series)
    assert result.label == STABLE
    assert result.years_used == 4
    assert abs(result.residual_slope) < NEUTRAL_BAND_FRACTION


def test_two_year_series_is_insufficient_history():
    series = [(2022, 8000), (2023, 7500)]
    result = classify_trend(series)
    assert result.label == INSUFFICIENT_HISTORY
    assert result.years_used == 2
    assert result.slope is None
    assert result.reason  # names why, never silent


def test_gap_year_series_still_classifies():
    """2020 is missing entirely, not padded and not interpolated - the
    classifier works on however many real points it's given, keyed on year,
    not on a contiguous run.
    """
    series = [(2018, 16000), (2019, 13000), (2021, 7000), (2022, 4000)]
    result = classify_trend(series)
    assert result.label == TIGHTENING
    assert result.years_used == 4


def test_single_outlier_year_does_not_flip_the_label():
    """Five years of a clear tightening trend plus one loosening spike (2022)
    - ordinary least squares over enough real points shouldn't let one bad
    year flip the overall direction.
    """
    series = [(2018, 20000), (2019, 18000), (2020, 16000), (2021, 14000), (2022, 20000), (2023, 10000)]
    result = classify_trend(series)
    assert result.label == TIGHTENING


def test_all_null_round_history_classifies_the_same_as_any_other():
    """2023 and 2024 carry no round breakdown at all (docs/Memory.md) - every
    row in the source history is round: null. classify_trend never sees
    round at all, and series_from_history must not treat a null round as
    missing or as a reason to drop the row.
    """
    all_null_round_history = [
        {"year": 2021, "closing_rank": 12000, "round": None, "opening_rank": None},
        {"year": 2022, "closing_rank": 9000, "round": None, "opening_rank": None},
        {"year": 2023, "closing_rank": 6000, "round": None, "opening_rank": None},
        {"year": 2024, "closing_rank": 3000, "round": None, "opening_rank": None},
    ]
    mixed_round_history = [
        {"year": 2021, "closing_rank": 12000, "round": 6, "opening_rank": 8000},
        {"year": 2022, "closing_rank": 9000, "round": 5, "opening_rank": 6000},
        {"year": 2023, "closing_rank": 6000, "round": None, "opening_rank": None},
        {"year": 2024, "closing_rank": 3000, "round": None, "opening_rank": None},
    ]
    result_all_null = classify_trend(series_from_history(all_null_round_history))
    result_mixed = classify_trend(series_from_history(mixed_round_history))
    assert result_all_null.label == TIGHTENING
    assert result_all_null == result_mixed


def test_loosening_raw_slope_that_lags_the_field_is_not_loosening():
    """The case detrending exists for. This series' raw slope is clearly
    loosening (positive, and on its own would have cleared the pre-detrend
    NEUTRAL_BAND_FRACTION=0.03 threshold) - but it is loosening at roughly
    the same pace as the system-wide drift (DRIFT_MEDIAN_SLOPE), so relative
    to the field it is not getting distinguishably easier. Without
    detrending this comes back Loosening; with it, the excess over the
    field's own drift falls inside the neutral band, so it must not.
    """
    series = [(2019, 8500), (2020, 9000), (2021, 9500), (2022, 10000)]
    result = classify_trend(series)
    mean_rank = sum(rank for _, rank in series) / len(series)
    raw_normalized_slope = result.slope / mean_rank

    assert result.slope > 0
    assert raw_normalized_slope >= 0.03  # would have cleared the old, un-detrended threshold
    assert result.label != LOOSENING
    assert result.residual_slope == round(raw_normalized_slope - DRIFT_MEDIAN_SLOPE, 4)


def test_min_years_matches_phase0_coverage_floor():
    """Not a behavioural test - a tripwire. If MIN_YEARS ever changes, the
    69.7% coverage figure this phase put in the README and in trend.py's own
    top-of-file comment (computed at MIN_YEARS=3) needs to change with it.
    """
    assert MIN_YEARS == 3


if __name__ == "__main__":
    test_clearly_tightening_series()
    test_clearly_loosening_series()
    test_series_moving_with_the_field_is_stable()
    test_two_year_series_is_insufficient_history()
    test_gap_year_series_still_classifies()
    test_single_outlier_year_does_not_flip_the_label()
    test_all_null_round_history_classifies_the_same_as_any_other()
    test_loosening_raw_slope_that_lags_the_field_is_not_loosening()
    test_min_years_matches_phase0_coverage_floor()
    print("ok")
