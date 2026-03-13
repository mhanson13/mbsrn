from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.integrations import (
    DevEmailProvider,
    DevSMSProvider,
    EmailProvider,
    MockEmailProvider,
    MockSMSProvider,
    SMTPEmailProvider,
    SMSProvider,
    TwilioSMSProvider,
)
from app.jobs.lead_reminders import LeadReminderJob
from app.repositories.business_repository import BusinessRepository
from app.repositories.lead_repository import LeadRepository
from app.services.business_settings import BusinessSettingsService
from app.services.dedupe import LeadDeduplicationService
from app.services.email_intake import EmailIntakeService
from app.services.lead_intake import LeadIntakeService
from app.services.lifecycle import LeadLifecycleService
from app.services.notifications import NotificationDispatchService
from app.services.parser import LeadParserService
from app.services.reminder_engine import ReminderEngineService
from app.services.response_metrics import ResponseMetricsService
from app.services.summary import LeadSummaryService
from app.services.timeline import LeadTimelineService


@dataclass(frozen=True)
class TenantContext:
    business_id: str
    auth_source: str


def get_db() -> Generator[Session, None, None]:
    yield from get_db_session()


def get_business_repository(db: Session = Depends(get_db)) -> BusinessRepository:
    return BusinessRepository(db)


def get_lead_repository(db: Session = Depends(get_db)) -> LeadRepository:
    return LeadRepository(db)


def get_parser_service() -> LeadParserService:
    return LeadParserService()


def get_deduplication_service(
    lead_repository: LeadRepository = Depends(get_lead_repository),
) -> LeadDeduplicationService:
    return LeadDeduplicationService(lead_repository=lead_repository)


def get_sms_provider() -> SMSProvider:
    settings = get_settings()
    provider = settings.sms_provider
    if provider == "twilio":
        if settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number:
            return TwilioSMSProvider(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token,
                from_number=settings.twilio_from_number,
                timeout_seconds=settings.notification_timeout_seconds,
            )
        return DevSMSProvider()
    if provider == "dev":
        return DevSMSProvider()
    return MockSMSProvider()


def get_email_provider() -> EmailProvider:
    settings = get_settings()
    provider = settings.email_provider
    if provider == "smtp":
        if settings.smtp_host and settings.smtp_from_address:
            return SMTPEmailProvider(
                host=settings.smtp_host,
                port=settings.smtp_port,
                from_address=settings.smtp_from_address,
                username=settings.smtp_username,
                password=settings.smtp_password,
                use_tls=settings.smtp_use_tls,
                timeout_seconds=settings.notification_timeout_seconds,
            )
        return DevEmailProvider()
    if provider == "dev":
        return DevEmailProvider()
    return MockEmailProvider()


def get_notification_service(
    lead_repository: LeadRepository = Depends(get_lead_repository),
    email_provider: EmailProvider = Depends(get_email_provider),
    sms_provider: SMSProvider = Depends(get_sms_provider),
) -> NotificationDispatchService:
    return NotificationDispatchService(
        lead_repository=lead_repository,
        email_provider=email_provider,
        sms_provider=sms_provider,
    )


def get_lead_intake_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    lead_repository: LeadRepository = Depends(get_lead_repository),
) -> LeadIntakeService:
    return LeadIntakeService(
        session=db,
        business_repository=business_repository,
        lead_repository=lead_repository,
    )


def get_email_intake_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    lead_repository: LeadRepository = Depends(get_lead_repository),
    parser_service: LeadParserService = Depends(get_parser_service),
    dedupe_service: LeadDeduplicationService = Depends(get_deduplication_service),
    notification_service: NotificationDispatchService = Depends(get_notification_service),
) -> EmailIntakeService:
    return EmailIntakeService(
        session=db,
        business_repository=business_repository,
        lead_repository=lead_repository,
        parser_service=parser_service,
        dedupe_service=dedupe_service,
        notification_service=notification_service,
    )


def get_lifecycle_service(
    db: Session = Depends(get_db),
    lead_repository: LeadRepository = Depends(get_lead_repository),
) -> LeadLifecycleService:
    return LeadLifecycleService(session=db, lead_repository=lead_repository)


def get_response_metrics_service(
    lead_repository: LeadRepository = Depends(get_lead_repository),
) -> ResponseMetricsService:
    return ResponseMetricsService(lead_repository=lead_repository)


def get_summary_service(
    lead_repository: LeadRepository = Depends(get_lead_repository),
    response_metrics_service: ResponseMetricsService = Depends(get_response_metrics_service),
) -> LeadSummaryService:
    return LeadSummaryService(
        lead_repository=lead_repository,
        response_metrics_service=response_metrics_service,
    )


def get_timeline_service(
    lead_repository: LeadRepository = Depends(get_lead_repository),
) -> LeadTimelineService:
    return LeadTimelineService(lead_repository=lead_repository)


def get_reminder_engine_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    lead_repository: LeadRepository = Depends(get_lead_repository),
    notification_service: NotificationDispatchService = Depends(get_notification_service),
) -> ReminderEngineService:
    return ReminderEngineService(
        session=db,
        business_repository=business_repository,
        lead_repository=lead_repository,
        notification_service=notification_service,
    )


def get_lead_reminder_job(
    reminder_engine_service: ReminderEngineService = Depends(get_reminder_engine_service),
) -> LeadReminderJob:
    return LeadReminderJob(reminder_engine=reminder_engine_service)


def get_business_settings_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
) -> BusinessSettingsService:
    return BusinessSettingsService(session=db, business_repository=business_repository)


def _parse_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>.",
        )
    return token.strip()


def get_tenant_context(authorization: str | None = Header(default=None)) -> TenantContext:
    """Resolve tenant scope from server-side auth context (not request business_id fields)."""
    settings = get_settings()

    # Incremental auth mode: when API_AUTH_TOKEN is configured, require Bearer auth
    # and derive tenant scope from server-side settings.
    if settings.api_auth_token:
        token = _parse_bearer_token(authorization)
        if token is None or not secrets.compare_digest(token, settings.api_auth_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized.",
            )
        return TenantContext(
            business_id=settings.api_auth_business_id or settings.default_business_id,
            auth_source="api_token",
        )

    # Local/dev fallback: single-tenant scope from server config only.
    return TenantContext(
        business_id=settings.default_business_id,
        auth_source="default_business",
    )


def resolve_tenant_business_id(
    *,
    tenant_context: TenantContext,
    requested_business_id: str | None,
) -> str:
    if requested_business_id and requested_business_id != tenant_context.business_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    return tenant_context.business_id
