"""Orders a student's eligible college-branches for them specifically - the
piece that makes this a recommendation system rather than a filtered
lookup. This is the project's core claim, so the design below is built
around one hard constraint: the relevance label a LightGBM LGBMRanker
(LambdaRank objective) learns from cannot be circular.

THE PROBLEM: there is no real per-student choice data to learn from. If a
relevance label were invented and the model trained to reproduce it, the
model would just relearn the inventor's formula - worthless.

THE GROUNDING: JoSAA closing ranks are not arbitrary. They are the outcome
of millions of real students' actual ranked choices, so the ordering of
college-branches by closing rank is genuine revealed preference - lower
closing rank means more collectively desired. compute_base_desirability()
builds this from the real 2018-2024 data already in the database (a
college-branch's typical OPEN-category closing rank, most recent years
weighted more), not from an invented formula.

THE CIRCULARITY GUARD: that base desirability is closing-rank-derived, so
it must never leak into the ranker's FEATURES, or the model would trivially
reconstruct the label from itself instead of learning anything. The feature
list (RANKER_FEATURES below) is deliberately restricted to attributes that
correlate with desirability without being derived from the same closing-rank
data that built the label: NIRF rank (an independent government ranking,
not JoSAA data), institute type, fees, hostel availability, and the coarse
band (safe/moderate/dream) - a 3-way bucket, not the underlying margin or
predicted closing rank, so attainability informs the model without handing
it a near-continuous version of the label to copy. print_feature_importance
confirms this by construction, not just by eyeballing the numbers: raw
closing rank and margin are simply never in the feature list to begin with.

THE PERSONALIZATION: real students deviate from the collective ranking for
real reasons. personalized_relevance() adjusts the base desirability per
synthetic student profile - home state, budget, branch taste, NIRF
appetite, and ownership preference all shift the grade, and attainability
itself (the band) shifts it too, since an unreachable dream school is a
weaker recommendation than a strong safe one. This adjusted, personalized
score is what gets discretized into the ordinal relevance grade LambdaRank
trains on.

THE HONESTY: real student profiles don't exist here, so this trains on
sampled synthetic ones - only the profiles are synthetic. The colleges,
their real closing-rank history, real NIRF ranks, and the regressor's real
forecasts are exactly what the rest of the project already built. Stated
plainly, not hidden. And the ranker only earns its place if it beats three
non-personalized baselines (rank by NIRF, rank by a margin-based admission-
probability proxy, rank by base desirability alone) on NDCG - see
evaluate_against_baselines. If it doesn't, that is a finding to report, not
to bury.
"""

import os

import numpy as np
import pandas as pd
from lightgbm import LGBMRanker
from sklearn.metrics import ndcg_score

from api.eligibility import StudentProfile, build_forecasts, get_eligible_colleges, load_reference_tables, merge_forecasts_with_colleges
from db.connection import get_database_url, get_engine

N_STUDENTS = 240
TRAIN_FRACTION = 0.8
N_RELEVANCE_GRADES = 5
RANDOM_SEED = 7

CS_ADJACENT_KEYWORDS = ["computer science", "information technology", "data science", "artificial intelligence", "software"]

# Small, named, documented weights for how much each stated preference shifts
# the base desirability grade - illustrative and defensible, not a precision
# calibration, same spirit as every other small named weight in this project.
W_HOME_STATE = 0.15
W_BUDGET = 0.20
W_BRANCH = 0.15
W_NIRF = 0.15
W_OWNERSHIP = 0.05
W_SAFE_BONUS = 0.05
W_DREAM_PENALTY = 0.10

# Deliberately excludes predicted_closing_rank, margin, and margin_ratio - see
# the module docstring's circularity guard. "band" is the one attainability
# signal allowed in, and only as a coarse 3-way category.
RANKER_FEATURES = [
    "nirf_rank",
    "institute_type",
    "fees_annual_lakhs",
    "hostel_available",
    "home_state_match",
    "is_cs_adjacent",
    "band",
    "student_category",
    "prefers_home_state",
    "wants_top_nirf",
    "is_over_budget",
    "preferred_branch_category",
    "institute_ownership_pref",
]
CATEGORICAL_RANKER_FEATURES = ["institute_type", "band", "student_category", "preferred_branch_category", "institute_ownership_pref"]


