# Work Boots Console

Monolithic FastAPI service for contractor lead intake and follow-up operations.

## Overview
Work Boots Console is an MVP backend for small contractor businesses.  
It supports:
- manual lead intake
- GoDaddy email intake
- lead deduplication and event tracking
- response-time and stale-lead reporting
- reminder/escalation runs for untouched leads
- notification delivery adapters with business-level controls

## Repository Layout
```text
work-boots/
  app/
  alembic/
  docs/
  frontend/
  infra/
  scripts/
  _archive/
  .env.example
  .gitignore
  alembic.ini
  pyproject.toml
  requirements.txt
  requirements-dev.txt
  README.md
```

## Run The API
Recommended on Windows:
```powershell
.\scripts\run_api.bat
```

Direct command:
```powershell
python -m uvicorn app.main:app --reload
```

Schema initialization policy:
- Local/dev/test convenience: startup `create_all()` is allowed only when `APP_ENV` is local-like and `DB_AUTO_CREATE_LOCAL=true`.
- CI/staging/production/GKE: set `DB_AUTO_CREATE_LOCAL=false`; Alembic migrations are authoritative.
- Deploy path runs `alembic upgrade head` before rollout.

Health check:
```powershell
curl.exe http://127.0.0.1:8000/health
```

## Run Tests
Recommended on Windows:
```powershell
.\scripts\test_api.bat
```

Direct command:
```powershell
python -m pip install -r requirements-dev.txt
pytest
```

Local backend quality checks (matches CI scope):
```powershell
ruff check app/main.py app/core/config.py app/core/rate_limit.py app/core/session_state.py app/core/session_token.py app/integrations/google_auth.py
black --check app/main.py app/core/config.py app/core/rate_limit.py app/core/session_state.py app/core/session_token.py app/integrations/google_auth.py
mypy app/core/config.py
pytest --cov=app --cov-report=term-missing --cov-report=xml
```
CI applies a modest backend coverage gate (`--cov-fail-under=70`) to prevent silent regression.

Optional local migration check:
```powershell
alembic upgrade head
```

## Run Operator UI
The standalone operator console lives under `frontend/operator-ui`.

```powershell
cd frontend/operator-ui
npm ci
npm run dev
```

