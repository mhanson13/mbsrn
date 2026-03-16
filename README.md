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
- `seo-ai-phase2-competitor-intelligence.md`
- `seo-ai-phase2-data-model.md`
- `seo-ai-phase2-api.md`
- `seo-ai-phase2a-foundations-summary.md`
- `seo-ai-phase2b-deterministic-comparison-summary.md`
- `seo-ai-phase2c-deterministic-comparison-enrichment-summary.md`
- `seo-ai-phase2d-manual-competitor-summaries.md`
- `seo-ai-phase2e-summary-contract-hardening.md`
- `phase3-response-and-reminders.md`
- `phase4-notifications-and-hardening.md`
- `security-architecture.md`

## SEO.ai Phase 1
Current SEO.ai Phase 1 endpoints (business-scoped):
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

## SEO.ai Phase 2 (Current)
Current competitor-intelligence endpoints (business-scoped):
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

## Notification Provider Modes
Set provider selection in `.env`:
- `SMS_PROVIDER=mock|dev|twilio`
- `EMAIL_PROVIDER=mock|dev|smtp`

Default local mode is `mock`.  
When using `twilio` or `smtp`, configure the corresponding credentials in `.env`.

## API Credential Auth
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
  - bearer-auth request throttling (client IP keyed)
  - stricter admin-route throttling for principal/credential/audit management actions
  - throttled requests return `429 Rate limit exceeded. Retry later.`
- Rate limits are configurable via:
  - `RATE_LIMIT_ENABLED`
  - `AUTH_RATE_LIMIT_REQUESTS` / `AUTH_RATE_LIMIT_WINDOW_SECONDS`
  - `ADMIN_RATE_LIMIT_REQUESTS` / `ADMIN_RATE_LIMIT_WINDOW_SECONDS`
- `API_TOKEN_HASH_PEPPER` is required in production.
- Legacy unpeppered hash verification is off by default and can be enabled temporarily with `ALLOW_LEGACY_TOKEN_HASH_FALLBACK=true`.
- Legacy shared-token auth (`API_AUTH_TOKEN` / `API_AUTH_BUSINESS_ID`) is no longer part of runtime auth resolution.

Out of scope in this pass: full IAM/user-role management and enterprise-grade audit retention/compliance tooling.

Archived legacy scaffolding and deprecated files live under [`_archive/`](_archive).
