"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  OperatorPageHero,
  OperatorPageSectionStack,
} from "../../../components/layout/OperatorPageSurface";
import { OperatorRouteSupportState } from "../../../components/layout/OperatorRouteSupportState";
import { PageContainer } from "../../../components/layout/PageContainer";
import { RouteActionCluster } from "../../../components/layout/RouteActionCluster";
import { SectionCard } from "../../../components/layout/SectionCard";
import { SectionHeader } from "../../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../../components/layout/SummaryStatCard";
import { WorkspaceActionBar } from "../../../components/layout/WorkspaceActionBar";
import { useOperatorContext } from "../../../components/useOperatorContext";
import {
  createCompetitorProfileGenerationRun,
  createRecommendationRun,
  fetchAuditRuns,
  fetchCompetitorProfileGenerationRunDetail,
  fetchCompetitorProfileGenerationRuns,
  fetchCompetitorProfileGenerationSummary,
  fetchGA4SiteOnboardingStatus,
  fetchGoogleBusinessProfileConnection,
  fetchRecommendationRuns,
  fetchRecommendations,
  fetchRecommendationWorkspaceSummary,
  fetchSearchConsoleSiteSummary,
  fetchSiteAnalyticsSummary,
} from "../../../lib/api/client";
import type {
  CompetitorProfileDraft,
  CompetitorProfileGenerationRun,
  CompetitorProfileGenerationSummaryResponse,
  GA4SiteOnboardingStatusResponse,
  GoogleBusinessProfileConnectionStatusResponse,
  RecommendationListResponse,
  RecommendationRun,
  RecommendationWorkspaceSummaryResponse,
  SEOAuditRun,
  SearchConsoleSiteSummaryResponse,
  SEOSite,
  SiteAnalyticsSummaryResponse,
  SiteGA4Insights,
  WorkspaceSectionFreshness,
} from "../../../lib/api/types";

type WorkspaceContentTab = "recommendations" | "activity";
type Tone = "neutral" | "success" | "warning" | "danger";
type ChecklistStatus = "done" | "pending" | "warning" | "blocked";

type RecommendationQueueSummary = {
  total: number;
  open: number;
  highPriority: number;
};

type GoogleWorkspaceStatus = {
  stateLabel: string;
  detail: string;
  nextActionLabel: string;
  tone: Tone;
  connected: boolean;
  reconnectRequired: boolean;
};

type OperatorPrimaryAction = {
  urgencyLabel: string;
  urgencyBadgeClass: string;
  title: string;
  reason: string;
  contextHint: string | null;
  actionLabel: string;
  actionKind: "navigate" | "callback";
  actionHref: string | null;
};

type ChecklistItem = {
  key: string;
  label: string;
  detail: string;
  status: ChecklistStatus;
  actionLabel: string | null;
  actionHref: string | null;
};

const MAX_AUDIT_ROWS = 8;
const MAX_RECOMMENDATION_ROWS = 8;

function normalizeLowerCaseString(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function normalizeOptionalString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

function normalizeNumericValue(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return value;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Not available";
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return "Not available";
  }
  return new Date(timestamp).toLocaleString();
}

function formatRelativeTime(value: string | null | undefined): string {
  if (!value) {
    return "Not available";
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return "Not available";
  }
  const deltaMinutes = Math.round((Date.now() - timestamp) / 60000);
  if (Math.abs(deltaMinutes) < 60) {
    return `${deltaMinutes}m ago`;
  }
  const deltaHours = Math.round(deltaMinutes / 60);
  if (Math.abs(deltaHours) < 48) {
    return `${deltaHours}h ago`;
  }
  const deltaDays = Math.round(deltaHours / 24);
  return `${deltaDays}d ago`;
}

function formatSignedPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "0%";
  }
  const rounded = Math.round(value * 10) / 10;
  const sign = rounded > 0 ? "+" : "";
  const formatted = Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1);
  return `${sign}${formatted}%`;
}

function formatGa4PercentValue(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "Not available";
  }
  const rounded = Math.round(value * 1000) / 10;
  const formatted = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `${formatted}%`;
}

function formatGa4DurationSeconds(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "Not available";
  }
  return `${Math.max(0, Math.round(value))}s`;
}

function normalizeWorkspaceStatusLabel(value: string | null | undefined): string {
  const normalized = normalizeOptionalString(value);
  if (!normalized) {
    return "Not available";
  }
  return normalized
    .split("_")
    .map((part) => (part.length > 0 ? `${part[0].toUpperCase()}${part.slice(1).toLowerCase()}` : ""))
    .join(" ");
}

function normalizeQueueSummary(response: RecommendationListResponse | null): RecommendationQueueSummary {
  if (!response) {
    return { total: 0, open: 0, highPriority: 0 };
  }
  if (response.filtered_summary) {
    return {
      total: response.filtered_summary.total,
      open: response.filtered_summary.open,
      highPriority: response.filtered_summary.high_priority,
    };
  }
  const byStatus = response.by_status || {};
  const byPriorityBand = response.by_priority_band || {};
  return {
    total: response.total,
    open: Number(byStatus.open || 0),
    highPriority: Number(byPriorityBand.high || 0) + Number(byPriorityBand.critical || 0),
  };
}

function inferGa4HealthStatus(
  status: SiteAnalyticsSummaryResponse["ga4_status"] | string | null | undefined,
  reason: SiteAnalyticsSummaryResponse["ga4_error_reason"] | null | undefined,
):
  | "configured"
  | "not_configured"
  | "reachable"
  | "unavailable"
  | "missing_oauth_scope"
  | "permission_denied"
  | "invalid_property"
  | "no_data"
  | "unknown" {
  const normalizedStatus = normalizeLowerCaseString(status);
  const normalizedReason = normalizeLowerCaseString(reason);
  if (normalizedStatus === "connected") {
    return normalizedReason === "no_data" ? "no_data" : "reachable";
  }
  if (normalizedStatus === "configured") {
    return "configured";
  }
  if (normalizedStatus === "not_configured") {
    return "not_configured";
  }
  if (normalizedReason === "missing_oauth_scope") {
    return "missing_oauth_scope";
  }
  if (normalizedReason === "access_denied" || normalizedReason === "permission_denied") {
    return "permission_denied";
  }
  if (normalizedReason === "invalid_property_format" || normalizedReason === "property_not_found") {
    return "invalid_property";
  }
  if (normalizedStatus === "error") {
    return "unavailable";
  }
  return "unknown";
}

function formatGa4HealthStatusLabel(
  status:
    | "configured"
    | "not_configured"
    | "reachable"
    | "unavailable"
    | "missing_oauth_scope"
    | "permission_denied"
    | "invalid_property"
    | "no_data"
    | "unknown",
): string {
  if (status === "not_configured") {
    return "Not configured";
  }
  if (status === "configured") {
    return "Configured";
  }
  if (status === "reachable") {
    return "Reachable";
  }
  if (status === "no_data") {
    return "No recent data";
  }
  if (status === "missing_oauth_scope") {
    return "GA4 authorization missing";
  }
  if (status === "permission_denied") {
    return "Permission issue";
  }
  if (status === "invalid_property") {
    return "Invalid property";
  }
  if (status === "unavailable") {
    return "Temporarily unavailable";
  }
  return "Unknown";
}

function ga4DiagnosticReasonMessage(
  reason: SiteAnalyticsSummaryResponse["ga4_error_reason"] | null | undefined,
): string | null {
  if (!reason) {
    return null;
  }
  if (reason === "not_configured") {
    return "GA4 is not connected for this site yet.";
  }
  if (reason === "access_denied" || reason === "permission_denied") {
    return "This property is not accessible. Ensure the service account has Viewer access.";
  }
  if (reason === "missing_oauth_scope") {
    return "GA4 authorization scope is missing.";
  }
  if (reason === "property_not_found") {
    return "This GA4 property ID was not found.";
  }
  if (reason === "invalid_property_format") {
    return "GA4 property ID format is invalid.";
  }
  if (reason === "no_data") {
    return "Property is connected but has limited or no recent data.";
  }
  return "GA4 connection failed for an unknown reason.";
}

