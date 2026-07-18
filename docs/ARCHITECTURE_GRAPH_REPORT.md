# Graph Report - .  (2026-07-18)

## Corpus Check
- 50 files · ~329,822 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 500 nodes · 983 edges · 27 communities (26 shown, 1 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 32 edges (avg confidence: 0.82)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Admission Probability Calibration
- Raw Data Ingestion
- Frontend App Shell + API Client
- Grounded Counsellor Generation
- Recommend API Endpoint
- Ranker Feature Preparation
- Counsellor Context Retrieval
- Postgres Migration Parity Check
- Frontend TS Config (app)
- Eligibility Filter and Banding
- Frontend TS Config (base)
- College Similarity Index
- Frontend Dev Dependencies
- DB Schema Definitions
- Dataset Build and Coverage Report
- DB Connection and Postgres Migration
- Frontend Lint Config
- TS Project References
- Frontend Package Metadata
- React Runtime Dependencies
- NPM Scripts
- Cutoff Regressor Training
- Vite and Node TS Config

## God Nodes (most connected - your core abstractions)
1. `get_database_url()` - 23 edges
2. `get_engine()` - 23 edges
3. `compilerOptions` - 18 edges
4. `build_context_bundle()` - 18 edges
5. `Shared frontend TypeScript types` - 17 edges
6. `run()` - 17 edges
7. `build_forecasts()` - 16 edges
8. `generate_answer()` - 16 edges
9. `compilerOptions` - 15 edges
10. `run()` - 15 edges

## Surprising Connections (you probably didn't know these)
- `Known gap: mixed-mode counsellor context can exceed a free-tier provider's per-minute token limit` --rationale_for--> `build_context_bundle()`  [EXTRACTED]
  KNOWN_ISSUES.md → models/counsellor_retrieval.py
- `Known gap: grounding validation checks a flat value pool, not per-field/per-college attribution` --rationale_for--> `validate_grounding()`  [EXTRACTED]
  KNOWN_ISSUES.md → models/counsellor.py
- `Known gap: mixed-mode counsellor context can exceed a free-tier provider's per-minute token limit` --rationale_for--> `generate_answer()`  [EXTRACTED]
  KNOWN_ISSUES.md → models/counsellor.py
- `Known gap: Postgres migration adds no indexes beyond SQLAlchemy PK/FK defaults` --rationale_for--> `load_regressor_training_data()`  [EXTRACTED]
  KNOWN_ISSUES.md → models/regressor_dataset.py
- `favicon.svg (purple diamond compass mark)` --semantically_similar_to--> `App header logo mark (inline SVG diamond/compass)`  [INFERRED] [semantically similar]
  frontend/public/favicon.svg → frontend/src/App.tsx

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **DB connection module adopted as single source of truth by every backend-touching caller** — db_connection_get_database_url, db_connection_get_engine, db_connection_get_backend_name, db_connection_redact_database_url, api_eligibility_load_reference_tables, data_pipeline_build_dataset_run, db_migrate_to_postgres_migrate, db_parity_check_build_environment [EXTRACTED 1.00]
- **Eligibility forecast-to-band candidate pipeline** — api_eligibility_build_forecasts, api_eligibility_load_reference_tables, api_eligibility_merge_forecasts_with_colleges, api_eligibility_select_best_quota_rows, api_eligibility_get_eligible_colleges [INFERRED 0.85]
- **PDF report reuses /recommend's exact computed output, nothing recomputed** — api_main_report, api_main_compute_recommendation, api_report_data_build_report_data, api_report_pdf_render_report_pdf [EXTRACTED 1.00]
- **Student profile to ranked recommendation flow** — frontend_src_components_studentform_studentform, frontend_src_app_handlesubmit, frontend_src_api_client_fetchrecommendation, frontend_src_components_resultsview_resultsview [INFERRED 0.85]
- **Personalized grounded-counsellor chat flow** — frontend_src_app_app, frontend_src_components_chatpanel_chatpanel, frontend_src_components_chatpanel_handleask, frontend_src_api_client_askcounsellor [INFERRED 0.85]
- **Diamond compass mark visual identity** — frontend_public_favicon, frontend_src_app_appmark, frontend_index [INFERRED 0.75]
- **Temporal Leakage Discipline Across Regressor, Probability Calibration, and Ranker** — models_cutoff_regressor_run, models_admission_probability_run, models_ranker_run [INFERRED 0.85]
- **Grounded Counsellor Honesty Enforcement Pipeline** — models_counsellor_retrieval_build_context_bundle, models_counsellor_generate_answer, models_counsellor_validate_grounding, tests_test_counsellor_grounding_test_generate_answer_blocks_fabricated_number_when_retry_still_fabricates [EXTRACTED 1.00]
- **Cutoff Regressor Production Artifact Bundle** — models_cutoff_regressor_save_artifacts, models_artifacts_delta_model, models_artifacts_fallback_model, models_artifacts_metadata [EXTRACTED 1.00]

## Communities (27 total, 1 thin omitted)

### Community 0 - "Admission Probability Calibration"
Cohesion: 0.06
Nodes (58): Cold-start fallback: absolute-rank model for groups with no year-1 lag, apply_calibration(), brier_score(), build_eval_rows_from_predictions(), build_probability_eval_dataset(), compute_residual_distributions(), expected_calibration_error(), fit_calibration() (+50 more)

### Community 1 - "Raw Data Ingestion"
Cohesion: 0.08
Nodes (49): fetch_full_2021_2022(), fetch_josaa_2024(), fetch_josaa_rounds(), fetch_nirf(), fetch_seat_matrix(), fetch_snapshot_2023(), _get(), main() (+41 more)

### Community 2 - "Frontend App Shell + API Client"
Cohesion: 0.08
Nodes (46): favicon.svg (purple diamond compass mark), askCounsellor, extractErrorMessage, fetchMeta, fetchRecommendation, fetchReportPdf, fetchSimilarColleges, App (root component) (+38 more)

### Community 3 - "Grounded Counsellor Generation"
Cohesion: 0.07
Nodes (37): Ranker circularity guard: exclude closing-rank-derived features from RANKER_FEATURES, Known gap: mixed-mode counsellor context can exceed a free-tier provider's per-minute token limit, Known gap: grounding validation checks a flat value pool, not per-field/per-college attribution, _client(), extract_numbers(), _format_context(), generate_answer(), _grounded_value_strings() (+29 more)

### Community 4 - "Recommend API Endpoint"
Cohesion: 0.07
Nodes (39): Category rank vs overall CRL rank distinction for reserved categories, jee_rank must be on the same scale as the category's own JoSAA     closing ranks, StudentProfile, chat(), ChatRequest, compute_recommendation(), meta(), FastAPI backend: the first working end-to-end path from a student's input to a r (+31 more)

### Community 5 - "Ranker Feature Preparation"
Cohesion: 0.13
Nodes (27): band_for(), Regressor covers Gender-Neutral seats only (stated scope limitation), get_eligible_colleges(), merge_forecasts_with_colleges(), Precompute forecast-college merge once, reuse across many candidate sets, Vectorized equivalent of "for each college-branch, pick whichever     applicable, reference_tables lets a caller that's going to call this many times in     a loo, The forecasts-to-colleges merge doesn't depend on any one student, so     a call (+19 more)

### Community 6 - "Counsellor Context Retrieval"
Cohesion: 0.15
Nodes (21): _branch_core(), build_context_bundle(), _college_aliases(), _forecast_records(), is_placement_question(), _match_branch(), _match_college(), Assembles a grounded context bundle for a student's counsellor question, from th (+13 more)

### Community 7 - "Postgres Migration Parity Check"
Cohesion: 0.18
Nodes (20): lifespan(), Model warmup at boot amortizes first-predict cost, build_environment(), compare_counsellor_retrieval(), compare_recommend(), compare_row_counts(), compare_similarity_profiles(), _diff_dicts() (+12 more)

### Community 8 - "Frontend TS Config (app)"
Cohesion: 0.10
Nodes (21): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+13 more)