Set `frontend/operator-ui/.env.local` with:
- `NEXT_PUBLIC_API_BASE_URL` (for example `http://127.0.0.1:8000`)
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID` (Google OIDC client ID)

## Documentation
Project docs live under [`docs/`](docs):
- `lead-intake-engine.md`
- `lead-intake-engine-api.md`
- `lead-intake-engine-data-model.md`
- `lead-intake-flow.md`
- `seo-ai-requirements.md`
- `seo-ai-phase1-implementation-checklist.md`
- `seo-ai-phase1-audit-hardening.md`
- `seo-ai-phase1-5-usability-and-diagnostics.md`
- `seo-ai-phase2-competitor-intelligence.md` (implemented Phase 2 architecture + workflow scope)
- `seo-ai-phase2-data-model.md` (implemented Phase 2 table/lineage model)
- `seo-ai-phase2-api.md` (implemented Phase 2 endpoint and response contracts)
- `seo-ai-phase2a-foundations-summary.md`
- `seo-ai-phase2b-deterministic-comparison-summary.md`
- `seo-ai-phase2c-deterministic-comparison-enrichment-summary.md`
- `seo-ai-phase2d-manual-competitor-summaries.md`
- `seo-ai-phase2e-summary-contract-hardening.md`
- `seo-ai-phase3a-deterministic-recommendations.md` (implemented deterministic recommendation generation)
- `seo-ai-phase3a-data-model.md` (implemented recommendation run/recommendation schema)
- `seo-ai-phase3a-api.md` (implemented recommendation endpoint contract)
- `seo-ai-phase3b-workflow-and-prioritization.md` (implemented deterministic recommendation workflow management)
- `seo-ai-phase3b-data-model.md` (implemented recommendation workflow/prioritization schema updates)
- `seo-ai-phase3b-api.md` (implemented workflow list/update/backlog/report API contract)
- `seo-ai-phase3c-recommendation-narratives.md` (implemented AI narrative layer over persisted deterministic recommendations)
- `seo-ai-phase3c-data-model.md` (implemented recommendation narrative persistence schema)
- `seo-ai-phase3c-api.md` (implemented narrative endpoint contract)
- `seo-ai-phase4-automation-and-operationalization.md` (implemented monolith-safe orchestration over persisted SEO pipeline artifacts)
- `seo-ai-phase4-data-model.md` (implemented automation config/run persistence model)
- `seo-ai-phase4-api.md` (implemented automation config/run API contract)
- `phase4-platform-operationalization-roadmap.md` (current Phase 4 operationalization status, remaining pilot hardening tasks, and Phase 4 exit checklist)
- `phase4-runtime-validation-runbook.md` (step-by-step pilot runtime validation and Phase 4 signoff execution runbook)
- `phase5-security-maturity-roadmap.md` (next-phase security maturity plan for browser/session hardening, observability, and production posture validation)
- `operator-ui-and-google-auth.md` (implemented operator UI + Google identity exchange to internal principal authorization)
- `deployment-gke-cicd.md` (implemented GKE deployment, Artifact Registry image flow, and GitHub Actions CI/CD)
- `phase3-response-and-reminders.md`
- `phase4-notifications-and-hardening.md`
- `security-architecture.md` (current platform and security architecture baseline with explicit Phase 4 -> Phase 5 transition)

## SEO.ai Implementation Status
Implemented today:
- Phase 1: deterministic site audit + findings + manual-trigger audit summaries
- Phase 1.5: hardening/usability improvements for audit diagnostics and contracts
- Phase 2: competitor foundations, snapshotting, deterministic comparison runs/reports, and manual-trigger competitor summaries
- Phase 3A: deterministic recommendation runs generated from persisted audit/comparison evidence
- Phase 3B: deterministic recommendation workflow state, prioritization views, and operator update APIs
- Phase 3C: manual-trigger AI recommendation narratives grounded in persisted deterministic recommendation data
- Phase 4: persisted SEO automation config/run orchestration with manual trigger and scheduler-ready due execution

## SEO.ai Phase 1 (Implemented)
Current Phase 1 endpoints (business-scoped):
- Sites:
  - `GET /api/businesses/{business_id}/seo/sites`
  - `POST /api/businesses/{business_id}/seo/sites`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}`
  - `PATCH /api/businesses/{business_id}/seo/sites/{site_id}`
- Audit runs:
  - `POST /api/businesses/{business_id}/seo/sites/{site_id}/audit-runs`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/audit-runs`
  - `GET /api/businesses/{business_id}/seo/audit-runs/{run_id}`
  - `GET /api/businesses/{business_id}/seo/audit-runs/{run_id}/findings`
  - `GET /api/businesses/{business_id}/seo/audit-runs/{run_id}/summary`
  - `GET /api/businesses/{business_id}/seo/audit-runs/{run_id}/report`
- Audit summary (manual trigger only):
  - `POST /api/businesses/{business_id}/seo/audit-runs/{run_id}/summarize`

## SEO.ai Phase 2 (Implemented)
Current competitor-intelligence endpoints (business-scoped):
Architecture notes:
- deterministic comparison findings and rollups are persisted first
- AI is used only for manual-trigger comparison summaries from persisted comparison outputs
- no AI-generated findings or recommendations

Endpoint inventory:
- Competitor sets:
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/competitor-sets`
  - `POST /api/businesses/{business_id}/seo/sites/{site_id}/competitor-sets`
  - `GET /api/businesses/{business_id}/seo/competitor-sets/{set_id}`
  - `PATCH /api/businesses/{business_id}/seo/competitor-sets/{set_id}`
- Competitor domains:
  - `GET /api/businesses/{business_id}/seo/competitor-sets/{set_id}/domains`
  - `POST /api/businesses/{business_id}/seo/competitor-sets/{set_id}/domains`
  - `DELETE /api/businesses/{business_id}/seo/competitor-sets/{set_id}/domains/{domain_id}`
- Snapshot runs:
  - `POST /api/businesses/{business_id}/seo/competitor-sets/{set_id}/snapshot-runs`
  - `GET /api/businesses/{business_id}/seo/competitor-sets/{set_id}/snapshot-runs`
  - `GET /api/businesses/{business_id}/seo/snapshot-runs/{run_id}`
