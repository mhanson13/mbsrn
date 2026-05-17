from __future__ import annotations

import io
from urllib.error import HTTPError

import pytest

from app.integrations.email_provider import DevEmailProvider
from app.integrations.sms_provider import DevSMSProvider, TwilioSMSProvider


def test_dev_email_provider_does_not_print_message_body(capsys: pytest.CaptureFixture[str]) -> None:
    provider = DevEmailProvider(from_address="noreply@mbsrn.local")

    provider.send_email(
        to_address="user@example.com",
        subject="Reset token",
        body="FAKE_SECRET_EMAIL_BODY_FOR_TEST",
    )

    output = capsys.readouterr().out
    assert "FAKE_SECRET_EMAIL_BODY_FOR_TEST" not in output
    assert "body_chars=" in output


def test_dev_sms_provider_does_not_print_message_body(capsys: pytest.CaptureFixture[str]) -> None:
    provider = DevSMSProvider()

    provider.send_sms(
        to_number="+15551234567",
        body="FAKE_SECRET_SMS_BODY_FOR_TEST",
    )

    output = capsys.readouterr().out
    assert "FAKE_SECRET_SMS_BODY_FOR_TEST" not in output
    assert "body_chars=" in output


def test_twilio_http_error_message_does_not_include_raw_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = TwilioSMSProvider(
        account_sid="AC123",
        auth_token="token",
        from_number="+15551234567",
    )

    def _raise_http_error(*args, **kwargs):  # noqa: ANN001, ANN002
        del args, kwargs
        raise HTTPError(
            url="https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"Bearer FAKE_BEARER_SECRET_FOR_TEST"}'),
        )

    monkeypatch.setattr("app.integrations.sms_provider.urlopen", _raise_http_error)

    with pytest.raises(RuntimeError) as exc_info:
        provider.send_sms(to_number="+15551234567", body="hello")

    message = str(exc_info.value)
    assert "Twilio HTTP error 400" in message
    assert "FAKE_BEARER_SECRET_FOR_TEST" not in message
