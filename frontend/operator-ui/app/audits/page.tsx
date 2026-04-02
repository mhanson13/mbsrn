"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { OperationalItemCard } from "../../components/layout/OperationalItemCard";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { WorkflowSiteSelector } from "../../components/layout/WorkflowSiteSelector";
import { useOperatorContext } from "../../components/useOperatorContext";
import { ApiRequestError, fetchAuditRuns } from "../../lib/api/client";
import type { SEOAuditRun } from "../../lib/api/types";

function formatDateTime(value: string | null): string {
  if (!value) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt) {
    return "—";
  }
  const startedAtMs = Date.parse(startedAt);
  if (!Number.isFinite(startedAtMs)) {
    return "—";
  }
  const completedAtMs = completedAt ? Date.parse(completedAt) : Date.now();
  if (!Number.isFinite(completedAtMs)) {
    return "—";
  }
  const durationSeconds = Math.max(0, Math.floor((completedAtMs - startedAtMs) / 1000));
  if (durationSeconds < 60) {
    return `${durationSeconds}s`;
  }
  const minutes = Math.floor(durationSeconds / 60);
  const seconds = durationSeconds % 60;
  if (minutes < 60) {
    return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes.toString().padStart(2, "0")}m`;
}

function deriveResultIndicator(run: SEOAuditRun): string {
  const status = (run.status || "").trim().toLowerCase();
  if (status === "completed") {
    if (run.errors_encountered > 0) {
      return `Completed with ${run.errors_encountered} crawl error(s)`;
    }
    return `Completed; ${run.pages_crawled} page(s) crawled`;
  }
  if (status === "failed") {
    return run.error_summary ? "Run failed; review run details" : "Run failed";
  }
  if (status === "running" || status === "queued") {
    return "Run in progress";
  }
  return "Status unknown";
}

function safeAuditErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view audit runs.";
    }
    if (error.status === 404) {
      return "Audit data for the selected site was not found.";
    }
  }
  return "Unable to load audit runs right now. Please try again.";
}

export default function AuditsPage() {
  const router = useRouter();
  const context = useOperatorContext();
  const [runs, setRuns] = useState<SEOAuditRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  const selectedSite = context.sites.find((site) => site.id === context.selectedSiteId) || null;
  const completedRuns = runs.filter((run) => run.status.toLowerCase() === "completed").length;
  const inProgressRuns = runs.filter((run) => {
    const normalized = run.status.toLowerCase();
    return normalized === "queued" || normalized === "running";
  }).length;
  const failedRuns = runs.filter((run) => run.status.toLowerCase() === "failed").length;

  useEffect(() => {
    if (context.loading || context.error || !context.selectedSiteId) {
      setRuns([]);
      setRunsError(null);
      setLoadingRuns(false);
      return;
    }
    let cancelled = false;
    const selectedSiteId = context.selectedSiteId;

    async function loadRuns() {
      setLoadingRuns(true);
      setRunsError(null);
      try {
        const response = await fetchAuditRuns(context.token, context.businessId, selectedSiteId);
        if (!cancelled) {
          setRuns(response.items);
        }
      } catch (err) {
        if (!cancelled) {
          setRunsError(safeAuditErrorMessage(err));
        }
      } finally {
        if (!cancelled) {
          setLoadingRuns(false);
        }
      }
    }
    void loadRuns();
    return () => {
      cancelled = true;
    };
  }, [context.businessId, context.error, context.loading, context.selectedSiteId, context.token]);

  if (context.loading) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Audit Runs"
            subtitle="Loading audit history and run status for the selected site."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Audit Runs"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.sites.length === 0) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Audit Runs"
            subtitle="No SEO sites are configured yet. Add a site first to view audit runs."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="wide" density="compact">
      <SectionCard variant="support" className="role-surface-support">
        <WorkflowSiteSelector
          id="site-picker-audit"
          sites={context.sites}
          selectedSiteId={context.selectedSiteId}
          onChange={context.setSelectedSiteId}
        />
      </SectionCard>
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Audit Runs"
            subtitle="Track crawl coverage, run outcomes, and retry needs across your selected site."
            headingLevel={1}
            variant="hero"
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Total runs"
              value={runs.length}
              detail={runs.length > 0 ? "Run history for selected site" : "No runs recorded yet"}
              tone={runs.length > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Completed"
              value={completedRuns}
              detail="Successful crawl outcomes"
              tone={completedRuns > 0 ? "success" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="In progress"
              value={inProgressRuns}
              detail="Queued or running now"
              tone={inProgressRuns > 0 ? "warning" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Failed"
              value={failedRuns}
              detail="Runs needing investigation"
              tone={failedRuns > 0 ? "danger" : "success"}
              variant="elevated"
            />
          </div>
        </SectionCard>
      </div>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Audit run list"
          subtitle="Select a site and open individual runs for details."
          headingLevel={2}
          variant="support"
        />

        {loadingRuns ? <p className="hint muted">Loading audit runs...</p> : null}
        {runsError ? <p className="hint error">{runsError}</p> : null}

        <div className="stack" data-testid="audit-quick-scan">
          <h3 className="heading-reset">Run quick scan</h3>
          <p className="hint muted">
            Summary-first cards surface current run state before full run-history table review.
          </p>
          {runs.length === 0 && !loadingRuns ? (
            <p className="hint muted">No audit runs available for quick scan.</p>
          ) : null}
          {runs.length > 0 ? (
            <div className="operational-item-list">
              {runs.slice(0, 6).map((run) => {
                const normalizedStatus = run.status.toLowerCase();
                const statusBadgeClass =
                  normalizedStatus === "completed"
                    ? "badge-success"
                    : normalizedStatus === "failed"
                      ? "badge-error"
                      : "badge-warn";
                return (
                  <OperationalItemCard
                    key={`audit-quick-scan-${run.id}`}
                    data-testid={`audit-quick-scan-item-${run.id}`}
                    title={`Audit run ${run.id}`}
                    chips={(
                      <>
                        <span className={`badge ${statusBadgeClass}`}>{run.status}</span>
                        <span className="badge badge-muted">{run.pages_crawled} crawled</span>
                        <span
                          className={`badge ${
                            run.errors_encountered > 0 ? "badge-warn" : "badge-success"
                          }`}
                        >
                          {run.errors_encountered} errors
                        </span>
                      </>
                    )}
                    summary={deriveResultIndicator(run)}
                    primaryAction={
                      <button
                        type="button"
                        className="button button-tertiary button-inline"
                        onClick={() => router.push(`/audits/${run.id}`)}
                      >
                        Open run detail
                      </button>
                    }
                    secondaryMeta={
                      <span className="hint muted">
                        Completed: {formatDateTime(run.completed_at)} | Started: {formatDateTime(run.started_at)}
                      </span>
                    }
                    expandedDetail={
                      <>
                        <p className="hint muted">
                          <span className="text-strong">Business:</span> {run.business_id}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Site:</span> {run.site_id}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Created:</span> {formatDateTime(run.created_at)}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Error summary:</span> {run.error_summary || "None"}
                        </p>
                      </>
                    }
                  />
                );
              })}
            </div>
          ) : null}
        </div>

        <div className="table-container">
          <table className="table table-dense">
            <thead>
              <tr>
                <th>Status</th>
                <th>Created</th>
                <th>Duration</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={run.id}
                  role="link"
                  tabIndex={0}
                  className="clickable-row"
                  onClick={() => router.push(`/audits/${run.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      router.push(`/audits/${run.id}`);
                    }
                  }}
                >
                  <td>{run.status}</td>
                  <td>{formatDateTime(run.created_at)}</td>
                  <td>{formatDuration(run.started_at, run.completed_at)}</td>
                  <td>{deriveResultIndicator(run)}</td>
                </tr>
              ))}
              {runs.length === 0 && !loadingRuns ? (
                <tr>
                  <td colSpan={4}>No audit runs found for the selected site.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </PageContainer>
  );
}
