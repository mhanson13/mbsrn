import Link from "next/link";
import type { RecommendationTargetContext } from "../../../lib/api/types";

export interface RecommendationDetailClarityView {
  observedPattern: string | null;
  observedGap: string | null;
  recommendedAction: string | null;
  evidenceContextLines: string[];
}

interface RecommendationDetailClarityBuildParams {
  actionDelta: {
    observedCompetitorPattern: string;
    observedSiteGap: string;
    recommendedOperatorAction: string;
    evidenceStrength: "high" | "medium" | "low";
  } | null;
  evidenceSummary: string | null;
  observedGapSummary: string | null;
  actionClarity: string | null;
  expectedOutcome: string | null;
  competitorLinkageSummary: string | null;
  evidenceTrace: string[];
  targetContext: RecommendationTargetContext | null;
  targetPageHints: string[];
  targetContentSummary: string | null;
  formatActionDeltaEvidenceStrength: (value: "high" | "medium" | "low") => string;
  formatTargetContext: (value: RecommendationTargetContext) => string;
}

export function buildRecommendationDetailClarityView(
  params: RecommendationDetailClarityBuildParams,
): RecommendationDetailClarityView {
  const observedPattern =
    params.actionDelta?.observedCompetitorPattern
    || params.evidenceSummary
    || null;
  const observedGap =
    params.actionDelta?.observedSiteGap
    || params.observedGapSummary
    || params.competitorLinkageSummary
    || null;
  const recommendedAction =
    params.actionDelta?.recommendedOperatorAction
    || params.actionClarity
    || params.expectedOutcome
    || null;
  const evidenceContextLines: string[] = [];
  if (params.actionDelta) {
    evidenceContextLines.push(
      `Evidence strength: ${params.formatActionDeltaEvidenceStrength(params.actionDelta.evidenceStrength)}.`,
    );
  }
  if (params.evidenceTrace.length > 0) {
    evidenceContextLines.push(`Evidence trace: ${params.evidenceTrace.join(" · ")}`);
  }
  if (params.targetContext) {
    evidenceContextLines.push(`Target context: ${params.formatTargetContext(params.targetContext)}`);
  }
  if (params.targetPageHints.length > 0) {
    evidenceContextLines.push(`Likely pages: ${params.targetPageHints.join(", ")}`);
  }
  if (params.targetContentSummary) {
    evidenceContextLines.push(`Content to update: ${params.targetContentSummary}`);
  }
  if (params.expectedOutcome && params.expectedOutcome !== recommendedAction) {
    evidenceContextLines.push(`Expected outcome: ${params.expectedOutcome}`);
  }
  return {
    observedPattern,
    observedGap,
    recommendedAction,
    evidenceContextLines,
  };
}

export function hasRecommendationDetailClarityContent(clarity: RecommendationDetailClarityView): boolean {
  return Boolean(
    clarity.observedPattern
    || clarity.observedGap
    || clarity.recommendedAction
    || clarity.evidenceContextLines.length > 0,
  );
}

