from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
import hashlib
import logging

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.core.session_state import get_session_state_store
from app.core.session_token import AppSessionTokenError, AppSessionTokenService
from app.db.session import get_db_session
from app.integrations import (
    DevEmailProvider,
    DevSMSProvider,
    EmailProvider,
    MockSEOCompetitorComparisonSummaryProvider,
    MockSEORecommendationNarrativeProvider,
    MockSEOAuditSummaryProvider,
    MockEmailProvider,
    MockSMSProvider,
    SEORecommendationNarrativeProvider,
    SEOCompetitorComparisonSummaryProvider,
    SEOAuditSummaryProvider,
    GoogleOIDCJWKSVerifier,
    SMTPEmailProvider,
    SMSProvider,
    TwilioSMSProvider,
)
from app.jobs.lead_reminders import LeadReminderJob
from app.jobs.seo_automation import SEOAutomationJob
from app.models.principal import Principal, PrincipalRole
from app.repositories.api_credential_repository import APICredentialRepository
from app.repositories.auth_audit_repository import AuthAuditRepository
from app.repositories.business_repository import BusinessRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.principal_identity_repository import PrincipalIdentityRepository
from app.repositories.principal_repository import PrincipalRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_audit_summary_repository import SEOAuditSummaryRepository
from app.repositories.seo_automation_repository import SEOAutomationRepository
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_competitor_summary_repository import SEOCompetitorSummaryRepository
from app.repositories.seo_recommendation_narrative_repository import SEORecommendationNarrativeRepository
from app.repositories.seo_recommendation_repository import SEORecommendationRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.business_settings import BusinessSettingsService
from app.services.api_credentials import APICredentialService
from app.services.auth_identity import AuthIdentityService
from app.services.auth_audit import AuthAuditService
from app.services.dedupe import LeadDeduplicationService
from app.services.email_intake import EmailIntakeService
from app.services.lead_intake import LeadIntakeService
from app.services.lifecycle import LeadLifecycleService
from app.services.notifications import NotificationDispatchService
from app.services.parser import LeadParserService
from app.services.principal_identities import PrincipalIdentityService
from app.services.principals import PrincipalService
from app.services.reminder_engine import ReminderEngineService
from app.services.response_metrics import ResponseMetricsService
from app.services.seo_audit import SEOAuditService
from app.services.seo_automation import SEOAutomationService
from app.services.seo_competitor_comparison import SEOCompetitorComparisonService
from app.services.seo_competitors import SEOCompetitorService
from app.services.seo_competitor_summary import SEOCompetitorSummaryService
from app.services.seo_crawler import SEOCrawler
from app.services.seo_extractor import SEOExtractor
from app.services.seo_finding_rules import SEOFindingRules
from app.services.seo_recommendation_narratives import SEORecommendationNarrativeService
from app.services.seo_recommendations import SEORecommendationService
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
    principal_role: PrincipalRole | None = None


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


def get_principal_identity_repository(db: Session = Depends(get_db)) -> PrincipalIdentityRepository:
    return PrincipalIdentityRepository(db)


def get_seo_site_repository(db: Session = Depends(get_db)) -> SEOSiteRepository:
    return SEOSiteRepository(db)


def get_seo_audit_repository(db: Session = Depends(get_db)) -> SEOAuditRepository:
    return SEOAuditRepository(db)


def get_seo_audit_summary_repository(db: Session = Depends(get_db)) -> SEOAuditSummaryRepository:
    return SEOAuditSummaryRepository(db)


def get_seo_automation_repository(db: Session = Depends(get_db)) -> SEOAutomationRepository:
    return SEOAutomationRepository(db)


def get_seo_competitor_repository(db: Session = Depends(get_db)) -> SEOCompetitorRepository:
    return SEOCompetitorRepository(db)


def get_seo_competitor_summary_repository(db: Session = Depends(get_db)) -> SEOCompetitorSummaryRepository:
    return SEOCompetitorSummaryRepository(db)


def get_seo_recommendation_repository(db: Session = Depends(get_db)) -> SEORecommendationRepository:
    return SEORecommendationRepository(db)


def get_seo_recommendation_narrative_repository(
    db: Session = Depends(get_db),
) -> SEORecommendationNarrativeRepository:
    return SEORecommendationNarrativeRepository(db)


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


def get_seo_recommendation_narrative_provider() -> SEORecommendationNarrativeProvider:
    return MockSEORecommendationNarrativeProvider()


def get_google_oidc_verifier() -> GoogleOIDCJWKSVerifier:
    settings = get_settings()
    client_id = (settings.google_oidc_client_id or "").strip()
    if not settings.google_auth_enabled or not client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google authentication is not configured.",
        )
    return GoogleOIDCJWKSVerifier(
        client_id=client_id,
        jwks_url=settings.google_oidc_jwks_url,
        allowed_issuers=settings.google_oidc_allowed_issuers,
        require_email_verified=settings.google_oidc_require_email_verified,
        timeout_seconds=settings.google_oidc_timeout_seconds,
    )