def is_cs_adjacent(branch_name):
    lowered = str(branch_name).lower()
    return any(kw in lowered for kw in CS_ADJACENT_KEYWORDS)


def compute_is_over_budget(fees, budget):
    """Missing (nan) when the student stated no budget at all, rather than 0
    - "no budget constraint" and "within budget" are different things, and
    collapsing them would tell the model a stated-but-satisfied budget looks
    the same as never having stated one, when they shouldn't necessarily
    behave identically.
    """
    if budget is None or fees is None or pd.isna(fees):
        return np.nan
    return int(fees > budget)


def compute_base_desirability(database_url=None):
    """Real revealed preference, not an invented formula: each college-branch's
    typical OPEN-category closing rank across 2018-2024 (Gender-Neutral, the
    regressor's own population), weighted toward the most recent years so a
    branch's current standing matters more than its standing five years ago,
    converted to a percentile where 1.0 is most desired (lowest rank) and 0.0
    is least desired.
    """
    database_url = database_url or get_database_url()
    engine = get_engine(database_url)
    df = pd.read_sql(
        "SELECT college_id, program_id, year, closing_rank FROM cutoffs "
        "WHERE category = 'OPEN' AND gender_seat_type = 'Gender-Neutral' AND year >= 2018",
        engine,
    )
    # Vectorized weighted average (sum of rank*weight over sum of weight per
    # group) instead of groupby().apply(np.average) - the apply form calls a
    # Python function once per group, which is fine for a handful of groups
    # but scales badly here (thousands of college-branch groups) and was the
    # main reason an earlier run of this function never finished in a
    # reasonable time.
    df = df.assign(weight=(df["year"] - 2017).clip(lower=1))
    df["weighted_rank"] = df["closing_rank"] * df["weight"]
    grouped = df.groupby(["college_id", "program_id"], sort=False).agg(
        weighted_rank_sum=("weighted_rank", "sum"), weight_sum=("weight", "sum")
    )
    grouped["typical_closing_rank"] = grouped["weighted_rank_sum"] / grouped["weight_sum"]
    grouped["desirability_percentile"] = 1 - grouped["typical_closing_rank"].rank(pct=True)
    return grouped["desirability_percentile"].to_dict()


def compute_nirf_percentile(colleges):
    ranked = colleges.dropna(subset=["nirf_rank_latest"])
    percentile = 1 - ranked["nirf_rank_latest"].rank(pct=True)
    return dict(zip(ranked["college_id"], percentile))


def sample_synthetic_students(database_url=None, n=N_STUDENTS, seed=RANDOM_SEED):
    """Only the student profiles here are synthetic - everything else
    (colleges, real closing-rank history, real NIRF, the regressor's real
    forecasts) is the same real data the rest of the project uses. Ranks are
    drawn from real 2024 closing ranks actually observed (so the distribution
    of sampled ranks matches reality, not a guessed shape), categories in
    their real observed proportions, home states uniformly over states that
    actually have a JoSAA college in them.
    """
    database_url = database_url or get_database_url()
    engine = get_engine(database_url)
    real_2024 = pd.read_sql(
        "SELECT category, closing_rank FROM cutoffs WHERE year = 2024 AND gender_seat_type = 'Gender-Neutral'", engine
    )
    colleges, _, _ = load_reference_tables(database_url)
    states = sorted(colleges["state"].dropna().unique().tolist())

    rng = np.random.default_rng(seed)
    sample_idx = rng.integers(0, len(real_2024), size=n)
    sampled = real_2024.iloc[sample_idx].reset_index(drop=True)

    students = []
    for i in range(n):
        home_state = str(rng.choice(states)) if rng.random() < 0.75 else None
        budget = float(rng.choice([1.0, 1.5, 2.0, 2.5, 3.0])) if rng.random() < 0.6 else None
        students.append(
            StudentProfile(
                jee_rank=int(sampled.loc[i, "closing_rank"]),
                category=sampled.loc[i, "category"],
                home_state=home_state,
                preferred_branch_category=str(rng.choice(["cs_adjacent", "core", "any"], p=[0.35, 0.35, 0.30])),
                budget_annual_lakhs=budget,
                wants_top_nirf=bool(rng.random() < 0.5),
                institute_ownership_pref=str(rng.choice(["government", "ppp", "both"], p=[0.45, 0.1, 0.45])),
                prefers_home_state=bool(rng.random() < 0.5),
            )
        )
    return students


