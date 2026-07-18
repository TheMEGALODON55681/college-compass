"""Predicts a college/branch/category/quota's closing rank for a target year.

THE CENTRAL DESIGN PROBLEM: the product premise is "predict this year's
cutoffs," but the most recent year with an actual closing-rank label is 2024
(2025 has only a seat matrix, no result). So any 2025-or-later prediction is a
genuine forecast with nothing to check it against, and raw calendar `year`
cannot be the mechanism the model uses to get there: gradient-boosted trees
do not extrapolate past the numeric range they trained on, so a model that
leans on year=2018..2024 as a naked feature would be asked to extrapolate to
year=2025, a value it never saw, and would produce garbage.

THE FIX: predict the year-over-year CHANGE in closing rank, not the absolute
value, then reconstruct the absolute prediction as last_year_actual + predicted_delta.
The delta stays inside the training range no matter how far forward you
forecast - forecasting 2025 becomes "take 2024's real closing rank and add a
predicted change," which is interpolation on a trend the model has seen many
times, not extrapolation off the edge of it. Raw year never drives the model;
the only time-shaped feature used is "years since this group's first
appearance," a bounded count, not a calendar point - see build_features().

COLD START: some groups have no year-1 row (a group's earliest appearance, or
a genuine gap - see below) and the delta framing doesn't apply to them. Those
get a separate absolute-rank model trained on non-temporal features
(category, quota, branch, college, NIRF rank, round), generalizing from peer
groups instead of the group's own history.

A NOTE ON COLD START'S SIZE: an earlier run of this file, before the data
pipeline sourced two more real backfill files for 2021-2022 and 2023 (see
data_pipeline/sources.py), found that a NIT/IIIT/GFTI cutoff-data gap for
those years pushed 82% of the 2024 test set into cold start, and that the
naive last-year baseline was scored on a lag-eligible subset that was
entirely IIT rows as a direct result - which turned out to be an unusually
stable population, making that baseline look far stronger than it would be
market-wide. With that gap closed, cold start is down to 14.7% of the 2024
test set and the lag-eligible subset is representative across institute
types; see the evaluation output for the current, honest numbers. The
evaluation below still reports the lag-eligible and cold-start subsets
separately rather than blending them, because they remain genuinely
different prediction regimes with different data support, and blending them
into one MAE would hide exactly the distinction that matters most for
reading this model's results honestly.

Seat-count-change is in the PRD's feature wishlist but is deliberately left
out here: the only real seat-count source ingested is a single 2025 snapshot
(see data_pipeline/normalize.py), so no genuine year-over-year seat-count
delta exists for any training year. Fabricating one would be worse than
omitting it.

SHRINKAGE: with a representative test set, the delta model came out close to
but still behind the naive last-year baseline on the lag-eligible slice - a
sign it was carrying a bit more noise than signal on a population whose true
deltas are usually small. The fix is shrinkage: predict
`alpha * predicted_delta` instead of the raw delta, blending the model's
output partway back toward the naive baseline. alpha=0 reproduces the naive
baseline exactly; alpha=1 reproduces the unshrunk model. alpha is selected by
sweeping a validation year (2023) with a model trained only on years before
it (2018-2022) - never on the 2024 test set, which would be tuning a
hyperparameter on the exact data used to report the headline number, the
same leakage mistake as a leaked feature. The production delta model itself
is retrained on the full 2018-2023 window afterward, same as always;
shrinkage only rescales what that model already outputs, so nothing about
training, features, or the temporal split changes because of it.
"""

import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

from db.connection import get_database_url, get_engine
from models.regressor_dataset import load_regressor_training_data

GROUP_COLS = ["college_id", "program_id", "quota", "category"]
CATEGORICAL_FEATURES = ["college_id", "program_id", "quota", "category"]
TREND_WINDOW = 3

ARTIFACT_DIR = "models/artifacts"
DELTA_MODEL_PATH = os.path.join(ARTIFACT_DIR, "delta_model.txt")
FALLBACK_MODEL_PATH = os.path.join(ARTIFACT_DIR, "fallback_model.txt")
METADATA_PATH = os.path.join(ARTIFACT_DIR, "metadata.json")

