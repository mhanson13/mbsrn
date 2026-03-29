from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlparse

_LOCALHOST_ALLOWED_APP_ENVS = {"local", "development", "dev", "test", "ci"}
_PRODUCTION_LOCALHOST_ALLOWED_DB_CONNECTION_MODES = {"cloudsql_proxy"}
_LOCALHOST_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}
_LOCAL_DATABASE_URL_FALLBACK = "postgresql+psycopg://postgres:postgres@localhost:5432/mbsrn"


@dataclass(frozen=True)
class _AIPromptResolution:
    prompt_text: str
    prompt_source: str
    legacy_config_used: bool


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    environment: str
    db_connection_mode: str
    database_url: str
    db_auto_create_local: bool
    google_auth_enabled: bool
    google_oidc_client_id: str | None
    google_oidc_jwks_url: str
    google_oidc_allowed_issuers: tuple[str, ...]
    google_oidc_require_email_verified: bool
    google_oidc_timeout_seconds: int
    google_oauth_client_id: str | None
    google_oauth_client_secret: str | None
    google_oauth_authorization_url: str
    google_oauth_token_url: str
    google_oauth_revoke_url: str
    google_oauth_timeout_seconds: int
    google_business_profile_redirect_uri: str | None
    google_business_profile_state_ttl_seconds: int
    google_business_profile_account_api_base_url: str
    google_business_profile_business_information_api_base_url: str
    google_business_profile_verifications_api_base_url: str
    google_business_profile_api_timeout_seconds: int
    google_places_api_key: str | None
    google_places_api_base_url: str
    google_places_api_timeout_seconds: int
    google_places_seed_max_candidates: int
    google_places_seed_query_limit: int
    gcp_logging_project_id: str | None
    gcp_logging_api_timeout_seconds: int
    google_oauth_token_encryption_secret: str | None
    google_oauth_token_encryption_key_version: str
    google_oauth_token_encryption_keys: dict[str, str]
    google_oauth_refresh_skew_seconds: int
    app_session_secret: str | None
    app_session_issuer: str
    app_session_audience: str
    app_session_algorithm: str
    app_session_ttl_seconds: int
    app_session_refresh_ttl_seconds: int
    api_token_hash_pepper: str | None
    allow_legacy_token_hash_fallback: bool
    redis_url: str | None
    session_state_backend: str
    session_state_fail_open: bool
    session_state_allow_inmemory_fallback: bool
    sms_provider: str
    email_provider: str
    ai_provider_api_key: str | None = field(repr=False)
    ai_provider_name: str
    ai_model_name: str
    ai_timeout_value: int
    ai_prompt_text_competitor: str
    ai_prompt_text_competitor_source: str
    ai_prompt_text_competitor_legacy_config_used: bool
    ai_prompt_text_recommendations: str
    ai_prompt_text_recommendations_source: str
    ai_prompt_text_recommendations_legacy_config_used: bool
    ai_eval_allow_real_provider: bool
    # DEPRECATED: DO NOT USE - replaced by AI_PROMPT_TEXT_COMPETITOR and AI_PROMPT_TEXT_RECOMMENDATIONS.
    ai_prompt_text_recommendation: str
    seo_competitor_profile_raw_output_retention_days: int
    seo_competitor_profile_run_retention_days: int
    seo_competitor_profile_rejected_draft_retention_days: int
    openai_api_base_url: str
    twilio_account_sid: str | None
    twilio_auth_token: str | None
    twilio_from_number: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_from_address: str | None
    smtp_use_tls: bool
    notification_timeout_seconds: int
    rate_limit_enabled: bool
    rate_limit_backend: str
    rate_limit_fail_open: bool
    auth_rate_limit_requests: int
    auth_rate_limit_window_seconds: int
    admin_rate_limit_requests: int
    admin_rate_limit_window_seconds: int
    api_cors_allowed_origins: tuple[str, ...]
    security_headers_enabled: bool
    security_headers_hsts_enabled: bool
    security_headers_hsts_max_age_seconds: int


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer.") from exc
    if min_value is not None and value < min_value:
        raise RuntimeError(f"{name} must be >= {min_value}.")
    return value


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_json_object(name: str) -> dict[str, str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be valid JSON object.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{name} must be a JSON object mapping key versions to key material.")

    normalized: dict[str, str] = {}
    for key, value in payload.items():
        normalized_key = str(key).strip()
        normalized_value = str(value).strip()
        if not normalized_key:
            continue
        if not normalized_value:
            raise RuntimeError(f"{name} contains empty key material for version '{normalized_key}'.")
        normalized[normalized_key] = normalized_value
    return normalized


def _normalize_app_env(raw_value: str | None) -> str:
    return (raw_value or "").strip().lower()


def _normalize_db_connection_mode(raw_value: str | None) -> str:
    return (raw_value or "").strip().lower()


def _is_localhost_allowed_for_app_env(app_env: str) -> bool:
    return app_env in _LOCALHOST_ALLOWED_APP_ENVS


def _is_localhost_allowed_for_runtime(*, app_env: str, db_connection_mode: str) -> bool:
    if _is_localhost_allowed_for_app_env(app_env):
        return True
    return (
        app_env == "production"
        and db_connection_mode in _PRODUCTION_LOCALHOST_ALLOWED_DB_CONNECTION_MODES
    )


def _resolve_database_url(*, app_env: str, db_connection_mode: str) -> str:
    raw_database_url = os.getenv("DATABASE_URL")
    localhost_allowed = _is_localhost_allowed_for_runtime(
        app_env=app_env,
        db_connection_mode=db_connection_mode,
    )
    if raw_database_url is None or not raw_database_url.strip():
        if _is_localhost_allowed_for_app_env(app_env):
            return _LOCAL_DATABASE_URL_FALLBACK
        if app_env == "production":
            raise RuntimeError("DATABASE_URL is required when APP_ENV=production")
        if app_env:
            raise RuntimeError("DATABASE_URL is required when APP_ENV is not one of local/development/dev/test/ci")
        raise RuntimeError(
            "DATABASE_URL is required when APP_ENV is unset; set APP_ENV to local/dev/test/ci for localhost fallback"
        )

    database_url = raw_database_url.strip()
    if database_url.lower().startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://") :]
    parsed = urlparse(database_url)
    if not parsed.scheme:
        raise RuntimeError("DATABASE_URL must be a valid URL.")

    host = (parsed.hostname or "").strip().lower()
    if host in _LOCALHOST_DATABASE_HOSTS and not localhost_allowed:
        if app_env == "production":
            raise RuntimeError(
                "Invalid DATABASE_URL: localhost is not allowed when APP_ENV=production "
                "unless DB_CONNECTION_MODE=cloudsql_proxy"
            )
        if app_env:
            raise RuntimeError(f"Invalid DATABASE_URL: localhost is not allowed when APP_ENV={app_env}")
        raise RuntimeError("Invalid DATABASE_URL: localhost is not allowed when APP_ENV is unset")
    return database_url


def _resolve_ai_prompt_text(*, split_env_name: str, legacy_prompt_text: str) -> _AIPromptResolution:
    split_prompt_text = os.getenv(split_env_name)
    split_prompt_present = split_prompt_text is not None and bool(split_prompt_text.strip())
    legacy_prompt_present = bool((legacy_prompt_text or "").strip())

    if split_prompt_present:
        return _AIPromptResolution(
            prompt_text=split_prompt_text or "",
            prompt_source="split",
            legacy_config_used=False,
        )
    if legacy_prompt_present:
        return _AIPromptResolution(
            prompt_text=legacy_prompt_text,
            prompt_source="legacy_fallback",
            legacy_config_used=True,
        )
    return _AIPromptResolution(
        prompt_text=legacy_prompt_text,
        prompt_source="empty",
        legacy_config_used=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    environment = os.getenv("ENVIRONMENT", "development")
    env_normalized = environment.strip().lower()
    app_env_raw = os.getenv("APP_ENV")
    db_connection_mode_raw = os.getenv("DB_CONNECTION_MODE")
    app_env = _normalize_app_env(app_env_raw) or env_normalized
    db_connection_mode = _normalize_db_connection_mode(db_connection_mode_raw)
    database_url = _resolve_database_url(
        app_env=_normalize_app_env(app_env_raw),
        db_connection_mode=db_connection_mode,
    )
    google_auth_enabled = _env_bool("GOOGLE_AUTH_ENABLED", False)
    google_oidc_client_id = os.getenv("GOOGLE_OIDC_CLIENT_ID")
    google_oauth_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID") or google_oidc_client_id
    google_oauth_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or os.getenv("GOOGLE_OIDC_CLIENT_SECRET")
    app_session_secret = os.getenv("APP_SESSION_SECRET")
    google_oauth_token_encryption_secret = os.getenv("GOOGLE_OAUTH_TOKEN_ENCRYPTION_SECRET") or app_session_secret
    google_oauth_token_encryption_key_version = os.getenv("GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION", "v1").strip()
    google_oauth_token_encryption_keys = _env_json_object("GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON")
    if not google_oauth_token_encryption_keys and google_oauth_token_encryption_secret:
        google_oauth_token_encryption_keys = {
            google_oauth_token_encryption_key_version: google_oauth_token_encryption_secret
        }
    if (
        google_oauth_token_encryption_keys
        and google_oauth_token_encryption_key_version not in google_oauth_token_encryption_keys
    ):
        raise RuntimeError(
            "GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION must exist in GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON."
        )
    redis_url = os.getenv("REDIS_URL")
    api_token_hash_pepper = os.getenv("API_TOKEN_HASH_PEPPER")
    cors_allowed_origins = _env_csv("API_CORS_ALLOWED_ORIGINS")
    if not cors_allowed_origins and app_env in {"local", "development", "dev", "test"}:
        cors_allowed_origins = ("http://localhost:3000", "http://127.0.0.1:3000")

    if env_normalized in {"production", "staging"} and "*" in cors_allowed_origins:
        raise RuntimeError("API_CORS_ALLOWED_ORIGINS cannot include '*' in production/staging environments.")
    if env_normalized == "production" and not api_token_hash_pepper:
        raise RuntimeError("API_TOKEN_HASH_PEPPER is required when ENVIRONMENT=production.")
    if env_normalized == "production" and google_auth_enabled:
        if not google_oidc_client_id:
            raise RuntimeError("GOOGLE_OIDC_CLIENT_ID is required when GOOGLE_AUTH_ENABLED=true in production.")
        if not app_session_secret:
            raise RuntimeError("APP_SESSION_SECRET is required when GOOGLE_AUTH_ENABLED=true in production.")
    session_state_backend = os.getenv("SESSION_STATE_BACKEND", "auto").strip().lower()
    rate_limit_backend = os.getenv("RATE_LIMIT_BACKEND", "auto").strip().lower()
    session_state_fail_open = _env_bool(
        "SESSION_STATE_FAIL_OPEN",
        env_normalized in {"development", "dev", "test", "local"},
    )
    session_state_allow_inmemory_fallback = _env_bool(
        "SESSION_STATE_ALLOW_INMEMORY_FALLBACK",
        True,
    )
    rate_limit_fail_open = _env_bool(
        "RATE_LIMIT_FAIL_OPEN",
        env_normalized in {"development", "dev", "test", "local"},
    )

    if env_normalized in {"production", "staging"}:
        redis_security_required = bool(redis_url) and (
            session_state_backend in {"auto", "redis"} or rate_limit_backend in {"auto", "redis"}
        )
        if redis_security_required and (session_state_fail_open or rate_limit_fail_open):
            raise RuntimeError(
                "Production/staging Redis-backed security controls must be fail-closed "
                "(SESSION_STATE_FAIL_OPEN=false and RATE_LIMIT_FAIL_OPEN=false)."
            )

    legacy_prompt_text_recommendation = os.getenv("AI_PROMPT_TEXT_RECOMMENDATION", "")
    competitor_prompt_resolution = _resolve_ai_prompt_text(
        split_env_name="AI_PROMPT_TEXT_COMPETITOR",
        legacy_prompt_text=legacy_prompt_text_recommendation,
    )
    recommendations_prompt_resolution = _resolve_ai_prompt_text(
        split_env_name="AI_PROMPT_TEXT_RECOMMENDATIONS",
        legacy_prompt_text=legacy_prompt_text_recommendation,
    )

    return Settings(
        app_name=os.getenv("APP_NAME", "MBSRN Operator Platform"),
        app_env=app_env,
        environment=environment,
        db_connection_mode=db_connection_mode or "direct",
        database_url=database_url,
        db_auto_create_local=_env_bool(
            "DB_AUTO_CREATE_LOCAL",
            False,
        ),
        google_auth_enabled=google_auth_enabled,
        google_oidc_client_id=google_oidc_client_id,
        google_oidc_jwks_url=os.getenv("GOOGLE_OIDC_JWKS_URL", "https://www.googleapis.com/oauth2/v3/certs"),
        google_oidc_allowed_issuers=(
            "https://accounts.google.com",
            "accounts.google.com",
        ),
        google_oidc_require_email_verified=_env_bool("GOOGLE_OIDC_REQUIRE_EMAIL_VERIFIED", True),
        google_oidc_timeout_seconds=int(os.getenv("GOOGLE_OIDC_TIMEOUT_SECONDS", "5")),
        google_oauth_client_id=google_oauth_client_id,
        google_oauth_client_secret=google_oauth_client_secret,
        google_oauth_authorization_url=os.getenv(
            "GOOGLE_OAUTH_AUTHORIZATION_URL",
            "https://accounts.google.com/o/oauth2/v2/auth",
        ),
        google_oauth_token_url=os.getenv("GOOGLE_OAUTH_TOKEN_URL", "https://oauth2.googleapis.com/token"),
        google_oauth_revoke_url=os.getenv("GOOGLE_OAUTH_REVOKE_URL", "https://oauth2.googleapis.com/revoke"),
        google_oauth_timeout_seconds=int(os.getenv("GOOGLE_OAUTH_TIMEOUT_SECONDS", "10")),
        google_business_profile_redirect_uri=os.getenv("GOOGLE_BUSINESS_PROFILE_REDIRECT_URI"),
        google_business_profile_state_ttl_seconds=int(os.getenv("GOOGLE_BUSINESS_PROFILE_STATE_TTL_SECONDS", "600")),
        google_business_profile_account_api_base_url=os.getenv(
            "GOOGLE_BUSINESS_PROFILE_ACCOUNT_API_BASE_URL",
            "https://mybusinessaccountmanagement.googleapis.com",
        ),
        google_business_profile_business_information_api_base_url=os.getenv(
            "GOOGLE_BUSINESS_PROFILE_BUSINESS_INFORMATION_API_BASE_URL",
            "https://mybusinessbusinessinformation.googleapis.com",
        ),
        google_business_profile_verifications_api_base_url=os.getenv(
            "GOOGLE_BUSINESS_PROFILE_VERIFICATIONS_API_BASE_URL",
            "https://mybusinessverifications.googleapis.com",
        ),
        google_business_profile_api_timeout_seconds=int(os.getenv("GOOGLE_BUSINESS_PROFILE_API_TIMEOUT_SECONDS", "10")),
        google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY"),
        google_places_api_base_url=os.getenv(
            "GOOGLE_PLACES_API_BASE_URL",
            "https://places.googleapis.com/v1",
        ).strip(),
        google_places_api_timeout_seconds=_env_int("GOOGLE_PLACES_API_TIMEOUT_SECONDS", 8, min_value=1),
        google_places_seed_max_candidates=_env_int("GOOGLE_PLACES_SEED_MAX_CANDIDATES", 8, min_value=1),
        google_places_seed_query_limit=_env_int("GOOGLE_PLACES_SEED_QUERY_LIMIT", 5, min_value=1),
        gcp_logging_project_id=(os.getenv("GCP_PROJECT_ID") or None),
        gcp_logging_api_timeout_seconds=_env_int("GCP_LOGGING_API_TIMEOUT_SECONDS", 10, min_value=1),
        google_oauth_token_encryption_secret=google_oauth_token_encryption_secret,
        google_oauth_token_encryption_key_version=google_oauth_token_encryption_key_version,
        google_oauth_token_encryption_keys=google_oauth_token_encryption_keys,
        google_oauth_refresh_skew_seconds=int(os.getenv("GOOGLE_OAUTH_REFRESH_SKEW_SECONDS", "120")),
        app_session_secret=app_session_secret,
        app_session_issuer=os.getenv("APP_SESSION_ISSUER", "mbsrn-operator"),
        app_session_audience=os.getenv("APP_SESSION_AUDIENCE", "mbsrn-api"),
        app_session_algorithm=os.getenv("APP_SESSION_ALGORITHM", "HS256"),
        app_session_ttl_seconds=int(os.getenv("APP_SESSION_TTL_SECONDS", "3600")),
        app_session_refresh_ttl_seconds=int(os.getenv("APP_SESSION_REFRESH_TTL_SECONDS", "2592000")),
        api_token_hash_pepper=api_token_hash_pepper,
        allow_legacy_token_hash_fallback=_env_bool("ALLOW_LEGACY_TOKEN_HASH_FALLBACK", False),
        redis_url=redis_url,
        session_state_backend=session_state_backend,
        session_state_fail_open=session_state_fail_open,
        session_state_allow_inmemory_fallback=session_state_allow_inmemory_fallback,
        sms_provider=os.getenv("SMS_PROVIDER", "mock").strip().lower(),
        email_provider=os.getenv("EMAIL_PROVIDER", "mock").strip().lower(),
        ai_provider_api_key=os.getenv("AI_PROVIDER_API_KEY"),
        ai_provider_name=(os.getenv("AI_PROVIDER_NAME", "openai").strip().lower() or "openai"),
        ai_model_name=(os.getenv("AI_MODEL_NAME", "gpt-4o-mini").strip() or "gpt-4o-mini"),
        ai_timeout_value=_env_int("AI_TIMEOUT_VALUE", 30, min_value=1),
        ai_prompt_text_competitor=competitor_prompt_resolution.prompt_text,
        ai_prompt_text_competitor_source=competitor_prompt_resolution.prompt_source,
        ai_prompt_text_competitor_legacy_config_used=competitor_prompt_resolution.legacy_config_used,
        ai_prompt_text_recommendations=recommendations_prompt_resolution.prompt_text,
        ai_prompt_text_recommendations_source=recommendations_prompt_resolution.prompt_source,
        ai_prompt_text_recommendations_legacy_config_used=recommendations_prompt_resolution.legacy_config_used,
        ai_eval_allow_real_provider=_env_bool("AI_EVAL_ALLOW_REAL_PROVIDER", False),
        ai_prompt_text_recommendation=legacy_prompt_text_recommendation,
        seo_competitor_profile_raw_output_retention_days=_env_int(
            "SEO_COMPETITOR_PROFILE_RAW_OUTPUT_RETENTION_DAYS",
            30,
            min_value=1,
        ),
        seo_competitor_profile_run_retention_days=_env_int(
            "SEO_COMPETITOR_PROFILE_RUN_RETENTION_DAYS",
            180,
            min_value=1,
        ),
        seo_competitor_profile_rejected_draft_retention_days=_env_int(
            "SEO_COMPETITOR_PROFILE_REJECTED_DRAFT_RETENTION_DAYS",
            90,
            min_value=1,
        ),
        openai_api_base_url=os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1").strip(),
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
        twilio_from_number=os.getenv("TWILIO_FROM_NUMBER"),
        smtp_host=os.getenv("SMTP_HOST"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME"),
        smtp_password=os.getenv("SMTP_PASSWORD"),
        smtp_from_address=os.getenv("SMTP_FROM_ADDRESS"),
        smtp_use_tls=_env_bool("SMTP_USE_TLS", True),
        notification_timeout_seconds=int(os.getenv("NOTIFICATION_TIMEOUT_SECONDS", "10")),
        rate_limit_enabled=_env_bool("RATE_LIMIT_ENABLED", True),
        rate_limit_backend=rate_limit_backend,
        rate_limit_fail_open=rate_limit_fail_open,
        auth_rate_limit_requests=int(os.getenv("AUTH_RATE_LIMIT_REQUESTS", "60")),
        auth_rate_limit_window_seconds=int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")),
        admin_rate_limit_requests=int(os.getenv("ADMIN_RATE_LIMIT_REQUESTS", "20")),
        admin_rate_limit_window_seconds=int(os.getenv("ADMIN_RATE_LIMIT_WINDOW_SECONDS", "60")),
        api_cors_allowed_origins=cors_allowed_origins,
        security_headers_enabled=_env_bool("SECURITY_HEADERS_ENABLED", True),
        security_headers_hsts_enabled=_env_bool(
            "SECURITY_HEADERS_HSTS_ENABLED",
            env_normalized in {"production", "staging"},
        ),
        security_headers_hsts_max_age_seconds=int(os.getenv("SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS", "31536000")),
    )