function ga4HealthNextActionMessage(
  status:
    | "configured"
    | "not_configured"
    | "reachable"
    | "unavailable"
    | "missing_oauth_scope"
    | "permission_denied"
    | "invalid_property"
    | "no_data"
    | "unknown",
): string | null {
  if (status === "not_configured") {
    return "Add a GA4 property ID for this site.";
  }
  if (status === "permission_denied") {
    return "Verify the connected Google account can read this GA4 property.";
  }
  if (status === "missing_oauth_scope") {
    return "Reconnect Google with GA4 read-only access and retry.";
  }
  if (status === "invalid_property") {
    return "Enter the numeric GA4 property ID, not the G- measurement ID.";
  }
  if (status === "no_data") {
    return "GA4 is reachable, but no recent data was returned.";
  }
  if (status === "unavailable") {
    return "Retry after a short delay.";
  }
  return null;
}

function normalizeGa4InsightsStatusValue(value: unknown): SiteGA4Insights["status"] | null {
  const normalized = normalizeLowerCaseString(value);
  if (
    normalized === "available"
    || normalized === "not_configured"
    || normalized === "missing_oauth_scope"
    || normalized === "permission_denied"
    || normalized === "invalid_property"
    || normalized === "no_data"
    || normalized === "unavailable"
    || normalized === "unknown"
  ) {
    return normalized;
  }
  return null;
}

function formatGa4InsightsStatusLabel(status: SiteGA4Insights["status"]): string {
  if (status === "available") {
    return "Available";
  }
  if (status === "not_configured") {
    return "Not configured";
  }
  if (status === "missing_oauth_scope") {
    return "Authorization missing";
  }
  if (status === "permission_denied") {
    return "Permission issue";
  }
  if (status === "invalid_property") {
    return "Invalid property";
  }
  if (status === "no_data") {
    return "No recent data";
  }
  if (status === "unavailable") {
    return "Temporarily unavailable";
  }
  return "Unknown";
}

function ga4InsightsToneForStatus(status: SiteGA4Insights["status"]): Tone {
  if (status === "available") {
    return "success";
  }
  if (status === "not_configured" || status === "no_data") {
    return "warning";
  }
  if (
    status === "missing_oauth_scope"
    || status === "permission_denied"
    || status === "invalid_property"
    || status === "unavailable"
  ) {
    return "danger";
  }
  return "neutral";
}

function normalizeGa4TrendLabel(value: unknown): "improving" | "declining" | "steady" | "unknown" {
  const normalized = normalizeLowerCaseString(value);
  if (normalized === "improving" || normalized === "declining" || normalized === "steady") {
    return normalized;
  }
  return "unknown";
}

function ga4InsightsToneForTrend(
  trendLabel: "improving" | "declining" | "steady" | "unknown" | null | undefined,
): Tone {
  if (trendLabel === "improving") {
    return "success";
  }
  if (trendLabel === "declining") {
    return "warning";
  }
  return "neutral";
}

function formatGa4TopLandingPagesCompactList(
  pages: Array<{ path?: string | null; sessions?: number | null }>,
): string {
  if (!pages.length) {
    return "No landing-page summaries returned for this period.";
  }
  return pages
    .slice(0, 3)
    .map((page) => {
      const normalizedPath = normalizeOptionalString(page.path) || "/";
      const sessions = Math.max(0, Number(page.sessions) || 0);
      return `${normalizedPath} (${sessions.toLocaleString()} sessions)`;
    })
    .join(" · ");
}

function deriveFreshnessLabel(freshness: WorkspaceSectionFreshness | null | undefined, fallback: string): string {
  const label = normalizeOptionalString(freshness?.state_label);
  if (label) {
    return label;
  }
  return fallback;
}

function checklistBadgeClass(status: ChecklistStatus): string {
  if (status === "done") {
    return "badge badge-success";
  }
  if (status === "warning") {
    return "badge badge-warn";
  }
  if (status === "blocked") {
    return "badge badge-critical";
  }
  return "badge badge-muted";
}

function checklistStatusLabel(status: ChecklistStatus): string {
  if (status === "done") {
    return "Done";
  }
  if (status === "warning") {
    return "Needs attention";
  }
  if (status === "blocked") {
    return "Blocked";
  }
  return "Pending";
}

function deriveGoogleWorkspaceStatus(
  connection: GoogleBusinessProfileConnectionStatusResponse | null,
  connectionError: string | null,
): GoogleWorkspaceStatus {
  if (connectionError) {
    return {
      stateLabel: "Unavailable",
      detail: connectionError,
      nextActionLabel: "Open Google Profile",
      tone: "danger",
      connected: false,
      reconnectRequired: true,
    };
  }
  if (!connection || !connection.connected) {
    return {
      stateLabel: "Not connected",
      detail: "Connect Google Profile to unlock profile sync and workflow guidance.",
      nextActionLabel: "Open Google Profile",
      tone: "warning",
      connected: false,
      reconnectRequired: false,
    };
  }

  const reconnectRequired = Boolean(
    connection.reconnect_required
      || connection.token_status === "reconnect_required"
      || connection.token_status === "insufficient_scope"
      || connection.token_status === "refresh_required"
      || !connection.refresh_token_present,
  );

  if (reconnectRequired) {
    return {
      stateLabel: "Reconnect required",
      detail: "Google session needs reconnect before profile and analytics reads can continue.",
      nextActionLabel: "Open Google Profile",
      tone: "warning",
      connected: true,
      reconnectRequired: true,
    };
  }

  if (!connection.required_scopes_satisfied) {
    return {
      stateLabel: "Scope update needed",
      detail: "Connected account is missing one or more required read scopes.",
      nextActionLabel: "Open Google Profile",
      tone: "warning",
      connected: true,
      reconnectRequired: true,
    };
  }

  return {
    stateLabel: "Connected",
    detail: connection.last_refreshed_at
      ? `Connected and refreshed ${formatRelativeTime(connection.last_refreshed_at)}.`
      : "Connected and ready.",
    nextActionLabel: "Open Google Profile",
    tone: "success",
    connected: true,
    reconnectRequired: false,
  };
}

function checklistItem(
  key: string,
  label: string,
  detail: string,
  status: ChecklistStatus,
  actionLabel: string | null,
  actionHref: string | null,
): ChecklistItem {
  return { key, label, detail, status, actionLabel, actionHref };
}

type SiteWorkspaceHeroProps = {
  selectedSite: SEOSite;
  recommendationFreshnessLabel: string;
  recommendationQueueOpen: number;
  competitorFreshnessLabel: string;
  workspaceReadinessMessage: string;
  operatorPrimaryAction: OperatorPrimaryAction;
  loadingWorkspace: boolean;
  onPrimaryAction: () => void;
};