TRAIN_YEARS = list(range(2018, 2024))
TEST_YEAR = 2024

ALPHA_TRAIN_YEARS = list(range(2018, 2023))
VALIDATION_YEAR = 2023
ALPHA_SWEEP = [round(x * 0.1, 1) for x in range(0, 11)]

RANK_BANDS = [(0, 10_000, "top (<=10k)"), (10_000, 50_000, "mid (10k-50k)"), (50_000, float("inf"), "high (>50k)")]


def _load_nirf(database_url=None):
    database_url = database_url or get_database_url()
    engine = get_engine(database_url)
    return pd.read_sql("SELECT college_id, year, rank AS nirf_rank FROM nirf_rankings", engine)


def collapse_to_one_row_per_group_year(filtered_cutoffs):
    """Round varies within a year (2018-2023); 2024 is already a single
    terminal snapshot with round unset. For each (group, year), keep the
    row with the highest round number - the settled, final-round closing
    rank for that year, which is what "the closing rank for year X" means
    anywhere else in this project (Phase 1's direct lookup included).
    NaN round (2024) sorts as the highest so it is kept as-is, which is
    correct since it is already the terminal snapshot.
    """
    df = filtered_cutoffs.copy()
    df["_round_sort_key"] = df["round"].fillna(np.inf)
    idx = df.groupby(GROUP_COLS + ["year"])["_round_sort_key"].idxmax()
    out = df.loc[idx].drop(columns="_round_sort_key").reset_index(drop=True)
    return out


def build_features(group_year_df, nirf_df):
    """Attaches lag, trend, and bounded time-context features, all computed
    using only years strictly before the row's own year where that matters,
    so nothing here can leak future information into a training row.
    """
    df = group_year_df.merge(nirf_df, on=["college_id", "year"], how="left")

    df = df.sort_values(GROUP_COLS + ["year"]).reset_index(drop=True)

    lag_values = []
    trend_values = []
    years_since_first = []

    for _, group in df.groupby(GROUP_COLS, sort=False):
        years = group["year"].tolist()
        ranks = group["closing_rank"].tolist()
        year_to_rank = dict(zip(years, ranks))
        first_year = min(years)

        deltas_by_year = {}
        prev_year, prev_rank = None, None
        for y, r in sorted(zip(years, ranks)):
            if prev_year is not None:
                deltas_by_year[y] = r - prev_rank
            prev_year, prev_rank = y, r

        for y in years:
            lag_values.append(year_to_rank.get(y - 1))

            prior_deltas = [deltas_by_year[dy] for dy in deltas_by_year if dy < y]
            prior_deltas = prior_deltas[-TREND_WINDOW:] if prior_deltas else []
            trend_values.append(sum(prior_deltas) / len(prior_deltas) if prior_deltas else np.nan)

            years_since_first.append(y - first_year)

    df["lag_closing_rank"] = lag_values
    df["trend_term"] = trend_values
    df["years_since_first_seen"] = years_since_first
    df["delta"] = df["closing_rank"] - df["lag_closing_rank"]

    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("category")

    return df


def leakage_check(df, n=5):
    """Prints concrete evidence that the lag comes only from strictly
    earlier years - the easy mistake to make with lag features.
    """
    print("\n=== Leakage check: lag must come from year - 1, never the same or a future year ===")
    sample = df.dropna(subset=["lag_closing_rank"]).sample(min(n, df["lag_closing_rank"].notna().sum()), random_state=1)
    all_ok = True
    for _, row in sample.iterrows():
        prior_row = df[
            (df["college_id"] == row["college_id"])
            & (df["program_id"] == row["program_id"])
            & (df["quota"] == row["quota"])
            & (df["category"] == row["category"])
            & (df["year"] == row["year"] - 1)
        ]
        matches = not prior_row.empty and prior_row.iloc[0]["closing_rank"] == row["lag_closing_rank"]
        all_ok = all_ok and matches
        print(
            f"  {row['college_id']} / {row['program_id']} / {row['category']} / {row['quota']}: "
            f"year {row['year']}, lag={row['lag_closing_rank']}, "
            f"year-1 actual={prior_row.iloc[0]['closing_rank'] if not prior_row.empty else 'MISSING'} -> {'OK' if matches else 'MISMATCH'}"
        )
    print(f"leakage check: {'PASSED' if all_ok else 'FAILED'}")


