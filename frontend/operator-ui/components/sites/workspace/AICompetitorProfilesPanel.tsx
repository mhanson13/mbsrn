import type { ReactNode } from "react";

import { SectionCard } from "../../layout/SectionCard";
import { SectionHeader } from "../../layout/SectionHeader";

interface AICompetitorProfilesPanelProps {
  loadingWorkspace: boolean;
  generationInFlight: boolean;
  retryInFlight: boolean;
  competitorProfileLoading: boolean;
  showRetryAction: boolean;
  onGenerate: () => void;
  onRetry: () => void;
  competitorSectionFreshnessContent?: ReactNode;
  competitorProfileError: string | null;
  competitorProfileSummaryError: string | null;
  competitorProfileActionError: string | null;
  competitorProfileActionMessage: string | null;
  statusStripContent?: ReactNode;
  statusCalloutContent?: ReactNode;
  runOutcomeSummaryContent?: ReactNode;
  summaryStripContent?: ReactNode;
  children?: ReactNode;
}

export function AICompetitorProfilesPanel({
  loadingWorkspace,
  generationInFlight,
  retryInFlight,
  competitorProfileLoading,
  showRetryAction,
  onGenerate,
  onRetry,
  competitorSectionFreshnessContent,
  competitorProfileError,
  competitorProfileSummaryError,
  competitorProfileActionError,
  competitorProfileActionMessage,
  statusStripContent,
  statusCalloutContent,
  runOutcomeSummaryContent,
  summaryStripContent,
  children,
}: AICompetitorProfilesPanelProps): JSX.Element {
  return (
    <SectionCard className="operator-shell-section operator-shell-work-zone workspace-site-surface">
      <SectionHeader
        title="AI Competitor Profiles"
        subtitle="Generate AI-produced competitor profile drafts, then review and explicitly accept or reject each candidate."
        headingLevel={2}
        data-testid="competitor-section-header"
        actions={(
          <div className="toolbar-row">
            <button
              type="button"
              className="button button-primary"
              onClick={onGenerate}
              disabled={loadingWorkspace || generationInFlight || retryInFlight || competitorProfileLoading}
            >
              {generationInFlight ? "Queuing..." : "Generate Competitor Profiles"}
            </button>
            {showRetryAction ? (
              <button
                type="button"
                className="button button-secondary"
                onClick={onRetry}
                disabled={loadingWorkspace || generationInFlight || retryInFlight || competitorProfileLoading}
              >
                {retryInFlight ? "Retrying..." : "Retry"}
              </button>
            ) : null}
          </div>
        )}
      />
      {competitorSectionFreshnessContent}
      {competitorProfileError ? <p className="hint error">{competitorProfileError}</p> : null}
      {competitorProfileSummaryError ? <p className="hint warning">{competitorProfileSummaryError}</p> : null}
      {competitorProfileActionError ? <p className="hint error">{competitorProfileActionError}</p> : null}
      {competitorProfileActionMessage ? <p className="hint success">{competitorProfileActionMessage}</p> : null}
      {statusStripContent}
      {statusCalloutContent}
      {runOutcomeSummaryContent}
      {summaryStripContent}
      {children}
    </SectionCard>
  );
}
