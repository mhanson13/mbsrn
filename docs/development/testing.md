# Testing

## Scope
Backend tests are in `app/tests`.
Frontend tests are in `frontend/operator-ui/app/**/*.test.tsx`.

## Backend
Run all tests:
```powershell
pytest
```

Run targeted file:
```powershell
pytest app/tests/test_seo_competitor_profile_generation_api.py -q
```

Run with coverage:
```powershell
pytest --cov=app --cov-report=term-missing --cov-report=xml
```

## Frontend
```powershell
cd frontend/operator-ui
npm ci
npm test -- --runInBand
npm run lint
npm run typecheck
npm run build
```

## Discovery and Config
Pytest discovery is explicit in `pytest.ini`:
- `testpaths = app/tests`
- `pythonpath = .`

Pytest environment defaults are explicit:
- `APP_ENV` defaults to `test` for pytest runs.
- Developers do not need to manually export `APP_ENV` before running tests.
- If `APP_ENV` is already set (for example `APP_ENV=ci` in CI), it is preserved.

## CI Parity
- Backend pipeline: `.github/workflows/backend-ci.yml`
- Frontend pipeline: `.github/workflows/frontend-ci.yml`

Use the same command set locally before opening a PR to reduce CI-only failures.

## CI Database Strategy
- Backend CI intentionally starts an ephemeral Postgres service container for the migration gate:
  - `alembic upgrade head`
- This is CI-only isolation and is independent of production Cloud SQL/GKE runtime topology.
- Most backend pytest coverage uses the in-memory SQLite `db_session` fixture from `app/tests/conftest.py`.
