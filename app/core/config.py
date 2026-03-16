from __future__ import annotations

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
    db_auto_create_local: bool
    google_auth_enabled: bool
    google_oidc_client_id: str | None
    google_oidc_jwks_url: str
    google_oidc_allowed_issuers: tuple[str, ...]
    google_oidc_require_email_verified: bool
    google_oidc_timeout_seconds: int
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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    environment = os.getenv("ENVIRONMENT", "development")
    env_normalized = environment.strip().lower()
    app_env = os.getenv("APP_ENV", environment).strip().lower()
    google_auth_enabled = _env_bool("GOOGLE_AUTH_ENABLED", False)
    google_oidc_client_id = os.getenv("GOOGLE_OIDC_CLIENT_ID")
    app_session_secret = os.getenv("APP_SESSION_SECRET")
    redis_url = os.getenv("REDIS_URL")
    api_token_hash_pepper = os.getenv("API_TOKEN_HASH_PEPPER")
    if env_normalized == "production" and not api_token_hash_pepper:
        raise RuntimeError("API_TOKEN_HASH_PEPPER is required when ENVIRONMENT=production.")
    if env_normalized == "production" and google_auth_enabled:
        if not google_oidc_client_id:
            raise RuntimeError("GOOGLE_OIDC_CLIENT_ID is required when GOOGLE_AUTH_ENABLED=true in production.")
        if not app_session_secret:
            raise RuntimeError("APP_SESSION_SECRET is required when GOOGLE_AUTH_ENABLED=true in production.")

    return Settings(
        app_name=os.getenv("APP_NAME", "Work Boots Console Lead Intake"),
        app_env=app_env,
        environment=environment,
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/work_boots_console",
        ),
        default_business_id=os.getenv("DEFAULT_BUSINESS_ID", "11111111-1111-1111-1111-111111111111"),
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
        app_session_secret=app_session_secret,
        app_session_issuer=os.getenv("APP_SESSION_ISSUER", "work-boots-console"),
        app_session_audience=os.getenv("APP_SESSION_AUDIENCE", "work-boots-api"),
        app_session_algorithm=os.getenv("APP_SESSION_ALGORITHM", "HS256"),
        app_session_ttl_seconds=int(os.getenv("APP_SESSION_TTL_SECONDS", "3600")),
        app_session_refresh_ttl_seconds=int(os.getenv("APP_SESSION_REFRESH_TTL_SECONDS", "2592000")),
        api_token_hash_pepper=api_token_hash_pepper,
        allow_legacy_token_hash_fallback=_env_bool("ALLOW_LEGACY_TOKEN_HASH_FALLBACK", False),
        redis_url=redis_url,
        session_state_backend=os.getenv("SESSION_STATE_BACKEND", "auto").strip().lower(),
        session_state_fail_open=_env_bool(
            "SESSION_STATE_FAIL_OPEN",
            env_normalized in {"development", "dev", "test", "local"},
        ),
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
        rate_limit_backend=os.getenv("RATE_LIMIT_BACKEND", "auto").strip().lower(),
        rate_limit_fail_open=_env_bool(
            "RATE_LIMIT_FAIL_OPEN",
            env_normalized in {"development", "dev", "test", "local"},
        ),
        auth_rate_limit_requests=int(os.getenv("AUTH_RATE_LIMIT_REQUESTS", "60")),
        auth_rate_limit_window_seconds=int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")),
        admin_rate_limit_requests=int(os.getenv("ADMIN_RATE_LIMIT_REQUESTS", "20")),
        admin_rate_limit_window_seconds=int(os.getenv("ADMIN_RATE_LIMIT_WINDOW_SECONDS", "60")),
    )