### Community 9 - "Eligibility Filter and Banding"
Cohesion: 0.20
Nodes (16): load_reference_tables(), Given a student, returns eligible college-branches for the upcoming year, banded, get_database_url(), get_engine(), Cached per URL: every call site used to open its own fresh engine.     Harmless, Known gap: Postgres migration adds no indexes beyond SQLAlchemy PK/FK defaults, _historical_closing_ranks(), No student profile given, so there's no eligibility/forecast to run -     falls (+8 more)

### Community 10 - "Frontend TS Config (base)"
Cohesion: 0.12
Nodes (17): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+9 more)

### Community 11 - "College Similarity Index"
Cohesion: 0.17
Nodes (15): models/artifacts/similarity_metadata.json (FAISS index metadata), build_all_profiles(), build_college_profile(), build_index(), _demo(), _fee_level(), load_profile_tables(), _normalize_branch_name() (+7 more)

### Community 12 - "Frontend Dev Dependencies"
Cohesion: 0.13
Nodes (15): devDependencies, oxlint, @types/node, @types/react, @types/react-dom, typescript, vite, @vitejs/plugin-react (+7 more)

### Community 13 - "DB Schema Definitions"
Cohesion: 0.33
Nodes (12): Base, Regenerates schema.sql from models.py so the two never drift apart.  Run after a, run(), Base (declarative_base / metadata), College, Cutoff, NirfRanking, Program (+4 more)