function SiteWorkspaceHero({
  selectedSite,
  recommendationFreshnessLabel,
  recommendationQueueOpen,
  competitorFreshnessLabel,
  workspaceReadinessMessage,
  operatorPrimaryAction,
  loadingWorkspace,
  onPrimaryAction,
}: SiteWorkspaceHeroProps) {
  return (
    <OperatorPageHero
      title="Site SEO Workspace"
      subtitle="Decision-first command center for recommendations, competitors, migration, and integrations."
      headingLevel={1}
      className="site-workspace-hero"
      data-testid="site-workspace-hero"
      meta={(
        <div className="workspace-section-meta site-workspace-hero-meta">
          <span className="hint muted">Site: <strong>{selectedSite.display_name}</strong></span>
          <span className="hint muted">Domain: {selectedSite.normalized_domain}</span>
          <span className="hint muted">Base URL: {selectedSite.base_url}</span>
          <span className="hint muted">Business ID: <code>{selectedSite.business_id}</code></span>
          <span className="hint muted">Site ID: <code>{selectedSite.id}</code></span>
          <span className="hint muted">Last audit: {selectedSite.last_audit_status || "-"} ({formatDateTime(selectedSite.last_audit_completed_at)})</span>
        </div>
      )}
      actions={(
        <RouteActionCluster
          className="site-workspace-hero-links"
          secondaryActions={(
            <>
              <Link href="/sites">Back to Sites</Link>
              <Link href="/audits">Audit Runs</Link>
            </>
          )}
          shortcutActions={(
            <>
              <Link href={`/competitors?site_id=${encodeURIComponent(selectedSite.id)}`}>Competitor Workspace</Link>
              <Link href="/recommendations">Recommendation Queue</Link>
            </>
          )}
        />
      )}
      summary={(
        <>
          <SummaryStatCard
            label="What matters now"
            value={operatorPrimaryAction.urgencyLabel}
            detail={operatorPrimaryAction.title}
            tone={operatorPrimaryAction.urgencyBadgeClass.includes("critical") ? "danger" : "warning"}
            variant="elevated"
            data-testid="workspace-hero-summary-focus"
          />
          <SummaryStatCard
            label="Recommendations"
            value={recommendationFreshnessLabel}
            detail={`${recommendationQueueOpen} open actions`}
            tone={recommendationQueueOpen > 0 ? "warning" : "neutral"}
            variant="elevated"
            data-testid="workspace-hero-summary-recommendations"
          />
          <SummaryStatCard
            label="Migration workflow"
            value="Dedicated route"
            detail="Use the migration page for draft, review, publish, and deploy."
            tone="neutral"
            variant="elevated"
            data-testid="workspace-hero-summary-migration"
          />
          <SummaryStatCard
            label="Supporting context"
            value={competitorFreshnessLabel}
            detail={workspaceReadinessMessage}
            tone="neutral"
            variant="elevated"
            data-testid="workspace-hero-summary-supporting-context"
          />
        </>
      )}
    >
      <div className="site-workspace-hero-control-grid" data-testid="site-workspace-control-grid">
        <div className="panel panel-compact stack-tight site-workspace-hero-control-card site-workspace-hero-control-card-primary">
          <span className="hint muted">Primary decision</span>
          <div className="link-row operator-focus-status-row">
            <span className={operatorPrimaryAction.urgencyBadgeClass} data-testid="workspace-hero-primary-urgency">
              {operatorPrimaryAction.urgencyLabel}
            </span>
          </div>
          <strong>{operatorPrimaryAction.title}</strong>
          <span className="hint">{operatorPrimaryAction.reason}</span>
          {operatorPrimaryAction.contextHint ? <span className="hint muted">{operatorPrimaryAction.contextHint}</span> : null}
          <WorkspaceActionBar variant="primary">
            {operatorPrimaryAction.actionKind === "navigate" && operatorPrimaryAction.actionHref ? (
              <Link href={operatorPrimaryAction.actionHref} className="button button-primary" data-testid="workspace-hero-primary-action-link">
                {operatorPrimaryAction.actionLabel}
              </Link>
            ) : (
              <button
                type="button"
                className="button button-primary"
                data-testid="workspace-hero-primary-action-button"
                onClick={onPrimaryAction}
              >
                {operatorPrimaryAction.actionLabel}
              </button>
            )}
          </WorkspaceActionBar>
        </div>
        <div className="panel panel-compact stack-tight site-workspace-hero-control-card site-workspace-hero-control-card-migration" data-testid="workspace-hero-migration-callout">
          <span className="hint muted">Migration workflow</span>
          <strong>Migration execution stays on the dedicated route.</strong>
          <span className="hint">Review, approve, publish, and deploy migration artifacts from the migration workflow page.</span>
          <WorkspaceActionBar variant="secondary">
            <Link href={`/sites/${encodeURIComponent(selectedSite.id)}/migration`} className="button button-secondary button-inline" data-testid="workspace-hero-open-migration-button">
              Open Migration Workflow
            </Link>
          </WorkspaceActionBar>
        </div>
      </div>
      {loadingWorkspace ? <p className="hint muted">Loading workspace data...</p> : null}
    </OperatorPageHero>
  );
}

type WorkspaceSnapshotProps = {
  competitorFreshnessLabel: string;
  workspaceReadinessMessage: string;
  recommendationFreshnessLabel: string;
  recommendationQueueSummary: RecommendationQueueSummary;
  actionableRecommendationCount: number;
  ga4TopLandingValue: string;
  ga4TopLandingDetail: string;
  ga4TopLandingTone: Tone;
  ga4TrafficTrendValue: string;
  ga4TrafficTrendDetail: string;
  ga4TrafficTrendTone: Tone;
  ga4EngagementTrendValue: string;
  ga4EngagementTrendDetail: string;
  ga4EngagementTrendTone: Tone;
  ga4OnboardingValue: string;
  ga4OnboardingDetail: string;
  ga4OnboardingTone: Tone;
  searchVisibilityTrendValue: string;
  searchVisibilityTrendDetail: string;
  searchVisibilityTrendTone: Tone;
  googleStatus: GoogleWorkspaceStatus;
};

function WorkspaceSnapshot({
  competitorFreshnessLabel,
  workspaceReadinessMessage,
  recommendationFreshnessLabel,
  recommendationQueueSummary,
  actionableRecommendationCount,
  ga4TopLandingValue,
  ga4TopLandingDetail,
  ga4TopLandingTone,
  ga4TrafficTrendValue,
  ga4TrafficTrendDetail,
  ga4TrafficTrendTone,
  ga4EngagementTrendValue,
  ga4EngagementTrendDetail,
  ga4EngagementTrendTone,
  ga4OnboardingValue,
  ga4OnboardingDetail,
  ga4OnboardingTone,
  searchVisibilityTrendValue,
  searchVisibilityTrendDetail,
  searchVisibilityTrendTone,
  googleStatus,
}: WorkspaceSnapshotProps) {
  return (
    <SectionCard className="operator-shell-summary-panel" variant="summary">
      <SectionHeader
        title="Workspace Snapshot"
        subtitle="At-a-glance health and readiness across recommendation, competitor, and analytics context."
        headingLevel={2}
        variant="support"
        data-testid="workspace-snapshot-header"
      />
      <div className="workspace-summary-strip" data-testid="workspace-summary-strip">
        <SummaryStatCard
          label="Competitor section"
          value={competitorFreshnessLabel}
          detail={workspaceReadinessMessage}
          tone="neutral"
          variant="elevated"
          data-testid="workspace-summary-competitors"
        />
        <SummaryStatCard
          label="Recommendation section"
          value={recommendationFreshnessLabel}
          detail={`${recommendationQueueSummary.open} open of ${recommendationQueueSummary.total} total`}
          tone={recommendationQueueSummary.open > 0 ? "warning" : "neutral"}
          variant="elevated"
          data-testid="workspace-summary-recommendations"
        />
        <SummaryStatCard
          label="Actionable recommendations"
          value={actionableRecommendationCount}
          detail="Recommendations still open, in progress, or unresolved."
          tone={actionableRecommendationCount > 0 ? "success" : "neutral"}
          variant="elevated"
          data-testid="workspace-summary-actionable"
        />
        <SummaryStatCard
          label="Top landing pages"
          value={ga4TopLandingValue}
          detail={ga4TopLandingDetail}
          tone={ga4TopLandingTone}
          variant="elevated"
          data-testid="workspace-summary-ga4-top-landing-pages"
        />
        <SummaryStatCard
          label="Traffic trend"
          value={ga4TrafficTrendValue}
          detail={ga4TrafficTrendDetail}
          tone={ga4TrafficTrendTone}
          variant="elevated"
          data-testid="workspace-summary-traffic"
        />
        <SummaryStatCard
          label="Engagement trend"
          value={ga4EngagementTrendValue}
          detail={ga4EngagementTrendDetail}
          tone={ga4EngagementTrendTone}
          variant="elevated"
          data-testid="workspace-summary-ga4-engagement-trend"
        />
        <SummaryStatCard
          label="GA4 onboarding"
          value={ga4OnboardingValue}
          detail={ga4OnboardingDetail}
          tone={ga4OnboardingTone}
          variant="elevated"
          data-testid="workspace-summary-ga4-onboarding"
        />
        <SummaryStatCard
          label="Search visibility trend"
          value={searchVisibilityTrendValue}
          detail={searchVisibilityTrendDetail}
          tone={searchVisibilityTrendTone}
          variant="elevated"
          data-testid="workspace-summary-search-visibility"
        />
        <SummaryStatCard
          label="Google Profile"
          value={googleStatus.stateLabel}
          detail={<>{googleStatus.detail} <Link href="/google-profile">{googleStatus.nextActionLabel}</Link></>}
          tone={googleStatus.tone}
          variant="elevated"
          data-testid="workspace-summary-gbp"
        />
      </div>
    </SectionCard>
  );
}

type WorkspaceSetupChecklistProps = {
  setupChecklistItems: ChecklistItem[];
};

