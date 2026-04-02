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
  onBindAutomation?: (actionExecutionItemId: string, automationId: string) => Promise<void> | void;
  bindAutomationTargetId?: string | null;
  bindAutomationPendingByActionId?: Record<string, boolean>;
  bindAutomationErrorByActionId?: Record<string, string | null>;
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

function lineageActivationBadgeClass(activationState: "pending" | "activated"): string {
  return activationState === "activated" ? "badge badge-success" : "badge badge-muted";
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
  onBindAutomation,
  bindAutomationTargetId = null,
  bindAutomationPendingByActionId = {},
  bindAutomationErrorByActionId = {},
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
  const actionLineage = item.actionLineage || null;
  const chainedDrafts = actionLineage?.chained_drafts || [];
  const activatedActions = actionLineage?.activated_actions || [];
  const hasLineage = Boolean(actionLineage && (chainedDrafts.length > 0 || activatedActions.length > 0));
  const visibleChainedDrafts = chainedDrafts.slice(0, 3);
  const hiddenDraftCount = Math.max(chainedDrafts.length - visibleChainedDrafts.length, 0);
  const activatedActionByDraftId = new Map(
    activatedActions
      .filter((action) => Boolean(action.source_draft_id))
      .map((action) => [action.source_draft_id, action] as const),
  );
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
      {hasLineage ? (
        <div className="output-review-lineage" data-testid={dataTestId ? `${dataTestId}-lineage` : undefined}>
          <p className="hint muted">
            <span className="text-strong">Next-step lineage:</span>{" "}
            {actionLineage?.counts.chained_draft_count || 0} draft
            {(actionLineage?.counts.chained_draft_count || 0) === 1 ? "" : "s"}
            {" | "}
            {actionLineage?.counts.activated_action_count || 0} activated
            {" | "}
            {actionLineage?.counts.automation_ready_count || 0} automation-ready
          </p>
          {visibleChainedDrafts.length > 0 ? (
            <ul className="output-review-lineage-list">
              {visibleChainedDrafts.map((draft) => {
                const activatedAction = activatedActionByDraftId.get(draft.id);
                const automationBindingState =
                  activatedAction?.automation_binding_state === "bound" ? "bound" : "unbound";
                const boundAutomationId = activatedAction?.bound_automation_id || null;
                const bindActionId = activatedAction?.id || null;
                const bindPending = bindActionId ? Boolean(bindAutomationPendingByActionId[bindActionId]) : false;
                const bindError = bindActionId ? bindAutomationErrorByActionId[bindActionId] : null;
                const canBindAutomation = Boolean(
                  !readOnly
                  && onBindAutomation
                  && bindActionId
                  && bindAutomationTargetId
                  && draft.automation_ready
                  && automationBindingState !== "bound",
                );
                return (
                  <li key={draft.id} className="output-review-lineage-item">
                    <div className="output-review-lineage-item-header">
                      <span className="hint">{draft.title}</span>
                      <span className={lineageActivationBadgeClass(draft.activation_state)}>
                        {draft.activation_state === "activated" ? "Activated" : "Next step available"}
                      </span>
                      {draft.automation_ready ? <span className="badge badge-muted">Automation-ready</span> : null}
                      {activatedAction && draft.automation_ready ? (
                        <span className={automationBindingState === "bound" ? "badge badge-success" : "badge badge-warn"}>
                          {automationBindingState === "bound" ? "Bound to automation" : "Unbound"}
                        </span>
                      ) : null}
                    </div>
                    {activatedAction ? (
                      <p className="hint muted">
                        Linked action <code>{activatedAction.id}</code> is currently {activatedAction.state}.
                      </p>
                    ) : null}
                    {boundAutomationId ? (
                      <p className="hint muted">
                        Bound automation: <code>{boundAutomationId}</code>
                      </p>
                    ) : null}
                    {draft.automation_template_key ? (
                      <p className="hint muted">Uses template: {draft.automation_template_key}</p>
                    ) : null}
                    {activatedAction && draft.automation_ready && automationBindingState !== "bound" ? (
                      canBindAutomation ? (
                        <div className="link-row">
                          <button
                            type="button"
                            className="button button-tertiary button-inline"
                            onClick={() => onBindAutomation?.(activatedAction.id, bindAutomationTargetId as string)}
                            disabled={bindPending}
                            data-testid={dataTestId ? `${dataTestId}-bind-${activatedAction.id}` : undefined}
                          >
                            {bindPending ? "Binding..." : "Bind automation"}
                          </button>
                        </div>
                      ) : (
                        <p className="hint muted">Automation-ready but no automation record is available to bind.</p>
                      )
                    ) : null}
                    {bindError ? <p className="hint warning">{bindError}</p> : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
          {hiddenDraftCount > 0 ? (
            <p className="hint muted">+{hiddenDraftCount} additional draft{hiddenDraftCount === 1 ? "" : "s"}</p>
          ) : null}
        </div>
      ) : null}
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
