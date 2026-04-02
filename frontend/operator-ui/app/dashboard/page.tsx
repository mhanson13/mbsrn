"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { WorkflowSiteSelector } from "../../components/layout/WorkflowSiteSelector";
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
      reason: "Operator signals are scoped by site. Choose a site to continue.",
      actionLabel: "Open Sites",
      href: "/sites",
      badgeClass: "badge-warn",
    };
  }

  if (!selectedSite.last_audit_run_id) {
    return {
      title: "Run the first audit",
      reason: "This site has no audit baseline yet, so recommendation quality is limited.",
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
    reason: "Signals look stable. Continue with routine review of recommendations and automation outcomes.",
    actionLabel: "Open Workspace",
    href: `/sites/${selectedSite.id}`,
    badgeClass: "badge-muted",
  };
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
            subtitle="Business context is unavailable for this session."
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

  const recentActivityItems: Array<{ label: string; value: string }> = [
    {
      label: "Latest audit",
      value: selectedSite
        ? `${selectedSite.last_audit_status || "unknown"} · ${formatDateTime(selectedSite.last_audit_completed_at)}`
        : "No site selected",
    },
    {
      label: "Latest automation",
      value: latestAutomation
        ? `${latestAutomation.status} · ${formatDateTime(latestAutomation.finished_at || latestAutomation.started_at)}`
        : "No automation run recorded",
    },
    {
      label: "Latest recommendation run",
      value: workspaceSummary?.latest_run
        ? `${workspaceSummary.latest_run.status} · ${formatDateTime(workspaceSummary.latest_run.completed_at)}`
        : "No recommendation run recorded",
    },
  ];

  return (
    <PageContainer width="wide" density="compact">
      <SectionCard variant="support" className="role-surface-support">
        <WorkflowSiteSelector
          id="site-picker-dashboard"
          sites={context.sites}
          selectedSiteId={context.selectedSiteId}
          onChange={context.setSelectedSiteId}
        />
      </SectionCard>
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Dashboard"
            subtitle="Operator-first summary for what to review next across audit, recommendations, and automation."
            headingLevel={1}
            variant="hero"
          />
          <div className="workspace-summary-strip role-summary-strip" data-testid="dashboard-summary-strip">
            <SummaryStatCard
              label="Tracked sites"
              value={context.sites.length}
              detail={context.sites.length > 0 ? "Configured and available" : "No sites configured"}
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
          {signalLoading ? <p className="hint muted">Refreshing dashboard signals…</p> : null}
          {signalError ? <p className="hint warning">{signalError}</p> : null}
        </SectionCard>
      </div>

      <SectionCard variant="emphasis" className="role-surface-support" data-testid="dashboard-priority-panel">
        <SectionHeader
          title="Do this now"
          subtitle="Highest-priority deterministic next step from current workspace signals."
          headingLevel={2}
          variant="support"
        />
        <div className="stack-tight">
          <div className="link-row">
            <span className={`badge ${priorityCue.badgeClass}`}>{priorityCue.title}</span>
            {recommendationRunStatus ? (
              <span className="badge badge-muted">Recommendation run: {recommendationRunStatus}</span>
            ) : null}
          </div>
          <p className="hint muted">{priorityCue.reason}</p>
          <div>
            <Link href={priorityCue.href} className="button button-primary button-inline">
              {priorityCue.actionLabel}
            </Link>
          </div>
        </div>
      </SectionCard>

      <SectionCard variant="summary" className="role-surface-support" data-testid="dashboard-recent-activity">
        <SectionHeader
          title="Recent activity"
          subtitle="Latest terminal outcomes across audit, automation, and recommendation generation."
          headingLevel={2}
          variant="support"
        />
        <div className="stack-tight">
          {recentActivityItems.map((item) => (
            <p key={item.label} className="hint muted">
              <span className="text-strong">{item.label}:</span> {item.value}
            </p>
          ))}
        </div>
      </SectionCard>

      <SectionCard variant="support" className="role-surface-support" data-testid="dashboard-quick-navigation">
        <SectionHeader
          title="Quick navigation"
          subtitle="Direct links to operator workflows."
          headingLevel={2}
          variant="support"
        />
        <div className="link-row">
          <Link href="/sites">Sites</Link>
          <Link href="/audits">Audit Runs</Link>
          <Link href="/recommendations">Recommendations</Link>
          <Link href="/automation">Automation</Link>
          <Link href="/competitors">Competitors</Link>
          <Link href="/business-profile">Business Profile</Link>
        </div>
      </SectionCard>
    </PageContainer>
  );
}
