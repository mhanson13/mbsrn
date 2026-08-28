web: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
migrate: python -m alembic upgrade head
migrate-baseline-existing: python -m alembic stamp --purge 0024_google_business_profile_oauth_connections
seo-competitor-profile-retention: python -m app.cli.seo_competitor_profile_generation_retention_cleanup
source-capture-worker: python -m app.cli.source_capture_worker
