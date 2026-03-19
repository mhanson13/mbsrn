from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import smtplib
from typing import Protocol


@dataclass(frozen=True)
class EmailDispatchResult:
    provider: str
    recipient: str
    subject: str
    status: str = "sent"
    provider_message_id: str | None = None


class EmailProvider(Protocol):
    def send_email(self, *, to_address: str, subject: str, body: str) -> EmailDispatchResult: ...


class MockEmailProvider:
    provider_name = "mock_email"

    def send_email(self, *, to_address: str, subject: str, body: str) -> EmailDispatchResult:
        _ = body
        return EmailDispatchResult(
            provider=self.provider_name,
            recipient=to_address,
            subject=subject,
            status="mocked",
        )


class DevEmailProvider:
    provider_name = "dev_email"

    def __init__(self, from_address: str = "noreply@workboots.local") -> None:
        self.from_address = from_address

    def send_email(self, *, to_address: str, subject: str, body: str) -> EmailDispatchResult:
        print(f"[dev-email] from={self.from_address} to={to_address} " f"subject={subject} body={body}")
        return EmailDispatchResult(
            provider=self.provider_name,
            recipient=to_address,
            subject=subject,
            status="dev_sent",
        )


class SMTPEmailProvider:
    provider_name = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_address: str,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        timeout_seconds: int = 10,
    ) -> None:
        self.host = host
        self.port = port
        self.from_address = from_address
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.timeout_seconds = timeout_seconds

    def send_email(self, *, to_address: str, subject: str, body: str) -> EmailDispatchResult:
        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = to_address
        message["Subject"] = subject
        message.set_content(body)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
                smtp.ehlo()
                if self.use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if self.username:
                    smtp.login(self.username, self.password or "")
                smtp.send_message(message)
        except smtplib.SMTPException as exc:
            raise RuntimeError(f"SMTP send failed: {exc}") from exc
        except OSError as exc:
            raise RuntimeError(f"SMTP connection failed: {exc}") from exc

        return EmailDispatchResult(
            provider=self.provider_name,
            recipient=to_address,
            subject=subject,
            status="sent",
        )