### Community 14 - "Dataset Build and Coverage Report"
Cohesion: 0.22
Nodes (12): attach_latest_nirf_rank(), Coverage report computed live from loaded data, never a fixed narrative, load_processed_tables(), print_coverage_report(), Loads the normalized tables into the dev database and prints a coverage report., Computed from the actual loaded data rather than a fixed narrative, so     this, run(), build_reference_metadata() (+4 more)

### Community 15 - "DB Connection and Postgres Migration"
Cohesion: 0.26
Nodes (10): get_backend_name(), Single source of truth for how every module in this app connects to its database, sqlite" or "postgres" - never the host, credentials, or full URL.     Used by st, _coerce_nullable_integers(), main(), migrate(), _nullable_integer_columns(), SQLite NaN-as-float vs Postgres NULL/INTEGER gotcha requires nullable Int64 coercion (+2 more)

### Community 16 - "Frontend Lint Config"
Cohesion: 0.18
Nodes (10): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema, frontend README.md, React Compiler, oxc (+2 more)

### Community 17 - "TS Project References"
Cohesion: 0.33
Nodes (4): include, files, references, src

### Community 18 - "Frontend Package Metadata"
Cohesion: 0.40
Nodes (4): name, private, type, version

### Community 19 - "React Runtime Dependencies"
Cohesion: 0.40
Nodes (5): dependencies, react, react-dom, react, react-dom

### Community 20 - "NPM Scripts"
Cohesion: 0.40
Nodes (5): scripts, build, dev, lint, preview

### Community 21 - "Cutoff Regressor Training"
Cohesion: 0.50
Nodes (4): build_forecasts(), _demo(), Concrete verification: a few real student profiles, printed with     their bands, Loads the persisted regressor artifacts and produces a predicted     closing ran

## Knowledge Gaps
- **74 isolated node(s):** `$schema`, `typescript`, `oxc`, `react/rules-of-hooks`, `warn` (+69 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_database_url()` connect `Eligibility Filter and Banding` to `Admission Probability Calibration`, `Recommend API Endpoint`, `Ranker Feature Preparation`, `Counsellor Context Retrieval`, `Postgres Migration Parity Check`, `College Similarity Index`, `Dataset Build and Coverage Report`, `DB Connection and Postgres Migration`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `get_engine()` connect `Eligibility Filter and Banding` to `Admission Probability Calibration`, `Ranker Feature Preparation`, `Counsellor Context Retrieval`, `Postgres Migration Parity Check`, `College Similarity Index`, `Dataset Build and Coverage Report`, `DB Connection and Postgres Migration`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `plugins` connect `Frontend Lint Config` to `Frontend App Shell + API Client`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **What connects `$schema`, `typescript`, `oxc` to the rest of the system?**
  _74 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Admission Probability Calibration` be split into smaller, more focused modules?**
  _Cohesion score 0.06144393241167435 - nodes in this community are weakly interconnected._
- **Should `Raw Data Ingestion` be split into smaller, more focused modules?**
  _Cohesion score 0.07541478129713423 - nodes in this community are weakly interconnected._
- **Should `Frontend App Shell + API Client` be split into smaller, more focused modules?**
  _Cohesion score 0.08144796380090498 - nodes in this community are weakly interconnected._