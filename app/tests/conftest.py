from __future__ import annotations

import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rate_limit import get_rate_limiter
from app.core.session_state import get_session_state_store
from app.core.time import utc_now
from app.db.base import Base
from app.models.api_credential import APICredential  # noqa: F401
from app.models.auth_audit_event import AuthAuditEvent  # noqa: F401
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.principal import Principal  # noqa: F401
from app.models.principal_identity import PrincipalIdentity  # noqa: F401
from app.models.provider_connection import ProviderConnection  # noqa: F401
from app.models.provider_oauth_state import ProviderOAuthState  # noqa: F401
from app.models.seo_audit_finding import SEOAuditFinding  # noqa: F401
from app.models.seo_audit_page import SEOAuditPage  # noqa: F401
from app.models.seo_audit_run import SEOAuditRun  # noqa: F401
from app.models.seo_audit_summary import SEOAuditSummary  # noqa: F401
from app.models.seo_automation_config import SEOAutomationConfig  # noqa: F401
from app.models.seo_automation_run import SEOAutomationRun  # noqa: F401
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding  # noqa: F401
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun  # noqa: F401
from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary  # noqa: F401
from app.models.seo_competitor_domain import SEOCompetitorDomain  # noqa: F401
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent  # noqa: F401
from app.models.seo_competitor_set import SEOCompetitorSet  # noqa: F401
from app.models.seo_competitor_snapshot_page import SEOCompetitorSnapshotPage  # noqa: F401
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun  # noqa: F401
from app.models.seo_recommendation import SEORecommendation  # noqa: F401
from app.models.seo_recommendation_narrative import SEORecommendationNarrative  # noqa: F401
from app.models.seo_recommendation_run import SEORecommendationRun  # noqa: F401
from app.models.seo_site import SEOSite  # noqa: F401

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")


@pytest.fixture(autouse=True)
def enforce_test_app_env() -> None:
    if "APP_ENV" not in os.environ:
        os.environ["APP_ENV"] = "test"


@pytest.fixture(autouse=True)
def _default_database_url_for_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_rate_limiter_state() -> None:
    get_rate_limiter().clear()


@pytest.fixture(autouse=True)
def _reset_session_state_store() -> None:
    get_session_state_store().clear()


@pytest.fixture()
def seeded_business(db_session: Session) -> Business:
    business = Business(
        id="11111111-1111-1111-1111-111111111111",
        name="T&M Fire",
        primary_phone="+13035550100",
        notification_phone="+13035550101",
        notification_email="owner@tmfire.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
    )
    db_session.add(business)
    db_session.commit()
    return business


@pytest.fixture()
def sample_lead(db_session: Session, seeded_business: Business) -> Lead:
    lead = Lead(
        id=str(uuid4()),
        business_id=seeded_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=20),
        customer_name="Casey Jones",
        phone="3035550109",
        email="casey@example.com",
        service_type="fire restoration",
        city="Denver",
        message="Need estimate",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()
    db_session.refresh(lead)
    return lead