def train_delta_model(train_df):
    features = CATEGORICAL_FEATURES + ["nirf_rank", "round", "years_since_first_seen", "trend_term", "lag_closing_rank"]
    eligible = train_df.dropna(subset=["lag_closing_rank"])
    X, y = eligible[features], eligible["delta"]
    dataset = lgb.Dataset(X, label=y, categorical_feature=CATEGORICAL_FEATURES, free_raw_data=False)
    params = {"objective": "regression_l1", "num_leaves": 31, "learning_rate": 0.05, "verbose": -1, "min_data_in_leaf": 15}
    model = lgb.train(params, dataset, num_boost_round=300)
    return model, features


def train_fallback_model(train_df):
    """Absolute-rank model for cold-start rows (no year-1 lag). Uses only
    non-temporal features so it can generalize from a group's peers -
    similar category/quota/branch/college/NIRF profile - rather than that
    group's own missing history.
    """
    features = CATEGORICAL_FEATURES + ["nirf_rank", "round", "years_since_first_seen"]
    X, y = train_df[features], train_df["closing_rank"]
    dataset = lgb.Dataset(X, label=y, categorical_feature=CATEGORICAL_FEATURES, free_raw_data=False)
    params = {"objective": "regression_l1", "num_leaves": 31, "learning_rate": 0.05, "verbose": -1, "min_data_in_leaf": 15}
    model = lgb.train(params, dataset, num_boost_round=300)
    return model, features


def predict(df, delta_model, delta_features, fallback_model, fallback_features, alpha=1.0):
    """alpha shrinks the delta model's output toward the naive baseline
    (alpha=0 is the naive baseline, alpha=1 is the raw model). Cold-start
    rows are unaffected by alpha - there is no delta to shrink, so they
    always go through the fallback model.
    """
    has_lag = df["lag_closing_rank"].notna()
    preds = pd.Series(index=df.index, dtype="float64")

    if has_lag.any():
        delta_pred = delta_model.predict(df.loc[has_lag, delta_features])
        preds.loc[has_lag] = df.loc[has_lag, "lag_closing_rank"].to_numpy() + alpha * delta_pred

    if (~has_lag).any():
        preds.loc[~has_lag] = fallback_model.predict(df.loc[~has_lag, fallback_features])

    return preds.clip(lower=1), has_lag


def mae(actual, predicted):
    return float(np.mean(np.abs(actual.to_numpy() - predicted.to_numpy())))


def select_alpha(full_df):
    """Sweeps the shrinkage weight on a held-out validation year (2023)
    using a model trained only on years before it (2018-2022) - never the
    2024 test set. Tuning a hyperparameter on the same data used to report
    the headline number is leakage just as much as a leaked feature would
    be, even though it feels lower-stakes.
    """
    train_df = full_df[full_df["year"].isin(ALPHA_TRAIN_YEARS)]
    val_df = full_df[full_df["year"] == VALIDATION_YEAR]
    val_eligible = val_df.dropna(subset=["lag_closing_rank"])

    val_delta_model, delta_features = train_delta_model(train_df)
    predicted_delta = val_delta_model.predict(val_eligible[delta_features])
    lag = val_eligible["lag_closing_rank"].to_numpy()
    actual = val_eligible["closing_rank"].to_numpy()

    results = []
    for alpha in ALPHA_SWEEP:
        blended = np.clip(lag + alpha * predicted_delta, 1, None)
        val_mae = float(np.mean(np.abs(actual - blended)))
        results.append((alpha, val_mae))

    best_alpha, best_mae = min(results, key=lambda r: r[1])

    print(f"\n=== Alpha sweep on {VALIDATION_YEAR} validation year (n={len(val_eligible)} lag-eligible rows, model trained on {ALPHA_TRAIN_YEARS}) ===")
    for alpha, val_mae in results:
        marker = "  <- selected" if alpha == best_alpha else ""
        print(f"  alpha={alpha:.1f}: validation MAE {val_mae:,.0f}{marker}")

    return best_alpha