function WorkspaceSetupChecklist({ setupChecklistItems }: WorkspaceSetupChecklistProps) {
  return (
    <SectionCard className="operator-shell-section operator-shell-secondary-zone">
      <SectionHeader
        title="Setup / Readiness Checklist"
        subtitle="Compact progression guide for clearing blockers before deeper workflow execution."
        headingLevel={2}
      />
      <div className="panel panel-compact stack-tight" data-testid="workspace-setup-checklist">
        <div className="stack-tight">
          {setupChecklistItems.map((item) => (
            <div key={item.key} className="stack-tight" data-testid={`workspace-setup-item-${item.key}`}>
              <div className="link-row">
                <span className={checklistBadgeClass(item.status)}>{checklistStatusLabel(item.status)}</span>
                <strong>{item.label}</strong>
              </div>
              <span className="hint muted">{item.detail}</span>
              {item.actionHref && item.actionLabel ? <Link href={item.actionHref}>{item.actionLabel}</Link> : null}
            </div>
          ))}
        </div>
      </div>
    </SectionCard>
  );
}

type WorkspaceLatestActivityProps = {
  latestAuditRun: SEOAuditRun | null;
  latestRecommendationRun: RecommendationRun | null;
  latestCompetitorRun: CompetitorProfileGenerationRun | null;
  competitorSummary: CompetitorProfileGenerationSummaryResponse | null;
  selectedSiteId: string;
};

function WorkspaceLatestActivity({
  latestAuditRun,
  latestRecommendationRun,
  latestCompetitorRun,
  competitorSummary,
  selectedSiteId,
}: WorkspaceLatestActivityProps) {
  return (
    <div
      className="panel panel-compact stack-tight"
      role="tabpanel"
      id="workspace-content-activity-panel"
      aria-labelledby="workspace-content-tab-activity"
      data-testid="workspace-activity-summary-panel"
    >
      <span className="hint muted">Latest activity summary</span>
      <div className="stack-tight">
        <p className="hint">
          Audit: <strong>{latestAuditRun?.status || "No run yet"}</strong>
          {latestAuditRun?.completed_at ? ` · ${formatDateTime(latestAuditRun.completed_at)}` : ""}
          {typeof latestAuditRun?.pages_crawled === "number" ? ` · ${latestAuditRun.pages_crawled} pages` : ""}
          {typeof latestAuditRun?.errors_encountered === "number" ? ` · ${latestAuditRun.errors_encountered} errors` : ""}
        </p>
        <p className="hint">
          Recommendations: <strong>{latestRecommendationRun?.status || "No run yet"}</strong>
          {latestRecommendationRun?.completed_at
            ? ` · ${formatDateTime(latestRecommendationRun.completed_at)}`
            : latestRecommendationRun?.created_at
              ? ` · ${formatDateTime(latestRecommendationRun.created_at)}`
              : ""}
        </p>
        <p className="hint">
          Competitors: <strong>{latestCompetitorRun?.status || "No run yet"}</strong>
          {latestCompetitorRun?.completed_at
            ? ` · ${formatDateTime(latestCompetitorRun.completed_at)}`
            : latestCompetitorRun?.created_at
              ? ` · ${formatDateTime(latestCompetitorRun.created_at)}`
              : ""}
        </p>
        <p className="hint">
          Competitor analytics window: <strong>{competitorSummary?.lookback_days || 0} days</strong>
        </p>
      </div>
      <WorkspaceActionBar variant="secondary">
        <Link href="/recommendations" className="button button-secondary button-inline">Recommendation Runs</Link>
        <Link href={`/competitors?site_id=${encodeURIComponent(selectedSiteId)}`} className="button button-secondary button-inline">Competitor Runs</Link>
        <Link href="/audits" className="button button-secondary button-inline">Audit Runs</Link>
      </WorkspaceActionBar>
    </div>
  );
}

type WorkflowLaunchpadProps = {
  activeWorkspaceContentTab: WorkspaceContentTab;
  setActiveWorkspaceContentTab: (tab: WorkspaceContentTab) => void;
  operatorPrimaryAction: OperatorPrimaryAction;
  recommendationQueueSummary: RecommendationQueueSummary;
  recommendationFreshnessLabel: string;
  recommendationGenerationPrerequisitesMet: boolean;
  recommendationGenerationInFlight: boolean;
  onGenerateRecommendations: () => void;
  reviewableDraftCount: number;
  competitorFreshnessLabel: string;
  pendingDraftCount: number;
  acceptedDraftCount: number;
  rejectedDraftCount: number;
  syntheticScaffoldWarningCount: number;
  competitorGenerationInFlight: boolean;
  onGenerateCompetitorProfiles: () => void;
  selectedSiteId: string;
  googleStatus: GoogleWorkspaceStatus;
  latestAuditRun: SEOAuditRun | null;
  latestRecommendationRun: RecommendationRun | null;
  latestCompetitorRun: CompetitorProfileGenerationRun | null;
  competitorSummary: CompetitorProfileGenerationSummaryResponse | null;
};

function WorkflowLaunchpad({
  activeWorkspaceContentTab,
  setActiveWorkspaceContentTab,
  operatorPrimaryAction,
  recommendationQueueSummary,
  recommendationFreshnessLabel,
  recommendationGenerationPrerequisitesMet,
  recommendationGenerationInFlight,
  onGenerateRecommendations,
  reviewableDraftCount,
  competitorFreshnessLabel,
  pendingDraftCount,
  acceptedDraftCount,
  rejectedDraftCount,
  syntheticScaffoldWarningCount,
  competitorGenerationInFlight,
  onGenerateCompetitorProfiles,
  selectedSiteId,
  googleStatus,
  latestAuditRun,
  latestRecommendationRun,
  latestCompetitorRun,
  competitorSummary,
}: WorkflowLaunchpadProps) {
  return (
    <SectionCard className="operator-shell-section operator-shell-secondary-zone workspace-content-tab-shell site-workspace-tab-shell">
      <SectionHeader
        title="Workflow Launchpad"
        subtitle="Site workspace is a launchpad. Full execution stays on dedicated workflow routes."
        headingLevel={2}
      />
      <div className="workspace-subtabs site-workspace-subtabs" role="tablist" aria-label="Workspace launchpad views">
        <button
          type="button"
          id="workspace-content-tab-recommendations"
          role="tab"
          className={`button button-secondary workspace-subtab-button ${activeWorkspaceContentTab === "recommendations" ? "workspace-subtab-button-active" : ""}`}
          aria-selected={activeWorkspaceContentTab === "recommendations"}
          aria-controls="workspace-content-recommendations-panel"
          onClick={() => setActiveWorkspaceContentTab("recommendations")}
        >
          Workflows
        </button>
        <button
          type="button"
          id="workspace-content-tab-activity"
          role="tab"
          className={`button button-secondary workspace-subtab-button ${activeWorkspaceContentTab === "activity" ? "workspace-subtab-button-active" : ""}`}
          aria-selected={activeWorkspaceContentTab === "activity"}
          aria-controls="workspace-content-activity-panel"
          onClick={() => setActiveWorkspaceContentTab("activity")}
        >
          Latest Activity
        </button>
      </div>
      <p className="hint muted">
        {activeWorkspaceContentTab === "recommendations"
          ? "Launch recommendations, competitors, migration, and profile workflows from here."
          : "Compact activity summary only. Full run tables stay on workflow-specific pages."}
      </p>
      <div className="site-workspace-tab-meta" data-testid="workspace-content-tab-meta">
        <WorkspaceActionBar variant="secondary" className="row-wrap-tight">
          <span className="badge badge-muted">Active view: {activeWorkspaceContentTab === "recommendations" ? "Recommendations" : "Activity"}</span>
          <span className={operatorPrimaryAction.urgencyBadgeClass}>Next action: {operatorPrimaryAction.urgencyLabel}</span>
        </WorkspaceActionBar>
      </div>

      {activeWorkspaceContentTab === "recommendations" ? (
        <div
          className="site-workspace-launcher-grid"
          role="tabpanel"
          id="workspace-content-recommendations-panel"
          aria-labelledby="workspace-content-tab-recommendations"
          data-testid="workspace-launchers-panel"
        >
          <article className="panel panel-compact stack-tight" data-testid="workspace-launcher-recommendations">
            <span className="hint muted">Recommendations</span>
            <strong>{recommendationQueueSummary.open} open actions</strong>
            <span className="hint">High-priority ready now: {recommendationQueueSummary.highPriority}. Freshness: {recommendationFreshnessLabel}.</span>
            <WorkspaceActionBar variant="secondary">
              <Link href="/recommendations" className="button button-secondary button-inline" data-testid="workspace-open-recommendations-shortcut">
                Open Recommendation Queue
              </Link>
              <button
                type="button"
                className="button button-tertiary button-inline"
                onClick={onGenerateRecommendations}
                disabled={!recommendationGenerationPrerequisitesMet || recommendationGenerationInFlight}
                data-testid="workspace-generate-recommendations-shortcut"
              >
                {recommendationGenerationInFlight ? "Generating..." : "Generate Recommendations"}
              </button>
            </WorkspaceActionBar>
          </article>

          <article className="panel panel-compact stack-tight" data-testid="workspace-launcher-competitors">
            <span className="hint muted">Competitors</span>
            <strong>{reviewableDraftCount} reviewable drafts</strong>
            <span className="hint">Freshness: {competitorFreshnessLabel}. Pending {pendingDraftCount}, accepted {acceptedDraftCount}, rejected {rejectedDraftCount}.</span>
            {syntheticScaffoldWarningCount > 0 ? (
              <span className="hint warning">Synthetic scaffold warnings: {syntheticScaffoldWarningCount}</span>
            ) : null}
            <WorkspaceActionBar variant="secondary">
              <Link href={`/competitors?site_id=${encodeURIComponent(selectedSiteId)}`} className="button button-secondary button-inline" data-testid="workspace-open-competitors-shortcut">
                Open Competitor Workspace
              </Link>
              <button
                type="button"
                className="button button-tertiary button-inline"
                onClick={onGenerateCompetitorProfiles}
                disabled={competitorGenerationInFlight}
                data-testid="workspace-generate-competitors-shortcut"
              >
                {competitorGenerationInFlight ? "Generating..." : "Generate Competitor Profiles"}
              </button>
            </WorkspaceActionBar>
          </article>

          <article className="panel panel-compact stack-tight" data-testid="workspace-launcher-migration">
            <span className="hint muted">Migration</span>
            <strong>Draft, review, publish, and deploy workflow</strong>
            <span className="hint">Migration execution remains on the dedicated route.</span>
            <WorkspaceActionBar variant="secondary">
              <Link href={`/sites/${encodeURIComponent(selectedSiteId)}/migration`} className="button button-secondary button-inline" data-testid="workspace-open-migration-shortcut">
                Open Migration Workflow
              </Link>
            </WorkspaceActionBar>
          </article>

          <article className="panel panel-compact stack-tight" data-testid="workspace-launcher-integrations">
            <span className="hint muted">Google Profile / Integrations</span>
            <strong>{googleStatus.stateLabel}</strong>
            <span className="hint">{googleStatus.detail}</span>
            <WorkspaceActionBar variant="secondary">
              <Link href="/google-profile" className="button button-secondary button-inline">Open Google Profile</Link>
            </WorkspaceActionBar>
          </article>
        </div>
      ) : (
        <WorkspaceLatestActivity
          latestAuditRun={latestAuditRun}
          latestRecommendationRun={latestRecommendationRun}
          latestCompetitorRun={latestCompetitorRun}
          competitorSummary={competitorSummary}
          selectedSiteId={selectedSiteId}
        />
      )}
    </SectionCard>
  );
}

