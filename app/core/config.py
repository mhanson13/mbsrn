from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    database_url: str
    default_business_id: str
    api_auth_token: str | None
    api_auth_business_id: str | None
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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Work Boots Console Lead Intake"),
        environment=os.getenv("ENVIRONMENT", "development"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/work_boots_console",
        ),
        default_business_id=os.getenv("DEFAULT_BUSINESS_ID", "11111111-1111-1111-1111-111111111111"),
        api_auth_token=os.getenv("API_AUTH_TOKEN"),
        api_auth_business_id=os.getenv("API_AUTH_BUSINESS_ID"),
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
    )
