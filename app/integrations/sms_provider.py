from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SMSDispatchResult:
    provider: str
    recipient: str
    status: str = "sent"
    provider_message_id: str | None = None


class SMSProvider(Protocol):
    def send_sms(self, *, to_number: str, body: str) -> SMSDispatchResult: ...


class MockSMSProvider:
    provider_name = "mock_sms"

    def send_sms(self, *, to_number: str, body: str) -> SMSDispatchResult:
        _ = body
        return SMSDispatchResult(
            provider=self.provider_name,
            recipient=to_number,
            status="mocked",
        )


class DevSMSProvider:
    provider_name = "dev_sms"

    def send_sms(self, *, to_number: str, body: str) -> SMSDispatchResult:
        print(f"[dev-sms] to={to_number} body={body}")
        return SMSDispatchResult(
            provider=self.provider_name,
            recipient=to_number,
            status="dev_sent",
        )


class TwilioSMSProvider:
    provider_name = "twilio"

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        timeout_seconds: int = 10,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.timeout_seconds = timeout_seconds

    def send_sms(self, *, to_number: str, body: str) -> SMSDispatchResult:
        endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        encoded = urlencode({"From": self.from_number, "To": to_number, "Body": body}).encode("utf-8")
        request = Request(endpoint, data=encoded, method="POST")
        auth_header = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode("utf-8")).decode("utf-8")
        request.add_header("Authorization", f"Basic {auth_header}")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Twilio HTTP error {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Twilio connection error: {exc.reason}") from exc
        except OSError as exc:
            raise RuntimeError(f"Twilio send failed: {exc}") from exc

        payload = json.loads(raw) if raw else {}
        return SMSDispatchResult(
            provider=self.provider_name,
            recipient=to_number,
            status=str(payload.get("status", "queued")),
            provider_message_id=payload.get("sid"),
        )
