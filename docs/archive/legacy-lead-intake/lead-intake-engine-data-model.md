# Lead Intake Engine Data Model (Phase 1)

## `businesses`
- `id` (string UUID, PK)
- `name` (string)
- `primary_phone` (nullable string)
- `notification_phone` (nullable string)
- `notification_email` (nullable string)
- `timezone` (string)
- `sms_enabled` (boolean)
- `email_enabled` (boolean)
- `customer_auto_ack_enabled` (boolean)
- `contractor_alerts_enabled` (boolean)
- `created_at` (datetime tz)
- `updated_at` (datetime tz)

## `leads`
- `id` (string UUID, PK)
- `business_id` (string UUID, FK)
- `source` (enum: `godaddy_email`, `manual`, `phone`, `other`)
- `source_ref` (nullable string)
- `submitted_at` (datetime tz)
- `customer_name` (nullable string)
- `phone` (nullable string)
- `email` (nullable string)
- `service_type` (nullable string)
- `city` (nullable string)
- `message` (nullable text)
- `status` (enum: `new`, `contacted`, `estimate_scheduled`, `won`, `lost`)
- `customer_acknowledged_at` (nullable datetime tz, reserved for later phases)
- `owner_notified_at` (nullable datetime tz, reserved for later phases)
- `first_human_response_at` (nullable datetime tz)
- `estimated_job_value` (nullable numeric)
- `actual_job_value` (nullable numeric)
- `created_at` (datetime tz)
- `updated_at` (datetime tz)

## `lead_events`
- `id` (string UUID, PK)
- `lead_id` (string UUID, FK)
- `event_type` (string)
- `event_timestamp` (datetime tz)
- `actor_type` (enum: `system`, `owner`, `admin`, `customer`)
- `actor_id` (nullable string)
- `payload_json` (json)

## Notes
- Phase 1 writes `lead_created` and `status_changed` events.
- Notification timestamp fields exist now to avoid schema churn later.