export function RecommendationDetailClarity({
  clarity,
  bucketKey,
  testId = "recommendation-detail-clarity",
}: {
  clarity: RecommendationDetailClarityView;
  bucketKey: string;
  testId?: string;
}): JSX.Element | null {
  if (!hasRecommendationDetailClarityContent(clarity)) {
    return null;
  }
  return (
    <div className={`recommendation-detail-clarity recommendation-detail-clarity-${bucketKey}`} data-testid={testId}>
      {clarity.observedPattern ? (
        <div className="recommendation-detail-clarity-row" data-testid="recommendation-clarity-observed-pattern">
          <span className="recommendation-detail-clarity-label">What we observed</span>
          <span className="hint muted">{clarity.observedPattern}</span>
        </div>
      ) : null}
      {clarity.observedGap ? (
        <div className="recommendation-detail-clarity-row" data-testid="recommendation-clarity-gap">
          <span className="recommendation-detail-clarity-label">What needs improvement</span>
          <span className="hint muted">{clarity.observedGap}</span>
        </div>
      ) : null}
      {clarity.recommendedAction ? (
        <div className="recommendation-detail-clarity-row recommendation-detail-clarity-row-action" data-testid="recommendation-clarity-action">
          <span className="recommendation-detail-clarity-label">What to do next</span>
          <strong>{clarity.recommendedAction}</strong>
        </div>
      ) : null}
      {clarity.evidenceContextLines.length > 0 ? (
        <div className="recommendation-detail-clarity-row recommendation-detail-clarity-row-evidence" data-testid="recommendation-clarity-evidence">
          <span className="recommendation-detail-clarity-label">Why this is recommended</span>
          <div className="stack-micro">
            {clarity.evidenceContextLines.map((line, index) => (
              <span key={`recommendation-clarity-evidence-${index}`} className="hint muted">
                {line}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

interface RecommendationBadgeView {
  key?: string;
  label: string;
  className: string;
}

interface RecommendationActionPlanStepView {
  key: string;
  stepNumber: number;
  title: string;
  instruction: string;
  beforeExample: string | null;
  afterExample: string | null;
}

interface RecommendationCompetitorEvidenceLinkView {
  key: string;
  competitorText: string;
  trustTierLabel: string | null;
  trustTierBadgeClass: string | null;
}

export interface RecommendationWorkspaceItemViewModel {
  id: string;
  rowId: string;
  detailHref: string;
  title: string;
  isFocused: boolean;
  detailsToggleLabel: string;
  detailClarityBucketKey: string;
  detailClarityTestId: string;
  detailClarity: RecommendationDetailClarityView;
  actionSummary: string | null;
  whyItMattersSummary: string | null;
  executionReadinessBadge: RecommendationBadgeView | null;
  effortHintLabel: string | null;
  isBlocked: boolean;
  blockingReason: string | null;
  hasActionabilitySummary: boolean;
  hasActionSectionDetails: boolean;
  hasEvidenceSectionDetails: boolean;
  hasReadinessSectionDetails: boolean;
  evidenceSummary: string | null;
  evidenceTrace: string[];
  observedGapSummary: string | null;
  showObservedGapSummary: boolean;
  actionClarity: string | null;
  expectedOutcome: string | null;
  whyNow: string | null;
  competitorInsight: string | null;
  competitorInfluenceBadge: RecommendationBadgeView | null;
  nextAction: string | null;
  executionTypeLabel: string | null;
  executionScope: string | null;
  executionInputs: string[];
  showExecutionBlocking: boolean;
  targetContextLabel: string | null;
  targetPageHints: string[];
  targetContentSummary: string | null;
  measurementContextLine: string | null;
  measurementSinceLine: string | null;
  hasMeasurementNoMatch: boolean;
  searchVisibilityContextLine: string | null;
  searchVisibilitySinceLine: string | null;
  searchQueriesLine: string | null;
  hasSearchNoMatch: boolean;
  effectivenessSummary: string | null;
  actionPlanSteps: RecommendationActionPlanStepView[];
  competitorLinkageSummary: string | null;
  competitorEvidenceLinks: RecommendationCompetitorEvidenceLinkView[];
  actionDeltaSummary: string | null;
  impactBadge: RecommendationBadgeView | null;
  eeatBadges: RecommendationBadgeView[];
  priorityReasons: RecommendationBadgeView[];
  progressBadge: RecommendationBadgeView;
  lifecycleBadge: RecommendationBadgeView | null;
  priorityLevelBadge: RecommendationBadgeView | null;
  priorityEffortHintLabel: string | null;
  priorityRationale: string | null;
  evidenceStrengthBadge: RecommendationBadgeView | null;
  category: string;
  severity: string;
  priorityScore: number;
  priorityBand: string;
}

interface RecommendationWorkspaceItemCardProps {
  view: RecommendationWorkspaceItemViewModel;
}

export function RecommendationWorkspaceItemCard({ view }: RecommendationWorkspaceItemCardProps): JSX.Element {
  return (
    <article
      id={view.rowId}
      data-testid={`recommendation-workspace-item-${view.id}`}
      className={[
        "workspace-recommendation-row-card",
        view.isFocused ? "start-here-target-active" : "",
      ].filter(Boolean).join(" ")}
    >
      <div className="workspace-recommendation-row-layout">
        <div
          className="workspace-recommendation-row-main workspace-recommendation-row-main-bounded"
          data-testid={`recommendation-row-main-${view.id}`}
        >
          <Link href={view.detailHref}>{view.title}</Link>
          {view.actionSummary ? (
            <span className="hint workspace-recommendation-summary-line" data-testid="recommendation-what-to-do-now-summary">
              <span className="workspace-recommendation-summary-label">What to do now</span>
              <strong>{view.actionSummary}</strong>
            </span>
          ) : null}
          {view.whyItMattersSummary ? (
            <span className="hint muted workspace-recommendation-summary-line" data-testid="recommendation-why-it-matters-summary">
              <span className="workspace-recommendation-summary-label">Why it matters</span>
              <span>{view.whyItMattersSummary}</span>
            </span>
          ) : null}
          {view.hasActionabilitySummary ? (
            <div className="hint muted workspace-recommendation-summary-line" data-testid="recommendation-actionability-summary">
              <span className="workspace-recommendation-summary-label">How actionable</span>
              <div className="link-row">
                {view.executionReadinessBadge ? (
                  <span className={view.executionReadinessBadge.className}>
                    {view.executionReadinessBadge.label}
                  </span>
                ) : null}
                {view.effortHintLabel ? (
                  <span className="badge badge-muted">Effort: {view.effortHintLabel}</span>
                ) : null}
                {view.isBlocked ? (
                  <span className="badge badge-warn">Blocked by prerequisite</span>
                ) : null}
              </div>
            </div>
          ) : null}
          <details className="workspace-recommendation-details" data-testid={`recommendation-details-${view.id}`}>
            <summary className="workspace-recommendation-details-toggle">{view.detailsToggleLabel}</summary>
            <div className="workspace-recommendation-details-content">
              <RecommendationDetailClarity
                clarity={view.detailClarity}
                bucketKey={view.detailClarityBucketKey}
                testId={view.detailClarityTestId}
              />
              {view.hasActionSectionDetails ? (
                <span className="workspace-recommendation-summary-label" data-testid="recommendation-action-section-label">
                  Action
                </span>
              ) : null}
              {view.hasEvidenceSectionDetails ? (
                <span className="workspace-recommendation-summary-label" data-testid="recommendation-evidence-section-label">
                  Why this matters
                </span>
              ) : null}
              {view.evidenceSummary ? (
                <span className="hint muted" data-testid="recommendation-evidence-summary">
                  Why this matters: {view.evidenceSummary}
                </span>
              ) : null}
              {view.evidenceTrace.length > 0 ? (
                <span className="hint muted" data-testid="recommendation-evidence-trace">
                  Evidence trace: {view.evidenceTrace.join(" · ")}
                </span>
              ) : null}
              {view.showObservedGapSummary && view.observedGapSummary ? (
                <span className="hint muted" data-testid="recommendation-observed-gap-summary">
                  Observed gap: {view.observedGapSummary}
                </span>
              ) : null}
              {view.actionClarity ? (
                <span className="hint muted" data-testid="recommendation-action-clarity">
                  Action: {view.actionClarity}
                </span>
              ) : null}
              {view.expectedOutcome ? (
                <span className="hint muted" data-testid="recommendation-expected-outcome">
                  Expected outcome: {view.expectedOutcome}
                </span>
              ) : null}
              {view.whyNow ? (
                <span className="hint muted" data-testid="recommendation-why-now">
                  Why now: {view.whyNow}
                </span>
              ) : null}
              {view.competitorInsight ? (
                <span className="hint muted" data-testid="recommendation-competitor-insight">
                  Competitor insight: {view.competitorInsight}
                </span>
              ) : null}
              {view.competitorInfluenceBadge ? (
                <span className="hint muted" data-testid="recommendation-competitor-influence">
                  Competitor influence:{" "}
                  <span className={view.competitorInfluenceBadge.className}>
                    {view.competitorInfluenceBadge.label}
                  </span>
                </span>
              ) : null}
              {view.nextAction ? (
                <span className="hint muted" data-testid="recommendation-next-action">
                  Next action: {view.nextAction}
                </span>
              ) : null}
              {view.executionReadinessBadge ? (
                <span className="hint muted" data-testid="recommendation-execution-readiness">
                  Execution readiness:{" "}
                  <span className={view.executionReadinessBadge.className}>
                    {view.executionReadinessBadge.label}
                  </span>
                </span>
              ) : null}
              {view.executionTypeLabel ? (
                <span className="hint muted" data-testid="recommendation-execution-type">
                  Execution type: {view.executionTypeLabel}
                </span>
              ) : null}
              {view.executionScope ? (
                <span className="hint muted" data-testid="recommendation-execution-scope">
                  Execution scope: {view.executionScope}
                </span>
              ) : null}
              {view.executionInputs.length > 0 ? (
                <span className="hint muted" data-testid="recommendation-execution-inputs">
                  Execution inputs: {view.executionInputs.join(" · ")}
                </span>
              ) : null}
              {view.showExecutionBlocking && view.blockingReason ? (
                <span className="hint muted" data-testid="recommendation-execution-blocking">
                  Execution blocker: {view.blockingReason}
                </span>
              ) : null}
              {view.targetContextLabel ? (
                <span className="hint muted" data-testid="recommendation-target-context">
                  Where: {view.targetContextLabel}
                </span>
              ) : null}
              {view.targetPageHints.length > 0 ? (
                <span className="hint muted" data-testid="recommendation-target-page-hints">
                  Likely pages: {view.targetPageHints.join(", ")}
                </span>
              ) : null}
              {view.targetContentSummary ? (
                <span className="hint muted" data-testid="recommendation-target-content-summary">
                  Content to update: {view.targetContentSummary}
                </span>
              ) : null}
              {view.measurementContextLine ? (
                <span className="hint muted" data-testid="recommendation-measurement-context">
                  Recent traffic for this page/topic: {view.measurementContextLine}
                </span>
              ) : null}
              {view.measurementSinceLine ? (
                <span className="hint muted" data-testid="recommendation-measurement-since">
                  Since this recommendation: {view.measurementSinceLine}
                </span>
              ) : null}
              {view.hasMeasurementNoMatch ? (
                <span className="hint muted" data-testid="recommendation-measurement-no-match">
                  No page-level measurement match available.
                </span>
              ) : null}
              {view.searchVisibilityContextLine ? (
                <span className="hint muted" data-testid="recommendation-search-context">
                  Recent search visibility for this page/topic: {view.searchVisibilityContextLine}
                </span>
              ) : null}
              {view.searchVisibilitySinceLine ? (
                <span className="hint muted" data-testid="recommendation-search-since">
                  Since this recommendation (search): {view.searchVisibilitySinceLine}
                </span>
              ) : null}
              {view.searchQueriesLine ? (
                <span className="hint muted" data-testid="recommendation-search-queries">
                  Top queries: {view.searchQueriesLine}
                </span>
              ) : null}
              {view.hasSearchNoMatch ? (
                <span className="hint muted" data-testid="recommendation-search-no-match">
                  No page-level search visibility match available.
                </span>
              ) : null}
              {view.effectivenessSummary ? (
                <span className="hint muted" data-testid="recommendation-effectiveness-summary">
                  Directional outcome: {view.effectivenessSummary}
                </span>
              ) : null}
              {view.actionPlanSteps.length > 0 ? (
                <div className="stack-tight" data-testid={`recommendation-action-plan-${view.id}`}>
                  <span className="hint muted">
                    <span className="text-strong">How to implement:</span>
                  </span>
                  <ol className="compact-list">
                    {view.actionPlanSteps.map((step) => (
                      <li key={step.key}>
                        <span className="hint muted">
                          <span className="text-strong">Step {step.stepNumber}:</span> {step.title}
                        </span>
                        <br />
                        <span className="hint muted">{step.instruction}</span>
                        {step.beforeExample ? (
                          <>
                            <br />
                            <span className="hint muted">Before: {step.beforeExample}</span>
                          </>
                        ) : null}
                        {step.afterExample ? (
                          <>
                            <br />
                            <span className="hint muted">After: {step.afterExample}</span>
                          </>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                </div>
              ) : null}
              {view.competitorLinkageSummary ? (
                <span className="hint muted" data-testid="recommendation-competitor-linkage-summary">
                  Competitor linkage: {view.competitorLinkageSummary}
                </span>
              ) : null}
              {view.competitorEvidenceLinks.length > 0 ? (
                <span className="hint muted" data-testid="recommendation-competitor-linkage">
                  Linked competitor evidence:{" "}
                  {view.competitorEvidenceLinks.map((link, index) => (
                    <span key={link.key} className="recommendation-linkage-entry">
                      {index > 0 ? "; " : null}
                      {link.competitorText}{" "}
                      {link.trustTierLabel && link.trustTierBadgeClass
                        ? <span className={link.trustTierBadgeClass}>{link.trustTierLabel}</span>
                        : null}
                    </span>
                  ))}
                </span>
              ) : null}
              {view.actionDeltaSummary ? (
                <span className="hint muted" data-testid="recommendation-action-delta">
                  {view.actionDeltaSummary}
                </span>
              ) : null}
              {view.hasReadinessSectionDetails ? (
                <span className="workspace-recommendation-summary-label" data-testid="recommendation-readiness-section-label">
                  Readiness and confidence
                </span>
              ) : null}
            </div>
          </details>
        </div>
        <aside className="workspace-recommendation-row-support" data-testid="recommendation-row-support">
          {view.impactBadge ? (
            <span className={view.impactBadge.className}>{view.impactBadge.label}</span>
          ) : null}
          {view.eeatBadges.length > 0 ? (
            <div className="workspace-recommendation-row-support-group">
              <span className="workspace-recommendation-row-support-label">EEAT impact</span>
              <div className="link-row" data-testid="recommendation-eeat-badges">
                {view.eeatBadges.map((badge) => (
                  <span key={badge.key || badge.label} className={badge.className}>
                    {badge.label}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          {view.priorityReasons.length > 0 ? (
            <div className="workspace-recommendation-row-support-group">
              <span className="workspace-recommendation-row-support-label">Why surfaced</span>
              <div className="link-row" data-testid="recommendation-priority-reasons">
                {view.priorityReasons.map((badge) => (
                  <span key={badge.key || badge.label} className={badge.className}>
                    {badge.label}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          <div className="workspace-recommendation-row-support-group">
            <span className="workspace-recommendation-row-support-label">Progress</span>
            <div className="link-row" data-testid="recommendation-progress-status">
              <span className={view.progressBadge.className}>{view.progressBadge.label}</span>
            </div>
          </div>
          {view.lifecycleBadge ? (
            <div className="workspace-recommendation-row-support-group">
              <span className="workspace-recommendation-row-support-label">Lifecycle</span>
              <div className="link-row" data-testid="recommendation-lifecycle-state">
                <span className={view.lifecycleBadge.className}>{view.lifecycleBadge.label}</span>
              </div>
            </div>
          ) : null}
          {view.priorityLevelBadge ? (
            <div className="workspace-recommendation-row-support-group" data-testid="recommendation-priority">
              <span className="workspace-recommendation-row-support-label">Priority</span>
              <div className="link-row">
                <span className={view.priorityLevelBadge.className}>
                  {view.priorityLevelBadge.label}
                </span>
                {view.priorityEffortHintLabel ? (
                  <span className="badge badge-muted">
                    Effort: {view.priorityEffortHintLabel}
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}
          {view.priorityRationale ? (
            <div className="workspace-recommendation-row-support-group">
              <span className="workspace-recommendation-row-support-label">Priority rationale</span>
              <span className="hint muted" data-testid="recommendation-priority-rationale">
                {view.priorityRationale}
              </span>
            </div>
          ) : null}
          {view.evidenceStrengthBadge ? (
            <div className="workspace-recommendation-row-support-group">
              <span className="workspace-recommendation-row-support-label">Evidence strength</span>
              <div className="link-row" data-testid="recommendation-evidence-strength">
                <span className={view.evidenceStrengthBadge.className}>
                  {view.evidenceStrengthBadge.label}
                </span>
              </div>
            </div>
          ) : null}
          {view.hasActionabilitySummary ? (
            <div className="workspace-recommendation-row-support-group" data-testid="recommendation-actionability-support">
              <span className="workspace-recommendation-row-support-label">Actionability</span>
              <div className="link-row">
                {view.executionReadinessBadge ? (
                  <span className={view.executionReadinessBadge.className}>
                    {view.executionReadinessBadge.label}
                  </span>
                ) : null}
                {view.effortHintLabel ? (
                  <span className="badge badge-muted">Effort: {view.effortHintLabel}</span>
                ) : null}
              </div>
              {view.isBlocked && view.blockingReason ? (
                <span className="hint muted">{view.blockingReason}</span>
              ) : null}
            </div>
          ) : null}
          <div className="workspace-recommendation-row-support-group">
            <span className="workspace-recommendation-row-support-label">Details</span>
            <div className="link-row">
              <span className="badge badge-muted">{view.category}</span>
              <span className="badge badge-muted">{view.severity}</span>
              <span className="badge badge-muted">
                {view.priorityScore} ({view.priorityBand})
              </span>
            </div>
          </div>
        </aside>
      </div>
    </article>
  );
}
