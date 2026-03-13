# Pilot Readiness Checklist

## Summary

Create and validate a pilot-readiness checklist for the current backend so the system can support the first real contractor pilot safely.

## Scope

Cross-cutting review of:

- lead intake
- notification dispatch
- business settings
- reminders
- local configuration
- migration/run scripts

## Goals

- Confirm the backend can support a pilot for one or more real businesses.
- Identify remaining gaps before a first live rollout.
- Separate "must fix before pilot" from "can wait until after pilot".

## Tasks

- [ ] Verify local run/test scripts are reliable.
- [ ] Verify migrations work from a clean database.
- [ ] Verify lead intake to notification flow end to end.
- [ ] Verify business settings control actual behavior.
- [ ] Document must-fix items before pilot.

## Acceptance Criteria

- A written pilot checklist exists.
- Remaining risks are prioritized.
- The team can clearly answer "what must be done before onboarding T&M Fire or Lars Construction?"
