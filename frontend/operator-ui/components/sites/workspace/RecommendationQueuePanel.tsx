import Link from "next/link";
import type { ReactNode } from "react";

import { WorkspaceActionBar } from "../../layout/WorkspaceActionBar";
import { WorkspaceEmptyStateCard } from "../../layout/WorkspaceEmptyStateCard";
import { WorkspaceMessageStack } from "../../layout/WorkspaceMessageStack";
import { SectionCard } from "../../layout/SectionCard";
import { SectionHeader } from "../../layout/SectionHeader";
import { SummaryStatCard } from "../../layout/SummaryStatCard";

interface RecommendationQueueSummary {
  total: number;
  open: number;
  accepted: number;
  dismissed: number;
  highPriority: number;
}

interface RecommendationQueuePanelProps {
  loadingWorkspace: boolean;
  recommendationGenerationInFlight: boolean;
  recommendationGenerationPrerequisitesMet: boolean;
  onGenerateRecommendations: () => void;
  recommendationSectionFreshnessContent?: ReactNode;
  recommendationGenerationError: string | null;
  recommendationGenerationMessage: string | null;
  queueError: string | null;
  recommendationQueueSummary: RecommendationQueueSummary;
  recommendationSectionFreshnessLabel: string | null;
  recommendationSectionFreshnessReason: string | null;
  recommendationSectionFreshnessTone: "neutral" | "success" | "warning" | "danger";
  topActionStateContent?: ReactNode;
  openRecommendationQueueHref: string;
  hasQueueItems: boolean;
  emptyQueueMessage: string;
  queueListContent?: ReactNode;
}

export function RecommendationQueuePanel({
  loadingWorkspace,
  recommendationGenerationInFlight,
  recommendationGenerationPrerequisitesMet,
  onGenerateRecommendations,
  recommendationSectionFreshnessContent,
  recommendationGenerationError,
  recommendationGenerationMessage,
  queueError,
  recommendationQueueSummary,
  recommendationSectionFreshnessLabel,
  recommendationSectionFreshnessReason,
  recommendationSectionFreshnessTone,
  topActionStateContent,
  openRecommendationQueueHref,
  hasQueueItems,
  emptyQueueMessage,
  queueListContent,
}: RecommendationQueuePanelProps): JSX.Element {
  return (
    <SectionCard
      className="operator-shell-section operator-shell-work-zone workspace-site-surface"
      role="tabpanel"
      id="workspace-content-recommendations-panel"
      aria-labelledby="workspace-content-tab-recommendations"
    >
      <SectionHeader
        title="Recommendation Queue"
        subtitle="Run deterministic recommendation analysis from the latest audit and competitor comparison context."
        headingLevel={2}
        data-testid="recommendation-queue-header"
        actions={(
          <WorkspaceActionBar variant="primary">
            <button
              type="button"
              className="button button-primary"
              onClick={onGenerateRecommendations}
              disabled={loadingWorkspace || recommendationGenerationInFlight || !recommendationGenerationPrerequisitesMet}
            >
              {recommendationGenerationInFlight ? "Generating..." : "Generate Recommendations"}
            </button>
          </WorkspaceActionBar>
        )}
      />
      {recommendationSectionFreshnessContent}
      <WorkspaceMessageStack data-testid="workspace-recommendation-queue-message-stack">
        <p className="hint muted">
          Creates a recommendation run from the latest completed audit and/or competitor comparison inputs.
        </p>
        {!loadingWorkspace && !recommendationGenerationPrerequisitesMet ? (
          <p className="hint warning">
            Run site audit before generating recommendations.
          </p>
        ) : null}
        {recommendationGenerationError ? <p className="hint error">{recommendationGenerationError}</p> : null}
        {recommendationGenerationMessage ? <p className="hint success">{recommendationGenerationMessage}</p> : null}
        {queueError ? <p className="hint error">{queueError}</p> : null}
      </WorkspaceMessageStack>
      <div className="workspace-summary-strip workspace-summary-strip-compact" data-testid="workspace-recommendation-queue-summary-strip">
        <SummaryStatCard
          label="Queue total"
          value={recommendationQueueSummary.total}
          detail={`Open ${recommendationQueueSummary.open} | Accepted ${recommendationQueueSummary.accepted}`}
          tone={recommendationQueueSummary.total > 0 ? "neutral" : "warning"}
          variant="elevated"
          data-testid="workspace-recommendation-queue-total-summary"
        />
        <SummaryStatCard
          label="High priority"
          value={recommendationQueueSummary.highPriority}
          detail={recommendationQueueSummary.highPriority > 0 ? "Review these first." : "No high-priority items queued."}
          tone={recommendationQueueSummary.highPriority > 0 ? "warning" : "neutral"}
          variant="elevated"
          data-testid="workspace-recommendation-queue-high-priority-summary"
        />
        <SummaryStatCard
          label="Dismissed"
          value={recommendationQueueSummary.dismissed}
          detail="Previously reviewed and dismissed queue items"
          tone={recommendationQueueSummary.dismissed > 0 ? "neutral" : "success"}
          variant="elevated"
          data-testid="workspace-recommendation-queue-dismissed-summary"
        />
        <SummaryStatCard
          label="Section freshness"
          value={recommendationSectionFreshnessLabel || "No freshness signal"}
          detail={recommendationSectionFreshnessReason || "Freshness updates after recommendation runs complete."}
          tone={recommendationSectionFreshnessTone}
          variant="elevated"
          data-testid="workspace-recommendation-queue-freshness-summary"
        />
      </div>
      {topActionStateContent}
      <WorkspaceActionBar variant="secondary">
        <Link href={openRecommendationQueueHref}>Open Recommendation Queue</Link>
      </WorkspaceActionBar>
      {!queueError && !hasQueueItems ? (
        <WorkspaceEmptyStateCard data-testid="workspace-recommendation-queue-empty-state">
          <p className="hint muted">{emptyQueueMessage}</p>
        </WorkspaceEmptyStateCard>
      ) : null}
      {hasQueueItems ? queueListContent : null}
    </SectionCard>
  );
}
