import type { ReactNode } from "react";

import { WorkspaceMessageStack } from "../../layout/WorkspaceMessageStack";
import { SectionCard } from "../../layout/SectionCard";
import { SectionHeader } from "../../layout/SectionHeader";

interface RecommendationRunsPanelProps {
  latestCompletedRunMeta?: ReactNode;
  recommendationRunError: string | null;
  narrativeLookupError: string | null;
  children: ReactNode;
}

export function RecommendationRunsPanel({
  latestCompletedRunMeta,
  recommendationRunError,
  narrativeLookupError,
  children,
}: RecommendationRunsPanelProps): JSX.Element {
  return (
    <SectionCard className="operator-shell-section operator-shell-work-zone workspace-site-surface">
      <SectionHeader
        title="Recommendation Runs and Narratives"
        subtitle="Review deterministic recommendations, AI narrative overlays, and recent tuning outcomes."
        headingLevel={2}
        data-testid="recommendation-runs-header"
        meta={latestCompletedRunMeta || null}
      />
      {recommendationRunError || narrativeLookupError ? (
        <WorkspaceMessageStack data-testid="workspace-recommendation-runs-message-stack">
          {recommendationRunError ? <p className="hint error">{recommendationRunError}</p> : null}
          {narrativeLookupError ? <p className="hint warning">{narrativeLookupError}</p> : null}
        </WorkspaceMessageStack>
      ) : null}
      {children}
    </SectionCard>
  );
}
