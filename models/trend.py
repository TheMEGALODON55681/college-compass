"""Deterministic year-over-year cutoff trend classifier. Pure: no I/O, no
database access, no randomness, no LLM (docs/Rules.md section 5's honesty
rule for this feature). Given a college / branch / category / seat-pool's
settled closing-rank history, says whether the cutoff has been getting more
competitive (Tightening), easier (Loosening), or basically flat (Stable) -
or, below the minimum history, says so honestly instead of guessing.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

# Fixed product decision (docs/PRD.md), not tuned here: below three usable
# years there is nothing to fit a trend to, and two points would always fit
# a "trend" perfectly by construction, which would be worse than admitting
# there isn't one. Phase 0's audit (docs/BuildLog.md) found 6,904 of 9,911
# college/branch/category/quota keys (69.7%) have three or more usable
# years, so this floor leaves most of the product's real coverage intact.
MIN_YEARS = 3

# A raw normalized slope mixes two things: how this key is moving, and how
# the whole system is moving. JoSAA's seat pool broadly expanded 2016-2024,
# so most keys drift toward an easier cutoff regardless of anything specific
# to that college or branch - at the old raw threshold (docs/BuildLog.md,
# Phase 2 Task 3), 57.2% of keys came back Loosening, which is a broken
# label: it tells a student nothing when it's true for more than half of
# everything they compare. This is the system-wide drift, subtracted before
# classification so the label means "moving against the field", not "moving".
#
# Computed once as the median normalized OLS slope (same per-key fit as
# NEUTRAL_BAND_FRACTION below) across every one of the 6,904 keys with 3+
# usable years, year span 2016-2024. Must be refit if the data is
# reingested with years outside that span - a materially different year
# range changes what "system-wide" means.
DRIFT_MEDIAN_SLOPE = 0.0412

# How far the slope has to move, as a fraction of the series' own mean
# closing rank, *after* subtracting DRIFT_MEDIAN_SLOPE, before it counts as
# a real direction instead of noise. Refit against the residual
# distribution, not the raw one the old value was fit against - the two
# happen to land on the same number, but they answer different questions.
#
# Swept over the same 6,904-key population (residual = normalized slope -
# DRIFT_MEDIAN_SLOPE): 0.03 is the smallest band where Stable is the
# plurality label - 36.6% Stable, 32.6% Tightening, 30.7% Loosening. Below
# it (e.g. 0.02) Tightening edges out Stable (38.0% vs 25.1%); above it
# (e.g. 0.05) Stable dominates more than the data supports (55.1%). At 0.03,
# most colleges land where they should: not moving relative to the field.
NEUTRAL_BAND_FRACTION = 0.03

# The slope is normalized against the series' own arithmetic mean closing
# rank, not its first or last value, so one outlier year at either end can't
# dominate the scale the way it would against a single-point basis - and a
# rank-40,000 college's neutral band means a different absolute rank move
# than a rank-500 college's, which is the whole reason this is a fraction.
NORMALIZATION_BASIS = "arithmetic mean of the series' own closing ranks"

TIGHTENING = "Tightening"
STABLE = "Stable"
LOOSENING = "Loosening"
INSUFFICIENT_HISTORY = "Insufficient history"


@dataclass(frozen=True)
class TrendResult:
    label: str
    years_used: int
    slope: Optional[float] = None
    residual_slope: Optional[float] = None
    reason: Optional[str] = None


def classify_trend(series):
    """series: an iterable of (year, closing_rank) pairs for one college /
    branch / category / seat-pool key, any order - sorted here by year.

    `slope` is the raw fitted slope in rank units per year - kept in the
    result even though the label isn't based on it, because it's what
    explains the label to anyone asking how it was derived. `residual_slope`
    (normalized, then detrended by DRIFT_MEDIAN_SLOPE) is what the label
    actually compares against NEUTRAL_BAND_FRACTION.
    """
    ordered = sorted(series)
    years_used = len(ordered)

    if years_used < MIN_YEARS:
        return TrendResult(
            label=INSUFFICIENT_HISTORY,
            years_used=years_used,
            reason=f"only {years_used} usable year{'s' if years_used != 1 else ''}, minimum is {MIN_YEARS}",
        )

    years = np.array([year for year, _ in ordered], dtype=float)
    ranks = np.array([rank for _, rank in ordered], dtype=float)
    slope, _intercept = np.polyfit(years, ranks, 1)
    normalized_slope = slope / ranks.mean()
    residual_slope = normalized_slope - DRIFT_MEDIAN_SLOPE

    if residual_slope <= -NEUTRAL_BAND_FRACTION:
        label = TIGHTENING
    elif residual_slope >= NEUTRAL_BAND_FRACTION:
        label = LOOSENING
    else:
        label = STABLE

    return TrendResult(
        label=label,
        years_used=years_used,
        slope=round(float(slope), 1),
        residual_slope=round(float(residual_slope), 4),
    )


def series_from_history(history):
    """Adapts get_cutoff_history()/get_cutoff_history_bulk()'s row shape
    (api/main.py: year, closing_rank, round, opening_rank) down to
    classify_trend's (year, closing_rank) input. round and opening_rank are
    dropped, not inspected either way - a null round (2023/2024's shape,
    settled with no round breakdown) describes that year the same as any
    other for trend purposes.
    """
    return [(row["year"], row["closing_rank"]) for row in history]
