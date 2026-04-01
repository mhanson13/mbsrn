"use client";

import { useEffect, useState } from "react";

import { OperationalItemCard } from "../../components/layout/OperationalItemCard";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { useOperatorContext } from "../../components/useOperatorContext";
import { fetchAutomationRuns } from "../../lib/api/client";
import type { AutomationRun } from "../../lib/api/types";

export default function AutomationPage() {
  const context = useOperatorContext();
  const [items, setItems] = useState<AutomationRun[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);

  const selectedSite = context.sites.find((site) => site.id === context.selectedSiteId) || null;
  const completedRuns = items.filter((run) => run.status.toLowerCase() === "completed").length;
  const runningRuns = items.filter((run) => run.status.toLowerCase() === "running").length;
  const failedRuns = items.filter((run) => run.status.toLowerCase() === "failed").length;

  useEffect(() => {
    if (!context.selectedSiteId || context.loading || context.error) {
      return;
    }
    let cancelled = false;
    async function loadRuns() {
      setLoadingItems(true);
      setItemsError(null);
      try {
        const response = await fetchAutomationRuns(context.token, context.businessId, context.selectedSiteId as string);
        if (!cancelled) {
          setItems(response.items);
        }
      } catch (err) {
        if (!cancelled) {
          setItemsError(err instanceof Error ? err.message : "Failed to load automation runs.");
        }
      } finally {
        if (!cancelled) {
          setLoadingItems(false);
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
            title="Automation Run History"
            subtitle="Loading automation run status for your selected site."
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
            title="Automation Run History"
            subtitle={`Error: ${context.error}`}
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
            title="Automation Run History"
            subtitle="No SEO sites are configured yet. Add a site before reviewing automation run history."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="wide" density="compact">
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Automation Run History"
            subtitle="Monitor automated recommendation and workflow run outcomes."
            headingLevel={1}
            variant="hero"
            meta={(
              <span className="hint muted">
                Selected site: <code>{selectedSite?.display_name || context.selectedSiteId || "none"}</code>
              </span>
            )}
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Total runs"
              value={items.length}
              detail={items.length > 0 ? "Automation events for selected site" : "No runs recorded"}
              tone={items.length > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Completed"
              value={completedRuns}
              detail="Finished successfully"
              tone={completedRuns > 0 ? "success" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Running"
              value={runningRuns}
              detail="Active automation executions"
              tone={runningRuns > 0 ? "warning" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Failed"
              value={failedRuns}
              detail="Runs requiring attention"
              tone={failedRuns > 0 ? "danger" : "success"}
              variant="elevated"
            />
          </div>
        </SectionCard>
      </div>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Automation runs"
          subtitle="Select a site and review trigger, lifecycle, and error outcome details."
          headingLevel={2}
          variant="support"
        />
        <label htmlFor="site-picker-automation">Site</label>
        <select
          id="site-picker-automation"
          value={context.selectedSiteId || ""}
          onChange={(event) => context.setSelectedSiteId(event.target.value)}
        >
          {context.sites.map((site) => (
            <option key={site.id} value={site.id}>
              {site.display_name}
            </option>
          ))}
        </select>

        {loadingItems ? <p className="hint muted">Loading automation runs...</p> : null}
        {itemsError ? <p className="hint error">{itemsError}</p> : null}

        <div className="stack" data-testid="automation-quick-scan">
          <h3 className="heading-reset">Run quick scan</h3>
          <p className="hint muted">
            Summary-first cards show automation status, blockers, and follow-up urgency before deep history review.
          </p>
          {items.length === 0 && !loadingItems ? (
            <p className="hint muted">No automation runs available for quick scan.</p>
          ) : null}
          {items.length > 0 ? (
            <div className="operational-item-list">
              {items.slice(0, 6).map((item) => {
                const normalizedStatus = item.status.toLowerCase();
                const statusBadgeClass =
                  normalizedStatus === "completed"
                    ? "badge-success"
                    : normalizedStatus === "failed"
                      ? "badge-error"
                      : "badge-warn";
                const blockerLabel =
                  normalizedStatus === "failed"
                    ? "Manual follow-up required"
                    : normalizedStatus === "running"
                      ? "In progress"
                      : "No blocker";
                const blockerClass =
                  normalizedStatus === "failed"
                    ? "badge-warn"
                    : normalizedStatus === "running"
                      ? "badge-warn"
                      : "badge-muted";
                return (
                  <OperationalItemCard
                    key={`automation-quick-scan-${item.id}`}
                    data-testid={`automation-quick-scan-item-${item.id}`}
                    title={`Automation run ${item.id}`}
                    chips={(
                      <>
                        <span className={`badge ${statusBadgeClass}`}>{item.status}</span>
                        <span className="badge badge-muted">{item.trigger_source}</span>
                        <span className={`badge ${blockerClass}`}>{blockerLabel}</span>
                      </>
                    )}
                    summary={
                      normalizedStatus === "completed"
                        ? "Run completed. Confirm downstream visibility where applicable."
                        : normalizedStatus === "running"
                          ? "Run is active. Wait for finish before acting on output."
                          : normalizedStatus === "failed"
                            ? "Run failed and needs operator follow-up."
                            : "Run state requires review."
                    }
                    secondaryMeta={
                      <span className="hint muted">
                        Started: {item.started_at || "-"} | Finished: {item.finished_at || "-"}
                      </span>
                    }
                    expandedDetail={
                      <>
                        <p className="hint muted">
                          <span className="text-strong">Business:</span> {item.business_id}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Site:</span> {item.site_id}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Error:</span> {item.error_message || "None"}
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
                <th>Run ID</th>
                <th>Status</th>
                <th>Trigger</th>
                <th>Started</th>
                <th>Finished</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.id}</td>
                  <td>{item.status}</td>
                  <td>{item.trigger_source}</td>
                  <td>{item.started_at || "-"}</td>
                  <td>{item.finished_at || "-"}</td>
                  <td>{item.error_message || "-"}</td>
                </tr>
              ))}
              {items.length === 0 && !loadingItems ? (
                <tr>
                  <td colSpan={6}>No automation runs found for this site.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </PageContainer>
  );
}
