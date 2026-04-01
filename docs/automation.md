# Automation

## Lifecycle And Outcome Visibility

Automation surfaces now prioritize a compact "what happened / what next" read model using existing run data.

Operator-visible lifecycle states:
- `queued`
- `running`
- `completed`
- `failed`

These states are presentation-only signals from existing API payloads. No automation execution semantics were changed.

## Operator Action-State Mapping

Automation surfaces now include deterministic operator action-state cues using existing run + step-output linkage data:

- `Automation output ready`
- `Waiting on automation`
- `Blocked / unavailable`
- `Informational only`

Cue contract on automation-facing pages:
- one action-state badge
- one concise outcome line (`what happened`)
- one concise next-step line (`what to do now`)

This mapping is read-only and presentation-only. It does not change automation orchestration, retry logic, or execution behavior.

## Step-Level Outcome Visibility

When `steps_json` is present for a run, the UI shows per-step outcomes with safe fallbacks for missing data:
- step name
- step status
- started/finished timestamps
- linked output id (when present)
- step error message (when present)

If step payloads are partial or absent, pages degrade safely without throwing runtime errors.

## Recommendation Output Linkage

When step outputs include recommendation artifact ids, the UI renders deterministic deep links:
- recommendation run detail
- recommendation narrative detail

If no linked output is present, the UI explicitly shows a bounded "no linked output" outcome cue.

## Operator Guidance Pattern

Automation-facing surfaces now consistently expose:
- **What happened**: compact outcome summary
- **What next**: deterministic operator guidance

This same pattern appears on:
- `/automation` (latest run + run cards)
- `/sites/[site_id]` workspace (compact automation status block)

## Local Testability

All lifecycle and linkage visibility is verified through mocked frontend payloads:
- no live provider/runtime calls required
- missing/partial step payloads are covered
- linkage rendering is covered for both present and absent output ids

## Legacy Pipeline Note

Legacy conceptual flow (kept for context):

```text
Customer submits form
        ↓
Email notification arrives
        ↓
Automation parses the lead
        ↓
Lead saved to CRM
        ↓
Customer receives instant SMS
        ↓
Contractor receives alert
        ↓
Response timer begins
```