- Deterministic comparison runs:
  - `POST /api/businesses/{business_id}/seo/competitor-sets/{set_id}/comparison-runs`
  - `GET /api/businesses/{business_id}/seo/competitor-sets/{set_id}/comparison-runs`
  - `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}`
  - `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}/findings`
  - `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}/report`
- Competitor summaries (manual trigger only):
  - `POST /api/businesses/{business_id}/seo/comparison-runs/{run_id}/summarize`
  - `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}/summaries`
  - `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}/summaries/latest`
  - `GET /api/businesses/{business_id}/seo/comparison-summaries/{summary_id}`

Compatibility site-scoped Phase 2 paths are also mounted at:
- `/api/v1/businesses/{business_id}/seo/sites/{site_id}/...`

## SEO.ai Phase 3A (Implemented)
Deterministic recommendations are derived from persisted SEO audit findings and persisted competitor comparison findings/rollups.

Endpoint inventory (business-scoped):
- Recommendation runs:
  - `POST /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}`
- Recommendations:
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/recommendations`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendations/{recommendation_id}`
- Deterministic recommendation report:
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/report`

Compatibility site-scoped Phase 3A paths are also mounted at:
- `/api/v1/businesses/{business_id}/seo/sites/{site_id}/...`

## SEO.ai Phase 3B (Implemented)
Phase 3B adds deterministic workflow and prioritization management over persisted recommendations.

Endpoint inventory (business-scoped):
- Site recommendation workflow:
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendations`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendations/{recommendation_id}`
  - `PATCH /api/businesses/{business_id}/seo/sites/{site_id}/recommendations/{recommendation_id}`
- Deterministic prioritization views:
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendations/backlog`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendations/prioritized-report`

Compatibility site-scoped Phase 3B paths are also mounted at:
- `/api/v1/businesses/{business_id}/seo/sites/{site_id}/...`

## SEO.ai Phase 3C (Implemented)
Phase 3C adds manual-trigger AI narratives that explain persisted deterministic recommendations and workflow state.

Endpoint inventory (business-scoped):
- Recommendation narratives:
  - `POST /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives/latest`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-narratives/{narrative_id}`

Compatibility site-scoped Phase 3C paths are also mounted at:
- `/api/v1/businesses/{business_id}/seo/sites/{site_id}/...`

Phase 3C boundary:
- AI narratives explain persisted deterministic recommendation artifacts only.
- AI does not generate recommendation items, findings, priorities, or workflow decisions.

## SEO.ai Phase 4 (Implemented)
Phase 4 operationalizes the existing deterministic + grounded-summary pipeline with persisted configuration, run history, and step tracking.

Endpoint inventory (business-scoped):
- Automation config:
  - `POST /api/businesses/{business_id}/seo/sites/{site_id}/automation-config`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/automation-config`
  - `PATCH /api/businesses/{business_id}/seo/sites/{site_id}/automation-config`
  - `POST /api/businesses/{business_id}/seo/sites/{site_id}/automation-config/enable`
  - `POST /api/businesses/{business_id}/seo/sites/{site_id}/automation-config/disable`
- Automation runs:
  - `POST /api/businesses/{business_id}/seo/sites/{site_id}/automation-runs`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/automation-runs`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/automation-runs/{automation_run_id}`
  - `GET /api/businesses/{business_id}/seo/sites/{site_id}/automation-status`
- Scheduler-ready due execution:
  - `POST /api/jobs/seo-automation/run-due`

Compatibility site-scoped Phase 4 paths are also mounted at:
- `/api/v1/businesses/{business_id}/seo/sites/{site_id}/...`

Phase 4 boundary:
- Automation orchestrates existing deterministic and grounded-AI services only.
- Automation does not generate findings or recommendations autonomously.
- No distributed orchestration framework was introduced.

## Notification Provider Modes
Set provider selection in `.env`:
- `SMS_PROVIDER=mock|dev|twilio`
- `EMAIL_PROVIDER=mock|dev|smtp`

Default local mode is `mock`.  
When using `twilio` or `smtp`, configure the corresponding credentials in `.env`.

## API Credential Auth
- Runtime auth supports two bearer-token paths:
  - DB API credentials (`api_credentials`) for service-to-service and operator-issued keys.
  - Google OIDC exchange -> internal signed JWT access/refresh app session tokens for human operator UI sessions.
- Google remains identity-only; authorization is enforced by internal principal/business/role mappings.
- Google auth endpoints:
  - `POST /api/auth/google/exchange` (exchange Google ID token for app bearer token)
  - `POST /api/auth/refresh` (rotate refresh token and mint a new access/refresh pair)
  - `POST /api/auth/logout` (revoke current access token and optionally the presented refresh token)
  - `GET /api/auth/me` (current principal context)
- Principal identity mapping endpoints (admin only):
  - `GET /api/businesses/{business_id}/principal-identities`
  - `POST /api/businesses/{business_id}/principal-identities`
  - `POST /api/businesses/{business_id}/principal-identities/{identity_id}/activate`
  - `POST /api/businesses/{business_id}/principal-identities/{identity_id}/deactivate`
- Primary auth path is DB-backed bearer credentials in `api_credentials`.
- Credentials are tied to persisted principals in `principals` scoped by business.
- Principals have minimal roles (`admin`, `operator`) for sensitive business actions.
- Manage principals per business (admin only):
  - `GET /api/businesses/{business_id}/principals`
  - `POST /api/businesses/{business_id}/principals`
  - `PATCH /api/businesses/{business_id}/principals/{principal_id}`
  - `POST /api/businesses/{business_id}/principals/{principal_id}/activate`
  - `POST /api/businesses/{business_id}/principals/{principal_id}/deactivate`
- Manage credentials per business:
  - `POST /api/businesses/{business_id}/credentials`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/disable`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/revoke`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/rotate`