def get_session_token_service() -> AppSessionTokenService | None:
    settings = get_settings()
    secret = (settings.app_session_secret or "").strip()
    if not secret:
        return None
    return AppSessionTokenService(
        secret=secret,
        issuer=settings.app_session_issuer,
        audience=settings.app_session_audience,
        algorithm=settings.app_session_algorithm,
        access_ttl_seconds=settings.app_session_ttl_seconds,
        refresh_ttl_seconds=settings.app_session_refresh_ttl_seconds,
        state_store=get_session_state_store(),
    )


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


def get_seo_recommendation_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    principal_repository: PrincipalRepository = Depends(get_principal_repository),
    seo_site_repository: SEOSiteRepository = Depends(get_seo_site_repository),
    seo_audit_repository: SEOAuditRepository = Depends(get_seo_audit_repository),
    seo_competitor_repository: SEOCompetitorRepository = Depends(get_seo_competitor_repository),
    seo_recommendation_repository: SEORecommendationRepository = Depends(get_seo_recommendation_repository),
) -> SEORecommendationService:
    return SEORecommendationService(
        session=db,
        business_repository=business_repository,
        principal_repository=principal_repository,
        seo_site_repository=seo_site_repository,
        seo_audit_repository=seo_audit_repository,
        seo_competitor_repository=seo_competitor_repository,
        seo_recommendation_repository=seo_recommendation_repository,
    )


def get_seo_recommendation_narrative_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    seo_recommendation_repository: SEORecommendationRepository = Depends(get_seo_recommendation_repository),
    seo_recommendation_narrative_repository: SEORecommendationNarrativeRepository = Depends(
        get_seo_recommendation_narrative_repository
    ),
    provider: SEORecommendationNarrativeProvider = Depends(get_seo_recommendation_narrative_provider),
) -> SEORecommendationNarrativeService:
    return SEORecommendationNarrativeService(
        session=db,
        business_repository=business_repository,
        seo_recommendation_repository=seo_recommendation_repository,
        seo_recommendation_narrative_repository=seo_recommendation_narrative_repository,
        provider=provider,
    )


def get_seo_automation_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    seo_site_repository: SEOSiteRepository = Depends(get_seo_site_repository),
    seo_automation_repository: SEOAutomationRepository = Depends(get_seo_automation_repository),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
    seo_summary_service: SEOSummaryService = Depends(get_seo_summary_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
    seo_competitor_comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
    seo_competitor_summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
    seo_recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
    seo_recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEOAutomationService:
    return SEOAutomationService(
        session=db,
        business_repository=business_repository,
        seo_site_repository=seo_site_repository,
        seo_automation_repository=seo_automation_repository,
        seo_audit_service=seo_audit_service,
        seo_summary_service=seo_summary_service,
        seo_competitor_service=seo_competitor_service,
        seo_competitor_comparison_service=seo_competitor_comparison_service,
        seo_competitor_summary_service=seo_competitor_summary_service,
        seo_recommendation_service=seo_recommendation_service,
        seo_recommendation_narrative_service=seo_recommendation_narrative_service,
    )


def get_seo_automation_job(
    seo_automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationJob:
    return SEOAutomationJob(automation_service=seo_automation_service)


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
    session_token_service: AppSessionTokenService | None = Depends(get_session_token_service),
) -> PrincipalService:
    return PrincipalService(
        session=db,
        business_repository=business_repository,
        principal_repository=principal_repository,
        auth_audit_service=auth_audit_service,
        session_token_service=session_token_service,
    )


def get_principal_identity_service(
    db: Session = Depends(get_db),
    business_repository: BusinessRepository = Depends(get_business_repository),
    principal_repository: PrincipalRepository = Depends(get_principal_repository),
    principal_identity_repository: PrincipalIdentityRepository = Depends(get_principal_identity_repository),
    auth_audit_service: AuthAuditService = Depends(get_auth_audit_service),
    session_token_service: AppSessionTokenService | None = Depends(get_session_token_service),
) -> PrincipalIdentityService:
    return PrincipalIdentityService(
        session=db,
        business_repository=business_repository,
        principal_repository=principal_repository,
        principal_identity_repository=principal_identity_repository,
        auth_audit_service=auth_audit_service,
        session_token_service=session_token_service,
    )


def get_auth_identity_service(
    db: Session = Depends(get_db),
    principal_repository: PrincipalRepository = Depends(get_principal_repository),
    principal_identity_repository: PrincipalIdentityRepository = Depends(get_principal_identity_repository),
    oidc_verifier: GoogleOIDCJWKSVerifier = Depends(get_google_oidc_verifier),
    session_token_service: AppSessionTokenService | None = Depends(get_session_token_service),
    auth_audit_service: AuthAuditService = Depends(get_auth_audit_service),
) -> AuthIdentityService:
    if session_token_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application session token configuration is missing.",
        )
    return AuthIdentityService(
        session=db,
        principal_repository=principal_repository,
        principal_identity_repository=principal_identity_repository,
        oidc_verifier=oidc_verifier,
        session_token_service=session_token_service,
        auth_audit_service=auth_audit_service,
    )


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _normalized_user_agent(request: Request) -> str:
    raw = (request.headers.get("User-Agent") or "unknown").strip().lower()
    if not raw:
        raw = "unknown"
    # Keep cardinality bounded while still bucketing distinct clients.
    return raw[:256]


