import Link from "next/link";

import type { ActionDecision, ActionExecutionItem } from "../../lib/api/types";
import { deriveOutputReview } from "../../lib/transforms/actionExecution";

type OutputReviewProps = {
  item: ActionExecutionItem;
  stateLabel: string;
  stateBadgeClass: string;
  outcome: string;
  nextStep: string;
  onDecision?: (decision: ActionDecision) => void;
  decisionPending?: boolean;
  decisionError?: string | null;
  resolveOutputHref?: (outputId: string) => string | undefined;
  readOnly?: boolean;
  className?: string;
  "data-testid"?: string;
};

const DECISION_BUTTONS: Array<{
  decision: ActionDecision;
  label: string;
  className: string;
}> = [
  { decision: "accepted", label: "Accept", className: "button button-primary button-inline" },
  { decision: "rejected", label: "Reject", className: "button button-secondary button-inline" },
  { decision: "deferred", label: "Defer", className: "button button-tertiary button-inline" },
];

function trustBadgeConfig(trustTier: ActionExecutionItem["trustTier"]): {
  label: string;
  className: string;
} | null {
  if (trustTier === "trusted_verified") {
    return { label: "Trusted evidence", className: "badge badge-success" };
  }
  if (trustTier === "informational_unverified") {
    return { label: "Informational (unverified)", className: "badge badge-muted" };
  }
  if (trustTier === "informational_candidate") {
    return { label: "Informational (candidate)", className: "badge badge-muted" };
  }
  return null;
}

function decisionSummary(decision: ActionDecision | null | undefined): string | null {
  if (decision === "accepted") {
    return "Decision captured: accepted";
  }
  if (decision === "rejected") {
    return "Decision captured: rejected";
  }
  if (decision === "deferred") {
    return "Decision captured: deferred";
  }
  return null;
}

function shouldRenderDecisionButtons(item: ActionExecutionItem, readOnly: boolean): boolean {
  if (readOnly) {
    return false;
  }
  if (item.actionStateCode !== "automation_output_ready" && item.actionStateCode !== "recommendation_only_review") {
    return false;
  }
  const review = deriveOutputReview(item);
  return Boolean(review?.outputId || review?.summary || review?.details);
}

export function OutputReview({
  item,
  stateLabel,
  stateBadgeClass,
  outcome,
  nextStep,
  onDecision,
  decisionPending = false,
  decisionError = null,
  resolveOutputHref,
  readOnly = false,
  className = "",
  "data-testid": dataTestId,
}: OutputReviewProps) {
  const review = deriveOutputReview(item);
  if (!review && !item.decision) {
    return null;
  }

  const outputId = review?.outputId || null;
  const summary = review?.summary || "Output is available for operator review.";
  const details = review?.details || null;
  const sourceLabel = review?.sourceLabel || "Automation output";
  const trustBadge = trustBadgeConfig(item.trustTier);
  const decisionCapturedLabel = decisionSummary(item.decision);
  const outputHref = outputId && resolveOutputHref ? resolveOutputHref(outputId) : undefined;
  const showDecisionButtons = shouldRenderDecisionButtons(item, readOnly) && Boolean(onDecision);
  const wrapperClassName = ["output-review", className].filter(Boolean).join(" ");

  return (
    <div className={wrapperClassName} data-testid={dataTestId}>
      <div className="link-row">
        <span className={stateBadgeClass}>{stateLabel}</span>
        <span className="badge badge-muted">{sourceLabel}</span>
        {trustBadge ? <span className={trustBadge.className}>{trustBadge.label}</span> : null}
      </div>
      <p className="hint">{summary}</p>
      <p className="hint muted">{outcome}</p>
      <p className="hint muted">Next step: {nextStep}</p>
      {outputId ? (
        <p className="hint muted">
          <span className="text-strong">Output reference:</span>{" "}
          {outputHref ? <Link href={outputHref}><code>{outputId}</code></Link> : <code>{outputId}</code>}
        </p>
      ) : null}
      {details ? (
        <details className="output-review-details">
          <summary>View output details</summary>
          <p className="hint muted">{details}</p>
        </details>
      ) : null}
      {decisionCapturedLabel ? <p className="hint muted text-strong">{decisionCapturedLabel}</p> : null}
      {showDecisionButtons ? (
        <div className="output-review-actions">
          {DECISION_BUTTONS.map((button) => (
            <button
              key={`${item.id}-${button.decision}`}
              type="button"
              className={button.className}
              onClick={() => onDecision?.(button.decision)}
              disabled={decisionPending}
              data-testid={dataTestId ? `${dataTestId}-decision-${button.decision}` : undefined}
            >
              {decisionPending ? "Saving..." : button.label}
            </button>
          ))}
        </div>
      ) : null}
      {decisionError ? <p className="hint warning">{decisionError}</p> : null}
    </div>
  );
}
