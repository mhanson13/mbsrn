import type {
  ActionControl,
  ActionDecision,
  ActionExecutionItem,
  ActionExecutionStateCode,
  ActionOutputReview,
} from "../api/types";

type ActionBadgeClass =
  | "badge badge-success"
  | "badge badge-warn"
  | "badge badge-muted"
  | "badge badge-error";

type ActionStateDefaults = {
  label: string;
  badgeClass: ActionBadgeClass;
  outcome: string;
  nextStep: string;
};

export interface ActionStatePresentation {
  code: ActionExecutionStateCode;
  label: string;
  badgeClass: ActionBadgeClass;
  outcome: string;
  nextStep: string;
}

export interface ActionDecisionState {
  decision: ActionDecision;
  actionStateCode: ActionExecutionStateCode;
  outcome: string;
  nextStep: string;
  blockedReason?: string | null;
}

const ACTION_STATE_DEFAULTS: Record<ActionExecutionStateCode, ActionStateDefaults> = {
  informational_only: {
    label: "Informational only",
    badgeClass: "badge badge-muted",
    outcome: "This item is informational and does not require immediate execution.",
    nextStep: "Keep context visible and review when related workflow state changes.",
  },
  recommendation_only_review: {
    label: "Recommendation-only review",
    badgeClass: "badge badge-warn",
    outcome: "Recommendation context is available for operator review.",
    nextStep: "Review recommendation details and decide whether to proceed or defer.",
  },
  automation_output_ready: {
    label: "Automation output ready",
    badgeClass: "badge badge-success",
    outcome: "Automation output is ready for operator review.",
    nextStep: "Review output and capture a decision.",
  },
  waiting_on_automation: {
    label: "Waiting on automation",
    badgeClass: "badge badge-warn",
    outcome: "Automation is still in progress or pending context linkage.",
    nextStep: "Track automation status before taking a downstream decision.",
  },
  blocked_unavailable: {
    label: "Blocked / unavailable",
    badgeClass: "badge badge-error",
    outcome: "Action is blocked until upstream issues are resolved.",
    nextStep: "Review blockers, then retry or adjust before acting.",
  },
  completed_acted: {
    label: "Completed / acted on",
    badgeClass: "badge badge-success",
    outcome: "Action has already been completed by an operator decision.",
    nextStep: "Track impact visibility and move to the next actionable item.",
  },
};

function blockedControl(label: string, reason: string, emphasis: "secondary" | "muted" = "muted"): ActionControl {
  return {
    type: "blocked",
    label,
    enabled: false,
    reason,
    emphasis,
  };
}

function hasInformationalTrustTier(item: ActionExecutionItem): boolean {
  return item.trustTier === "informational_unverified" || item.trustTier === "informational_candidate";
}

export function deriveOutputReview(item: ActionExecutionItem): ActionOutputReview | null {
  const review = item.outputReview || null;
  const outputId = review?.outputId || item.linkedOutputId || null;
  const summary = review?.summary || null;
  const details = review?.details || null;
  const sourceLabel = review?.sourceLabel || null;
  const stepDetails = review?.stepDetails || null;

  if (!outputId && !summary && !details && !sourceLabel && !stepDetails) {
    return null;
  }

  return {
    outputId,
    summary,
    details,
    sourceLabel,
    stepDetails,
  };
}

export function deriveDecisionState(decision: ActionDecision): ActionDecisionState {
  if (decision === "accepted") {
    return {
      decision,
      actionStateCode: "completed_acted",
      outcome: "Automation output accepted.",
      nextStep: "Track execution impact or move to the next recommended action.",
    };
  }
  if (decision === "rejected") {
    return {
      decision,
      actionStateCode: "blocked_unavailable",
      blockedReason: "Operator rejected this output after review.",
      outcome: "Automation output rejected.",
      nextStep: "Review recommendation context or adjust inputs before retrying.",
    };
  }
  return {
    decision,
    actionStateCode: "recommendation_only_review",
    outcome: "Automation output review deferred.",
    nextStep: "Return later to review this output before acting.",
  };
}

export function applyActionDecisionLocally(item: ActionExecutionItem, decision: ActionDecision): ActionExecutionItem {
  const decisionState = deriveDecisionState(decision);
  const currentOutputReview = deriveOutputReview(item);
  const outputReview: ActionOutputReview | null = {
    outputId: currentOutputReview?.outputId || item.linkedOutputId || null,
    summary: currentOutputReview?.summary || decisionState.outcome,
    details: currentOutputReview?.details || null,
    sourceLabel: currentOutputReview?.sourceLabel || item.outputReview?.sourceLabel || "Automation output",
    stepDetails: currentOutputReview?.stepDetails || null,
  };

  return {
    ...item,
    decision,
    actionStateCode: decisionState.actionStateCode,
    blockedReason: decisionState.blockedReason ?? item.blockedReason ?? null,
    outputReview,
  };
}

