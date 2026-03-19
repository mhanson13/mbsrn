from __future__ import annotations

import re
from datetime import datetime

from app.schemas.lead import EmailLeadFields, ParsedLeadData


class LeadParserService:
    """Rules-based parser for GoDaddy style form notification emails."""

    _PHONE_REGEX = re.compile(r"(?:(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})")
    _EMAIL_REGEX = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    _SUBJECT_NAME_REGEX = re.compile(
        r"(?:new|website|form)?\s*(?:lead|submission|message).*?\bfrom\b[:\s-]*([A-Za-z][A-Za-z .'\-]+)$",
        re.IGNORECASE,
    )
    _LINE_REGEX = re.compile(r"^\s*([A-Za-z][A-Za-z /_-]{1,48})\s*:\s*(.*?)\s*$")
    _FIELD_ALIASES: dict[str, set[str]] = {
        "customer_name": {"name", "full name", "customer name", "contact", "contact name"},
        "phone": {"phone", "phone number", "mobile", "cell", "cell phone"},
        "email": {"email", "email address", "e-mail"},
        "service_type": {"service", "service type", "job type", "project type", "requested service"},
        "city": {"city", "location", "service city", "town"},
        "message": {"message", "details", "comments", "project details", "description", "notes"},
    }

    def parse_payload(
        self,
        *,
        received_at: datetime,
        source_ref: str | None,
        subject: str | None,
        body_text: str | None,
        normalized_fields: EmailLeadFields | None,
    ) -> ParsedLeadData:
        if normalized_fields is not None:
            return self._parse_normalized_fields(
                received_at=received_at,
                source_ref=source_ref,
                fields=normalized_fields,
            )
        return self.parse_godaddy_email(
            subject=subject,
            body_text=body_text,
            received_at=received_at,
            source_ref=source_ref,
        )

    def parse_godaddy_email(
        self,
        *,
        subject: str | None,
        body_text: str | None,
        received_at: datetime,
        source_ref: str | None,
    ) -> ParsedLeadData:
        errors: list[str] = []
        text = (body_text or "").strip()
        if not text:
            errors.append("Email body is empty.")
            return ParsedLeadData(
                source_ref=source_ref,
                submitted_at=received_at,
                customer_name=None,
                phone=None,
                email=None,
                service_type=None,
                city=None,
                message=None,
                parse_status="failed",
                parse_errors=errors,
            )

        extracted = self._extract_labeled_fields(text)
        customer_name = self._normalize_name(extracted.get("customer_name"))
        phone = self._normalize_phone(extracted.get("phone") or self._extract_phone(text))
        email = self._normalize_email(extracted.get("email") or self._extract_email(text))
        service_type = self._clean_text(extracted.get("service_type"))
        city = self._clean_text(extracted.get("city"))
        message = self._clean_text(extracted.get("message"))

        if not customer_name:
            customer_name = self._extract_name_from_subject(subject)

        parse_status = "parsed"
        if not any([customer_name, phone, email]):
            parse_status = "failed"
            errors.append("Unable to extract a customer identifier (name, phone, or email).")

        return ParsedLeadData(
            source_ref=source_ref,
            submitted_at=received_at,
            customer_name=customer_name,
            phone=phone,
            email=email,
            service_type=service_type,
            city=city,
            message=message,
            parse_status=parse_status,
            parse_errors=errors,
        )

    def _parse_normalized_fields(
        self,
        *,
        received_at: datetime,
        source_ref: str | None,
        fields: EmailLeadFields,
    ) -> ParsedLeadData:
        errors: list[str] = []
        customer_name = self._normalize_name(fields.customer_name)
        phone = self._normalize_phone(fields.phone)
        email = self._normalize_email(fields.email)
        service_type = self._clean_text(fields.service_type)
        city = self._clean_text(fields.city)
        message = self._clean_text(fields.message)

        parse_status = "normalized"
        if not any([customer_name, phone, email]):
            parse_status = "failed"
            errors.append("Normalized payload did not include name, phone, or email.")

        return ParsedLeadData(
            source_ref=source_ref,
            submitted_at=received_at,
            customer_name=customer_name,
            phone=phone,
            email=email,
            service_type=service_type,
            city=city,
            message=message,
            parse_status=parse_status,
            parse_errors=errors,
        )

    def _extract_labeled_fields(self, body_text: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        message_lines: list[str] = []
        collecting_message = False

        for line in body_text.splitlines():
            stripped = line.strip()
            if not stripped:
                if collecting_message and message_lines:
                    message_lines.append("")
                continue

            match = self._LINE_REGEX.match(stripped)
            if not match:
                if collecting_message:
                    message_lines.append(stripped)
                continue

            label = re.sub(r"\s+", " ", match.group(1).strip().lower())
            value = match.group(2).strip()
            field_name = self._map_label(label)
            if field_name is None:
                collecting_message = False
                continue

            if field_name == "message":
                collecting_message = True
                if value:
                    message_lines.append(value)
                continue

            collecting_message = False
            if value:
                fields[field_name] = value

        if message_lines:
            fields["message"] = "\n".join(message_lines).strip()

        return fields

    def _map_label(self, label: str) -> str | None:
        for field_name, aliases in self._FIELD_ALIASES.items():
            if label in aliases:
                return field_name
        return None

    def _extract_phone(self, text: str) -> str | None:
        match = self._PHONE_REGEX.search(text)
        return match.group(0) if match else None

    def _extract_email(self, text: str) -> str | None:
        match = self._EMAIL_REGEX.search(text)
        return match.group(0) if match else None

    def _extract_name_from_subject(self, subject: str | None) -> str | None:
        if not subject:
            return None
        match = self._SUBJECT_NAME_REGEX.search(subject.strip())
        if not match:
            return None
        return self._normalize_name(match.group(1))

    def _normalize_phone(self, value: str | None) -> str | None:
        cleaned = self._clean_text(value)
        if not cleaned:
            return None

        digits = re.sub(r"\D", "", cleaned)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            return f"+1{digits}"
        if not digits:
            return None
        if cleaned.startswith("+"):
            return f"+{digits}"
        return digits

    def _normalize_email(self, value: str | None) -> str | None:
        cleaned = self._clean_text(value)
        if not cleaned:
            return None
        return cleaned.lower()

    def _normalize_name(self, value: str | None) -> str | None:
        cleaned = self._clean_text(value)
        if not cleaned:
            return None
        return cleaned

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned
