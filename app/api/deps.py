from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
import logging

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import InMemoryRateLimiter, get_rate_limiter
from app.db.session import get_db_session
from app.integrations import (
    DevEmailProvider,
    DevSMSProvider,
    EmailProvider,
    MockSEOCompetitorComparisonSummaryProvider,
    MockSEOAuditSummaryProvider,
    MockEmailProvider,
    MockSMSProvider,
    SEOCompetitorComparisonSummaryProvider,
    SEOAuditSummaryProvider,
    SMTPEmailProvider,
    SMSProvider,
    TwilioSMSProvider,
)
from app.jobs.lead_reminders import LeadReminderJob
from app.models.principal import Principal, PrincipalRole
from app.repositories.api_credential_repository import APICredentialRepository
from app.repositories.auth_audit_repository import AuthAuditRepository
from app.repositories.business_repository import BusinessRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.principal_repository import PrincipalRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_audit_summary_repository import SEOAuditSummaryRepository
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_competitor_summary_repository import SEOCompetitorSummaryRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.business_settings import BusinessSettingsService
from app.services.api_credentials import APICredentialService
from app.services.auth_audit import AuthAuditService
from app.services.dedupe import LeadDeduplicationService
from app.services.email_intake import EmailIntakeService
from app.services.lead_intake import LeadIntakeService
from app.services.lifecycle import LeadLifecycleService
from app.services.notifications import NotificationDispatchService
from app.services.parser import LeadParserService
from app.services.principals import PrincipalService
from app.services.reminder_engine import ReminderEngineService
from app.services.response_metrics import ResponseMetricsService
from app.services.seo_audit import SEOAuditService
from app.services.seo_competitor_comparison import SEOCompetitorComparisonService
from app.services.seo_competitors import SEOCompetitorService
from app.services.seo_competitor_summary import SEOCompetitorSummaryService
from app.services.seo_crawler import SEOCrawler
from app.services.seo_extractor import SEOExtractor
from app.services.seo_finding_rules import SEOFindingRules
from app.services.seo_sites import SEOSiteService
from app.services.seo_summary import SEOSummaryService
from app.services.summary import LeadSummaryService
from app.services.timeline import LeadTimelineService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantContext:
    business_id: str
    principal_id: str
    auth_source: str


def get_db() -> Generator[Session, None, None]:
    yield from get_db_session()


def get_business_repository(db: Session = Depends(get_db)) -> BusinessRepository:
    return BusinessRepository(db)


def get_lead_repository(db: Session = Depends(get_db)) -> LeadRepository:
    return LeadRepository(db)


def get_api_credential_repository(
    db: Session = Depends(get_db),
) -> APICredentialRepository:
    settings = get_settings()
    return APICredentialRepository(
        db,
        token_hash_pepper=settings.api_token_hash_pepper,
        allow_legacy_hash_fallback=settings.allow_legacy_token_hash_fallback,
    )


def get_auth_audit_repository(db: Session = Depends(get_db)) -> AuthAuditRepository:
    return AuthAuditRepository(db)


def get_principal_repository(db: Session = Depends(get_db)) -> PrincipalRepository:
    return PrincipalRepository(db)


def get_seo_site_repository(db: Session = Depends(get_db)) -> SEOSiteRepository:
    return SEOSiteRepository(db)


def get_seo_audit_repository(db: Session = Depends(get_db)) -> SEOAuditRepository:
    return SEOAuditRepository(db)


def get_seo_audit_summary_repository(db: Session = Depends(get_db)) -> SEOAuditSummaryRepository:
    return SEOAuditSummaryRepository(db)


def get_seo_competitor_repository(db: Session = Depends(get_db)) -> SEOCompetitorRepository:
    return SEOCompetitorRepository(db)


def get_seo_competitor_summary_repository(db: Session = Depends(get_db)) -> SEOCompetitorSummaryRepository:
    return SEOCompetitorSummaryRepository(db)


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


def get_seo_site_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    seo_site_repository: SEOSiteRepository = Depends(get_seo_site_repository),
) -> SEOSiteService:
    return SEOSiteService(
        session=db,
        business_repository=business_repository,
        seo_site_repository=seo_site_repository,
    )


