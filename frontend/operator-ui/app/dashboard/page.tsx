"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PageContainer } from "../../components/layout/PageContainer";
import {
  OperatorPageHero,
  OperatorPageSectionStack,
} from "../../components/layout/OperatorPageSurface";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { RouteActionCluster } from "../../components/layout/RouteActionCluster";
import { SectionStatusItem, SectionStatusStrip } from "../../components/layout/SectionStatusStrip";
import { WorkspaceActionBar } from "../../components/layout/WorkspaceActionBar";
import { WorkspaceMessageStack } from "../../components/layout/WorkspaceMessageStack";
import { WorkspaceMetadataGrid, WorkspaceMetadataItem } from "../../components/layout/WorkspaceMetadataGrid";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  fetchAutomationRuns,
  fetchRecommendationWorkspaceSummary,
} from "../../lib/api/client";
import type {
  AutomationRun,
  RecommendationWorkspaceSummaryResponse,
  SEOSite,
} from "../../lib/api/types";

type DashboardPriorityCue = {
  title: string;
  reason: string;
  actionLabel: string;
  href: string;
  badgeClass: "badge-success" | "badge-warn" | "badge-muted" | "badge-error";
};

type DashboardLaunchLane = {
  title: string;
  summary: string;
  statusLabel: string;
  badgeClass: "badge-success" | "badge-warn" | "badge-muted" | "badge-error";
  ctaLabel: string;
  href: string;
};

function formatDateTime(value: string | null): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function normalizeStatus(status: string | null | undefined): string {
  return (status || "").trim().toLowerCase();
}

function latestAutomationRun(runs: AutomationRun[]): AutomationRun | null {
  if (runs.length === 0) {
    return null;
  }
  const sortedRuns = [...runs].sort((left, right) => {
    const leftTime = Date.parse(left.updated_at || left.finished_at || left.started_at || "");
    const rightTime = Date.parse(right.updated_at || right.finished_at || right.started_at || "");
    if (!Number.isFinite(leftTime) || !Number.isFinite(rightTime)) {
      return right.id.localeCompare(left.id);
    }
    return rightTime - leftTime;
  });
  return sortedRuns[0] || null;
}

function buildPriorityCue(params: {
  selectedSite: SEOSite | null;
  latestAutomation: AutomationRun | null;
  workspaceSummary: RecommendationWorkspaceSummaryResponse | null;
  openRecommendations: number;
}): DashboardPriorityCue {
  const { selectedSite, latestAutomation, workspaceSummary, openRecommendations } = params;
  const selectedSiteId = selectedSite?.id || "";
  const latestAutomationStatus = normalizeStatus(latestAutomation?.status);

  if (!selectedSite) {
    return {
      title: "Select a site first",
      reason: "Pick one site so we can turn scattered signals into a clear, ordered action list.",
      actionLabel: "Open Sites",
      href: "/sites",
      badgeClass: "badge-warn",
    };
  }

  if (!selectedSite.last_audit_run_id) {
    return {
      title: "Run the first audit",
      reason: "This site has no audit baseline yet. Start here so recommendations are grounded in real site data.",
      actionLabel: "Open Workspace",
      href: `/sites/${selectedSite.id}`,
      badgeClass: "badge-warn",
    };
  }

  if (latestAutomationStatus === "failed") {
    return {
      title: "Review failed automation run",
      reason: "The latest SEO automation run failed and needs operator follow-up before rerun.",
      actionLabel: "Open Automation",
      href: selectedSiteId ? `/automation?site_id=${selectedSiteId}` : "/automation",
      badgeClass: "badge-error",
    };
  }

  if (openRecommendations > 0) {
    return {
      title: "Review open recommendations",
      reason: `${openRecommendations} recommendation${openRecommendations === 1 ? "" : "s"} currently need review.`,
      actionLabel: "Open Recommendations",
      href: selectedSiteId ? `/recommendations?site_id=${selectedSiteId}` : "/recommendations",
      badgeClass: "badge-success",
    };
  }

  if (latestAutomationStatus === "queued" || latestAutomationStatus === "running") {
    return {
      title: "Track automation progress",
      reason: "Automation is currently in progress. Review the run outcome after completion.",
      actionLabel: "View Automation Status",
      href: selectedSiteId ? `/automation?site_id=${selectedSiteId}` : "/automation",
      badgeClass: "badge-warn",
    };
  }

  const analysisFreshnessStatus = workspaceSummary?.analysis_freshness?.status;
  if (analysisFreshnessStatus === "pending_refresh" || analysisFreshnessStatus === "unknown") {
    return {
      title: "Refresh recommendation context",
      reason: "Recommendation context is stale and should be refreshed before actioning changes.",
      actionLabel: "Open Workspace",
      href: `/sites/${selectedSite.id}`,
      badgeClass: "badge-warn",
    };
  }

  return {
    title: "No immediate action needed",
    reason: "Signals look stable. Keep momentum by reviewing fresh recommendations and routine automation outcomes.",
    actionLabel: "Open Workspace",
    href: `/sites/${selectedSite.id}`,
    badgeClass: "badge-muted",
  };
}