- View auth/admin audit history per business (admin only):
  - `GET /api/businesses/{business_id}/auth-audit-events`
- Credential-management endpoints require an `admin` principal role.
- Issued token plaintext is shown once at creation/rotation; only `token_hash` is persisted.
- Credentials store non-secret metadata for operations: `label`, `last_used_at`, `rotated_from_credential_id`.
- Successful DB credential authentication updates `last_used_at`.
- Inactive principals are blocked from authentication and admin operations immediately.
- Principals store non-secret metadata for lifecycle/audit visibility:
  - `created_by_principal_id`
  - `updated_by_principal_id`
  - `last_authenticated_at`
- Auth/admin audit events are persisted for principal and credential lifecycle actions with business scope and actor/target context.
- Audit payloads exclude secret fields (`token`, `token_hash`).
- Application-level abuse protections are enabled by default:
  - bearer-auth request throttling (client IP + normalized user-agent bucket)
  - stricter admin-route throttling for principal/credential/audit management actions (principal-aware)
  - throttled requests return `429 Rate limit exceeded. Retry later.`
- Rate-limit and token-state backends support Redis for distributed GKE enforcement with in-memory local fallback:
  - `REDIS_URL`
  - `RATE_LIMIT_BACKEND=auto|inmemory|redis`
  - `SESSION_STATE_BACKEND=auto|inmemory|redis`
  - `RATE_LIMIT_FAIL_OPEN` and `SESSION_STATE_FAIL_OPEN` control Redis failure behavior explicitly
    (production/staging Redis-backed mode is enforced fail-closed in config validation)
- Rate limits are configurable via:
  - `RATE_LIMIT_ENABLED`
  - `RATE_LIMIT_BACKEND`
  - `RATE_LIMIT_FAIL_OPEN`
  - `AUTH_RATE_LIMIT_REQUESTS` / `AUTH_RATE_LIMIT_WINDOW_SECONDS`
  - `ADMIN_RATE_LIMIT_REQUESTS` / `ADMIN_RATE_LIMIT_WINDOW_SECONDS`
- App session JWT config:
  - `APP_SESSION_ISSUER`
  - `APP_SESSION_AUDIENCE`
  - `APP_SESSION_ALGORITHM`
  - `APP_SESSION_TTL_SECONDS`
  - `APP_SESSION_REFRESH_TTL_SECONDS`
- Google ID token validation uses JWKS signature verification:
  - `GOOGLE_OIDC_JWKS_URL`
  - `GOOGLE_OIDC_REQUIRE_EMAIL_VERIFIED`
