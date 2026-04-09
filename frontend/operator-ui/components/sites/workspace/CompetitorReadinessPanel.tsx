import Link from "next/link";

import { WorkspaceActionBar } from "../../layout/WorkspaceActionBar";
import { WorkspaceEmptyStateCard } from "../../layout/WorkspaceEmptyStateCard";
import { WorkspaceMessageStack } from "../../layout/WorkspaceMessageStack";
import { WorkspaceTableShell } from "../../layout/WorkspaceTableShell";
import { SectionCard } from "../../layout/SectionCard";
import { SectionHeader } from "../../layout/SectionHeader";
import { SummaryStatCard } from "../../layout/SummaryStatCard";

interface CompetitorSnapshotRunSummary {
  id: string;
  status: string;
  completed_at: string | null;
  updated_at: string;
  competitor_set_id: string;
}

interface CompetitorComparisonRunSummary {
  id: string;
  status: string;
  completed_at: string | null;
  updated_at: string;
  competitor_set_id: string;
}

interface CompetitorSetSummaryRow {
  id: string;
  name: string;
  is_active: boolean;
  domain_count: number;
  active_domain_count: number;
  latest_snapshot_run: CompetitorSnapshotRunSummary | null;
  updated_at: string;
}

interface CompetitorReadinessPanelProps {
  competitorError: string | null;
  workspaceReadinessMessage: string;
  activeCompetitorSetCount: number;
  competitorDomainCount: number;
  activeCompetitorDomainCount: number;
  latestSnapshotRun: CompetitorSnapshotRunSummary | null;
  latestComparisonRun: CompetitorComparisonRunSummary | null;
  competitorSets: CompetitorSetSummaryRow[];
  maxRows: number;
  competitorWorkspaceHref: string;
  getSnapshotRunHref: (runId: string, competitorSetId: string) => string;
  getComparisonRunHref: (runId: string, competitorSetId: string) => string;
  getCompetitorSetHref: (setId: string) => string;
  formatDateTime: (value: string | null) => string;
}

export function CompetitorReadinessPanel({
  competitorError,
  workspaceReadinessMessage,
  activeCompetitorSetCount,
  competitorDomainCount,
  activeCompetitorDomainCount,
  latestSnapshotRun,
  latestComparisonRun,
  competitorSets,
  maxRows,
  competitorWorkspaceHref,
  getSnapshotRunHref,
  getComparisonRunHref,
  getCompetitorSetHref,
  formatDateTime,
}: CompetitorReadinessPanelProps): JSX.Element {
  return (
    <SectionCard className="operator-shell-section operator-shell-secondary-zone workspace-site-surface">
      <SectionHeader
        title="Competitor Readiness"
        subtitle="Configured competitor sets, active domains, and recent snapshot/comparison activity."
        headingLevel={2}
      />
      {competitorError ? (
        <WorkspaceMessageStack data-testid="workspace-competitor-readiness-message-stack">
          <p className="hint error">{competitorError}</p>
        </WorkspaceMessageStack>
      ) : null}
      <div className="workspace-summary-strip workspace-summary-strip-compact" data-testid="workspace-competitor-readiness-summary-strip">
        <SummaryStatCard
          label="Readiness"
          value={workspaceReadinessMessage}
          detail={
            activeCompetitorSetCount > 0
              ? "Competitor sets and domains are configured."
              : "Add at least one active competitor set to continue."
          }
          tone={activeCompetitorSetCount > 0 ? "success" : "warning"}
          variant="elevated"
          data-testid="workspace-competitor-readiness-summary"
        />
        <SummaryStatCard
          label="Active sets"
          value={activeCompetitorSetCount}
          detail={`Total sets: ${competitorSets.length}`}
          tone={activeCompetitorSetCount > 0 ? "success" : "neutral"}
          variant="elevated"
          data-testid="workspace-competitor-sets-summary"
        />
        <SummaryStatCard
          label="Active domains"
          value={activeCompetitorDomainCount}
          detail={`Total domains: ${competitorDomainCount}`}
          tone={activeCompetitorDomainCount > 0 ? "success" : "neutral"}
          variant="elevated"
          data-testid="workspace-competitor-domains-summary"
        />
        <SummaryStatCard
          label="Latest snapshot"
          value={
            latestSnapshotRun ? (
              <Link href={getSnapshotRunHref(latestSnapshotRun.id, latestSnapshotRun.competitor_set_id)}>
                {latestSnapshotRun.status}
              </Link>
            ) : "No snapshot run"
          }
          detail={
            latestSnapshotRun
              ? formatDateTime(latestSnapshotRun.completed_at || latestSnapshotRun.updated_at)
              : "Run a snapshot to populate this signal."
          }
          tone={latestSnapshotRun ? "neutral" : "warning"}
          variant="elevated"
          data-testid="workspace-competitor-snapshot-summary"
        />
        <SummaryStatCard
          label="Latest comparison"
          value={
            latestComparisonRun ? (
              <Link href={getComparisonRunHref(latestComparisonRun.id, latestComparisonRun.competitor_set_id)}>
                {latestComparisonRun.status}
              </Link>
            ) : "No comparison run"
          }
          detail={
            latestComparisonRun
              ? formatDateTime(latestComparisonRun.completed_at || latestComparisonRun.updated_at)
              : "Run comparison after snapshot completion."
          }
          tone={latestComparisonRun ? "neutral" : "warning"}
          variant="elevated"
          data-testid="workspace-competitor-comparison-summary"
        />
      </div>
      <div className="workspace-status-callout stack-tight">
        <span className="hint">{workspaceReadinessMessage}</span>
        <WorkspaceActionBar
          variant="secondary"
          className="workspace-status-callout-links"
        >
          <Link href={competitorWorkspaceHref}>Open Competitor Surfaces</Link>
        </WorkspaceActionBar>
      </div>
      {competitorSets.length === 0 ? (
        <WorkspaceEmptyStateCard data-testid="workspace-competitor-readiness-empty-state">
          <p className="hint muted">
            No competitor sets yet. Add one to compare your site against nearby businesses in your market.
          </p>
        </WorkspaceEmptyStateCard>
      ) : (
        <>
          <WorkspaceTableShell>
            <table className="table table-dense">
              <thead>
                <tr>
                  <th>Set</th>
                  <th>Active</th>
                  <th>Domains</th>
                  <th>Latest Snapshot</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {competitorSets.slice(0, maxRows).map((setItem) => (
                  <tr key={setItem.id}>
                    <td className="table-cell-wrap">
                      <Link href={getCompetitorSetHref(setItem.id)}>{setItem.name}</Link>
                      <br />
                      <span className="hint muted"><code>{setItem.id}</code></span>
                    </td>
                    <td>{setItem.is_active ? "yes" : "no"}</td>
                    <td>
                      {setItem.active_domain_count}/{setItem.domain_count}
                    </td>
                    <td>
                      {setItem.latest_snapshot_run ? (
                        <Link
                          href={getSnapshotRunHref(
                            setItem.latest_snapshot_run.id,
                            setItem.id,
                          )}
                        >
                          {setItem.latest_snapshot_run.status}
                        </Link>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td>{formatDateTime(setItem.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </WorkspaceTableShell>
          {competitorSets.length > maxRows ? (
            <p className="hint muted">
              Showing the {maxRows} most recently updated competitor sets for this site.
            </p>
          ) : null}
        </>
      )}
    </SectionCard>
  );
}
