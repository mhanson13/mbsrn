from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.models.principal import Principal, PrincipalRole
from app.models.principal_identity import PrincipalIdentity
from app.scripts import bootstrap_admin as bootstrap_cli


class _SessionContext:
    def __init__(self, session) -> None:
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    default_business_id: str,
    default_admin_email: str | None = None,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEFAULT_BUSINESS_ID", default_business_id)
    if default_admin_email is None:
        monkeypatch.delenv("DEFAULT_ADMIN_EMAIL", raising=False)
    else:
        monkeypatch.setenv("DEFAULT_ADMIN_EMAIL", default_admin_email)


def test_bootstrap_admin_creates_principal_and_is_idempotent(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, default_business_id=seeded_business.id)
    monkeypatch.setattr(bootstrap_cli, "SessionLocal", lambda: _SessionContext(db_session))

    first = bootstrap_cli.run_bootstrap_admin(
        email="MHANSON13@GMAIL.COM",
        role=PrincipalRole.ADMIN,
    )
    assert first.principal_action == "created"
    assert first.identity_action == "created"
    assert first.principal_id == "mhanson13@gmail.com"
    assert first.business_id == seeded_business.id

    principal = db_session.get(Principal, (seeded_business.id, "mhanson13@gmail.com"))
    assert principal is not None
    assert principal.role == PrincipalRole.ADMIN
    assert principal.is_active is True

    placeholder_identity = (
        db_session.query(PrincipalIdentity)
        .filter(PrincipalIdentity.business_id == seeded_business.id)
        .filter(PrincipalIdentity.principal_id == "mhanson13@gmail.com")
        .filter(PrincipalIdentity.provider == "google")
        .one_or_none()
    )
    assert placeholder_identity is not None
    assert placeholder_identity.provider_subject == "mhanson13@gmail.com"
    assert placeholder_identity.email == "mhanson13@gmail.com"
    assert placeholder_identity.is_active is True

    second = bootstrap_cli.run_bootstrap_admin(
        email="mhanson13@gmail.com",
        role=PrincipalRole.ADMIN,
    )
    assert second.principal_action == "noop"
    assert second.identity_action == "noop"


def test_bootstrap_admin_updates_existing_principal_role(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, default_business_id=seeded_business.id)
    monkeypatch.setattr(bootstrap_cli, "SessionLocal", lambda: _SessionContext(db_session))

    principal = Principal(
        business_id=seeded_business.id,
        id="operator@example.com",
        display_name="operator@example.com",
        role=PrincipalRole.OPERATOR,
        is_active=False,
    )
    db_session.add(principal)
    db_session.commit()

    result = bootstrap_cli.run_bootstrap_admin(
        email="operator@example.com",
        role=PrincipalRole.ADMIN,
    )
    assert result.principal_action == "updated"

    db_session.expire_all()
    refreshed = db_session.get(Principal, (seeded_business.id, "operator@example.com"))
    assert refreshed is not None
    assert refreshed.role == PrincipalRole.ADMIN
    assert refreshed.is_active is True


def test_bootstrap_admin_main_uses_default_admin_email_when_email_arg_omitted(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        default_business_id=seeded_business.id,
        default_admin_email="default-admin@example.com",
    )
    monkeypatch.setattr(bootstrap_cli, "SessionLocal", lambda: _SessionContext(db_session))

    exit_code = bootstrap_cli.main(["--role", "admin"])
    assert exit_code == 0

    principal = db_session.get(Principal, (seeded_business.id, "default-admin@example.com"))
    assert principal is not None
    assert principal.role == PrincipalRole.ADMIN
