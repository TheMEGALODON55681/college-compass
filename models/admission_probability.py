"""Calibrated P(admit) per (student rank, college-branch), built entirely on
top of the finished regressor's outputs - no separate model architecture,
matching the PRD's own framing that this is "cheap" given the regressor
already exists.

THE METHOD: admission is "is the student's rank better than the true closing
rank," and the true closing rank has real uncertainty around the regressor's
point prediction. That uncertainty is grounded in real residuals (actual
minus predicted) from a held-out year, not a hand-tuned sigmoid - the raw
probability for a given (predicted, student_rank) pair is the empirical tail
probability of the residual distribution: what fraction of real historical
residuals were large enough that the actual closing rank would still have
admitted this student. Lag-eligible and cold-start rows get separate residual
samples, since the regressor's own evaluation already established they are
different error regimes (cold-start's MAE ran roughly double the lag-eligible
subset's) - using one pooled distribution would understate cold-start
uncertainty and overstate lag-eligible uncertainty.

THE TEMPORAL DISCIPLINE (mirrors the regressor's own alpha-tuning pattern):
- Residual distributions are estimated from a model trained on 2018-2021,
  evaluated on 2022 - never touching 2023 or 2024.
- Isotonic calibration is fit on 2023, using a model trained on 2018-2022 -
  a validation year, never the test year.
- The reliability curve and calibration metrics (ECE, Brier) are reported on
  2024 using the actual production regressor artifacts (trained on
  2018-2023), touched exactly once, before and after calibration.

THE GROUND TRUTH FOR CALIBRATION: there is no recorded "P(admit) was correct"
label anywhere, but there doesn't need to be one. For any real group with a
real actual closing rank in a given year, whether a hypothetical rank R would
have been admitted is a deterministic fact (R <= actual closing rank), not
itself a probability. build_probability_eval_dataset exploits this: for each
real group, it generates several hypothetical ranks spaced at residual-scale
offsets from that group's own predicted closing rank (not uniformly random
ranks, which would rarely land near any specific group's boundary), pairs
each with the raw predicted probability and the deterministic true outcome,
and that becomes real, grounded calibration and evaluation data.

HONESTY GUARDS: raw empirical tail probabilities are Laplace-clipped away
from exact 0 or 1 (a finite residual sample cannot honestly claim absolute
certainty). The serving function rounds to the nearest 5% - showing 73.418%
would imply precision the model does not have.
"""

import os

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

import models.cutoff_regressor as cutoff_regressor
from models.regressor_dataset import load_regressor_training_data

RESIDUAL_ESTIMATION_TRAIN_YEARS = list(range(2018, 2022))
RESIDUAL_ESTIMATION_EVAL_YEAR = 2022

CALIBRATION_TRAIN_YEARS = list(range(2018, 2023))
CALIBRATION_YEAR = 2023

TEST_YEAR = 2024

MIN_TAIL_PROB = 0.02
MAX_TAIL_PROB = 0.98
# Target raw probabilities to evaluate at, spaced evenly across [0,1] - not
# offsets in units of the residual std. Ranks/residuals are heavy-tailed (a
# few huge outliers inflate std far past the typical spread), so stepping in
# std-multiples was confirmed to skip most of the middle of the distribution
# entirely and leave large gaps in the reliability curve. Quantiles of the
# same residual sample used for raw_tail_probability give even coverage by
# construction instead.
PROBABILITY_TARGET_GRID = np.linspace(0.02, 0.98, 49)
DISPLAY_PRECISION_PCT = 5

ARTIFACT_PATH = "models/artifacts/admission_probability.joblib"


def _prepare_full_df(database_url=None):
    _, filtered = load_regressor_training_data(database_url)
    group_year = cutoff_regressor.collapse_to_one_row_per_group_year(filtered)
    nirf_df = cutoff_regressor._load_nirf(database_url)
    return cutoff_regressor.build_features(group_year, nirf_df)


def _train_and_predict(full_df, train_years, eval_year, alpha=1.0):
    """Trains fresh delta/fallback models scoped to train_years - used only
    for the internal estimation and calibration steps below, which need
    windows narrower than the production regressor (2018-2023) so nothing
    here leaks into the final 2024 check. Does not touch or replace the
    production artifacts saved by cutoff_regressor.py.
    """
    train_df = full_df[full_df["year"].isin(train_years)]
    eval_df = full_df[full_df["year"] == eval_year]
    delta_model, delta_features = cutoff_regressor.train_delta_model(train_df)
    fallback_model, fallback_features = cutoff_regressor.train_fallback_model(train_df)
    predictions, has_lag = cutoff_regressor.predict(
        eval_df, delta_model, delta_features, fallback_model, fallback_features, alpha=alpha
    )
    result = eval_df.copy()
    result["predicted_closing_rank"] = predictions.to_numpy()
    result["has_lag"] = has_lag.to_numpy()
    return result


