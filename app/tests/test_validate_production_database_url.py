from scripts.validate_production_database_url import analyze_database_url


def test_direct_mode_loopback_rejection_message_is_actionable() -> None:
    accepted, message, diagnostics = analyze_database_url(
        "postgresql://user:pass@localhost:5432/dbname",
        db_connection_mode="direct",
    )

    assert accepted is False
    assert diagnostics.effective_target_kind == "loopback_host"
    assert "localhost/loopback target is not allowed for deploy-prod" in message
    assert "non-loopback cluster/service hostname" in message


def test_direct_mode_remote_hostname_is_accepted() -> None:
    accepted, message, diagnostics = analyze_database_url(
        "postgresql://user:pass@db.example.internal:5432/dbname",
        db_connection_mode="direct",
    )

    assert accepted is True
    assert diagnostics.effective_target_kind == "remote_host"
    assert message == "DATABASE_URL accepted for production deploy."
