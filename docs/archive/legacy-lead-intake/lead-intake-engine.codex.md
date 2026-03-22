# Lead Intake Engine — Codex Build Prompt

## Purpose

Use this prompt to scaffold the **Lead Intake Engine** for **mbsrn**.

The goal is to build a lightweight, contractor-friendly intake system that captures leads, acknowledges customers immediately, notifies the contractor, and tracks lead progress with minimal friction.

---

## Prompt

```text
You are helping me design and scaffold the Lead Intake Engine for an MVP product called "mbsrn."

Context:
- mbsrn is for very small contractor businesses like T&M Fire and Lars Construction.
- These businesses are owner-operators doing physical labor during the day and following up on leads later.
- Their websites are on GoDaddy Airo / Websites + Marketing.
- New website leads may arrive through GoDaddy contact form notification emails.
- The product must be extremely simple, mobile-friendly, and easy for non-technical contractors to use.
- The single biggest goal is to reduce time-to-response for new leads.

Business goals of the Lead Intake Engine:
1. Capture every incoming lead.
2. Normalize all leads into a common structure.
3. Instantly acknowledge the customer by SMS or email.
4. Instantly notify the contractor.
5. Track response time and lead status.
6. Keep the workflow simple: new, contacted, estimate_scheduled, won, lost.

Your task:
Design a lightweight Lead Intake Engine and generate implementation scaffolding.

Please produce:

1. A concise Markdown design doc for the Lead Intake Engine.
2. A proposed data model for:
   - leads
   - lead_events
   - businesses
3. A lead lifecycle/state model.
4. A service flow for:
   - GoDaddy email-based lead intake
   - manual lead entry
   - owner notification
   - customer auto-acknowledgment
5. Suggested backend API endpoints for:
   - email intake
   - manual intake
   - status updates
   - lead summaries
6. Pseudocode for:
   - parsing a GoDaddy lead email
   - deduplicating leads
   - triggering owner and customer notifications
7. A phased implementation plan:
   - Phase 1: manual lead capture
   - Phase 2: email intake parser
   - Phase 3: SMS and reminders
   - Phase 4: reporting and escalation
8. UX guidance for making the experience contractor-friendly and mobile-first.
9. Suggestions for what to mock first so development can begin before live integrations are finished.

Constraints:
- Keep it lightweight and MVP-friendly.
- Assume one developer is building this.
- Prefer boring, reliable technology.
- Avoid over-engineering.
- Use plain Markdown and practical examples.
- Optimize for rapid prototyping.

Output format:
- Executive summary
- Markdown design doc
- Data model
- API suggestions
- Pseudocode
- Phased implementation plan
- Recommended next coding steps
```

---

## Recommended File Location

```text
docs/lead-intake-engine.codex.md
```

---

## Notes for Use

- Paste the prompt into Codex as-is.
- Use it after the `lead-intake-engine.md` spec is already in the repo.
- Keep generated output lightweight and implementation-focused.
- Prioritize manual entry and email parsing before more advanced integrations.
