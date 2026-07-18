"""Shapes the exact output api/main.py's /recommend already computes into a
report model for the downloadable PDF - no eligibility, cutoff, band, or
probability logic lives here. If a number is in the report, it came from the
same eligibility filter, cutoff regressor forecast, and calibrated
admission-probability artifacts /recommend already used for this student.
"""

HOW_TO_READ_NOTE = (
    "Colleges are grouped safe / moderate / dream by how comfortably your rank clears the predicted "
    "closing rank for that college-branch-quota-category combination. Predicted closing rank and "
    "admission chance are model estimates built from historical JoSAA data, not guarantees. Where a "
    "college-branch has too little year-over-year history for the main model, its admission chance is "
    "marked approximate - it leans on a wider, less certain fallback estimate."
)

NEXT_STEPS_FACTS = [
    "JoSAA counselling runs over several rounds of seat allotment, not just one.",
    "In each round you can freeze an allotted seat, float it to be considered for a better one in a later "
    "round, or slide within your original institute for a different branch - check the official JoSAA "
    "process for the round you are in before responding.",
    "Closing ranks move year to year with the number of applicants and the seat matrix, so the predicted "
    "closing ranks in this report are this system's best estimate for the next cycle, not a fixed number.",
    "Missing a round's response deadline can mean forfeiting an allotted seat, per JoSAA's official rules - "
    "confirm current deadlines directly with JoSAA before each round.",
]

REPORT_SCOPE_NOTE = (
    "Scope: JEE Main / JoSAA admissions into IITs, NITs, IIITs, and GFTIs only. All figures in this report "
    "are model estimates based on historical JoSAA data, not guarantees of admission or a judgment of a "
    "college's quality."
)


def _report_row(result):
    """One college-branch row, carrying only what the report shows - trimmed
    from the same dict api/main.py's _row_to_result already produced.
    """
    return {
        "college_name": result["college_name"],
        "branch_name": result["branch_name"],
        "institute_type": result["institute_type"],
        "state": result["state"],
        "nirf_rank": result["nirf_rank"],
        "quota_used": result["quota_used"],
        "predicted_closing_rank": result["predicted_closing_rank"],
        "admission_probability": result["admission_probability"],
        "probability_is_approximate": result["probability_is_approximate"],
        "band": result["band"],
    }


def build_report_data(request, recommend_response):
    """request is the same RecommendRequest /recommend takes; recommend_response
    is the exact dict /recommend already returned for it (see api/main.py's
    compute_recommendation). Nothing here is recomputed.
    """
    return {
        "student": {
            "jee_rank": request.jee_rank,
            "category": request.category,
            "home_state": request.home_state,
            "preferred_branch_category": request.preferred_branch_category,
            "budget_annual_lakhs": request.budget_annual_lakhs,
            "wants_top_nirf": request.wants_top_nirf,
            "institute_ownership_pref": request.institute_ownership_pref,
            "prefers_home_state": request.prefers_home_state,
        },
        "based_on_year": recommend_response["based_on_year"],
        "counts": recommend_response["counts"],
        "bands": {
            "safe": [_report_row(r) for r in recommend_response["safe"]],
            "moderate": [_report_row(r) for r in recommend_response["moderate"]],
            "dream": [_report_row(r) for r in recommend_response["dream"]],
        },
        "how_to_read_note": HOW_TO_READ_NOTE,
        "next_steps_facts": NEXT_STEPS_FACTS,
        "scope_note": REPORT_SCOPE_NOTE,
    }
