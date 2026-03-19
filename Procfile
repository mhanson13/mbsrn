web: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
migrate: python -m alembic upgrade head
migrate-baseline-existing: python -m app.scripts.alembic_baseline_existing
