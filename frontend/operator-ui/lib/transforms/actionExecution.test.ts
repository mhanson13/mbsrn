import { actionExecutionMocks } from "../mocks/actionExecution.mock";
import {
  applyActionDecisionLocally,
  deriveActionControls,
  deriveActionStatePresentation,
  deriveDecisionState,
  deriveOutputReview,
} from "./actionExecution";

describe("deriveActionControls", () => {
  it("returns review + automation controls for recommendation-only review with automation available", () => {
    const controls = deriveActionControls(actionExecutionMocks.recommendationOnlyReview);

    expect(controls[0]).toMatchObject({
      type: "review_recommendation",
      enabled: true,
      emphasis: "primary",
    });
    expect(controls[1]).toMatchObject({
      type: "run_automation",
      enabled: true,
      emphasis: "secondary",
    });
  });

  it("returns disabled view-automation-status with explicit reason while automation is in progress", () => {
    const controls = deriveActionControls(actionExecutionMocks.waitingOnAutomation);

    expect(controls).toHaveLength(1);
    expect(controls[0]).toMatchObject({
      type: "view_automation_status",
      enabled: false,
      emphasis: "primary",
    });
    expect(controls[0].reason || "").toMatch(/in progress/i);
  });

  it("returns review-output + mark-completed for output-ready items", () => {
    const controls = deriveActionControls(actionExecutionMocks.automationOutputReady);

    expect(controls[0]).toMatchObject({
      type: "review_output",
      enabled: true,
      emphasis: "primary",
    });
    expect(controls[1]).toMatchObject({
      type: "mark_completed",
      enabled: true,
      emphasis: "secondary",
    });
  });

  it("returns blocked control with explicit reason for blocked state", () => {
    const controls = deriveActionControls(actionExecutionMocks.blockedUnavailable);

    expect(controls).toHaveLength(1);
    expect(controls[0]).toMatchObject({
      type: "blocked",
      enabled: false,
      label: "Action blocked",
    });
    expect(controls[0].reason).toContain("Upstream run failed");
  });

  it("returns muted completed control and optional review-output control for completed state", () => {
    const controls = deriveActionControls(actionExecutionMocks.completedActed);

    expect(controls[0]).toMatchObject({
      type: "mark_completed",
      enabled: false,
      label: "Completed",
      emphasis: "muted",
    });
    expect(controls[1]).toMatchObject({
      type: "review_output",
      enabled: true,
      emphasis: "secondary",
    });
  });

  it("keeps informational-only items non-actionable", () => {
    const controls = deriveActionControls(actionExecutionMocks.informationalOnly);

    expect(controls).toHaveLength(1);
    expect(controls[0]).toMatchObject({
      type: "blocked",
      enabled: false,
      label: "No immediate action",
      emphasis: "muted",
    });
  });

  it("preserves review-first trust semantics for informational output-ready items", () => {
    const controls = deriveActionControls({
      id: "informational-output-ready",
      title: "Informational output ready item",
      actionStateCode: "automation_output_ready",
      linkedOutputId: "rec-run-999",
      trustTier: "informational_candidate",
    });

    expect(controls[0]).toMatchObject({
      type: "review_output",
      enabled: true,
      label: "Review output (informational)",
    });
    expect(controls[1]).toMatchObject({
      type: "mark_completed",
      enabled: false,
      label: "Mark completed (review first)",
      emphasis: "muted",
    });
    expect(controls[1].reason || "").toMatch(/requires operator review/i);
  });

  it("maps accepted decision to completed state with deterministic outcome and next step", () => {
    const decisionState = deriveDecisionState("accepted");

    expect(decisionState).toMatchObject({
      actionStateCode: "completed_acted",
      outcome: "Automation output accepted.",
      nextStep: "Track execution impact or move to the next recommended action.",
    });
  });

  it("maps rejected decision to blocked state with deterministic outcome and next step", () => {
    const decisionState = deriveDecisionState("rejected");

    expect(decisionState).toMatchObject({
      actionStateCode: "blocked_unavailable",
      outcome: "Automation output rejected.",
      nextStep: "Review recommendation context or adjust inputs before retrying.",
      blockedReason: "Operator rejected this output after review.",
    });
  });

  it("maps deferred decision to recommendation review state with deterministic outcome and next step", () => {
    const decisionState = deriveDecisionState("deferred");

    expect(decisionState).toMatchObject({
      actionStateCode: "recommendation_only_review",
      outcome: "Automation output review deferred.",
      nextStep: "Return later to review this output before acting.",
    });
  });

  it("applies accepted decision locally and transitions to completed_acted", () => {
    const updated = applyActionDecisionLocally(actionExecutionMocks.automationOutputReady, "accepted");

    expect(updated.actionStateCode).toBe("completed_acted");
    expect(updated.decision).toBe("accepted");
    expect(updated.outputReview?.outputId).toBe("rec-run-123");
  });

  it("applies rejected decision locally and transitions to blocked_unavailable", () => {
    const updated = applyActionDecisionLocally(actionExecutionMocks.automationOutputReady, "rejected");

    expect(updated.actionStateCode).toBe("blocked_unavailable");
    expect(updated.decision).toBe("rejected");
    expect(updated.blockedReason).toBe("Operator rejected this output after review.");
  });

  it("applies deferred decision locally without losing output linkage", () => {
    const updated = applyActionDecisionLocally(actionExecutionMocks.automationOutputReady, "deferred");

    expect(updated.actionStateCode).toBe("recommendation_only_review");
    expect(updated.decision).toBe("deferred");
    expect(updated.linkedOutputId).toBe("rec-run-123");
    expect(updated.outputReview?.outputId).toBe("rec-run-123");
  });

  it("derives output review from linked output id when explicit review payload is missing", () => {
    const outputReview = deriveOutputReview({
      id: "fallback-output-item",
      title: "Fallback output review item",
      actionStateCode: "automation_output_ready",
      linkedOutputId: "rec-run-fallback",
    });

    expect(outputReview).toMatchObject({
      outputId: "rec-run-fallback",
    });
  });

  it("uses decision-driven action state presentation when decision is present", () => {
    const updated = applyActionDecisionLocally(actionExecutionMocks.automationOutputReady, "rejected");
    const presentation = deriveActionStatePresentation({
      item: updated,
      fallbackLabel: "Automation output ready",
      fallbackBadgeClass: "badge badge-success",
      fallbackOutcome: "Fallback outcome",
      fallbackNextStep: "Fallback next step",
    });

    expect(presentation.label).toBe("Blocked / unavailable");
    expect(presentation.badgeClass).toBe("badge badge-error");
    expect(presentation.outcome).toBe("Automation output rejected.");
  });

  it("uses decision-driven completed presentation for accepted decisions", () => {
    const updated = applyActionDecisionLocally(actionExecutionMocks.automationOutputReady, "accepted");
    const presentation = deriveActionStatePresentation({
      item: updated,
      fallbackLabel: "Automation output ready",
      fallbackBadgeClass: "badge badge-success",
      fallbackOutcome: "Fallback outcome",
      fallbackNextStep: "Fallback next step",
    });

    expect(presentation.label).toBe("Completed / acted on");
    expect(presentation.badgeClass).toBe("badge badge-success");
    expect(presentation.outcome).toBe("Automation output accepted.");
    expect(presentation.nextStep).toBe("Track execution impact or move to the next recommended action.");
  });

  it("uses decision-driven recommendation review presentation for deferred decisions", () => {
    const updated = applyActionDecisionLocally(actionExecutionMocks.automationOutputReady, "deferred");
    const presentation = deriveActionStatePresentation({
      item: updated,
      fallbackLabel: "Automation output ready",
      fallbackBadgeClass: "badge badge-success",
      fallbackOutcome: "Fallback outcome",
      fallbackNextStep: "Fallback next step",
    });

    expect(presentation.label).toBe("Recommendation-only review");
    expect(presentation.badgeClass).toBe("badge badge-warn");
    expect(presentation.outcome).toBe("Automation output review deferred.");
    expect(presentation.nextStep).toBe("Return later to review this output before acting.");
  });
});
