import type { AutomationRun, Recommendation, RecommendationRun } from "./api/types";

export type OperatorActionStateCode =
  | "informational_only"
  | "recommendation_only_review"
  | "automation_output_ready"
  | "waiting_on_automation"
  | "blocked_unavailable"
  | "completed_acted";

export interface OperatorActionStateCue {
  code: OperatorActionStateCode;
  label: string;
  badgeClass: "badge badge-success" | "badge badge-warn" | "badge badge-muted" | "badge badge-error";
  summaryTone: "success" | "warning" | "neutral" | "danger";
  outcome: string;
  nextStep: string;
}

interface RecommendationActionStateInput {
  status: Recommendation["status"] | string | null | undefined;
  automationLinkedOutput: boolean;
  automationContextAvailable: boolean;
}

interface RecommendationRunActionStateInput {
  runStatus: RecommendationRun["status"] | string | null | undefined;
  producedRecommendationCount: number;
  automationLinkedOutput: boolean;
}

interface AutomationRunActionStateInput {
  runStatus: AutomationRun["status"] | string | null | undefined;
  hasRecommendationOutput: boolean;
  hasNarrativeOutput: boolean;
}

function normalizeStatus(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase();
}

function cue(
  code: OperatorActionStateCode,
  label: string,
  badgeClass: OperatorActionStateCue["badgeClass"],
  summaryTone: OperatorActionStateCue["summaryTone"],
  outcome: string,
  nextStep: string,
): OperatorActionStateCue {
  return {
    code,
    label,
    badgeClass,
    summaryTone,
    outcome,
    nextStep,
  };
}

export function deriveRecommendationOperatorActionState(
  input: RecommendationActionStateInput,
): OperatorActionStateCue {
  const normalizedStatus = normalizeStatus(input.status);

  if (normalizedStatus === "accepted") {
    return cue(
      "completed_acted",
      "Completed / acted on",
      "badge badge-success",
      "success",
      "Recommendation apply action is already recorded.",
      "Confirm visibility after the next refresh cycle.",
    );
  }

  if (normalizedStatus === "dismissed" || normalizedStatus === "resolved" || normalizedStatus === "snoozed") {
    return cue(
      "informational_only",
      "Informational only",
      "badge badge-muted",
      "neutral",
      "Recommendation is deferred or archived for context.",
      "No immediate action unless site context changes.",
    );
  }

  if (normalizedStatus === "open" || normalizedStatus === "in_progress") {
    if (input.automationLinkedOutput) {
      return cue(
        "automation_output_ready",
        "Automation output ready",
        "badge badge-success",
        "success",
        "Automation produced this recommendation output for operator review.",
        "Review details and decide whether to apply or dismiss.",
      );
    }
    if (input.automationContextAvailable) {
      return cue(
        "recommendation_only_review",
        "Recommendation-only review",
        "badge badge-warn",
        "warning",
        "Recommendation is available but not tied to a completed automation output.",
        "Review and decide manually based on recommendation evidence.",
      );
    }
    return cue(
      "waiting_on_automation",
      "Waiting on automation context",
      "badge badge-warn",
      "warning",
      "Automation context has not been captured for this recommendation yet.",
      "Wait for automation context or continue with manual review.",
    );
  }

  if (normalizedStatus === "queued" || normalizedStatus === "running") {
    return cue(
      "waiting_on_automation",
      "Waiting on automation",
      "badge badge-warn",
      "warning",
      "Recommendation state is still progressing.",
      "Wait for completion before making a final decision.",
    );
  }

  if (normalizedStatus === "failed" || normalizedStatus === "error") {
    return cue(
      "blocked_unavailable",
      "Blocked / unavailable",
      "badge badge-error",
      "danger",
      "Recommendation lifecycle entered a failed state.",
      "Review blockers and rerun generation if needed.",
    );
  }

  return cue(
    "recommendation_only_review",
    "Needs operator review",
    "badge badge-warn",
    "warning",
    "Recommendation state requires operator verification.",
    "Review recommendation details and choose the next action.",
  );
}

export function deriveRecommendationRunOperatorActionState(
  input: RecommendationRunActionStateInput,
): OperatorActionStateCue {
  const normalizedStatus = normalizeStatus(input.runStatus);

  if (normalizedStatus === "failed") {
    return cue(
      "blocked_unavailable",
      "Blocked / unavailable",
      "badge badge-error",
      "danger",
      "Recommendation run failed before reliable output was ready.",
      "Review run errors and rerun recommendations after resolving blockers.",
    );
  }

  if (normalizedStatus === "queued" || normalizedStatus === "running") {
    return cue(
      "waiting_on_automation",
      "Waiting on automation",
      "badge badge-warn",
      "warning",
      "Recommendation run is still in progress.",
      "Wait for run completion before acting on downstream recommendations.",
    );
  }

  if (normalizedStatus === "completed") {
    if (input.producedRecommendationCount > 0 && input.automationLinkedOutput) {
      return cue(
        "automation_output_ready",
        "Automation output ready",
        "badge badge-success",
        "success",
        "Completed run produced recommendation output linked to automation execution.",
        "Review generated recommendations and apply highest-priority actions first.",
      );
    }
    if (input.producedRecommendationCount > 0) {
      return cue(
        "recommendation_only_review",
        "Recommendation-only review",
        "badge badge-warn",
        "warning",
        "Completed run produced recommendations without automation linkage.",
        "Review recommendations manually and apply where appropriate.",
      );
    }
    return cue(
      "informational_only",
      "Informational only",
      "badge badge-muted",
      "neutral",
      "Run completed without reviewable recommendation output.",
      "No immediate action from this run unless context changes.",
    );
  }

  return cue(
    "recommendation_only_review",
    "Needs operator review",
    "badge badge-warn",
    "warning",
    "Run state requires operator verification before action.",
    "Review run context and identify next operator step.",
  );
}

export function deriveAutomationRunOperatorActionState(
  input: AutomationRunActionStateInput,
): OperatorActionStateCue {
  const normalizedStatus = normalizeStatus(input.runStatus);
  const hasLinkedOutput = input.hasRecommendationOutput || input.hasNarrativeOutput;

  if (normalizedStatus === "failed") {
    return cue(
      "blocked_unavailable",
      "Blocked / unavailable",
      "badge badge-error",
      "danger",
      "Automation run failed before completing all lifecycle steps.",
      "Review failed steps, resolve blockers, and rerun automation.",
    );
  }

  if (normalizedStatus === "queued" || normalizedStatus === "running") {
    return cue(
      "waiting_on_automation",
      "Waiting on automation",
      "badge badge-warn",
      "warning",
      "Automation lifecycle is active and output may still change.",
      "Wait for completion before acting on linked recommendation outputs.",
    );
  }

  if (normalizedStatus === "completed" && hasLinkedOutput) {
    return cue(
      "automation_output_ready",
      "Automation output ready",
      "badge badge-success",
      "success",
      input.hasNarrativeOutput
        ? "Automation completed with linked recommendation and narrative outputs."
        : "Automation completed with linked recommendation output.",
      "Review linked outputs and confirm the next recommendation action.",
    );
  }

  if (normalizedStatus === "completed") {
    return cue(
      "informational_only",
      "Informational only",
      "badge badge-muted",
      "neutral",
      "Automation completed without linked recommendation output.",
      "Review run details only if additional follow-up is needed.",
    );
  }

  return cue(
    "informational_only",
    "Informational only",
    "badge badge-muted",
    "neutral",
    "Automation lifecycle state is available for monitoring.",
    "Review run details to determine if further action is needed.",
  );
}