def compute_residual_distributions(full_df):
    evaluated = _train_and_predict(full_df, RESIDUAL_ESTIMATION_TRAIN_YEARS, RESIDUAL_ESTIMATION_EVAL_YEAR)
    residual = evaluated["closing_rank"] - evaluated["predicted_closing_rank"]
    lag_residuals = np.sort(residual[evaluated["has_lag"]].to_numpy())
    cold_residuals = np.sort(residual[~evaluated["has_lag"]].to_numpy())
    print(
        f"[admission_probability] lag-eligible residuals (train {RESIDUAL_ESTIMATION_TRAIN_YEARS}, "
        f"eval {RESIDUAL_ESTIMATION_EVAL_YEAR}): n={len(lag_residuals)}, "
        f"mean={lag_residuals.mean():.0f}, std={lag_residuals.std():.0f}"
    )
    print(
        f"[admission_probability] cold-start residuals: n={len(cold_residuals)}, "
        f"mean={cold_residuals.mean():.0f}, std={cold_residuals.std():.0f}"
    )
    return {"lag": lag_residuals, "cold": cold_residuals}


def raw_tail_probability(residual_sample, x):
    """P(residual >= x) from the empirical distribution. Laplace-clipped so
    a finite sample never asserts absolute 0% or 100% certainty.
    """
    n = len(residual_sample)
    idx = np.searchsorted(residual_sample, x, side="left")
    raw = 1 - idx / n
    return float(np.clip(raw, MIN_TAIL_PROB, MAX_TAIL_PROB))


def offsets_for_probability_targets(residual_sample):
    """The rank offsets (from a predicted closing rank) that make
    raw_tail_probability hit roughly PROBABILITY_TARGET_GRID's values,
    derived as quantiles of the same residual sample the probability itself
    is computed from - guarantees even coverage across the probability
    range by construction, unlike stepping in units of std.
    """
    return np.quantile(residual_sample, 1 - PROBABILITY_TARGET_GRID)


def build_eval_rows_from_predictions(evaluated, residual_distributions):
    """For each real group in an already-predicted dataframe (columns
    predicted_closing_rank, has_lag, closing_rank), generates hypothetical
    ranks spanning the full probability range (see
    offsets_for_probability_targets) around that group's own predicted
    closing rank, and pairs each with the raw predicted probability and the
    deterministic true outcome (hypothetical rank <= that group's real
    actual closing rank). Uses each group's own predicted distribution
    rather than uniformly random ranks, which would rarely land near any
    one group's actual boundary. Shared by the calibration-fitting step
    (predictions from a freshly trained validation-window model) and the
    final test step (predictions from the loaded production artifacts).
    """
    offsets_by_segment = {
        "lag": offsets_for_probability_targets(residual_distributions["lag"]),
        "cold": offsets_for_probability_targets(residual_distributions["cold"]),
    }

    rows = []
    for row in evaluated.itertuples(index=False):
        segment = "lag" if row.has_lag else "cold"
        sample = residual_distributions[segment]
        for offset in offsets_by_segment[segment]:
            hypothetical_rank = row.predicted_closing_rank + offset
            if hypothetical_rank <= 0:
                continue
            raw_p = raw_tail_probability(sample, hypothetical_rank - row.predicted_closing_rank)
            actual_outcome = int(hypothetical_rank <= row.closing_rank)
            rows.append({"raw_probability": raw_p, "outcome": actual_outcome})
    return pd.DataFrame(rows)


def build_probability_eval_dataset(full_df, year, train_years, residual_distributions, alpha=1.0):
    evaluated = _train_and_predict(full_df, train_years, year, alpha=alpha)
    return build_eval_rows_from_predictions(evaluated, residual_distributions)


def fit_calibration(calibration_df):
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(calibration_df["raw_probability"], calibration_df["outcome"])
    return iso


def apply_calibration(calibrator, raw_probabilities):
    return calibrator.predict(np.asarray(raw_probabilities))