export function deriveActionStatePresentation(params: {
  item: ActionExecutionItem;
  fallbackLabel?: string | null;
  fallbackBadgeClass?: ActionBadgeClass | null;
  fallbackOutcome?: string | null;
  fallbackNextStep?: string | null;
}): ActionStatePresentation {
  const { item, fallbackLabel, fallbackBadgeClass, fallbackOutcome, fallbackNextStep } = params;
  const decisionState = item.decision ? deriveDecisionState(item.decision) : null;
  const effectiveCode = decisionState?.actionStateCode || item.actionStateCode;
  const defaults = ACTION_STATE_DEFAULTS[effectiveCode];

  return {
    code: effectiveCode,
    label: decisionState ? defaults.label : fallbackLabel || defaults.label,
    badgeClass: decisionState ? defaults.badgeClass : fallbackBadgeClass || defaults.badgeClass,
    outcome: decisionState?.outcome || fallbackOutcome || defaults.outcome,
    nextStep: decisionState?.nextStep || fallbackNextStep || defaults.nextStep,
  };
}

export function deriveActionControls(item: ActionExecutionItem): ActionControl[] {
  const controls: ActionControl[] = [];
  const informationalTrust = hasInformationalTrustTier(item);

  switch (item.actionStateCode) {
    case "informational_only":
      controls.push(
        blockedControl(
          "No immediate action",
          item.blockedReason || "This item is informational and does not require execution right now.",
          "muted",
        ),
      );
      break;
    case "recommendation_only_review":
      controls.push({
        type: "review_recommendation",
        label: informationalTrust ? "Review recommendation (informational)" : "Review recommendation",
        enabled: true,
        reason: informationalTrust
          ? "Review-first guidance: informational trust context should be validated before acting."
          : undefined,
        emphasis: "primary",
      });
      if (item.automationAvailable) {
        controls.push({
          type: "run_automation",
          label: "Run SEO automation",
          enabled: true,
          reason: "Run SEO automation to generate refreshed output linkage for operator review.",
          emphasis: "secondary",
        });
      } else {
        controls.push(
          blockedControl(
            "Automation unavailable",
            "Automation is not available for this item yet.",
            "secondary",
          ),
        );
      }
      break;
    case "waiting_on_automation":
      controls.push({
        type: "view_automation_status",
        label: "View automation status",
        enabled: false,
        reason: item.automationInFlight
          ? "Automation is currently in progress. Review status while waiting for completion."
          : "Automation context is pending. Check run status before acting.",
        emphasis: "primary",
      });
      break;
    case "automation_output_ready":
      controls.push({
        type: "review_output",
        label: informationalTrust ? "Review output (informational)" : "Review output",
        enabled: Boolean(item.linkedOutputId),
        reason: item.linkedOutputId
          ? informationalTrust
            ? "Output is ready but should be reviewed with informational trust context."
            : undefined
          : "No linked output is available yet for review.",
        emphasis: "primary",
      });
      controls.push({
        type: "mark_completed",
        label: informationalTrust ? "Mark completed (review first)" : "Mark completed",
        enabled: !informationalTrust,
        reason: informationalTrust
          ? "Informational trust context requires operator review before completion."
          : "Mark as completed after confirming output and follow-up tasks.",
        emphasis: informationalTrust ? "muted" : "secondary",
      });
      break;
    case "blocked_unavailable":
      controls.push(
        blockedControl(
          "Action blocked",
          item.blockedReason || "This item is blocked or unavailable until upstream issues are resolved.",
          "muted",
        ),
      );
      break;
    case "completed_acted":
      controls.push({
        type: "mark_completed",
        label: "Completed",
        enabled: false,
        reason: "This item has already been acted on.",
        emphasis: "muted",
      });
      if (item.linkedOutputId) {
        controls.push({
          type: "review_output",
          label: "Review output",
          enabled: true,
          reason: "Open linked output for verification or follow-up review.",
          emphasis: "secondary",
        });
      }
      break;
    default:
      controls.push(
        blockedControl(
          "No action available",
          "Action controls are unavailable for this item state.",
          "muted",
        ),
      );
      break;
  }

  if (controls.length === 0) {
    controls.push(
      blockedControl(
        "No action available",
        "No deterministic action controls were derived for this item.",
      ),
    );
  }

  return controls;
}
