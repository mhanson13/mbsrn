# MBSRN Operator Platform

[Feature Overview](docs/features/features.md)

MBSRN (My Business Sucks Right Now) is a FastAPI + Next.js platform for SEO operations, competitor intelligence, and operator-driven recommendation workflows. Ultimately, we're trying to democratize AI for small businesses who have GoDaddy(-like) generated sites but no SEO / EATT skills, or frankly time, because their time is spent on a ladder or servicing clients.

## What Is Shipped
- Business-scoped operator auth (Google identity exchange to internal principal authorization)
- Google Business Profile OAuth callback completion redirects browser flows back into the operator app (`/business-profile`) instead of ending on raw API JSON
- SEO site management, deterministic audit runs, and findings/reporting
- Competitor intelligence runs and comparison reporting
- AI-assisted competitor profile draft generation with strict review gating
- Structured AI competitor profile review surface (compact summary strip, primary pipeline table, and secondary debug details)
- Deterministic recommendation runs with AI narrative overlays and bounded tuning suggestions
- Manual, confirmed tuning apply flow (no automatic settings mutation)
- Operator Shell v4 workspace presentation (workflow emphasis for attention/recency/next-action cues on top of v3 visual-token and density standardization)
- Shared role-aware dashboard shell uplift (admin/operator/user pages now share reusable panel/header/stat variants with stronger admin-console page chrome and hierarchy, presentation-only)
- Phase-2 cross-route UI consistency uplift for high-traffic secondary operator routes (`audits`, `automation`, `competitors`, `recommendations`) including standardized loading/error/empty/no-data support states
- Phase-3 detail-route consistency uplift for deeper workspace views (`audits/[run_id]`, competitor run/set detail routes, recommendation detail) plus shared support-state framing on secondary cross-role surfaces (`dashboard`, `business-profile`)
- Phase-4 recommendation-flow detail consistency uplift for recommendation run and narrative routes (`recommendations/runs/[run_id]`, narrative history, narrative detail) with shared hero/summary/support-state framing
- Deep workflow context continuity uplift across audit/competitor/recommendation detail routes with clearer lineage back-links and adjacent next-step guidance
- Summary-before-detail refinement on recommendation/competitor deep routes (top takeaway + likely next action before dense supporting detail)
- Action-driven site workspace Operator Focus (deterministic top-priority next step with direct operator action links)
- Recommendation Presentation v1 (visual action-state buckets: ready/applied/pending/informational using existing recommendation semantics)
- Recommendation Detail Clarity v2 (per-item observed pattern/gap/action/supporting-context blocks for faster operator understanding without changing recommendation logic)
- Shared operational-item quick-scan pattern across dense operator flows (recommendations, competitors, audits, automation) with progressive disclosure for deeper detail
- Controlled workspace/layout width modes (`default` / `wide` / `full`) to reduce wasted horizontal space on dense operator pages while preserving safe padding and rhythm
- Workspace Copy + Label Tuning v1 (operator-facing wording refinement across recommendation/focus surfaces with unchanged behavior/semantics)
- Recommendation apply outcome visibility v1 (compact workspace outcome card showing what changed, current apply visibility state, and expected refresh timing)
- Recommendation outcome snapshot standardization across recommendation-facing routes (dashboard guidance + queue/detail/run summary-first status/change/follow-up/visibility cues)
- Recommendation decisiveness + rationale/evidence compression pass for dashboard/queue/detail surfaces (why-now/actionable/blocking/after-action cues, compact choice-support tags, lifecycle-stage/revisit cues, freshness/review posture + refresh-check cues, and trust-safe evidence preview wording)
- Site workspace Google Business Profile integration visibility (connected/action-needed/not-connected/status-unavailable) with direct connect/reconnect navigation to `/business-profile`
- Site workspace sub-tabs for content priority (`Summary` default, `Recommendations`, and `Activity`) with detailed operational history moved to `Activity`

## Trust Boundary
AI features are advisory only:

`AI generation -> draft/recommendation artifacts -> operator review -> explicit action`

The backend remains authoritative for authorization, validation, and settings bounds.

Competitor trust semantics:
- Accepted competitors can be `verified` or `unverified`.
- `verification_status` is enforced as the downstream website-backed trust gate.
- `unverified` competitors remain operator-visible but are excluded from trusted comparison/recommendation evidence paths.
- Recommendation competitor linkage exposes explicit trust tiers via `competitor_evidence_links[].trust_tier` (`trusted_verified`, `informational_unverified`, `informational_candidate`) so operators can distinguish trusted evidence from informational context.
- Workspace competitor review includes a `Hide synthetic scaffolds` visibility toggle; it defaults ON only when 5+ non-synthetic drafts exist and never removes synthetic data from API/state.

