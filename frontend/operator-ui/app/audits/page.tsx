"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { OperationalItemCard } from "../../components/layout/OperationalItemCard";
import { PageContainer } from "../../components/layout/PageContainer";
import {
  OperatorPageHero,
  OperatorPageSectionStack,
} from "../../components/layout/OperatorPageSurface";
import { RouteActionCluster } from "../../components/layout/RouteActionCluster";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { WorkspaceEmptyStateCard } from "../../components/layout/WorkspaceEmptyStateCard";
import { WorkspaceMessageStack } from "../../components/layout/WorkspaceMessageStack";
import { WorkspaceTableShell } from "../../components/layout/WorkspaceTableShell";
import { useOperatorContext } from "../../components/useOperatorContext";
import { ApiRequestError, createAuditRun, fetchAuditRuns } from "../../lib/api/client";
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

function safeAuditRunStartErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to run audits for this site.";
    }
    if (error.status === 404) {
      return "Selected site context could not be resolved. Re-select the site and try again.";
    }
    if (error.status === 409) {
      return "An audit run is already in progress for this site.";
    }
    if (error.status === 422) {
      return "This site is missing required audit inputs. Update site settings and retry.";
    }
  }
  return "Unable to start an audit run right now. Please try again.";
}

function deriveAuditRunRecencyMs(run: SEOAuditRun): number {
  const createdAtMs = Date.parse(run.created_at);
  if (Number.isFinite(createdAtMs)) {
    return createdAtMs;
  }
  const startedAtMs = run.started_at ? Date.parse(run.started_at) : Number.NaN;
  if (Number.isFinite(startedAtMs)) {
    return startedAtMs;
  }
  const updatedAtMs = Date.parse(run.updated_at);
  if (Number.isFinite(updatedAtMs)) {
    return updatedAtMs;
  }
  return 0;
}

export default function AuditsPage() {
  const router = useRouter();
  const context = useOperatorContext();
  const [runs, setRuns] = useState<SEOAuditRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [triggerRunPending, setTriggerRunPending] = useState(false);
  const [triggerRunError, setTriggerRunError] = useState<string | null>(null);
  const [triggerRunSuccess, setTriggerRunSuccess] = useState<string | null>(null);

  const selectedSite = context.sites.find((site) => site.id === context.selectedSiteId) || null;
  const completedRuns = runs.filter((run) => run.status.toLowerCase() === "completed").length;
  const inProgressRuns = runs.filter((run) => {
    const normalized = run.status.toLowerCase();
    return normalized === "queued" || normalized === "running";
  }).length;
  const failedRuns = runs.filter((run) => run.status.toLowerCase() === "failed").length;
  const latestRun = runs.reduce<SEOAuditRun | null>((currentLatest, run) => {
    if (!currentLatest) {
      return run;
    }
    const latestMs = deriveAuditRunRecencyMs(currentLatest);
    const candidateMs = deriveAuditRunRecencyMs(run);
    return candidateMs > latestMs ? run : currentLatest;
  }, null);
  const recommendationsHref = context.selectedSiteId
    ? `/recommendations?site_id=${encodeURIComponent(context.selectedSiteId)}`
    : "/recommendations";

  async function handleRunAuditNow(): Promise<void> {
    if (!context.selectedSiteId) {
      setTriggerRunError("Select a site before running an audit.");
      return;
    }
    setTriggerRunPending(true);
    setTriggerRunError(null);
    setTriggerRunSuccess(null);
    try {
      const createdRun = await createAuditRun(context.token, context.businessId, context.selectedSiteId, {});
      setRuns((current) => {
        const deduped = current.filter((item) => item.id !== createdRun.id);
        const merged = [createdRun, ...deduped];
        return merged.sort((left, right) => deriveAuditRunRecencyMs(right) - deriveAuditRunRecencyMs(left));
      });
      setTriggerRunSuccess("Audit run started. Refresh the run detail as new findings complete.");
    } catch (error) {
      setTriggerRunError(safeAuditRunStartErrorMessage(error));
    } finally {
      setTriggerRunPending(false);
    }
  }

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
      <OperatorPageHero
        title="Audit Runs"
        subtitle="Track crawl coverage, run outcomes, and retry needs across your selected site."
        headingLevel={1}
        data-testid="audits-page-hero"
        summary={(
          <>
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
          </>
        )}
      />

      <OperatorPageSectionStack>
        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="Audit run list"
            subtitle="Review findings history and run outcomes. Use Recommendations to decide what to do next."
            headingLevel={2}
            variant="support"
          />
          <RouteActionCluster
            data-testid="audits-page-actions"
            primaryActions={(
              <button
                type="button"
                className="button button-primary"
                onClick={() => {
                  void handleRunAuditNow();
                }}
                disabled={triggerRunPending || loadingRuns}
                data-testid="audits-run-audit-button"
              >
                {triggerRunPending ? "Starting audit..." : "Run Audit"}
              </button>
            )}
            secondaryActions={(
              <Link className="button button-secondary" href={recommendationsHref}>
                Open Recommendations
              </Link>
            )}
            shortcutActions={(
              <>
                {latestRun ? (
                  <Link
                    className="button button-tertiary"
                    href={`/audits/${latestRun.id}`}
                    data-testid="audits-open-latest-findings-link"
                  >
                    View Latest Findings
                  </Link>
                ) : null}
                {selectedSite ? (
                  <Link className="button button-tertiary" href={`/sites/${selectedSite.id}`}>
                    Open Site Workspace
                  </Link>
                ) : null}
              </>
            )}
          />
          <p className="hint muted" data-testid="audits-boundary-note">
            Audit Runs own evidence and history. Recommendation decisions stay on the Recommendations page.
          </p>

          {loadingRuns || runsError ? (
            <WorkspaceMessageStack data-testid="audits-page-message-stack">
              {loadingRuns ? <p className="hint muted">Loading audit runs...</p> : null}
              {runsError ? <p className="hint error">{runsError}</p> : null}
            </WorkspaceMessageStack>
          ) : null}
          {triggerRunError || triggerRunSuccess ? (
            <WorkspaceMessageStack data-testid="audits-page-trigger-messages">
              {triggerRunError ? (
                <p className="hint error" data-testid="audits-run-audit-error">
                  {triggerRunError}
                </p>
              ) : null}
              {triggerRunSuccess ? (
                <p className="hint" data-testid="audits-run-audit-success">
                  {triggerRunSuccess}
                </p>
              ) : null}
            </WorkspaceMessageStack>
          ) : null}

          <div className="stack" data-testid="audit-quick-scan">
            <h3 className="heading-reset">Run quick scan</h3>
            <p className="hint muted">
              Summary-first cards surface current run state before full run-history table review.
            </p>
            {runs.length === 0 && !loadingRuns ? (
              <WorkspaceEmptyStateCard compact={true}>
                <p className="hint muted">No audit runs available for quick scan.</p>
              </WorkspaceEmptyStateCard>
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

          <WorkspaceTableShell data-testid="audits-page-table-shell">
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
          </WorkspaceTableShell>
        </SectionCard>
      </OperatorPageSectionStack>
    </PageContainer>
  );
}
