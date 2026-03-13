from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class PrincipalCredential:
    token: str
    principal_id: str
    business_id: str


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    database_url: str
    default_business_id: str
    allow_auth_compat_fallback: bool
    api_principal_credentials: tuple[PrincipalCredential, ...]
    api_auth_token: str | None
    api_auth_business_id: str | None
    api_token_hash_pepper: str | None
    allow_legacy_token_hash_fallback: bool
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


def _parse_principal_credentials(raw: str | None) -> tuple[PrincipalCredential, ...]:
    if not raw:
        return ()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "API_AUTH_PRINCIPALS_JSON is invalid JSON. "
            "Expected a JSON list of objects with token, principal_id, and business_id."
        ) from exc

    if not isinstance(payload, list):
        raise RuntimeError("API_AUTH_PRINCIPALS_JSON must be a JSON list.")

    credentials: list[PrincipalCredential] = []
    seen_tokens: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise RuntimeError(f"API_AUTH_PRINCIPALS_JSON[{index}] must be an object.")

        token = str(item.get("token", "")).strip()
        principal_id = str(item.get("principal_id", "")).strip()
        business_id = str(item.get("business_id", "")).strip()
        if not token or not principal_id or not business_id:
            raise RuntimeError(
                "Each API_AUTH_PRINCIPALS_JSON entry must include non-empty "
                "token, principal_id, and business_id."
            )
        if token in seen_tokens:
            raise RuntimeError("Duplicate token values found in API_AUTH_PRINCIPALS_JSON.")
        seen_tokens.add(token)
        credentials.append(
            PrincipalCredential(
                token=token,
                principal_id=principal_id,
                business_id=business_id,
            )
        )

    return tuple(credentials)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    environment = os.getenv("ENVIRONMENT", "development")
    env_normalized = environment.strip().lower()
    default_allow_compat = env_normalized in {"development", "dev", "test"}

    return Settings(
        app_name=os.getenv("APP_NAME", "Work Boots Console Lead Intake"),
        environment=environment,
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/work_boots_console",
        ),
        default_business_id=os.getenv("DEFAULT_BUSINESS_ID", "11111111-1111-1111-1111-111111111111"),
        allow_auth_compat_fallback=_env_bool("ALLOW_AUTH_COMPAT_FALLBACK", default_allow_compat),
        api_principal_credentials=_parse_principal_credentials(os.getenv("API_AUTH_PRINCIPALS_JSON")),
        api_auth_token=os.getenv("API_AUTH_TOKEN"),
        api_auth_business_id=os.getenv("API_AUTH_BUSINESS_ID"),
        api_token_hash_pepper=os.getenv("API_TOKEN_HASH_PEPPER"),
        allow_legacy_token_hash_fallback=_env_bool("ALLOW_LEGACY_TOKEN_HASH_FALLBACK", True),
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