function toScopedRoute(basePath: string, siteId: string | null): string {
  if (!siteId) {
    return basePath;
  }
  if (basePath === "/sites") {
    return `/sites/${encodeURIComponent(siteId)}`;
  }
  const separator = basePath.includes("?") ? "&" : "?";
  return `${basePath}${separator}site_id=${encodeURIComponent(siteId)}`;
}

function buildDashboardLaunchLanes(params: {
  selectedSiteId: string | null;
  openRecommendations: number;
  latestAutomationStatus: string;
  recommendationRunStatus: string;
  analysisFreshnessStatus: string;
}): DashboardLaunchLane[] {
  const {
    selectedSiteId,
    openRecommendations,
    latestAutomationStatus,
    recommendationRunStatus,
    analysisFreshnessStatus,
  } = params;

  return [
    {
      title: "Recommendations",
      summary: "Review queue health, trigger generation, and move accepted items into execution.",
      statusLabel:
        openRecommendations > 0
          ? `${openRecommendations} open`
          : recommendationRunStatus
            ? `Run ${recommendationRunStatus}`
            : "No run yet",
      badgeClass: openRecommendations > 0 ? "badge-warn" : "badge-success",
      ctaLabel: "Open recommendations",
      href: toScopedRoute("/recommendations", selectedSiteId),
    },
    {
      title: "Site workspace",
      summary: "Drive recommendation and migration decisions inside the site-specific operator workspace.",
      statusLabel: selectedSiteId ? "Site selected" : "Select site",
      badgeClass: selectedSiteId ? "badge-success" : "badge-warn",
      ctaLabel: selectedSiteId ? "Open site workspace" : "Review sites",
      href: toScopedRoute("/sites", selectedSiteId),
    },
    {
      title: "Automation",
      summary: "Track run outcomes and intervene when automation health regresses.",
      statusLabel: latestAutomationStatus || "No runs",
      badgeClass:
        latestAutomationStatus === "failed"
          ? "badge-error"
          : latestAutomationStatus === "running" || latestAutomationStatus === "queued"
            ? "badge-warn"
            : "badge-muted",
      ctaLabel: "Open automation",
      href: toScopedRoute("/automation", selectedSiteId),
    },
    {
      title: "Competitor context",
      summary: "Keep supporting competitive context fresh before reshaping recommendation plans.",
      statusLabel:
        analysisFreshnessStatus === "pending_refresh" || analysisFreshnessStatus === "unknown"
          ? "Context stale"
          : "Context available",
      badgeClass:
        analysisFreshnessStatus === "pending_refresh" || analysisFreshnessStatus === "unknown"
          ? "badge-warn"
          : "badge-muted",
      ctaLabel: "Open competitors",
      href: toScopedRoute("/competitors", selectedSiteId),
    },
  ];
}