def get_seo_crawler() -> SEOCrawler:
    return SEOCrawler()


def get_seo_extractor() -> SEOExtractor:
    return SEOExtractor()


def get_seo_finding_rules() -> SEOFindingRules:
    return SEOFindingRules()


def get_seo_audit_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    seo_site_repository: SEOSiteRepository = Depends(get_seo_site_repository),
    seo_audit_repository: SEOAuditRepository = Depends(get_seo_audit_repository),
    crawler: SEOCrawler = Depends(get_seo_crawler),
    extractor: SEOExtractor = Depends(get_seo_extractor),
    finding_rules: SEOFindingRules = Depends(get_seo_finding_rules),
) -> SEOAuditService:
    return SEOAuditService(
        session=db,
        business_repository=business_repository,
        seo_site_repository=seo_site_repository,
        seo_audit_repository=seo_audit_repository,
        crawler=crawler,
        extractor=extractor,
        finding_rules=finding_rules,
    )


def get_seo_summary_provider() -> SEOAuditSummaryProvider:
    return MockSEOAuditSummaryProvider()


def get_seo_competitor_summary_provider() -> SEOCompetitorComparisonSummaryProvider:
    return MockSEOCompetitorComparisonSummaryProvider()


def get_seo_summary_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    seo_audit_repository: SEOAuditRepository = Depends(get_seo_audit_repository),
    seo_audit_summary_repository: SEOAuditSummaryRepository = Depends(get_seo_audit_summary_repository),
    provider: SEOAuditSummaryProvider = Depends(get_seo_summary_provider),
) -> SEOSummaryService:
    return SEOSummaryService(
        session=db,
        business_repository=business_repository,
        seo_audit_repository=seo_audit_repository,
        seo_audit_summary_repository=seo_audit_summary_repository,
        provider=provider,
    )


def get_seo_competitor_summary_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    seo_competitor_repository: SEOCompetitorRepository = Depends(get_seo_competitor_repository),
    seo_competitor_summary_repository: SEOCompetitorSummaryRepository = Depends(get_seo_competitor_summary_repository),
    provider: SEOCompetitorComparisonSummaryProvider = Depends(get_seo_competitor_summary_provider),
) -> SEOCompetitorSummaryService:
    return SEOCompetitorSummaryService(
        session=db,
        business_repository=business_repository,
        seo_competitor_repository=seo_competitor_repository,
        seo_competitor_summary_repository=seo_competitor_summary_repository,
        provider=provider,
    )


def get_seo_competitor_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    seo_site_repository: SEOSiteRepository = Depends(get_seo_site_repository),
    seo_competitor_repository: SEOCompetitorRepository = Depends(get_seo_competitor_repository),
) -> SEOCompetitorService:
    return SEOCompetitorService(
        session=db,
        business_repository=business_repository,
        seo_site_repository=seo_site_repository,
        seo_competitor_repository=seo_competitor_repository,
    )


def get_seo_competitor_comparison_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    seo_audit_repository: SEOAuditRepository = Depends(get_seo_audit_repository),
    seo_competitor_repository: SEOCompetitorRepository = Depends(get_seo_competitor_repository),
) -> SEOCompetitorComparisonService:
    return SEOCompetitorComparisonService(
        session=db,
        business_repository=business_repository,
        seo_audit_repository=seo_audit_repository,
        seo_competitor_repository=seo_competitor_repository,
    )


def get_auth_audit_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    auth_audit_repository: AuthAuditRepository = Depends(get_auth_audit_repository),
) -> AuthAuditService:
    return AuthAuditService(
        session=db,
        business_repository=business_repository,
        auth_audit_repository=auth_audit_repository,
    )


def get_api_credential_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    principal_repository: PrincipalRepository = Depends(get_principal_repository),
    api_credential_repository: APICredentialRepository = Depends(get_api_credential_repository),
    auth_audit_service: AuthAuditService = Depends(get_auth_audit_service),
) -> APICredentialService:
    return APICredentialService(
        session=db,
        business_repository=business_repository,
        principal_repository=principal_repository,
        api_credential_repository=api_credential_repository,
        auth_audit_service=auth_audit_service,
    )