## Repository Structure
```text
app/                    FastAPI app (routes, services, models, repositories, tests)
alembic/                Database migrations
docs/                   Canonical docs index, feature docs, operations and development guides
frontend/operator-ui/   Next.js operator workspace
infra/                  Kubernetes manifests/overlays
scripts/                Local/dev and bootstrap scripts
```

## Quick Start
### Backend
```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
alembic upgrade head
python -m uvicorn app.main:app --reload
```

Windows helper:
```powershell
.\scripts\run_api.bat
```

### Operator UI
```powershell
cd frontend/operator-ui
npm ci
npm run dev
```

Required local frontend env values in `frontend/operator-ui/.env.local`:
- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID`

## Tests and Quality
Backend tests live in `app/tests` and are discovered via `pytest.ini`.

### Backend
```powershell
pytest
pytest --cov=app --cov-report=term-missing --cov-report=xml
```

### Frontend
```powershell
cd frontend/operator-ui
npm test -- --runInBand
npm run lint
npm run typecheck
npm run build
```

### CI Alignment
- Backend CI: `.github/workflows/backend-ci.yml`
- Frontend CI: `.github/workflows/frontend-ci.yml`

Coverage and test suites include SEO audit/crawl behavior, competitor candidate quality/deduplication, recommendation+narrative APIs, tuning preview/attribution flows, and business settings validation.

## Database Runtime Safety
- Authoritative env names: `APP_ENV`, `DATABASE_URL`, `DB_CONNECTION_MODE`, `CLOUD_SQL_INSTANCE_CONNECTION_NAME`.
- Localhost database targets are allowed only for local-like app envs (`local`, `development`, `dev`, `test`, `ci`).
- In production, localhost/loopback targets are invalid unless `DB_CONNECTION_MODE=cloudsql_proxy` (current sidecar model).
- Production startup includes a bounded Cloud SQL proxy readiness retry (15 attempts, 1s delay) before failing.
- Schema readiness checks Alembic head from the running image (current repo head: `0039_competitor_domain_verification_status`).
- Post-deploy startup verification logs should include:
  - `Startup schema readiness expectation ... expected_revision=0039_competitor_domain_verification_status`
  - `Startup database connectivity check using cloudsql proxy retry budget ...` (proxy mode only)
  - `Startup database connectivity check succeeded ... proxy_retry_path_entered=<bool> recovered_after_retry=<bool>`
  - `Schema readiness passed expected=... current=...` (from readiness checks)

## GCP Logs Query Deployment Prerequisites
The admin `GCP Logs Query` feature relies on runtime Application Default Credentials (Workload Identity) and project-id wiring in the API pod.

Required deployment wiring:
- API deployment must use `serviceAccountName: mbsrn-api`.
- Kubernetes service account `mbsrn-api` must be mapped to a Google service account via annotation:
  - `iam.gke.io/gcp-service-account=<runtime-gsa>@<project>.iam.gserviceaccount.com`
- Runtime project-id env must be present in API pod:
  - `GCP_PROJECT_ID`
- Runtime GSA must have:
  - `roles/iam.workloadIdentityUser` binding for `serviceAccount:<project>.svc.id.goog[mbsrn/mbsrn-api]`
  - Cloud Logging read access (`roles/logging.viewer` or approved equivalent)

Preflight verification (read-only):
```powershell
python scripts/verify_gcp_logs_wiring.py
python scripts/verify_gcp_logs_wiring.py --cluster --project-id <PROJECT_ID> --gsa-email <RUNTIME_GSA_EMAIL>
```

## Session Backend Runtime Note
- Session state supports `SESSION_STATE_BACKEND=auto|redis|inmemory`.
- Redis-backed session state is required for correctness in multi-replica production; in-memory is process-local and non-shared across replicas.
- Kubernetes deploy manifests now include an internal Redis workload + ClusterIP service (`mbsrn-redis`) and wire API `REDIS_URL` to that internal service.
- Production-authoritative deploy path is `.github/workflows/deploy-prod.yml` + `k8s/*` (the `deploy-gke.yml` + `infra/k8s/overlays/*` path remains secondary/manual).
- If production/staging falls back to in-memory, API logs emit:
  - `event=session_state_backend_selection ... selected_backend=inmemory ... degraded_mode=True`
- Production-safe posture:
  - `SESSION_STATE_BACKEND=redis`
  - valid `REDIS_URL`
  - `SESSION_STATE_FAIL_OPEN=false`
  - `SESSION_STATE_ALLOW_INMEMORY_FALLBACK=false`
- Post-deploy verification commands and Logs Explorer queries are documented in [docs/deployment-gke-cicd.md](docs/deployment-gke-cicd.md) under `Redis-Backed Session Verification`.

## Documentation
Start with [docs/README.md](docs/README.md) for canonical navigation.

## Branding
- Product: **MBSRN (My Business Sucks Right Now)**
- Frontend surface: **Operator Workspace**

Legacy lead-intake and early exploration docs are retained under `docs/archive/` for historical reference and are not part of the primary implementation path.