def personalized_relevance(candidate, student, base_desirability, nirf_percentile):
    base = base_desirability.get((candidate["college_id"], candidate["program_id"]), 0.5)

    adjustment = 0.0
    if student.prefers_home_state and student.home_state and candidate["state"] == student.home_state:
        adjustment += W_HOME_STATE

    fees = candidate["fees_annual_lakhs"]
    if student.budget_annual_lakhs is not None and fees is not None and not pd.isna(fees) and fees > student.budget_annual_lakhs:
        overage = min(1.0, (fees - student.budget_annual_lakhs) / student.budget_annual_lakhs)
        adjustment -= W_BUDGET * overage

    branch_is_cs = is_cs_adjacent(candidate["branch_name"])
    if student.preferred_branch_category == "cs_adjacent" and branch_is_cs:
        adjustment += W_BRANCH
    elif student.preferred_branch_category == "core" and not branch_is_cs:
        adjustment += W_BRANCH

    if student.wants_top_nirf:
        adjustment += W_NIRF * nirf_percentile.get(candidate["college_id"], 0.5)

    if student.institute_ownership_pref != "both":
        ownership = "ppp" if candidate["institute_type"] == "IIIT" else "government"
        if ownership == student.institute_ownership_pref:
            adjustment += W_OWNERSHIP

    adjustment += {"safe": W_SAFE_BONUS, "moderate": 0.0, "dream": -W_DREAM_PENALTY}[candidate["band"]]

    return base + adjustment


def build_query_dataset(students, forecasts, reference_tables, base_desirability, nirf_percentile):
    colleges, programs, reference_metadata = reference_tables
    fees_by_college = reference_metadata.set_index("college_id")["fees_annual_lakhs"].to_dict()
    hostel_by_college = reference_metadata.set_index("college_id")["hostel_available"].to_dict()

    rows = []
    for query_id, student in enumerate(students):
        candidates = get_eligible_colleges(student, forecasts=forecasts, reference_tables=reference_tables)
        for c in candidates:
            c = dict(c)
            c["fees_annual_lakhs"] = fees_by_college.get(c["college_id"])
            relevance_score = personalized_relevance(c, student, base_desirability, nirf_percentile)
            rows.append(
                {
                    "query_id": query_id,
                    "college_id": c["college_id"],
                    "program_id": c["program_id"],
                    "college_name": c["college_name"],
                    "branch_name": c["branch_name"],
                    "nirf_rank": c["nirf_rank"],
                    "institute_type": c["institute_type"],
                    "fees_annual_lakhs": c["fees_annual_lakhs"],
                    "hostel_available": hostel_by_college.get(c["college_id"]),
                    "home_state_match": int(student.home_state is not None and c["state"] == student.home_state),
                    "is_cs_adjacent": int(is_cs_adjacent(c["branch_name"])),
                    "band": c["band"],
                    "student_category": student.category,
                    "prefers_home_state": int(student.prefers_home_state),
                    "wants_top_nirf": int(student.wants_top_nirf),
                    "is_over_budget": compute_is_over_budget(c["fees_annual_lakhs"], student.budget_annual_lakhs),
                    "preferred_branch_category": student.preferred_branch_category,
                    "institute_ownership_pref": student.institute_ownership_pref,
                    # kept for baseline comparisons and reporting only - never in RANKER_FEATURES
                    "predicted_closing_rank": c["predicted_closing_rank"],
                    "margin_ratio": c["margin_ratio"],
                    "base_desirability": base_desirability.get((c["college_id"], c["program_id"]), 0.5),
                    "relevance_score": relevance_score,
                }
            )

    df = pd.DataFrame(rows)
    df["relevance_grade"] = pd.qcut(df["relevance_score"], N_RELEVANCE_GRADES, labels=False, duplicates="drop")
    return df


