# SEO Recommendations (Deterministic + AI Narrative)

## Overview
This feature produces deterministic SEO recommendations from persisted audit/comparison evidence, then optionally generates an AI narrative over those persisted recommendation artifacts.

Deterministic recommendation records remain canonical. AI output is advisory explanation only.
Tuning impact preview is deterministic and advisory only, and preview-to-outcome accuracy is tracked for evaluation.
The site workspace now surfaces the latest completed recommendation run, deterministic recommendation items, latest AI narrative, AI tuning suggestions, deterministic preview impact, and a manual apply action for tuning suggestions.

## Why This Exists
- Deterministic rules provide stable, auditable recommendation artifacts.
- Operators still need fast, human-readable context on priorities and backlog.
- AI narrative generation improves explainability without turning AI into the source of truth.
- Bounded AI tuning suggestions provide controlled operator guidance for competitor candidate quality settings using persisted telemetry.

## Architecture / Flow
1. Deterministic run creation:
   - `POST /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs`
   - Service reads persisted lineage inputs (`audit_run_id`, `comparison_run_id`) and generates deterministic recommendations.
2. Persistence:
   - Run stored in `seo_recommendation_runs`
   - Recommendation rows stored in `seo_recommendations`
3. AI narrative generation (manual trigger or automation step):
   - `POST /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives`
   - Prompt is built from persisted recommendation artifacts, recommendation rollups, competitor candidate telemetry rollups, and current business tuning values.
   - Provider output is schema-validated before persistence.
   - Structured narrative sections can include `tuning_suggestions` (max 4), each constrained to allowed setting keys, bounded integer values, and valid linked recommendation IDs.
4. Narrative retrieval:
   - list/latest/by-id narrative endpoints return persisted narrative versions.
5. Deterministic tuning impact preview:
   - `POST /api/businesses/{business_id}/seo/sites/{site_id}/recommendations/tuning-preview`
   - Uses persisted competitor telemetry and bounded rule-based heuristics to estimate impact of proposed tuning changes.
   - Preview returns estimated deltas, caveats, and `preview_event_id`; no settings are mutated.
6. Manual tuning apply (operator-confirmed):
   - Workspace presents an explicit confirmation before applying a suggestion.
   - Apply uses existing business settings path: `PATCH /api/businesses/{business_id}/settings`.
   - PATCH payload includes only targeted tuning field(s), with optional `competitor_tuning_preview_event_id` for explicit attribution.
   - Backend validation remains authoritative; no auto-apply path exists.
7. Preview accuracy feedback loop:
   - Each preview request persists a bounded preview event (`request` + `response` payload snapshots).
   - When matching tuning values are later applied through business settings, the event is linked via `applied_at` (explicit id when provided, heuristic fallback otherwise).
   - On the next completed competitor profile generation run for that site, estimated vs actual included-candidate deltas are evaluated and persisted.
   - Site observability summary now reports aggregate preview accuracy (`preview_accuracy_rate`, `avg_error_margin`, and `last_n_preview_accuracy`).
8. UI:
   - Recommendation queue and run detail pages render deterministic recommendation data.
   - Narrative views render AI explanation when available.
   - Site workspace surfaces:
     - latest completed run summary
     - deterministic recommendation list for that run
     - latest narrative overlay (if available)
     - AI-assisted tuning suggestions
     - deterministic tuning preview per suggestion
     - explicit manual apply action per suggestion with confirmation
   - Missing run/narrative/preview data is handled with section-scoped safe empty/failure states.