def reliability_curve(probabilities, outcomes, n_bins=10):
    bins = np.linspace(0, 1, n_bins + 1)
    bin_ids = np.clip(np.digitize(probabilities, bins[1:-1]), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        mask = bin_ids == b
        if mask.sum() == 0:
            continue
        rows.append(
            {
                "bin_range": f"{bins[b]:.1f}-{bins[b + 1]:.1f}",
                "n": int(mask.sum()),
                "mean_predicted": float(np.mean(probabilities[mask])),
                "observed_frequency": float(np.mean(outcomes[mask])),
            }
        )
    return pd.DataFrame(rows)


def expected_calibration_error(probabilities, outcomes, n_bins=10):
    curve = reliability_curve(probabilities, outcomes, n_bins)
    total = len(probabilities)
    return float(np.sum(curve["n"] / total * np.abs(curve["mean_predicted"] - curve["observed_frequency"])))


def brier_score(probabilities, outcomes):
    return float(np.mean((np.asarray(probabilities) - np.asarray(outcomes)) ** 2))


def save_artifacts(residual_distributions, calibrator):
    import joblib

    os.makedirs(os.path.dirname(ARTIFACT_PATH), exist_ok=True)
    joblib.dump({"residual_distributions": residual_distributions, "calibrator": calibrator}, ARTIFACT_PATH)
    print(f"[admission_probability] saved to {ARTIFACT_PATH}")


def load_artifacts():
    import joblib

    return joblib.load(ARTIFACT_PATH)


def predict_admission_probability(predicted_closing_rank, student_rank, has_lag, artifacts):
    """The serving function - api/main.py calls this per result row. Rounds
    to the nearest 5% so the number never implies more precision than a
    residual-distribution estimate can honestly support.
    """
    sample = artifacts["residual_distributions"]["lag" if has_lag else "cold"]
    raw_p = raw_tail_probability(sample, student_rank - predicted_closing_rank)
    calibrated = float(apply_calibration(artifacts["calibrator"], [raw_p])[0])
    rounded_pct = round(calibrated * 100 / DISPLAY_PRECISION_PCT) * DISPLAY_PRECISION_PCT
    return rounded_pct / 100


def run(database_url=None):
    print("[admission_probability] building features across 2018-2024...")
    full_df = _prepare_full_df(database_url)

    print(f"\n[admission_probability] estimating residual distributions (train {RESIDUAL_ESTIMATION_TRAIN_YEARS}, eval {RESIDUAL_ESTIMATION_EVAL_YEAR})...")
    residual_distributions = compute_residual_distributions(full_df)

    print(f"\n[admission_probability] building calibration dataset (train {CALIBRATION_TRAIN_YEARS}, eval {CALIBRATION_YEAR})...")
    calibration_df = build_probability_eval_dataset(full_df, CALIBRATION_YEAR, CALIBRATION_TRAIN_YEARS, residual_distributions)
    print(f"[admission_probability] {len(calibration_df)} calibration rows from {CALIBRATION_YEAR}")

    print(f"[admission_probability] fitting isotonic calibration on {CALIBRATION_YEAR} (never on {TEST_YEAR})...")
    calibrator = fit_calibration(calibration_df)

    print(f"\n[admission_probability] building final test set from the production regressor ({TEST_YEAR}, touched once)...")
    delta_model, fallback_model, metadata = cutoff_regressor.load_artifacts()
    test_df = full_df[full_df["year"] == TEST_YEAR].copy()
    predictions, has_lag = cutoff_regressor.predict(
        test_df, delta_model, metadata["delta_features"], fallback_model, metadata["fallback_features"], alpha=metadata["alpha"]
    )
    test_df["predicted_closing_rank"] = predictions.to_numpy()
    test_df["has_lag"] = has_lag.to_numpy()

    test_eval_df = build_eval_rows_from_predictions(test_df, residual_distributions)
    print(f"[admission_probability] {len(test_eval_df)} test rows from {TEST_YEAR}")

    raw_probs = test_eval_df["raw_probability"].to_numpy()
    outcomes = test_eval_df["outcome"].to_numpy()
    calibrated_probs = apply_calibration(calibrator, raw_probs)

    print(f"\n=== Reliability curve on {TEST_YEAR} - BEFORE calibration ===")
    print(reliability_curve(raw_probs, outcomes).to_string(index=False))
    ece_before, brier_before = expected_calibration_error(raw_probs, outcomes), brier_score(raw_probs, outcomes)
    print(f"ECE before: {ece_before:.4f}   Brier before: {brier_before:.4f}")

    print(f"\n=== Reliability curve on {TEST_YEAR} - AFTER calibration ===")
    print(reliability_curve(calibrated_probs, outcomes).to_string(index=False))
    ece_after, brier_after = expected_calibration_error(calibrated_probs, outcomes), brier_score(calibrated_probs, outcomes)
    print(f"ECE after: {ece_after:.4f}   Brier after: {brier_after:.4f}")

    print(f"\nECE improvement: {ece_before - ece_after:+.4f}   Brier improvement: {brier_before - brier_after:+.4f}")

    save_artifacts(residual_distributions, calibrator)
    return residual_distributions, calibrator


if __name__ == "__main__":
    run()