def prepare_xy(df):
    df = df.sort_values("query_id").reset_index(drop=True)
    X = df[RANKER_FEATURES].copy()
    for col in CATEGORICAL_RANKER_FEATURES:
        X[col] = X[col].astype("category")
    y = df["relevance_grade"]
    group = df.groupby("query_id", sort=False).size().to_numpy()
    return X, y, group, df


def train_ranker(train_df):
    X, y, group, _ = prepare_xy(train_df)
    ranker = LGBMRanker(objective="lambdarank", n_estimators=200, num_leaves=31, learning_rate=0.05, min_child_samples=5, verbose=-1)
    ranker.fit(X, y, group=group, categorical_feature=CATEGORICAL_RANKER_FEATURES)
    return ranker


def ndcg_at_k_per_query(test_df, score_col, k):
    scores = []
    for _, group in test_df.groupby("query_id"):
        if len(group) < 2:
            continue
        true_rel = group["relevance_grade"].to_numpy().reshape(1, -1)
        pred_score = group[score_col].to_numpy().reshape(1, -1)
        scores.append(ndcg_score(true_rel, pred_score, k=k))
    return float(np.mean(scores)) if scores else float("nan")


def evaluate_against_baselines(ranker, test_df):
    X_test, _, _, ordered_test_df = prepare_xy(test_df)
    ordered_test_df = ordered_test_df.copy()
    ordered_test_df["learned_score"] = ranker.predict(X_test)
    ordered_test_df["nirf_baseline_score"] = -ordered_test_df["nirf_rank"].fillna(9999)
    ordered_test_df["admission_prob_baseline_score"] = ordered_test_df["margin_ratio"]
    ordered_test_df["base_desirability_baseline_score"] = ordered_test_df["base_desirability"]

    print(f"\n=== NDCG on {ordered_test_df['query_id'].nunique()} held-out test queries (never seen in training) ===")
    print(f"{'method':<28} {'NDCG@5':>10} {'NDCG@10':>10}")
    results = {}
    for label, col in [
        ("learned ranker", "learned_score"),
        ("baseline: NIRF alone", "nirf_baseline_score"),
        ("baseline: admission prob. alone", "admission_prob_baseline_score"),
        ("baseline: base desirability alone", "base_desirability_baseline_score"),
    ]:
        ndcg5 = ndcg_at_k_per_query(ordered_test_df, col, 5)
        ndcg10 = ndcg_at_k_per_query(ordered_test_df, col, 10)
        results[label] = (ndcg5, ndcg10)
        print(f"{label:<28} {ndcg5:>10.4f} {ndcg10:>10.4f}")

    learned5, learned10 = results["learned ranker"]
    best_baseline_label = max(
        [k for k in results if k != "learned ranker"], key=lambda k: results[k][0]
    )
    best5, best10 = results[best_baseline_label]
    print(f"\nStrongest non-personalized baseline at K=5: {best_baseline_label} ({best5:.4f})")
    if learned5 > best5:
        print(f"RESULT: learned ranker BEATS the strongest baseline at K=5 by {learned5 - best5:.4f} ({100 * (learned5 - best5) / best5:.1f}%)")
    else:
        print(f"RESULT: learned ranker does NOT beat the strongest baseline at K=5 (behind by {best5 - learned5:.4f})")

    return results, ordered_test_df


def print_feature_importance(ranker):
    print("\n=== Ranker feature importance (confirms no circularity: raw closing rank / margin are not in this list at all) ===")
    print(f"Features used: {RANKER_FEATURES}")
    for name, imp in sorted(zip(RANKER_FEATURES, ranker.feature_importances_), key=lambda x: -x[1]):
        print(f"  {name}: {imp}")