function badgeClassToSummaryTone(
  badgeClass: DashboardPriorityCue["badgeClass"],
): "neutral" | "success" | "warning" | "danger" {
  if (badgeClass === "badge-success") {
    return "success";
  }
  if (badgeClass === "badge-error") {
    return "danger";
  }
  if (badgeClass === "badge-warn") {
    return "warning";
  }
  return "neutral";
}

export default function DashboardPage() {
  const context = useOperatorContext();
  const [workspaceSummary, setWorkspaceSummary] = useState<RecommendationWorkspaceSummaryResponse | null>(null);
  const [automationRuns, setAutomationRuns] = useState<AutomationRun[]>([]);
  const [signalError, setSignalError] = useState<string | null>(null);
  const [signalLoading, setSignalLoading] = useState(false);
  const businessContextAvailable = Boolean(context.businessId);

  const selectedSite = context.sites.find((site) => site.id === context.selectedSiteId) || null;

  useEffect(() => {
    if (context.loading || context.error || !businessContextAvailable || !context.selectedSiteId) {
      setWorkspaceSummary(null);
      setAutomationRuns([]);
      setSignalError(null);
      setSignalLoading(false);
      return;
    }
    let cancelled = false;

    async function loadSignals() {
      setSignalLoading(true);
      setSignalError(null);
      const [workspaceResult, automationResult] = await Promise.allSettled([
        fetchRecommendationWorkspaceSummary(context.token, context.businessId, context.selectedSiteId as string),
        fetchAutomationRuns(context.token, context.businessId, context.selectedSiteId as string),
      ]);
      if (cancelled) {
        return;
      }

      if (workspaceResult.status === "fulfilled") {
        setWorkspaceSummary(workspaceResult.value);
      } else {
        setWorkspaceSummary(null);
      }

      if (automationResult.status === "fulfilled") {
        setAutomationRuns(automationResult.value.items);
      } else {
        setAutomationRuns([]);
      }

      if (workspaceResult.status === "rejected" || automationResult.status === "rejected") {
        setSignalError("Some dashboard signals are temporarily unavailable.");
      }
      setSignalLoading(false);
    }

    void loadSignals();
    return () => {
      cancelled = true;
    };
  }, [
    businessContextAvailable,
    context.businessId,
    context.error,
    context.loading,
    context.selectedSiteId,
    context.token,
  ]);

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Dashboard"
            subtitle="Loading dashboard overview and role-scoped status."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Dashboard"
            subtitle={`Error: ${context.error}`}
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (!businessContextAvailable) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Dashboard"
            subtitle="We could not load your business workspace context. Refresh or sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  const latestAutomation = latestAutomationRun(automationRuns);
  const latestAutomationStatus = normalizeStatus(latestAutomation?.status);
  const openRecommendations =
    workspaceSummary?.recommendations?.filtered_summary?.open
    ?? workspaceSummary?.recommendations?.items?.filter((item) => {
      const status = normalizeStatus(item.status);
      return status === "open" || status === "in_progress";
    }).length
    ?? 0;
  const needsReviewCount = openRecommendations;
  const priorityCue = buildPriorityCue({
    selectedSite,
    latestAutomation,
    workspaceSummary,
    openRecommendations,
  });

  const latestAuditStatus = selectedSite ? normalizeStatus(selectedSite.last_audit_status) : "";
  const auditFreshnessValue = selectedSite?.last_audit_completed_at
    ? formatDateTime(selectedSite.last_audit_completed_at)
    : "Missing";
  const recommendationRunStatus = normalizeStatus(workspaceSummary?.latest_run?.status);
  const analysisFreshnessStatus = normalizeStatus(workspaceSummary?.analysis_freshness?.status);
  const selectedSiteId = selectedSite?.id || null;
  const siteWorkspaceHref = toScopedRoute("/sites", selectedSiteId);
  const recommendationWorkspaceHref = toScopedRoute("/recommendations", selectedSiteId);
  const automationWorkspaceHref = toScopedRoute("/automation", selectedSiteId);
  const competitorsWorkspaceHref = toScopedRoute("/competitors", selectedSiteId);
  const auditsWorkspaceHref = toScopedRoute("/audits", selectedSiteId);
  const launchLanes = buildDashboardLaunchLanes({
    selectedSiteId,
    openRecommendations,
    latestAutomationStatus,
    recommendationRunStatus,
    analysisFreshnessStatus,
  });
  const showHeroSecondaryAction = priorityCue.href !== siteWorkspaceHref;

  const recentActivityItems: Array<{ label: string; value: string }> = [
    {
      label: "Latest audit",
      value: selectedSite
        ? `${selectedSite.last_audit_status || "unknown"} · ${formatDateTime(selectedSite.last_audit_completed_at)}`
        : "No site selected yet - pick a site to load activity",
    },
    {
      label: "Latest automation",
      value: latestAutomation
        ? `${latestAutomation.status} · ${formatDateTime(latestAutomation.finished_at || latestAutomation.started_at)}`
        : "No automation run yet - start one from the Automation page",
    },
    {
      label: "Latest recommendation run",
      value: workspaceSummary?.latest_run
        ? `${workspaceSummary.latest_run.status} · ${formatDateTime(workspaceSummary.latest_run.completed_at)}`
        : "No recommendation run yet - generate one from Site Workspace",
    },
  ];
  const supportSignalItems: Array<{ label: string; value: string }> = [
    {
      label: "Active site",
      value: selectedSite ? `${selectedSite.display_name} (${selectedSite.id})` : "No site selected",
    },
    {
      label: "Freshness signal",
      value: analysisFreshnessStatus || "unknown",
    },
    {
      label: "Next review lane",
      value: priorityCue.actionLabel,
    },
  ];

  return (
    <PageContainer width="wide" density="compact" className="workspace-shell-overview">
      <OperatorPageHero
        className="workspace-shell-overview-hero"
        title="Operator dashboard"
        subtitle="Decision-first launch surface across site execution, recommendations, migration readiness, and automation oversight."
        headingLevel={1}
        data-testid="dashboard-page-hero"
        meta={selectedSite ? `Active site: ${selectedSite.display_name}` : "No active site selected"}
        actions={(
          <RouteActionCluster
            className="dashboard-hero-actions"
            primaryActions={(
              <Link href={priorityCue.href} className="button button-primary button-inline">
                {priorityCue.actionLabel}
              </Link>
            )}
            secondaryActions={showHeroSecondaryAction ? (
              <Link href={siteWorkspaceHref} className="button button-secondary button-inline">
                {selectedSite ? "Open active site workspace" : "Open sites"}
              </Link>
            ) : null}
            shortcutActions={(
              <Link href={automationWorkspaceHref} className="button button-tertiary button-inline">
                Automation status
              </Link>
            )}
          />
        )}
        summary={(
          <div data-testid="dashboard-summary-strip">
            <SummaryStatCard
              label="Active site"
              value={selectedSite?.display_name || "none"}
              detail={selectedSite ? selectedSite.id : "Select a site to unlock workflow detail"}
              tone={selectedSite ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Tracked sites"
              value={context.sites.length}
              detail={context.sites.length > 0 ? "Configured and available" : "Add your first site to start"}
              tone={context.sites.length > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Audit freshness"
              value={latestAuditStatus ? latestAuditStatus : "missing"}
              detail={auditFreshnessValue}
              tone={latestAuditStatus === "completed" ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Needs review"
              value={needsReviewCount}
              detail={needsReviewCount > 0 ? "Open recommendations" : "No open recommendation backlog"}
              tone={needsReviewCount > 0 ? "warning" : "success"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Automation activity"
              value={latestAutomation ? latestAutomation.status : "none"}
              detail={
                latestAutomation
                  ? `Last update: ${formatDateTime(latestAutomation.finished_at || latestAutomation.started_at)}`
                  : "No automation run yet"
              }
              tone={
                latestAutomationStatus === "failed"
                  ? "danger"
                  : latestAutomationStatus === "running" || latestAutomationStatus === "queued"
                    ? "warning"
                    : "neutral"
              }
              variant="elevated"
            />
          </div>
        )}
      >
        {signalLoading || signalError ? (
          <WorkspaceMessageStack data-testid="dashboard-signal-messages">
            {signalLoading ? <p className="hint muted">Refreshing dashboard signals…</p> : null}
            {signalError ? <p className="hint warning">{signalError}</p> : null}
          </WorkspaceMessageStack>
        ) : null}
        <div className="panel panel-compact stack-tight dashboard-hero-guidance" data-testid="dashboard-hero-guidance">
          <p className="hint muted">
            Primary rhythm: confirm today&apos;s priority, launch the right workspace lane, then review recent outcomes.
          </p>
          <SectionStatusStrip compact={true} data-testid="dashboard-hero-guidance-strip">
            <SectionStatusItem
              label="Current priority"
              value={priorityCue.title}
              tone={badgeClassToSummaryTone(priorityCue.badgeClass)}
            />
            <SectionStatusItem
              label="Recommendation run"
              value={recommendationRunStatus || "none"}
              tone={recommendationRunStatus ? "success" : "warning"}
            />
            <SectionStatusItem
              label="Automation"
              value={latestAutomationStatus || "none"}
              tone={
                latestAutomationStatus === "failed"
                  ? "danger"
                  : latestAutomationStatus === "running" || latestAutomationStatus === "queued"
                    ? "warning"
                    : "neutral"
              }
            />
          </SectionStatusStrip>
        </div>
      </OperatorPageHero>

      <OperatorPageSectionStack>
        <SectionCard
          variant="emphasis"
          className="operator-shell-section operator-shell-primary-zone"
          data-testid="dashboard-operator-focus-zone"
        >
          <SectionHeader
            title="What matters now"
            subtitle="Highest-priority action lane based on deterministic workspace signals."
            headingLevel={2}
            variant="focus"
          />
          <div className="operator-focus-grid">
            <div className="operator-focus-main stack">
              <div className="panel panel-compact stack-tight operator-focus-callout" data-testid="dashboard-priority-callout">
                <span className="operator-focus-kicker">Do this next</span>
                <SectionStatusStrip compact={true} className="operator-focus-status-row" data-testid="dashboard-priority-strip">
                  <SectionStatusItem
                    label="Priority cue"
                    value={priorityCue.title}
                    tone={badgeClassToSummaryTone(priorityCue.badgeClass)}
                  />
                  <SectionStatusItem
                    label="Needs review"
                    value={needsReviewCount}
                    detail={needsReviewCount > 0 ? "Recommendations waiting" : "No open queue backlog"}
                    tone={needsReviewCount > 0 ? "warning" : "success"}
                  />
                </SectionStatusStrip>
                <p className="hint muted">{priorityCue.reason}</p>
                <WorkspaceActionBar variant="primary">
                  <Link href={priorityCue.href} className="button button-primary button-inline">
                    {priorityCue.actionLabel}
                  </Link>
                  <Link href={recommendationWorkspaceHref} className="button button-secondary button-inline">
                    Recommendations queue
                  </Link>
                </WorkspaceActionBar>
              </div>
              <div className="panel panel-compact stack operator-focus-next-step">
                <p className="hint muted">Keep supporting lanes in view while executing the primary step.</p>
                <WorkspaceActionBar variant="secondary">
                  <Link href={auditsWorkspaceHref} className="button button-tertiary button-inline">
                    Audit runs
                  </Link>
                  <Link href={competitorsWorkspaceHref} className="button button-tertiary button-inline">
                    Competitors
                  </Link>
                  <Link href={automationWorkspaceHref} className="button button-tertiary button-inline">
                    Automation
                  </Link>
                </WorkspaceActionBar>
              </div>
            </div>
            <div className="operator-focus-support stack">
              <div className="metrics-grid operator-focus-metrics">
                <SummaryStatCard
                  label="Open recommendations"
                  value={openRecommendations}
                  detail="Queue requiring review"
                  tone={openRecommendations > 0 ? "warning" : "success"}
                  variant="focus"
                />
                <SummaryStatCard
                  label="Latest automation"
                  value={latestAutomationStatus || "none"}
                  detail={latestAutomation ? formatDateTime(latestAutomation.finished_at || latestAutomation.started_at) : "No automation run yet"}
                  tone={latestAutomationStatus === "failed" ? "danger" : "neutral"}
                  variant="focus"
                />
                <SummaryStatCard
                  label="Recommendation freshness"
                  value={analysisFreshnessStatus || "unknown"}
                  detail={workspaceSummary?.analysis_freshness?.message || "No freshness summary yet"}
                  tone={
                    analysisFreshnessStatus === "pending_refresh" || analysisFreshnessStatus === "unknown"
                      ? "warning"
                      : "success"
                  }
                  variant="focus"
                />
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard
          variant="summary"
          className="operator-shell-section operator-shell-work-zone"
          data-testid="dashboard-launchpad-section"
        >
          <SectionHeader
            title="Workspace launchpad"
            subtitle="Jump directly into the right execution lane without losing context."
            headingLevel={2}
            variant="support"
          />
          <div className="metrics-grid grid-fit-180 dashboard-launch-grid">
            {launchLanes.map((lane) => (
              <article key={lane.title} className="panel panel-compact stack-tight dashboard-launch-card">
                <div className="link-row">
                  <strong>{lane.title}</strong>
                  <span className={`badge ${lane.badgeClass}`}>{lane.statusLabel}</span>
                </div>
                <p className="hint muted">{lane.summary}</p>
                <WorkspaceActionBar variant="secondary">
                  <Link href={lane.href} className="button button-secondary button-inline">
                    {lane.ctaLabel}
                  </Link>
                </WorkspaceActionBar>
              </article>
            ))}
          </div>
        </SectionCard>

        <SectionCard
          variant="support"
          className="operator-shell-section operator-shell-secondary-zone"
          data-testid="dashboard-recent-activity"
        >
          <SectionHeader
            title="Recent activity and context"
            subtitle="Track latest outcomes and support signals without crowding the primary action lane."
            headingLevel={2}
            variant="support"
          />
          <div className="metrics-grid grid-fit-180 dashboard-activity-grid" data-testid="dashboard-activity-context-grid">
            <div className="panel panel-compact stack-tight">
              <SectionHeader
                title="Recent outcomes"
                subtitle="Latest terminal events across major workflows."
                headingLevel={3}
                compact={true}
                variant="support"
              />
              <WorkspaceMetadataGrid>
                {recentActivityItems.map((item) => (
                  <WorkspaceMetadataItem key={item.label} label={item.label}>
                    <span className="hint muted">{item.value}</span>
                  </WorkspaceMetadataItem>
                ))}
              </WorkspaceMetadataGrid>
            </div>
            <div className="panel panel-compact stack-tight">
              <SectionHeader
                title="Support context"
                subtitle="Signals that influence what should be prioritized next."
                headingLevel={3}
                compact={true}
                variant="support"
              />
              <WorkspaceMetadataGrid>
                {supportSignalItems.map((item) => (
                  <WorkspaceMetadataItem key={item.label} label={item.label}>
                    <span className="hint muted">{item.value}</span>
                  </WorkspaceMetadataItem>
                ))}
              </WorkspaceMetadataGrid>
            </div>
          </div>
        </SectionCard>
      </OperatorPageSectionStack>
    </PageContainer>
  );
}
