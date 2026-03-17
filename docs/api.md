# GBP API

This document covers currently implemented Google Business Profile API routes.

## Scope
- `GET /api/integrations/google/business-profile/accounts`
- `GET /api/integrations/google/business-profile/locations`
- `GET /api/integrations/google/business-profile/locations/{location_id}/verification`
- `GET /api/integrations/google/business-profile/locations/{location_id}/verification/options`
- `GET /api/integrations/google/business-profile/locations/{location_id}/verification/status`
- `POST /api/integrations/google/business-profile/locations/{location_id}/verification/start`
- `POST /api/integrations/google/business-profile/locations/{location_id}/verification/complete`
- `POST /api/integrations/google/business-profile/locations/{location_id}/verification/retry`

All routes require authenticated tenant context and are business-scoped server-side.

## Auth And Business Scoping
- Caller must be authenticated (`get_tenant_context`, `get_authenticated_principal`).
- Business scope comes from resolved tenant context, not caller-provided business IDs.
- Provider token use is resolved by business-scoped provider connection state.
- Token usability checks run before provider calls and fail closed (`reconnect_required`, `insufficient_scope`, decrypt/refresh failures).

## Normalized Enums

### Read summary enums
- `state_summary`: `verified | pending | unverified | unknown`
- `recommended_next_action`: `none | start_verification | complete_pending | resolve_access | reconnect_google`

### Workflow status enums
- `verification_state`: `unverified | pending | in_progress | completed | failed | unknown`
- `action_required`: `none | choose_method | enter_code | wait | retry | reconnect_google | resolve_access`
- `method`: `postcard | phone | sms | email | live_call | video | vetted_partner | address | other | unknown`

### Guidance enums
- `recommended_action`: `verify_business | choose_method | enter_code | wait_for_code | retry_verification | reconnect_google | contact_support | no_action_needed | check_business_access | review_business_details | unknown`
- `priority`: `high | medium | low | info`
- `cta_type`: `start_verification | choose_method | submit_code | reconnect | retry | refresh_status | none`

### Internal token status enum (enforcement contract)
- `usable | refresh_required | reconnect_required | insufficient_scope`

## Reconnect Behavior And `reconnect_google` Contract
- Reconnect is primarily a connection-level concern (`GET /connection`, token usability, and structured API errors).
- APIs can signal reconnect via `409`/`reconnect_required` style responses when token/key/scope state is unusable.
- `recommended_next_action="reconnect_google"` exists in the schema/type contract.
- Current location-level read behavior does not treat `recommended_next_action` as the primary or consistent reconnect trigger.
- Consumers should use connection state and explicit reconnect errors as the main reconnect signal, not location-level `recommended_next_action` alone.

## Read Routes

### `GET /accounts`
Purpose:
- Returns normalized GBP accounts with nested locations and verification summaries.

Error behavior:
- `403` provider permission denied or insufficient scope
- `409` reconnect required
- `502` provider error

### `GET /locations`
Purpose:
- Returns flattened normalized location list across accessible accounts.

Error behavior:
- Same as `/accounts` (`403`, `409`, `502`)

### `GET /locations/{location_id}/verification`
Purpose:
- Returns normalized verification summary for one location in caller business scope.

Error behavior:
- `404` location not found in business scope
- Token/provider errors inherited from read path (`403`, `409`, `502`)

## Verification Workflow Routes

### `GET /locations/{location_id}/verification/options`
Purpose:
- Returns normalized available verification methods for the location.

Response shape:
```json
{
  "location_id": "location-1",
  "current_verification_state": "unverified",
  "guidance": {
    "recommended_action": "choose_method",
    "title": "Choose how to get your verification code"
  },
  "methods": [
    {
      "option_id": "method_2f4a1f3f9e90f4b8a6c7d912",
      "method": "email",
      "provider_method": "EMAIL",
      "label": "Email",
      "description": "owner@example.com",
      "destination": "owner@example.com",
      "requires_code": true,
      "eligible": true
    }
  ]
}
```

### `GET /locations/{location_id}/verification/status`
Purpose:
- Returns normalized current workflow status and actionable guidance.

Response shape:
```json
{
  "location_id": "location-1",
  "verification_state": "pending",
  "action_required": "enter_code",
  "message": "Enter the verification code to complete verification.",
  "reconnect_required": false,
  "current_verification": {
    "verification_id": "attempt-1",
    "provider_state": "PENDING",
    "method": "email",
    "provider_method": "EMAIL",
    "create_time": null,
    "complete_time": null,
    "expires_at": null
  },
  "available_methods": [],
  "guidance": {
    "recommended_action": "enter_code",
    "title": "Enter your verification code",
    "cta_type": "submit_code"
  }
}
```

### `POST /locations/{location_id}/verification/start`
Purpose:
- Starts verification using a selected available method.

Request shape:
```json
{
  "option_id": "method_2f4a1f3f9e90f4b8a6c7d912"
}
```

`option_id` is an opaque, deterministic token generated from provider option attributes.
The backend revalidates client-submitted option tokens against current provider options before starting verification.

Response shape:
- returns action result with `verification_state`, `verification_id`, `action_required`, top-level `guidance`, and nested refreshed `status`.

### `POST /locations/{location_id}/verification/complete`
Purpose:
- Completes an active verification attempt with a code.

Request shape:
```json
{
  "verification_id": "attempt-1",
  "code": "123456"
}
```

Response shape:
- returns action result with updated workflow state, top-level `guidance`, and nested refreshed `status`.

### `POST /locations/{location_id}/verification/retry`
Purpose:
- Restarts verification attempt when provider/location state allows retry.

Request shape:
```json
{
  "option_id": "method_2f4a1f3f9e90f4b8a6c7d912"
}
```

Response shape:
- same action result contract as `start`.
- `retry` is an app-level workflow convenience that reuses provider-supported start semantics when state allows it.

## Structured Error Model (Workflow Routes)

Workflow routes return object-style `detail`:
```json
{
  "detail": {
    "code": "method_not_available",
    "message": "Selected verification method is not available for this location.",
    "reconnect_required": false
  }
}
```

Implemented `code` values:
- `reconnect_required`
- `insufficient_scope`
- `permission_denied`
- `verification_not_supported`
- `method_not_available`
- `invalid_verification_state`
- `invalid_code`
- `provider_conflict`
- `provider_error`
- `not_found`

## Notes
- Verification routes do not expose OAuth tokens to the browser.
- Tenant/business boundaries are enforced server-side for every route.
- Provider transport details remain in the GBP client layer; API contracts stay normalized.
- Operator guidance is generated server-side from normalized state using deterministic rules (no live LLM dependency).
- Unknown/unmapped provider states, methods, and fallback error mappings degrade safely and emit structured observability logs.