def score_candidates_for_student(ranker, student, forecasts, reference_tables):
    fees_by_college = reference_tables[2].set_index("college_id")["fees_annual_lakhs"].to_dict()
    hostel_by_college = reference_tables[2].set_index("college_id")["hostel_available"].to_dict()

    candidates = get_eligible_colleges(student, forecasts=forecasts, reference_tables=reference_tables)
    rows = []
    for c in candidates:
        c = dict(c)
        c["fees_annual_lakhs"] = fees_by_college.get(c["college_id"])
        rows.append(
            {
                "college_id": c["college_id"],
                "program_id": c["program_id"],
                "college_name": c["college_name"],
                "branch_name": c["branch_name"],
                "fees_annual_lakhs": c["fees_annual_lakhs"],
                "state": c["state"],
                "nirf_rank": c["nirf_rank"],
                "institute_type": c["institute_type"],
                "band": c["band"],
                "hostel_available": hostel_by_college.get(c["college_id"]),
                "home_state_match": int(student.home_state is not None and c["state"] == student.home_state),
                "is_cs_adjacent": int(is_cs_adjacent(c["branch_name"])),
                "student_category": student.category,
                "prefers_home_state": int(student.prefers_home_state),
                "wants_top_nirf": int(student.wants_top_nirf),
                "is_over_budget": compute_is_over_budget(c["fees_annual_lakhs"], student.budget_annual_lakhs),
                "preferred_branch_category": student.preferred_branch_category,
                "institute_ownership_pref": student.institute_ownership_pref,
                # display-only, never in RANKER_FEATURES (see the module docstring's circularity guard)
                "quota_used": c["quota_used"],
                "predicted_closing_rank": c["predicted_closing_rank"],
                "margin": c["margin"],
                "prediction_source": c["prediction_source"],
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    X = df[RANKER_FEATURES].copy()
    for col in CATEGORICAL_RANKER_FEATURES:
        X[col] = X[col].astype("category")
    df["score"] = ranker.predict(X)
    return df.sort_values("score", ascending=False).reset_index(drop=True)


def _print_top(df, n=5):
    for i, r in df.head(n).iterrows():
        fee_str = f"{r['fees_annual_lakhs']:.1f}L" if pd.notna(r["fees_annual_lakhs"]) else "unknown"
        print(f"  #{i + 1}: {r['college_name']} / {r['branch_name']} - fees {fee_str}, state {r['state']}, NIRF {r['nirf_rank']}, band {r['band']}")


def show_contrasting_profiles(ranker, forecasts, reference_tables, base_desirability, nirf_percentile):
    """Each pair below holds rank/category/home-state fixed and varies
    exactly one preference, so any ordering difference is attributable to
    that one preference - not a confounded demo where two preferences move
    at once and the weaker one gets buried by the stronger one (an earlier
    version of this function set prefers_home_state and wants_top_nirf
    together, and since NIRF is by far the strongest feature, the home-state
    effect was invisible in the result; fixed here by isolating it).
    """
    print("\n=== Pair 1: home-state preference isolated (same rank, category, home state; NIRF preference off for both) ===")
    home_shared = dict(jee_rank=20000, category="OPEN", home_state="Tamil Nadu", wants_top_nirf=False)
    baseline = StudentProfile(**home_shared, prefers_home_state=False)
    home_focused = StudentProfile(**home_shared, prefers_home_state=True)

    df_baseline = score_candidates_for_student(ranker, baseline, forecasts, reference_tables)
    df_home = score_candidates_for_student(ranker, home_focused, forecasts, reference_tables)

    print(f"\n[baseline, prefers_home_state=False] top 5 of {len(df_baseline)} eligible:")
    _print_top(df_baseline)
    print(f"\n[prefers_home_state=True] top 5 of {len(df_home)} eligible:")
    _print_top(df_home)

    tn_rank_baseline = df_baseline.index[df_baseline["state"] == "Tamil Nadu"].tolist()
    tn_rank_home = df_home.index[df_home["state"] == "Tamil Nadu"].tolist()
    tn_count_top10_baseline = sum(1 for i in tn_rank_baseline if i < 10)
    tn_count_top10_home = sum(1 for i in tn_rank_home if i < 10)
    print(
        f"\nTamil Nadu colleges in top 10: baseline={tn_count_top10_baseline}, home-state-focused={tn_count_top10_home} "
        f"(best Tamil Nadu rank position: baseline=#{min(tn_rank_baseline) + 1 if tn_rank_baseline else 'none'}, "
        f"home-focused=#{min(tn_rank_home) + 1 if tn_rank_home else 'none'})"
    )

    print("\n=== Pair 2: budget preference isolated (same rank, category, home state; no home-state or NIRF preference) ===")
    budget_shared = dict(jee_rank=20000, category="OPEN", home_state="Tamil Nadu", prefers_home_state=False, wants_top_nirf=False)
    no_budget = StudentProfile(**budget_shared, budget_annual_lakhs=None)
    budget_constrained = StudentProfile(**budget_shared, budget_annual_lakhs=1.25)

    df_no_budget = score_candidates_for_student(ranker, no_budget, forecasts, reference_tables)
    df_budget = score_candidates_for_student(ranker, budget_constrained, forecasts, reference_tables)

    print(f"\n[no budget stated] top 5 of {len(df_no_budget)} eligible:")
    _print_top(df_no_budget)
    print(f"\n[budget capped at 1.25 lakh/year] top 5 of {len(df_budget)} eligible:")
    _print_top(df_budget)

    over_budget_mask_no = df_no_budget["fees_annual_lakhs"] > 1.25
    over_budget_mask_b = df_budget["fees_annual_lakhs"] > 1.25
    avg_rank_over_budget_no = (df_no_budget.index[over_budget_mask_no] + 1).to_series().mean() if over_budget_mask_no.any() else float("nan")
    avg_rank_over_budget_b = (df_budget.index[over_budget_mask_b] + 1).to_series().mean() if over_budget_mask_b.any() else float("nan")
    print(
        f"\nAverage rank position of over-budget (>1.25L) colleges: "
        f"no-budget-stated={avg_rank_over_budget_no:.1f}, budget-constrained={avg_rank_over_budget_b:.1f} "
        f"({'lower is better - budget-constrained pushes them down' if avg_rank_over_budget_b > avg_rank_over_budget_no else 'no shift observed'})"
    )


RANKER_ARTIFACT_PATH = "models/artifacts/ranker.joblib"


def save_ranker(ranker):
    import joblib

    os.makedirs(os.path.dirname(RANKER_ARTIFACT_PATH), exist_ok=True)
    joblib.dump(ranker, RANKER_ARTIFACT_PATH)
    print(f"[ranker] saved trained ranker to {RANKER_ARTIFACT_PATH}")


def load_ranker():
    import joblib

    return joblib.load(RANKER_ARTIFACT_PATH)


def run(database_url=None):
    print(f"[ranker] sampling {N_STUDENTS} synthetic student queries (real ranks/categories, synthetic profiles)...")
    students = sample_synthetic_students(database_url)

    print("[ranker] computing base desirability from real 2018-2024 OPEN-category closing ranks...")
    base_desirability = compute_base_desirability(database_url)

    print("[ranker] building forecasts and reference tables...")
    forecasts = build_forecasts(database_url)
    reference_tables = load_reference_tables(database_url)
    nirf_percentile = compute_nirf_percentile(reference_tables[0])
    # Merged once here rather than inside get_eligible_colleges on every one
    # of the 240 per-student calls below - the merge doesn't depend on the
    # student, so redoing it every call was pure waste.
    merged_forecasts = merge_forecasts_with_colleges(forecasts, reference_tables[0])

    print("[ranker] assembling per-student candidate sets and personalized relevance grades...")
    dataset = build_query_dataset(students, merged_forecasts, reference_tables, base_desirability, nirf_percentile)
    print(f"[ranker] {len(dataset)} (student, college-branch) rows across {dataset['query_id'].nunique()} queries")

    rng = np.random.default_rng(RANDOM_SEED)
    query_ids = np.arange(len(students))
    rng.shuffle(query_ids)
    n_train = int(len(students) * TRAIN_FRACTION)
    train_ids, test_ids = set(query_ids[:n_train].tolist()), set(query_ids[n_train:].tolist())
    print(f"[ranker] {len(train_ids)} training queries, {len(test_ids)} held-out test queries (disjoint)")

    train_df = dataset[dataset["query_id"].isin(train_ids)]
    test_df = dataset[dataset["query_id"].isin(test_ids)]

    ranker = train_ranker(train_df)

    print_feature_importance(ranker)
    results, _ = evaluate_against_baselines(ranker, test_df)
    show_contrasting_profiles(ranker, forecasts, reference_tables, base_desirability, nirf_percentile)

    save_ranker(ranker)

    return ranker, results


if __name__ == "__main__":
    run()