## API / Interfaces
- Canonical workspace read path for latest recommendation surfacing:
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendations/workspace-summary`
  - `GET /api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendations/workspace-summary`
- The workspace summary response is bounded and includes:
  - latest run metadata
  - latest completed run metadata
  - deterministic recommendations for the latest completed run
  - latest narrative (if present)
  - bounded tuning suggestions (if present)
  - safe summary state (`no_runs`, `no_completed_runs`, `completed_no_narrative`, `completed_with_narrative`)
- Existing run/recommendation/narrative endpoints remain available for history/detail workflows.
- Manual apply continues to use the canonical business settings endpoint:
  - `PATCH /api/businesses/{business_id}/settings`
  - optional attribution field: `competitor_tuning_preview_event_id`

## Data Model
- `seo_recommendation_runs`: deterministic run lineage/status/rollups.
- `seo_recommendations`: deterministic recommendation artifacts and workflow fields.
- `seo_recommendation_narratives`: versioned narrative records with:
  - `status` (`completed` or `failed`)
  - `narrative_text`
  - `top_themes_json`
  - `sections_json`
  - `provider_name`, `model_name`, `prompt_version`
  - `error_message`
- `seo_competitor_tuning_preview_events`: bounded preview evaluation records with:
  - `preview_request`, `preview_response` (bounded JSON payloads)
  - optional linkage fields (`source_narrative_id`, `source_recommendation_run_id`)
  - lifecycle fields (`applied_at`, `evaluated_at`, `evaluated_generation_run_id`)
  - accuracy metrics (`estimated_included_delta`, `actual_included_delta`, `error_margin`, `direction_correct`)

## Key Constraints / Invariants
- AI never creates canonical recommendation artifacts.
- AI never mutates business settings or workflow state.
- Narrative generation is grounded in persisted recommendation artifacts only.
- Tuning suggestions are advisory only and never auto-applied.
- Tuning impact preview is deterministic, uses persisted telemetry only, and never auto-applies settings.
- Workspace apply requires explicit operator confirmation and uses bounded section-scoped PATCH only.
- Preview accuracy tracking is observability-only and never mutates tuning settings automatically.
- Tuning suggestions are strictly bounded to:
  - `competitor_candidate_min_relevance_score` (`0..100`)
  - `competitor_candidate_big_box_penalty` (`0..50`)
  - `competitor_candidate_directory_penalty` (`0..50`)
  - `competitor_candidate_local_alignment_bonus` (`0..50`)
- Business/site scoping is enforced in routes, services, and repositories.

## Configuration
AI narrative provider wiring uses existing AI runtime settings:
- `AI_PROVIDER_API_KEY` (secret; required for OpenAI in production/staging)
- `AI_PROVIDER_NAME` (`openai` or `mock`)
- `AI_MODEL_NAME` (default `gpt-4o-mini`)
- `AI_TIMEOUT_VALUE` (default `30`)
- `AI_PROMPT_TEXT_RECOMMENDATION` (optional supplemental recommendation text)
- `OPENAI_API_BASE_URL` (default `https://api.openai.com/v1`)

Behavior:
- `openai` + valid key -> real provider.
- `openai` + missing key in local/test/dev -> mock fallback for local workflows/tests.
- `openai` + missing key in production/staging -> safe misconfigured-provider failure.

## Operational Behavior
- Narrative generation is versioned per recommendation run.
- Provider failures persist a `failed` narrative version with safe `error_message`.
- Failure isolation: recommendation run/recommendation records are not mutated by narrative failures.
- Provider/model/prompt metadata is persisted for auditability.
- Tuning suggestions are suppressed when competitor telemetry indicates a balanced candidate set (no excluded candidates in telemetry window).
- Preview endpoint returns bounded estimated deltas from deterministic heuristics over persisted telemetry and includes a non-guarantee caveat.
- Preview events are persisted for evaluation; linkage and accuracy scoring are observability signals and do not auto-mutate settings.
- Manual apply refreshes workspace summary and current tuning values after successful update.

## Failure Modes
- Timeout/provider request/auth/config/schema/parse failures are normalized to safe errors.
- API returns validation-safe failures (`422`) for narrative generation failures.
- Existing deterministic recommendation artifacts remain available even if narrative generation fails.

## Security Considerations
- Raw provider credentials are not exposed in API responses.
- Prompt context is treated as data; output is schema-validated before persistence.
- AI output remains advisory and cannot bypass review/workflow controls.
- Preview responses expose aggregate telemetry-derived estimates only; no raw candidate payloads are returned.

## Future Extensions
- Provider expansion behind the existing provider abstraction.
- Richer grounded narrative sections (still tied to deterministic IDs/rollups).
- Additional observability for narrative generation latency/error categories.