export default function SiteWorkspacePage() {
  const params = useParams<{ site_id: string }>();
  const siteId = (params?.site_id || "").trim();
  const context = useOperatorContext();
  const selectedSite = useMemo(
    () => context.sites.find((item) => item.id === siteId) || null,
    [context.sites, siteId],
  );

  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  const [auditRuns, setAuditRuns] = useState<SEOAuditRun[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationListResponse | null>(null);
  const [recommendationRuns, setRecommendationRuns] = useState<RecommendationRun[]>([]);
  const [recommendationWorkspaceSummary, setRecommendationWorkspaceSummary] =
    useState<RecommendationWorkspaceSummaryResponse | null>(null);

  const [competitorRuns, setCompetitorRuns] = useState<CompetitorProfileGenerationRun[]>([]);
  const [competitorDrafts, setCompetitorDrafts] = useState<CompetitorProfileDraft[]>([]);
  const [competitorSummary, setCompetitorSummary] = useState<CompetitorProfileGenerationSummaryResponse | null>(null);

  const [siteAnalyticsSummary, setSiteAnalyticsSummary] = useState<SiteAnalyticsSummaryResponse | null>(null);
  const [ga4OnboardingStatus, setGa4OnboardingStatus] = useState<GA4SiteOnboardingStatusResponse | null>(null);
  const [ga4OnboardingError, setGa4OnboardingError] = useState<string | null>(null);
  const [searchConsoleSiteSummary, setSearchConsoleSiteSummary] = useState<SearchConsoleSiteSummaryResponse | null>(null);
  const [searchConsoleSiteSummaryError, setSearchConsoleSiteSummaryError] = useState<string | null>(null);

  const [googleBusinessProfileConnection, setGoogleBusinessProfileConnection] =
    useState<GoogleBusinessProfileConnectionStatusResponse | null>(null);
  const [googleBusinessProfileConnectionError, setGoogleBusinessProfileConnectionError] = useState<string | null>(null);

  const [recommendationGenerationInFlight, setRecommendationGenerationInFlight] = useState(false);
  const [competitorGenerationInFlight, setCompetitorGenerationInFlight] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeWorkspaceContentTab, setActiveWorkspaceContentTab] = useState<WorkspaceContentTab>("recommendations");

  const refreshWorkspace = useCallback(async () => {
    if (!context.token || !context.businessId || !siteId) {
      return;
    }

    setLoadingWorkspace(true);
    setWorkspaceError(null);

    const settled = await Promise.allSettled([
      fetchAuditRuns(context.token, context.businessId, siteId),
      fetchRecommendations(context.token, context.businessId, siteId, { page_size: MAX_RECOMMENDATION_ROWS }),
      fetchRecommendationRuns(context.token, context.businessId, siteId),
      fetchRecommendationWorkspaceSummary(context.token, context.businessId, siteId),
      fetchCompetitorProfileGenerationRuns(context.token, context.businessId, siteId),
      fetchCompetitorProfileGenerationSummary(context.token, context.businessId, siteId),
      fetchSiteAnalyticsSummary(context.token, context.businessId, siteId),
      fetchGA4SiteOnboardingStatus(context.token, context.businessId, siteId),
      fetchSearchConsoleSiteSummary(context.token, context.businessId, siteId),
      fetchGoogleBusinessProfileConnection(context.token),
    ]);

    const [
      auditRunsResult,
      recommendationsResult,
      recommendationRunsResult,
      recommendationSummaryResult,
      competitorRunsResult,
      competitorSummaryResult,
      siteAnalyticsResult,
      ga4OnboardingResult,
      searchConsoleResult,
      googleProfileResult,
    ] = settled;

    const auditRunItems =
      auditRunsResult.status === "fulfilled" && Array.isArray(auditRunsResult.value?.items)
        ? auditRunsResult.value.items.slice(0, MAX_AUDIT_ROWS)
        : [];
    const recommendationListResponse =
      recommendationsResult.status === "fulfilled" && recommendationsResult.value
        ? recommendationsResult.value
        : null;
    const recommendationRunItems =
      recommendationRunsResult.status === "fulfilled" && Array.isArray(recommendationRunsResult.value?.items)
        ? recommendationRunsResult.value.items
        : [];
    const recommendationSummaryResponse =
      recommendationSummaryResult.status === "fulfilled" && recommendationSummaryResult.value
        ? recommendationSummaryResult.value
        : null;
    const competitorRunItems =
      competitorRunsResult.status === "fulfilled" && Array.isArray(competitorRunsResult.value?.items)
        ? competitorRunsResult.value.items
        : [];
    const competitorSummaryResponse =
      competitorSummaryResult.status === "fulfilled" && competitorSummaryResult.value
        ? competitorSummaryResult.value
        : null;

    setAuditRuns(auditRunItems);
    setRecommendations(recommendationListResponse);
    setRecommendationRuns(recommendationRunItems);
    setRecommendationWorkspaceSummary(recommendationSummaryResponse);
    setCompetitorRuns(competitorRunItems);
    setCompetitorSummary(competitorSummaryResponse);
    setSiteAnalyticsSummary(siteAnalyticsResult.status === "fulfilled" ? siteAnalyticsResult.value : null);

    if (ga4OnboardingResult.status === "fulfilled") {
      setGa4OnboardingStatus(ga4OnboardingResult.value);
      setGa4OnboardingError(null);
    } else {
      setGa4OnboardingStatus(null);
      setGa4OnboardingError("GA4 onboarding status unavailable.");
    }

    if (searchConsoleResult.status === "fulfilled") {
      setSearchConsoleSiteSummary(searchConsoleResult.value);
      setSearchConsoleSiteSummaryError(null);
    } else {
      setSearchConsoleSiteSummary(null);
      setSearchConsoleSiteSummaryError("Search Console summary unavailable.");
    }

    if (googleProfileResult.status === "fulfilled") {
      setGoogleBusinessProfileConnection(googleProfileResult.value);
      setGoogleBusinessProfileConnectionError(null);
    } else {
      setGoogleBusinessProfileConnection(null);
      setGoogleBusinessProfileConnectionError("Google Profile connection unavailable.");
    }

    if (competitorRunItems.length > 0) {
      const latestRun = competitorRunItems[0];
      try {
        const detail = await fetchCompetitorProfileGenerationRunDetail(
          context.token,
          context.businessId,
          siteId,
          latestRun.id,
        );
        setCompetitorDrafts(detail.drafts || []);
      } catch {
        setCompetitorDrafts([]);
      }
    } else {
      setCompetitorDrafts([]);
    }

    if (siteAnalyticsResult.status === "rejected") {
      setWorkspaceError("Site analytics summary is temporarily unavailable.");
    }
    setLoadingWorkspace(false);
  }, [context.businessId, context.token, siteId]);

  useEffect(() => {
    if (!selectedSite || !context.token || !context.businessId || !siteId) {
      return;
    }
    void refreshWorkspace();
  }, [context.businessId, context.token, refreshWorkspace, selectedSite, siteId]);

  const handleGenerateRecommendations = useCallback(async () => {
    if (!context.token || !context.businessId || !siteId) {
      return;
    }
    setRecommendationGenerationInFlight(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const run = await createRecommendationRun(context.token, context.businessId, siteId, {});
      setActionMessage(`Recommendation run ${run.id} is ${run.status}.`);
      await refreshWorkspace();
    } catch {
      setActionError("Unable to generate recommendations right now.");
    } finally {
      setRecommendationGenerationInFlight(false);
    }
  }, [context.businessId, context.token, refreshWorkspace, siteId]);

  const handleGenerateCompetitorProfiles = useCallback(async () => {
    if (!context.token || !context.businessId || !siteId) {
      return;
    }
    setCompetitorGenerationInFlight(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await createCompetitorProfileGenerationRun(context.token, context.businessId, siteId, {});
      setActionMessage(`Competitor run ${result.run.id} is ${result.run.status}.`);
      await refreshWorkspace();
    } catch {
      setActionError("Unable to generate competitor profiles right now.");
    } finally {
      setCompetitorGenerationInFlight(false);
    }
  }, [context.businessId, context.token, refreshWorkspace, siteId]);

  if (context.loading) {
    return (
      <OperatorRouteSupportState
        title="Site SEO Workspace"
        subtitle="Loading site workspace..."
        backHref="/sites"
        backLabel="Back to Sites"
      />
    );
  }
  if (!context.token || !context.businessId) {
    return (
      <OperatorRouteSupportState
        title="Site SEO Workspace"
        subtitle="Sign in required."
        backHref="/sites"
        backLabel="Back to Sites"
      />
    );
  }
  if (!siteId) {
    return (
      <OperatorRouteSupportState
        title="Site SEO Workspace"
        subtitle="Site identifier is missing."
        backHref="/sites"
        backLabel="Back to Sites"
      />
    );
  }
  if (!selectedSite) {
    return (
      <OperatorRouteSupportState
        title="Site SEO Workspace"
        subtitle="This site was not found or is not accessible in your tenant scope."
        backHref="/sites"
        backLabel="Back to Sites"
      />
    );
  }

  const recommendationQueueSummary = normalizeQueueSummary(recommendations);
  const latestAuditRun = auditRuns[0] || null;
  const latestCompletedAuditRun = auditRuns.find((run) => normalizeLowerCaseString(run.status) === "completed") || null;
  const latestRecommendationRun = recommendationRuns[0] || null;
  const latestCompetitorRun = competitorRuns[0] || null;
  const actionableRecommendationCount = recommendations
    ? recommendations.items.filter((item) => !["accepted", "dismissed", "resolved"].includes(item.status)).length
    : 0;

  const recommendationFreshnessLabel = deriveFreshnessLabel(
    recommendationWorkspaceSummary?.recommendation_section_freshness,
    latestRecommendationRun ? normalizeWorkspaceStatusLabel(latestRecommendationRun.status) : "No run state yet",
  );
  const competitorFreshnessLabel = deriveFreshnessLabel(
    recommendationWorkspaceSummary?.competitor_section_freshness,
    latestCompetitorRun ? normalizeWorkspaceStatusLabel(latestCompetitorRun.status) : "No run state yet",
  );

  const reviewableDraftCount = competitorDrafts.length;
  const pendingDraftCount = competitorDrafts.filter((draft) => draft.review_status === "pending").length;
  const acceptedDraftCount = competitorDrafts.filter((draft) => draft.review_status === "accepted").length;
  const rejectedDraftCount = competitorDrafts.filter((draft) => draft.review_status === "rejected").length;
  const syntheticScaffoldWarningCount = competitorDrafts.filter(
    (draft) => draft.source_type === "synthetic" || draft.provenance_classification === "synthetic_fallback",
  ).length;

  const workspaceReadinessMessage = recommendationQueueSummary.open > 0
    ? "Recommendations are available for operator review."
    : latestCompletedAuditRun && latestRecommendationRun
      ? "Audit and recommendation context is available."
      : !latestCompletedAuditRun
        ? "Run an audit to establish baseline context."
        : "Generate recommendations to build next-step action context.";

  const googleStatus = deriveGoogleWorkspaceStatus(
    googleBusinessProfileConnection,
    googleBusinessProfileConnectionError,
  );

  const recommendationGenerationPrerequisitesMet = Boolean(latestCompletedAuditRun);

  const operatorPrimaryAction: OperatorPrimaryAction = !googleStatus.connected || googleStatus.reconnectRequired
    ? {
      urgencyLabel: "Action needed",
      urgencyBadgeClass: "badge badge-critical",
      title: "Connect Google Profile",
      reason: "Google connection is required for profile and integration signals.",
      contextHint: googleStatus.detail,
      actionLabel: "Open Google Profile",
      actionKind: "navigate",
      actionHref: "/google-profile",
    }
    : recommendationQueueSummary.open > 0
      ? {
        urgencyLabel: "Ready now",
        urgencyBadgeClass: "badge badge-warn",
        title: "Review open recommendations",
        reason: `${recommendationQueueSummary.open} recommendation(s) are open and ready for review.`,
        contextHint: recommendationFreshnessLabel,
        actionLabel: "Open Recommendation Queue",
        actionKind: "navigate",
        actionHref: "/recommendations",
      }
      : !latestRecommendationRun
        ? {
          urgencyLabel: "Action needed",
          urgencyBadgeClass: "badge badge-warn",
          title: "Generate recommendations",
          reason: "No recommendation run is available yet for this site.",
          contextHint: recommendationGenerationPrerequisitesMet
            ? "Audit baseline is available."
            : "Run an audit first to improve recommendation relevance.",
          actionLabel: "Generate Recommendations",
          actionKind: "callback",
          actionHref: null,
        }
        : !latestCompetitorRun
          ? {
            urgencyLabel: "Action needed",
            urgencyBadgeClass: "badge badge-warn",
            title: "Generate competitor profiles",
            reason: "No competitor profile run is available for comparison context.",
            contextHint: "Generate competitor profiles in the dedicated workspace.",
            actionLabel: "Generate Competitor Profiles",
            actionKind: "callback",
            actionHref: null,
          }
          : {
            urgencyLabel: "On track",
            urgencyBadgeClass: "badge badge-success",
            title: "Use dedicated workflows",
            reason: "Core context is available. Continue from dedicated workflow pages.",
            contextHint: "Site workspace is a command-center launchpad.",
            actionLabel: "Open Recommendation Queue",
            actionKind: "navigate",
            actionHref: "/recommendations",
          };

  const ga4ConnectivityStatus = siteAnalyticsSummary?.ga4_status
    || ((selectedSite?.ga4_property_id || "").trim() ? "configured" : "not_configured");
  const ga4ConnectivityReason = siteAnalyticsSummary?.ga4_error_reason
    || (ga4ConnectivityStatus === "not_configured" ? "not_configured" : null);
  const ga4Health = siteAnalyticsSummary?.ga4_health || null;
  const ga4HealthStatus = ga4Health?.ga4_health_status || inferGa4HealthStatus(ga4ConnectivityStatus, ga4ConnectivityReason);
  const ga4HealthStatusLabel = formatGa4HealthStatusLabel(ga4HealthStatus);
  const ga4HealthMessage = ga4Health?.ga4_health_message
    || ga4DiagnosticReasonMessage(ga4ConnectivityReason)
    || "GA4 health is unavailable for this site.";
  const ga4HealthNextAction = ga4HealthNextActionMessage(ga4HealthStatus);

  const ga4Insights = siteAnalyticsSummary?.ga4_insights && typeof siteAnalyticsSummary.ga4_insights === "object"
    ? siteAnalyticsSummary.ga4_insights
    : null;
  const ga4InsightsStatus = (() => {
    const normalizedStatus = normalizeGa4InsightsStatusValue(ga4Insights?.status);
    if (normalizedStatus) {
      return normalizedStatus;
    }
    if (ga4HealthStatus === "reachable" || ga4HealthStatus === "configured") {
      return "available";
    }
    if (ga4HealthStatus === "permission_denied") {
      return "permission_denied";
    }
    if (ga4HealthStatus === "missing_oauth_scope") {
      return "missing_oauth_scope";
    }
    if (ga4HealthStatus === "invalid_property") {
      return "invalid_property";
    }
    if (ga4HealthStatus === "no_data") {
      return "no_data";
    }
    if (ga4HealthStatus === "not_configured") {
      return "not_configured";
    }
    if (ga4HealthStatus === "unavailable") {
      return "unavailable";
    }
    return "unknown";
  })();
  const ga4InsightsStatusLabel = formatGa4InsightsStatusLabel(ga4InsightsStatus);
  const ga4InsightsDateRangeLabel = normalizeOptionalString(ga4Insights?.date_range_label)
    || "Last 7 days vs previous 7 days";
  const ga4InsightsBaseMessage = normalizeOptionalString(ga4Insights?.message)
    || ga4HealthMessage
    || "GA4 insights are unavailable for this site.";
  const ga4InsightsUnavailableDetail = `${ga4InsightsBaseMessage} ${ga4InsightsDateRangeLabel}`.trim();

  const ga4TopLandingPages = Array.isArray(ga4Insights?.top_landing_pages)
    ? ga4Insights.top_landing_pages
      .filter((page) => Boolean(page) && typeof page === "object")
      .map((page) => ({
        path: normalizeOptionalString(page?.path) || "/",
        sessions: normalizeNumericValue(page?.sessions),
        trend_label: normalizeGa4TrendLabel(page?.trend_label),
        operator_hint: normalizeOptionalString(page?.operator_hint),
      }))
      .slice(0, 5)
    : [];
  const ga4TopLandingValue = ga4InsightsStatus === "available"
    ? `${ga4TopLandingPages.length} page${ga4TopLandingPages.length === 1 ? "" : "s"}`
    : ga4InsightsStatusLabel;
  const ga4TopLandingDetail = ga4InsightsStatus === "available"
    ? `${formatGa4TopLandingPagesCompactList(ga4TopLandingPages)}${ga4TopLandingPages[0]?.operator_hint ? ` · ${ga4TopLandingPages[0].operator_hint}` : ""}`
    : ga4InsightsUnavailableDetail;
  const ga4TopLandingTone = ga4InsightsStatus === "available"
    ? ga4InsightsToneForTrend(ga4TopLandingPages[0]?.trend_label)
    : ga4InsightsToneForStatus(ga4InsightsStatus);

  const ga4TrafficTrend = ga4Insights?.traffic_trend && typeof ga4Insights.traffic_trend === "object"
    ? {
      current_sessions: normalizeNumericValue(ga4Insights.traffic_trend.current_sessions),
      previous_sessions: normalizeNumericValue(ga4Insights.traffic_trend.previous_sessions),
      sessions_delta_percent: normalizeNumericValue(ga4Insights.traffic_trend.sessions_delta_percent),
      current_active_users: normalizeNumericValue(ga4Insights.traffic_trend.current_active_users),
      previous_active_users: normalizeNumericValue(ga4Insights.traffic_trend.previous_active_users),
      active_users_delta_percent: normalizeNumericValue(ga4Insights.traffic_trend.active_users_delta_percent),
      trend_label: normalizeGa4TrendLabel(ga4Insights.traffic_trend.trend_label),
      operator_hint: normalizeOptionalString(ga4Insights.traffic_trend.operator_hint),
    }
    : null;
  const ga4TrafficTrendValue = ga4InsightsStatus === "available" && ga4TrafficTrend
    ? `${formatSignedPercent(ga4TrafficTrend.sessions_delta_percent)} sessions`
    : ga4InsightsStatusLabel;
  const ga4TrafficTrendDetail = ga4InsightsStatus === "available" && ga4TrafficTrend
    ? `${Math.max(0, Number(ga4TrafficTrend.current_sessions) || 0).toLocaleString()} sessions vs ${Math.max(0, Number(ga4TrafficTrend.previous_sessions) || 0).toLocaleString()} · ${Math.max(0, Number(ga4TrafficTrend.current_active_users) || 0).toLocaleString()} active users (${formatSignedPercent(ga4TrafficTrend.active_users_delta_percent)} vs prior period). ${ga4TrafficTrend.operator_hint || ga4InsightsDateRangeLabel}`
    : ga4InsightsUnavailableDetail;
  const ga4TrafficTrendTone = ga4InsightsStatus === "available"
    ? ga4InsightsToneForTrend(ga4TrafficTrend?.trend_label)
    : ga4InsightsToneForStatus(ga4InsightsStatus);

  const ga4EngagementTrend = ga4Insights?.engagement_trend && typeof ga4Insights.engagement_trend === "object"
    ? {
      current_engagement_rate: normalizeNumericValue(ga4Insights.engagement_trend.current_engagement_rate),
      previous_engagement_rate: normalizeNumericValue(ga4Insights.engagement_trend.previous_engagement_rate),
      engagement_rate_delta_percent: normalizeNumericValue(ga4Insights.engagement_trend.engagement_rate_delta_percent),
      current_average_engagement_time_seconds: normalizeNumericValue(ga4Insights.engagement_trend.current_average_engagement_time_seconds),
      previous_average_engagement_time_seconds: normalizeNumericValue(ga4Insights.engagement_trend.previous_average_engagement_time_seconds),
      trend_label: normalizeGa4TrendLabel(ga4Insights.engagement_trend.trend_label),
      operator_hint: normalizeOptionalString(ga4Insights.engagement_trend.operator_hint),
    }
    : null;
  const ga4EngagementTrendValue = ga4InsightsStatus === "available" && ga4EngagementTrend
    ? `${formatSignedPercent(ga4EngagementTrend.engagement_rate_delta_percent)} engagement`
    : ga4InsightsStatusLabel;
  const ga4EngagementTrendDetail = ga4InsightsStatus === "available" && ga4EngagementTrend
    ? `Engagement ${formatGa4PercentValue(ga4EngagementTrend.current_engagement_rate)} vs ${formatGa4PercentValue(ga4EngagementTrend.previous_engagement_rate)} · Avg time ${formatGa4DurationSeconds(ga4EngagementTrend.current_average_engagement_time_seconds)} vs ${formatGa4DurationSeconds(ga4EngagementTrend.previous_average_engagement_time_seconds)}. ${ga4EngagementTrend.operator_hint || ga4InsightsDateRangeLabel}`
    : ga4InsightsUnavailableDetail;
  const ga4EngagementTrendTone = ga4InsightsStatus === "available"
    ? ga4InsightsToneForTrend(ga4EngagementTrend?.trend_label)
    : ga4InsightsToneForStatus(ga4InsightsStatus);

  const ga4OnboardingStatusCode = ga4OnboardingStatus?.ga4_onboarding_status || "unavailable";
  const ga4OnboardingValue = ga4OnboardingStatusCode === "stream_configured" || ga4OnboardingStatusCode === "property_configured"
    ? "Property configured"
    : ga4OnboardingStatusCode === "account_available" || ga4OnboardingStatusCode === "incomplete"
      ? "Property needed"
      : ga4OnboardingStatusCode === "not_connected"
        ? "Not connected"
        : "Unavailable";
  const ga4OnboardingDiscoveryDetail = ga4OnboardingStatus
    ? (
      ga4OnboardingStatus.account_discovery_available
        ? (ga4OnboardingStatus.message || "GA4 onboarding status available.")
        : "Account discovery is not enabled. Enter your GA4 property ID directly."
    )
    : ga4OnboardingError || "Account discovery is not enabled. Enter your GA4 property ID directly.";
  const ga4OnboardingDetail = `${ga4HealthStatusLabel}: ${ga4HealthMessage}${ga4HealthNextAction ? ` ${ga4HealthNextAction}` : ""} ${ga4OnboardingDiscoveryDetail}`.trim();
  const ga4OnboardingTone: Tone = ga4OnboardingStatusCode === "stream_configured" || ga4OnboardingStatusCode === "property_configured"
    ? "success"
    : ga4OnboardingStatusCode === "account_available" || ga4OnboardingStatusCode === "incomplete"
      ? "warning"
      : ga4OnboardingStatusCode === "unavailable"
        ? "danger"
        : "neutral";

  const searchSummary = searchConsoleSiteSummary?.site_metrics_summary || null;
  const searchVisibilityTrendValue = searchSummary
    ? `${searchSummary.clicks.current.toLocaleString()} clicks`
    : "Unavailable";
  const searchVisibilityTrendDetail = searchSummary
    ? `${searchSummary.impressions.current.toLocaleString()} impressions (${formatSignedPercent(searchSummary.impressions.delta_percent)} vs prior period), avg position ${searchSummary.average_position_current.toFixed(1)}`
    : searchConsoleSiteSummary?.message || searchConsoleSiteSummaryError || "Search Console is not connected for this site yet.";
  const searchVisibilityTrendTone: Tone = searchSummary
    ? "success"
    : searchConsoleSiteSummary?.status === "unavailable"
      ? "danger"
      : "warning";

  const setupChecklistItems: ChecklistItem[] = [
    checklistItem(
      "google_profile",
      "Google Profile connected",
      googleStatus.detail,
      googleStatus.connected && !googleStatus.reconnectRequired ? "done" : "blocked",
      "Open Google Profile",
      "/google-profile",
    ),
    checklistItem(
      "audit_baseline",
      "Audit baseline available",
      latestCompletedAuditRun
        ? `Completed ${formatDateTime(latestCompletedAuditRun.completed_at)}.`
        : "Run your first audit to establish a reliable baseline.",
      latestCompletedAuditRun ? "done" : "pending",
      "Open Audit Runs",
      "/audits",
    ),
    checklistItem(
      "recommendations",
      "Recommendations generated",
      latestRecommendationRun
        ? `Latest run ${latestRecommendationRun.id} is ${normalizeWorkspaceStatusLabel(latestRecommendationRun.status)}.`
        : "Generate recommendations to build a prioritized queue.",
      latestRecommendationRun ? "done" : "pending",
      "Open Recommendation Queue",
      "/recommendations",
    ),
    checklistItem(
      "competitors",
      "Competitor profiles available",
      latestCompetitorRun
        ? `${reviewableDraftCount} reviewable draft(s) in latest run.`
        : "Generate competitor profiles to strengthen supporting context.",
      latestCompetitorRun ? "done" : "pending",
      "Open Competitor Workspace",
      `/competitors?site_id=${encodeURIComponent(selectedSite.id)}`,
    ),
    checklistItem(
      "migration",
      "Migration workflow ready",
      "Migration draft, review, publish, and deploy are managed on the dedicated migration route.",
      "done",
      "Open Migration Workflow",
      `/sites/${encodeURIComponent(selectedSite.id)}/migration`,
    ),
  ];

  const onPrimaryAction = () => {
    if (operatorPrimaryAction.actionKind !== "callback") {
      return;
    }
    if (operatorPrimaryAction.actionLabel === "Generate Competitor Profiles") {
      void handleGenerateCompetitorProfiles();
      return;
    }
    void handleGenerateRecommendations();
  };

  return (
    <PageContainer width="full" density="compact">
      <SiteWorkspaceHero
        selectedSite={selectedSite}
        recommendationFreshnessLabel={recommendationFreshnessLabel}
        recommendationQueueOpen={recommendationQueueSummary.open}
        competitorFreshnessLabel={competitorFreshnessLabel}
        workspaceReadinessMessage={workspaceReadinessMessage}
        operatorPrimaryAction={operatorPrimaryAction}
        loadingWorkspace={loadingWorkspace}
        onPrimaryAction={onPrimaryAction}
      />

      {workspaceError ? <p className="hint warning">{workspaceError}</p> : null}
      {actionMessage ? <p className="hint success">{actionMessage}</p> : null}
      {actionError ? <p className="hint warning">{actionError}</p> : null}

      <OperatorPageSectionStack className="site-workspace-top-stack">
        <WorkspaceSnapshot
          competitorFreshnessLabel={competitorFreshnessLabel}
          workspaceReadinessMessage={workspaceReadinessMessage}
          recommendationFreshnessLabel={recommendationFreshnessLabel}
          recommendationQueueSummary={recommendationQueueSummary}
          actionableRecommendationCount={actionableRecommendationCount}
          ga4TopLandingValue={ga4TopLandingValue}
          ga4TopLandingDetail={ga4TopLandingDetail}
          ga4TopLandingTone={ga4TopLandingTone}
          ga4TrafficTrendValue={ga4TrafficTrendValue}
          ga4TrafficTrendDetail={ga4TrafficTrendDetail}
          ga4TrafficTrendTone={ga4TrafficTrendTone}
          ga4EngagementTrendValue={ga4EngagementTrendValue}
          ga4EngagementTrendDetail={ga4EngagementTrendDetail}
          ga4EngagementTrendTone={ga4EngagementTrendTone}
          ga4OnboardingValue={ga4OnboardingValue}
          ga4OnboardingDetail={ga4OnboardingDetail}
          ga4OnboardingTone={ga4OnboardingTone}
          searchVisibilityTrendValue={searchVisibilityTrendValue}
          searchVisibilityTrendDetail={searchVisibilityTrendDetail}
          searchVisibilityTrendTone={searchVisibilityTrendTone}
          googleStatus={googleStatus}
        />

        <WorkspaceSetupChecklist setupChecklistItems={setupChecklistItems} />
      </OperatorPageSectionStack>

      <WorkflowLaunchpad
        activeWorkspaceContentTab={activeWorkspaceContentTab}
        setActiveWorkspaceContentTab={setActiveWorkspaceContentTab}
        operatorPrimaryAction={operatorPrimaryAction}
        recommendationQueueSummary={recommendationQueueSummary}
        recommendationFreshnessLabel={recommendationFreshnessLabel}
        recommendationGenerationPrerequisitesMet={recommendationGenerationPrerequisitesMet}
        recommendationGenerationInFlight={recommendationGenerationInFlight}
        onGenerateRecommendations={() => void handleGenerateRecommendations()}
        reviewableDraftCount={reviewableDraftCount}
        competitorFreshnessLabel={competitorFreshnessLabel}
        pendingDraftCount={pendingDraftCount}
        acceptedDraftCount={acceptedDraftCount}
        rejectedDraftCount={rejectedDraftCount}
        syntheticScaffoldWarningCount={syntheticScaffoldWarningCount}
        competitorGenerationInFlight={competitorGenerationInFlight}
        onGenerateCompetitorProfiles={() => void handleGenerateCompetitorProfiles()}
        selectedSiteId={selectedSite.id}
        googleStatus={googleStatus}
        latestAuditRun={latestAuditRun}
        latestRecommendationRun={latestRecommendationRun}
        latestCompetitorRun={latestCompetitorRun}
        competitorSummary={competitorSummary}
      />
    </PageContainer>
  );
}