def _bucket_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _raise_rate_limit(*, category: str, retry_after_seconds: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded. Retry later.",
        headers={"Retry-After": str(retry_after_seconds), "X-RateLimit-Category": category},
    )


def _log_auth_failure(
    *,
    request: Request,
    reason: str,
    auth_kind: str,
) -> None:
    logger.warning(
        "auth_failure reason=%s auth_kind=%s client_ip=%s user_agent_bucket=%s",
        reason,
        auth_kind,
        _client_ip(request),
        _bucket_hash(_normalized_user_agent(request)),
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
    principal_identity_repository: PrincipalIdentityRepository = Depends(get_principal_identity_repository),
    session_token_service: AppSessionTokenService | None = Depends(get_session_token_service),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> TenantContext:
    """Resolve tenant scope from server-side auth context (not request business_id fields)."""
    settings = get_settings()
    token = _parse_bearer_token(authorization)

    if token is not None:
        if settings.rate_limit_enabled:
            ip = _client_ip(request)
            ua_bucket = _bucket_hash(_normalized_user_agent(request))
            decision = rate_limiter.check(
                key=f"auth:bearer:{ip}:{ua_bucket}",
                limit=settings.auth_rate_limit_requests,
                window_seconds=settings.auth_rate_limit_window_seconds,
            )
            if not decision.allowed:
                logger.warning(
                    "auth_rate_limit_denied category=auth client_ip=%s user_agent_bucket=%s retry_after=%s",
                    ip,
                    ua_bucket,
                    decision.retry_after_seconds,
                )
                _raise_rate_limit(category="auth", retry_after_seconds=decision.retry_after_seconds)

        if token.count(".") == 2:
            if session_token_service is None:
                _log_auth_failure(request=request, reason="session_service_unavailable", auth_kind="jwt")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.")
            try:
                claims = session_token_service.verify_access_token(token)
            except AppSessionTokenError as exc:
                _log_auth_failure(request=request, reason="invalid_access_token", auth_kind="jwt")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.") from exc

            principal = principal_repository.get_for_business(claims.business_id, claims.principal_id)
            if principal is None or not principal.is_active:
                _log_auth_failure(request=request, reason="principal_not_active_or_missing", auth_kind="jwt")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.")
            if claims.principal_identity_id:
                identity = principal_identity_repository.get_for_business(
                    business_id=claims.business_id,
                    identity_id=claims.principal_identity_id,
                )
                if identity is None or not identity.is_active:
                    _log_auth_failure(request=request, reason="identity_not_active_or_missing", auth_kind="jwt")
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.")
            return TenantContext(
                business_id=claims.business_id,
                principal_id=claims.principal_id,
                auth_source=claims.auth_source,
                principal_role=principal.role,
            )

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
                principal_role=db_credential.principal_role,
            )

        _log_auth_failure(request=request, reason="credential_not_found_or_inactive", auth_kind="api_credential")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
        )

    # Dev/test fallback only: keep local workflows operational without auth setup.
    if settings.environment.strip().lower() not in {"development", "dev", "test"}:
        _log_auth_failure(request=request, reason="missing_bearer_token", auth_kind="none")
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
        rate_limiter: RateLimiter = Depends(get_rate_limiter),
        auth_audit_service: AuthAuditService = Depends(get_auth_audit_service),
    ) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return

        ip = _client_ip(request)
        ua_bucket = _bucket_hash(_normalized_user_agent(request))
        key = f"admin:{action}:{tenant_context.business_id}:{principal.id}:{ip}:{ua_bucket}"
        decision = rate_limiter.check(
            key=key,
            limit=settings.admin_rate_limit_requests,
            window_seconds=settings.admin_rate_limit_window_seconds,
        )
        if decision.allowed:
            return

        logger.warning(
            (
                "admin_rate_limit_denied action=%s business_id=%s principal_id=%s "
                "client_ip=%s user_agent_bucket=%s retry_after=%s"
            ),
            action,
            tenant_context.business_id,
            principal.id,
            ip,
            ua_bucket,
            decision.retry_after_seconds,
        )
        try:
            auth_audit_service.record_event(
                business_id=tenant_context.business_id,
                actor_principal_id=principal.id,
                target_type="rate_limit",
                target_id=f"admin:{action}",
                event_type="admin_rate_limit_denied",
                details={
                    "action": action,
                    "client_ip": ip,
                    "user_agent_bucket": ua_bucket,
                    "retry_after_seconds": decision.retry_after_seconds,
                },
            )
            auth_audit_service.session.commit()
        except Exception:  # noqa: BLE001
            auth_audit_service.session.rollback()
            logger.warning(
                "Failed to persist admin rate-limit audit event for business_id=%s principal_id=%s action=%s",
                tenant_context.business_id,
                principal.id,
                action,
            )
        _raise_rate_limit(category=f"admin:{action}", retry_after_seconds=decision.retry_after_seconds)

    return _enforce