def get_principal_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    principal_repository: PrincipalRepository = Depends(get_principal_repository),
    auth_audit_service: AuthAuditService = Depends(get_auth_audit_service),
) -> PrincipalService:
    return PrincipalService(
        session=db,
        business_repository=business_repository,
        principal_repository=principal_repository,
        auth_audit_service=auth_audit_service,
    )


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _raise_rate_limit(*, category: str, retry_after_seconds: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded. Retry later.",
        headers={"Retry-After": str(retry_after_seconds), "X-RateLimit-Category": category},
    )


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


def get_tenant_context(
    request: Request,
    authorization: str | None = Header(default=None),
    api_credential_repository: APICredentialRepository = Depends(get_api_credential_repository),
    principal_repository: PrincipalRepository = Depends(get_principal_repository),
    rate_limiter: InMemoryRateLimiter = Depends(get_rate_limiter),
) -> TenantContext:
    """Resolve tenant scope from server-side auth context (not request business_id fields)."""
    settings = get_settings()
    token = _parse_bearer_token(authorization)

    if token is not None:
        if settings.rate_limit_enabled:
            ip = _client_ip(request)
            decision = rate_limiter.check(
                key=f"auth:{ip}",
                limit=settings.auth_rate_limit_requests,
                window_seconds=settings.auth_rate_limit_window_seconds,
            )
            if not decision.allowed:
                logger.warning(
                    "Auth rate limit exceeded client_ip=%s retry_after=%s",
                    ip,
                    decision.retry_after_seconds,
                )
                _raise_rate_limit(category="auth", retry_after_seconds=decision.retry_after_seconds)

        db_credential = api_credential_repository.get_active_by_token(token)
        if db_credential is not None:
            try:
                api_credential_repository.mark_last_used(db_credential)
                principal_repository.mark_last_authenticated(
                    business_id=db_credential.business_id,
                    principal_id=db_credential.principal_id,
                )
                api_credential_repository.session.commit()
            except Exception:  # noqa: BLE001
                api_credential_repository.session.rollback()
                logger.warning(
                    "Failed to persist auth usage metadata for credential_id=%s principal_id=%s.",
                    db_credential.id,
                    db_credential.principal_id,
                )
            return TenantContext(
                business_id=db_credential.business_id,
                principal_id=db_credential.principal_id,
                auth_source="db_api_credential",
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
        )

    # Dev/test fallback only: keep local workflows operational without auth setup.
    if settings.environment.strip().lower() not in {"development", "dev", "test"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
        )

    return TenantContext(
        business_id=settings.default_business_id,
        principal_id="dev-default-principal",
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


def get_authenticated_principal(
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_repository: PrincipalRepository = Depends(get_principal_repository),
) -> Principal:
    principal = principal_repository.get_for_business(
        tenant_context.business_id,
        tenant_context.principal_id,
    )
    if principal is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Principal not found")
    if not principal.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Principal is inactive")
    return principal


def require_credential_manager_principal(
    principal: Principal = Depends(get_authenticated_principal),
) -> Principal:
    if principal.role != PrincipalRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal is not allowed to manage credentials.",
        )
    return principal


def require_admin_rate_limit(action: str):
    def _enforce(
        request: Request,
        tenant_context: TenantContext = Depends(get_tenant_context),
        principal: Principal = Depends(get_authenticated_principal),
        rate_limiter: InMemoryRateLimiter = Depends(get_rate_limiter),
    ) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return

        ip = _client_ip(request)
        key = f"admin:{action}:{tenant_context.business_id}:{principal.id}:{ip}"
        decision = rate_limiter.check(
            key=key,
            limit=settings.admin_rate_limit_requests,
            window_seconds=settings.admin_rate_limit_window_seconds,
        )
        if decision.allowed:
            return

        logger.warning(
            "Admin rate limit exceeded action=%s business_id=%s principal_id=%s client_ip=%s retry_after=%s",
            action,
            tenant_context.business_id,
            principal.id,
            ip,
            decision.retry_after_seconds,
        )
        _raise_rate_limit(category=f"admin:{action}", retry_after_seconds=decision.retry_after_seconds)

    return _enforce
