import Link from "next/link";

import type { RecommendationNarrative, RecommendationRun } from "../../../lib/api/types";

interface RecommendationRunHistoryTableProps {
  recommendationRuns: RecommendationRun[];
  latestNarrativesByRunId: Record<string, RecommendationNarrative>;
  siteId: string;
  formatDateTime: (value: string | null) => string;
  buildRecommendationRunHref: (runId: string, siteId: string) => string;
  buildNarrativeHistoryHref: (recommendationRunId: string, siteId: string) => string;
  buildNarrativeDetailHref: (recommendationRunId: string, narrativeId: string, siteId: string) => string;
}

function formatLatestNarrativeLabel(narrative: RecommendationNarrative): string {
  return `Latest v${narrative.version} (${narrative.status})`;
}

export function RecommendationRunHistoryTable({
  recommendationRuns,
  latestNarrativesByRunId,
  siteId,
  formatDateTime,
  buildRecommendationRunHref,
  buildNarrativeHistoryHref,
  buildNarrativeDetailHref,
}: RecommendationRunHistoryTableProps): JSX.Element {
  return (
    <>
      <h3>Recent Run History</h3>
      {recommendationRuns.length > 0 ? (
        <div className="table-container">
          <table className="table table-dense">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Status</th>
                <th>Created</th>
                <th>Completed</th>
                <th>Total Recommendations</th>
                <th>Narrative</th>
              </tr>
            </thead>
            <tbody>
              {recommendationRuns.map((run) => {
                const latestNarrative = latestNarrativesByRunId[run.id] || null;
                return (
                  <tr key={run.id}>
                    <td>
                      <Link href={buildRecommendationRunHref(run.id, siteId)}>{run.id}</Link>
                    </td>
                    <td>{run.status}</td>
                    <td>{formatDateTime(run.created_at)}</td>
                    <td>{formatDateTime(run.completed_at)}</td>
                    <td>{run.total_recommendations}</td>
                    <td>
                      <div className="stack">
                        <Link href={buildNarrativeHistoryHref(run.id, siteId)}>History</Link>
                        {latestNarrative ? (
                          <Link href={buildNarrativeDetailHref(run.id, latestNarrative.id, siteId)}>
                            {formatLatestNarrativeLabel(latestNarrative)}
                          </Link>
                        ) : (
                          <span className="hint muted">No narrative yet</span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}
