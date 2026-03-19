from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    environment: str
    database_url: str
    default_business_id: str
    default_admin_email: str | None
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
    sms_provider: str
    email_provider: str
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


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_optional_email(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if not normalized:
        return None
    if len(normalized) > 320 or "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise RuntimeError(f"{name} must be a valid email address.")
    return normalized


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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    environment = os.getenv("ENVIRONMENT", "development")
    env_normalized = environment.strip().lower()
    app_env = os.getenv("APP_ENV", environment).strip().lower()
    google_auth_enabled = _env_bool("GOOGLE_AUTH_ENABLED", False)
    default_business_id = (os.getenv("DEFAULT_BUSINESS_ID") or "").strip()
    default_admin_email = _env_optional_email("DEFAULT_ADMIN_EMAIL")
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
    if env_normalized in {"production", "staging"} and not default_business_id:
        raise RuntimeError("DEFAULT_BUSINESS_ID is required in production/staging environments.")
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

    return Settings(
        app_name=os.getenv("APP_NAME", "Work Boots Console Lead Intake"),
        app_env=app_env,
        environment=environment,
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/work_boots_console",
        ),
        default_business_id=default_business_id,
        default_admin_email=default_admin_email,
        db_auto_create_local=_env_bool(
            "DB_AUTO_CREATE_LOCAL",
            app_env in {"local", "development", "dev", "test"},
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
        google_oauth_token_encryption_secret=google_oauth_token_encryption_secret,
        google_oauth_token_encryption_key_version=google_oauth_token_encryption_key_version,
        google_oauth_token_encryption_keys=google_oauth_token_encryption_keys,
        google_oauth_refresh_skew_seconds=int(os.getenv("GOOGLE_OAUTH_REFRESH_SKEW_SECONDS", "120")),
        app_session_secret=app_session_secret,
        app_session_issuer=os.getenv("APP_SESSION_ISSUER", "work-boots-console"),
        app_session_audience=os.getenv("APP_SESSION_AUDIENCE", "work-boots-api"),
        app_session_algorithm=os.getenv("APP_SESSION_ALGORITHM", "HS256"),
        app_session_ttl_seconds=int(os.getenv("APP_SESSION_TTL_SECONDS", "3600")),
        app_session_refresh_ttl_seconds=int(os.getenv("APP_SESSION_REFRESH_TTL_SECONDS", "2592000")),
        api_token_hash_pepper=api_token_hash_pepper,
        allow_legacy_token_hash_fallback=_env_bool("ALLOW_LEGACY_TOKEN_HASH_FALLBACK", False),
        redis_url=redis_url,
        session_state_backend=session_state_backend,
        session_state_fail_open=session_state_fail_open,
        sms_provider=os.getenv("SMS_PROVIDER", "mock").strip().lower(),
        email_provider=os.getenv("EMAIL_PROVIDER", "mock").strip().lower(),
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
