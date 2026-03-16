from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.business import Business
from app.models.seo_site import SEOSite


def _seed_business(db_session, *, name: str) -> Business:
    business = Business(
        id=str(uuid4()),
        name=name,
        notification_phone="+13035550199",
        notification_email=f"{name.lower().replace(' ', '-')}@example.com",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    db_session.add(business)
    db_session.flush()
    return business


def test_seo_site_domain_is_unique_within_business(db_session, seeded_business) -> None:
    db_session.add(
        SEOSite(
            id=str(uuid4()),
            business_id=seeded_business.id,
            display_name="Primary",
            base_url="https://example.com/",
            normalized_domain="example.com",
            is_active=True,
            is_primary=True,
        )
    )
    db_session.flush()

    db_session.add(
        SEOSite(
            id=str(uuid4()),
            business_id=seeded_business.id,
            display_name="Duplicate Domain",
            base_url="https://example.com/services",
            normalized_domain="example.com",
            is_active=True,
            is_primary=False,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_seo_site_domain_can_repeat_across_businesses(db_session, seeded_business) -> None:
    other_business = _seed_business(db_session, name="Other Tenant")

    db_session.add(
        SEOSite(
            id=str(uuid4()),
            business_id=seeded_business.id,
            display_name="Tenant A",
            base_url="https://example.com/",
            normalized_domain="example.com",
            is_active=True,
            is_primary=True,
        )
    )
    db_session.add(
        SEOSite(
            id=str(uuid4()),
            business_id=other_business.id,
            display_name="Tenant B",
            base_url="https://example.com/",
            normalized_domain="example.com",
            is_active=True,
            is_primary=True,
        )
    )
    db_session.flush()


def test_seo_site_only_one_primary_per_business(db_session, seeded_business) -> None:
    db_session.add_all(
        [
            SEOSite(
                id=str(uuid4()),
                business_id=seeded_business.id,
                display_name="Primary A",
                base_url="https://a.example.com/",
                normalized_domain="a.example.com",
                is_active=True,
                is_primary=True,
            ),
            SEOSite(
                id=str(uuid4()),
                business_id=seeded_business.id,
                display_name="Primary B",
                base_url="https://b.example.com/",
                normalized_domain="b.example.com",
                is_active=True,
                is_primary=True,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