- `API_TOKEN_HASH_PEPPER` is required in production.
- Legacy unpeppered hash verification is off by default and can be enabled temporarily with `ALLOW_LEGACY_TOKEN_HASH_FALLBACK=true`.
- Legacy shared-token auth (`API_AUTH_TOKEN` / `API_AUTH_BUSINESS_ID`) is no longer part of runtime auth resolution.

## API CORS And Security Headers
- CORS is explicit and origin-scoped via `API_CORS_ALLOWED_ORIGINS` (comma-separated).
- Local/dev/test defaults permit operator UI local origins:
  - `http://localhost:3000`
  - `http://127.0.0.1:3000`
- `*` is rejected for production/staging environments.
- API security headers are enabled by default:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Content-Security-Policy` on API/health responses
- HSTS is configurable:
  - `SECURITY_HEADERS_HSTS_ENABLED`
  - `SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS`

## Deployment And CI/CD
- Kubernetes manifests are under `infra/k8s` (kustomize base + `dev`/`prod` overlays).
- Kustomize base is namespace-neutral; overlays own namespaces:
  - `dev` -> `work-boots-dev`
  - `prod` -> `work-boots`
- Pilot default workload sizing (current baseline):
  - API deployment: requests `250m` CPU / `512Mi` memory, limits `750m` CPU / `1Gi` memory
  - UI deployment: requests `100m` CPU / `256Mi` memory, limits `500m` CPU / `512Mi` memory
  - pre-rollout Alembic migration Job: requests `100m` CPU / `256Mi` memory, limits `250m` CPU / `512Mi` memory
- For GKE Autopilot, workload cost is primarily driven by Pod resource requests; keep requests conservative and revisit after pilot usage is observed.
- CI/CD workflows are under `.github/workflows`:
  - `backend-ci.yml`
  - `frontend-ci.yml`
  - `deploy-gke.yml`
- JavaScript-based action runtime readiness:
  - CI workflows (`backend-ci.yml`, `frontend-ci.yml`) opt in to Node 24 action-runtime testing via `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`.
  - The deploy workflow keeps runtime forcing disabled while `azure/setup-kubectl@v4` remains on a Node 20 action runtime.
- `backend-ci.yml` runs backend validation:
  - dependency install
  - `ruff` (scoped)
  - `black --check` (scoped)
  - `mypy` (currently scoped to `app/core/config.py`)
  - Alembic migration-chain validation (`alembic upgrade head`) against CI Postgres
  - `pytest` with coverage (`--cov=app --cov-report=term-missing --cov-report=xml`)
  - coverage XML artifact upload
- `frontend-ci.yml` runs frontend validation (`npm ci`, lint, typecheck, build).
  - runs frontend tests only when a `test` script exists; otherwise logs explicit no-tests status
- `deploy-gke.yml` is the release pipeline:
  - builds/pushes backend and frontend images with Cloud Buildpacks
  - runs Alembic migrations as a pre-rollout gate
  - deploys only after successful upstream build gates
  - rolls out exact built image refs (no implicit SHA image assumptions)
- Image builds use Google Cloud Buildpacks (`gcloud builds submit --pack`) and produce OCI images for containerd/GKE.
- Artifact Registry image naming convention:
  - `us-central1-docker.pkg.dev/<project>/<repository>/api:<tag>`
  - `us-central1-docker.pkg.dev/<project>/<repository>/ui:<tag>`
- Google Cloud authentication in GitHub Actions uses Workload Identity Federation (no long-lived key files).
- Pilot/production Redis expectations:
  - `REDIS_URL` configured and reachable from workloads
  - `RATE_LIMIT_BACKEND=redis`
  - `SESSION_STATE_BACKEND=redis`
  - `RATE_LIMIT_FAIL_OPEN=false`
  - `SESSION_STATE_FAIL_OPEN=false`

## Operator UI Session Handling
- Operator UI exchanges Google ID tokens with `POST /api/auth/google/exchange`.
- Access tokens are stored in browser `sessionStorage` (not `localStorage`) for reduced persistence.
- Refresh tokens are kept in memory only for the active UI session and are not persisted across reloads.
- Sign out calls `POST /api/auth/logout`, then clears local session state.

Out of scope in this pass: full IAM/user-role management and enterprise-grade audit retention/compliance tooling.

Archived legacy scaffolding and deprecated files live under [`_archive/`](_archive).
