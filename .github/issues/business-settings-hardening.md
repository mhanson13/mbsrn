## Summary

Harden the business settings control plane so pilot customers can configure notifications safely and predictably.

## Scope

Files to inspect:

- `app/api/routes/businesses.py`
- `app/services/business_settings.py`
- `app/schemas/business.py`
- `app/models/business.py`
- `app/tests/test_business_settings_api.py`

## Goals

- Ensure email, phone, and timezone normalization/validation remain correct.
- Ensure contradictory notification configurations are rejected.
- Ensure partial PATCH updates validate effective configuration safely.
- Keep route handlers thin and service logic explicit.

## Tasks

- [ ] Review schema validators and normalization paths.
- [ ] Review service-level business-rule enforcement.
- [ ] Verify route maps not found vs validation errors correctly.
- [ ] Expand tests only if true gaps are found.

## Acceptance Criteria

- Business settings updates are pilot-safe.
- Invalid notification configuration yields 422.
- Normalized email and phone values are stored consistently.
- Tests cover both US fallback and global E.164 cases.