def three_way_comparison(test_df, delta_model, delta_features, alpha):
    """The headline number this whole PRD exists to produce: naive baseline
    vs the unshrunk model vs the shrinkage-blended model, all on the same
    2024 lag-eligible rows, touched exactly once.
    """
    eligible = test_df.dropna(subset=["lag_closing_rank"])
    lag = eligible["lag_closing_rank"].to_numpy()
    actual = eligible["closing_rank"].to_numpy()
    predicted_delta = delta_model.predict(eligible[delta_features])

    naive_mae = float(np.mean(np.abs(actual - lag)))
    raw_mae = float(np.mean(np.abs(actual - np.clip(lag + predicted_delta, 1, None))))
    blended_mae = float(np.mean(np.abs(actual - np.clip(lag + alpha * predicted_delta, 1, None))))

    print(f"\n=== Three-way comparison on {TEST_YEAR} lag-eligible subset (n={len(eligible)}) ===")
    print(f"  naive baseline   (alpha=0.0): MAE {naive_mae:,.0f}")
    print(f"  raw model        (alpha=1.0): MAE {raw_mae:,.0f}")
    print(f"  shrinkage-blended(alpha={alpha:.1f}): MAE {blended_mae:,.0f}")

    margin = naive_mae - blended_mae
    if margin > 0:
        print(f"  RESULT: shrinkage-blended model BEATS the naive baseline by {margin:,.0f} ranks ({100 * margin / naive_mae:.1f}%)")
    else:
        print(f"  RESULT: shrinkage-blended model does not beat the naive baseline (worse by {-margin:,.0f} ranks, {100 * -margin / naive_mae:.1f}%)")

    return {"naive_mae": naive_mae, "raw_mae": raw_mae, "blended_mae": blended_mae}


def band_label(rank):
    for lo, hi, label in RANK_BANDS:
        if lo <= rank < hi:
            return label
    return "unknown"


def evaluate(test_df, predictions, has_lag, label=""):
    print(f"\n=== Evaluation on {TEST_YEAR} holdout{f' - {label}' if label else ''} ===")
    actual = test_df["closing_rank"]

    overall_mae = mae(actual, predictions)
    print(f"Overall MAE (all 2024 rows, delta model + fallback combined): {overall_mae:,.0f} ranks")

    n_lag = int(has_lag.sum())
    n_cold = int((~has_lag).sum())
    print(f"\nRows with a valid year-1 lag (delta model applies): {n_lag} ({n_lag / len(test_df):.1%})")
    print(f"Rows with no year-1 lag (cold start, fallback model applies): {n_cold} ({n_cold / len(test_df):.1%})")

    if n_lag:
        lag_actual = actual[has_lag]
        lag_pred = predictions[has_lag]
        naive_pred = test_df.loc[has_lag, "lag_closing_rank"]
        print(f"\n[lag-eligible subset, n={n_lag}]")
        print(f"  Model MAE:          {mae(lag_actual, lag_pred):,.0f} ranks")
        print(f"  Naive baseline MAE (predict delta=0, i.e. last year's value): {mae(lag_actual, naive_pred):,.0f} ranks")
        improvement = mae(lag_actual, naive_pred) - mae(lag_actual, lag_pred)
        print(f"  Model {'beats' if improvement > 0 else 'does not beat'} the naive baseline by {improvement:,.0f} ranks")

    if n_cold:
        cold_actual = actual[~has_lag]
        cold_pred = predictions[~has_lag]
        print(f"\n[cold-start subset, n={n_cold}] (no naive last-year baseline exists for these - there is no prior row)")
        print(f"  Fallback model MAE: {mae(cold_actual, cold_pred):,.0f} ranks")

    print("\n=== MAE by rank band (overall) ===")
    bands = actual.apply(band_label)
    for _, _, label in RANK_BANDS:
        mask = bands == label
        if mask.any():
            print(f"  {label}: MAE {mae(actual[mask], predictions[mask]):,.0f} ranks, n={int(mask.sum())}")


def print_feature_importance(model, features):
    print("\n=== Delta model feature importance (gain) ===")
    importances = model.feature_importance(importance_type="gain")
    for name, imp in sorted(zip(features, importances), key=lambda x: -x[1]):
        print(f"  {name}: {imp:,.0f}")


def print_sample_predictions(test_df, predictions, n=8):
    print("\n=== Sample predictions vs actuals (2024) ===")
    sample_idx = test_df.sort_values("closing_rank").index[:: max(1, len(test_df) // n)][:n]
    for idx in sample_idx:
        row = test_df.loc[idx]
        print(
            f"  {row['college_id']} / {row['program_id']} / {row['category']} / {row['quota']}: "
            f"predicted={predictions[idx]:,.0f}, actual={row['closing_rank']:,.0f}, "
            f"diff={predictions[idx] - row['closing_rank']:,.0f}"
        )


def forecast_2025(full_df, delta_model, delta_features, alpha=1.0, n=6):
    """Uses each group's real 2024 closing rank as the year-1 lag to produce
    a 2025 forecast - interpolation on the learned trend, not extrapolation,
    since the delta model never sees a raw year value at all. Applies the
    same shrinkage alpha used in production for lag-eligible groups, so this
    forecast matches what the locked strategy would actually serve.
    """
    print("\n=== Sample 2025 forecast (2024 actual + shrinkage-blended predicted delta) ===")
    latest = full_df[full_df["year"] == 2024].dropna(subset=["lag_closing_rank"])
    if latest.empty:
        print("  no 2024 rows with a valid lag to forecast from")
        return

    sample = latest.sample(min(n, len(latest)), random_state=2).copy()
    sample["lag_closing_rank"] = sample["closing_rank"]
    sample["years_since_first_seen"] = sample["years_since_first_seen"] + 1
    sample["round"] = np.nan

    forecast_delta = alpha * delta_model.predict(sample[delta_features])
    forecast_rank = (sample["lag_closing_rank"].to_numpy() + forecast_delta).clip(min=1)

    for i, (_, row) in enumerate(sample.iterrows()):
        print(
            f"  {row['college_id']} / {row['program_id']} / {row['category']} / {row['quota']}: "
            f"2024 actual={row['closing_rank']:,.0f} -> 2025 forecast={forecast_rank[i]:,.0f} "
            f"(predicted delta {forecast_delta[i]:+,.0f})"
        )
    negative_or_wild = (forecast_rank < 1) | (forecast_rank > sample["closing_rank"].to_numpy() * 5)
    print(f"  sanity check: {int(negative_or_wild.sum())} of {len(sample)} forecasts look negative or wildly extrapolated")


def forecast_next_year_for_all_groups(full_df, delta_model, delta_features, fallback_model, fallback_features, alpha=1.0):
    """The eligibility filter and the ranker both need a predicted closing
    rank for every real (college, program, quota, category) combination, not
    just the sample forecast_2025 prints. Same mechanism, applied to every
    group at once: a group whose most recent real row is 2024 gets that row
    as its year-1 lag (interpolation, per the module docstring); anything
    else - a group that last appeared before 2024, or one so sparse it never
    lines up with the 2024 snapshot - falls back to the absolute-rank model,
    same as a cold-start row during evaluation.
    """
    latest_by_group = full_df.sort_values("year").drop_duplicates(subset=GROUP_COLS, keep="last").copy()

    is_current = latest_by_group["year"] == 2024
    latest_by_group.loc[is_current, "lag_closing_rank"] = latest_by_group.loc[is_current, "closing_rank"]
    latest_by_group.loc[is_current, "years_since_first_seen"] = latest_by_group.loc[is_current, "years_since_first_seen"] + 1
    latest_by_group.loc[is_current, "round"] = np.nan
    latest_by_group.loc[~is_current, "lag_closing_rank"] = np.nan

    predictions, has_lag = predict(latest_by_group, delta_model, delta_features, fallback_model, fallback_features, alpha=alpha)

    out = latest_by_group[GROUP_COLS].copy()
    out["predicted_closing_rank"] = predictions.to_numpy()
    out["prediction_source"] = np.where(has_lag.to_numpy(), "delta_model", "fallback_model")
    return out.reset_index(drop=True)


def save_artifacts(delta_model, fallback_model, delta_features, fallback_features, alpha):
    """LightGBM's own Booster.save_model already records which categories
    each categorical column had at training time (Booster.pandas_categorical)
    and re-applies that same mapping to any new DataFrame passed to
    predict() later, even a fresh one built in a different process with a
    different subset of rows - verified directly before relying on it,
    since a silent mismatch there would corrupt predictions without an
    error. So callers only need the feature list and alpha alongside the
    two model files, nothing more.
    """
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    delta_model.save_model(DELTA_MODEL_PATH)
    fallback_model.save_model(FALLBACK_MODEL_PATH)
    with open(METADATA_PATH, "w") as f:
        json.dump({"delta_features": delta_features, "fallback_features": fallback_features, "alpha": alpha}, f, indent=2)
    print(f"[cutoff_regressor] saved trained models and metadata to {ARTIFACT_DIR}/")


def load_artifacts():
    """Loads what save_artifacts wrote, for any other module (eligibility,
    ranker) that needs predicted closing ranks without retraining.
    """
    delta_model = lgb.Booster(model_file=DELTA_MODEL_PATH)
    fallback_model = lgb.Booster(model_file=FALLBACK_MODEL_PATH)
    with open(METADATA_PATH) as f:
        metadata = json.load(f)
    return delta_model, fallback_model, metadata


def run(database_url=None):
    print("[cutoff_regressor] loading training-set-policy-filtered data (Gender-Neutral, 2018-2024)...")
    _, filtered = load_regressor_training_data(database_url)

    print("[cutoff_regressor] collapsing to one row per group-year (final round per year)...")
    group_year = collapse_to_one_row_per_group_year(filtered)
    print(f"[cutoff_regressor] {len(group_year)} group-year rows (from {len(filtered)} raw rows)")

    nirf_df = _load_nirf(database_url)
    full_df = build_features(group_year, nirf_df)

    leakage_check(full_df)

    train_df = full_df[full_df["year"].isin(TRAIN_YEARS)]
    test_df = full_df[full_df["year"] == TEST_YEAR]
    print(f"\n[cutoff_regressor] train years: {sorted(train_df['year'].unique().tolist())}, test year: {TEST_YEAR}")
    print(f"[cutoff_regressor] train rows: {len(train_df)}, test rows: {len(test_df)}")

    chosen_alpha = select_alpha(full_df)
    print(f"\n[cutoff_regressor] selected shrinkage alpha = {chosen_alpha} (chosen on {VALIDATION_YEAR}, never on {TEST_YEAR})")

    delta_model, delta_features = train_delta_model(train_df)
    fallback_model, fallback_features = train_fallback_model(train_df)

    three_way_comparison(test_df, delta_model, delta_features, chosen_alpha)

    predictions_before, has_lag = predict(test_df, delta_model, delta_features, fallback_model, fallback_features, alpha=1.0)
    predictions_after, _ = predict(test_df, delta_model, delta_features, fallback_model, fallback_features, alpha=chosen_alpha)

    evaluate(test_df, predictions_before, has_lag, label=f"BEFORE (alpha=1.0, raw model, previously reported)")
    evaluate(test_df, predictions_after, has_lag, label=f"AFTER (alpha={chosen_alpha}, shrinkage-blended, production strategy)")

    print_feature_importance(delta_model, delta_features)
    print_sample_predictions(test_df, predictions_after)
    forecast_2025(full_df, delta_model, delta_features, alpha=chosen_alpha)

    save_artifacts(delta_model, fallback_model, delta_features, fallback_features, chosen_alpha)

    return delta_model, fallback_model, chosen_alpha


if __name__ == "__main__":
    run()
