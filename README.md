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
- `phase3-response-and-reminders.md`
- `phase4-notifications-and-hardening.md`

## Notification Provider Modes
Set provider selection in `.env`:
- `SMS_PROVIDER=mock|dev|twilio`
- `EMAIL_PROVIDER=mock|dev|smtp`

Default local mode is `mock`.  
When using `twilio` or `smtp`, configure the corresponding credentials in `.env`.

## API Credential Auth
- Primary auth path is DB-backed bearer credentials in `api_credentials`.
- Manage credentials per business:
  - `POST /api/businesses/{business_id}/credentials`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/disable`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/revoke`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/rotate`
- Issued token plaintext is shown once at creation/rotation; only `token_hash` is persisted.
- Env compatibility auth fallbacks are gated by `ALLOW_AUTH_COMPAT_FALLBACK`.

Archived legacy scaffolding and deprecated files live under [`_archive/`](_archive).
