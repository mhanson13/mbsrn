"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../../components/layout/PageContainer";
import { SectionCard } from "../../../components/layout/SectionCard";
import { useOperatorContext } from "../../../components/useOperatorContext";
import {
  acceptCompetitorProfileDraft,
  ApiRequestError,
  createCompetitorProfileGenerationRun,
  editCompetitorProfileDraft,
  fetchAuditRuns,
  fetchCompetitorProfileGenerationRunDetail,
  fetchCompetitorProfileGenerationRuns,
  fetchCompetitorProfileGenerationSummary,
  fetchCompetitorDomains,
  fetchCompetitorSets,
  fetchCompetitorSnapshotRuns,
  fetchLatestRecommendationRunNarrative,
  fetchRecommendationRuns,
  fetchRecommendations,
  fetchSiteCompetitorComparisonRuns,
  rejectCompetitorProfileDraft,
  retryCompetitorProfileGenerationRun,
} from "../../../lib/api/client";
import type {
  CompetitorComparisonRun,
  CompetitorProfileDraft,
  CompetitorProfileGenerationRun,
  CompetitorProfileGenerationSummaryResponse,
  CompetitorSet,
  CompetitorSnapshotRun,
  Recommendation,
  RecommendationListResponse,
  RecommendationNarrative,
  RecommendationRun,
  SEOAuditRun,
} from "../../../lib/api/types";

const MAX_AUDIT_ROWS = 8;
const MAX_COMPETITOR_ROWS = 8;
const MAX_RECOMMENDATION_ROWS = 8;
const MAX_RECOMMENDATION_RUN_ROWS = 8;
const NARRATIVE_LOOKUP_LIMIT = 5;
const MAX_TIMELINE_EVENTS = 20;
const TIMELINE_INITIAL_VISIBLE_COUNT = 10;
const COMPETITOR_PROFILE_DRAFT_CANDIDATE_COUNT = 5;
const COMPETITOR_PROFILE_POLL_INTERVAL_MS = 2000;
const COMPETITOR_PROFILE_POLL_MAX_ATTEMPTS = 30;

type SiteTimelineEventType =
  | "audit_run"
  | "snapshot_run"
  | "comparison_run"
  | "recommendation_run"
  | "narrative";

const TIMELINE_EVENT_TYPE_OPTIONS: Array<{ value: SiteTimelineEventType; label: string }> = [
  { value: "audit_run", label: "Audit Runs" },
  { value: "snapshot_run", label: "Snapshot Runs" },
  { value: "comparison_run", label: "Comparison Runs" },
  { value: "recommendation_run", label: "Recommendation Runs" },
  { value: "narrative", label: "Narratives" },
];

interface WorkspaceCompetitorSet extends CompetitorSet {
  domain_count: number;
  active_domain_count: number;
  latest_snapshot_run: CompetitorSnapshotRun | null;
}

interface SiteTimelineEvent {
  id: string;
  event_type: SiteTimelineEventType;
  type_label: "Audit Run" | "Snapshot Run" | "Comparison Run" | "Recommendation Run" | "Recommendation Narrative";
  status: string;
  timestamp: string;
  timestamp_label: "completed" | "started" | "updated" | "created";
  timestamp_ms: number;
  title: string;
  context: string;
  href: string;
}

interface SiteTimelineDayGroup {
  key: string;
  label: string;
  events: SiteTimelineEvent[];
}

interface DraftEditFormState {
  suggested_name: string;
  suggested_domain: string;
  competitor_type: string;
  summary: string;
  why_competitor: string;
  evidence: string;
  confidence_score: string;
}

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

function runActivityTimestamp(
  run: Pick<CompetitorSnapshotRun | CompetitorComparisonRun, "created_at" | "updated_at" | "completed_at">,
): number {
  const activityAt = run.completed_at || run.updated_at || run.created_at;
  const parsed = Date.parse(activityAt);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function latestByActivity<
  T extends Pick<CompetitorSnapshotRun | CompetitorComparisonRun, "created_at" | "updated_at" | "completed_at">,
>(runs: T[]): T | null {
  if (runs.length === 0) {
    return null;
  }
  return [...runs].sort((left, right) => runActivityTimestamp(right) - runActivityTimestamp(left))[0];
}

function timestampToMs(value: string): number {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function dayKeyFromTimestampMs(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "unknown";
  }
  const year = String(date.getFullYear());
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localDayStartMs(value: Date): number {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
}

function formatTimelineDayLabel(timestampMs: number, referenceNowMs: number): string {
  const eventDate = new Date(timestampMs);
  if (Number.isNaN(eventDate.getTime())) {
    return "Unknown date";
  }
  const eventDayStartMs = localDayStartMs(eventDate);
  const referenceDayStartMs = localDayStartMs(new Date(referenceNowMs));
  const dayDiff = Math.round((referenceDayStartMs - eventDayStartMs) / (24 * 60 * 60 * 1000));
  if (dayDiff === 0) {
    return "Today";
  }
  if (dayDiff === 1) {
    return "Yesterday";
  }
  return eventDate.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function deriveLifecycleTimestamp(
  item: Pick<
    SEOAuditRun | CompetitorSnapshotRun | CompetitorComparisonRun | RecommendationRun,
    "created_at" | "updated_at" | "started_at" | "completed_at"
  >,
): { value: string; label: "completed" | "started" | "updated" | "created" } {
  if (item.completed_at) {
    return { value: item.completed_at, label: "completed" };
  }
  if (item.started_at) {
    return { value: item.started_at, label: "started" };
  }
  if (item.updated_at) {
    return { value: item.updated_at, label: "updated" };
  }
  return { value: item.created_at, label: "created" };
}

function isNotFoundError(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 404;
}

function safeSectionErrorMessage(section: string, error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return `You are not authorized to view ${section} for this site.`;
    }
    if (error.status === 404) {
      return `${section} data was not found for this site in your tenant scope.`;
    }
  }
  return `Unable to load ${section} right now. Please try again.`;
}

function normalizeTimelineStatus(value: string | null | undefined): string {
  const normalized = (value || "").trim();
  return normalized || "-";
}

function truncateText(value: string | null | undefined, limit: number): string {
  const normalized = (value || "").trim();
  if (!normalized) {
    return "-";
  }
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit - 1)}…`;
}

function formatFailureCategory(value: string | null | undefined): string {
  const normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return "-";
  }
  return normalized.replace(/_/g, " ");
}

function safeActionErrorMessage(actionLabel: string, error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return `You are not authorized to ${actionLabel} for this site.`;
    }
    if (error.status === 404) {
      return `${actionLabel} target was not found in your tenant scope.`;
    }
    if (error.status === 422) {
      return error.message || `Unable to ${actionLabel} due to validation constraints.`;
    }
  }
  return `Unable to ${actionLabel} right now. Please try again.`;
}

function isCompetitorProfileRunTerminalStatus(status: CompetitorProfileGenerationRun["status"]): boolean {
  return status === "completed" || status === "failed";
}

function recommendationSourceType(item: Recommendation): string {
  if (item.audit_run_id && item.comparison_run_id) {
    return "mixed";
  }
  if (item.audit_run_id) {
    return "audit";
  }
  if (item.comparison_run_id) {
    return "comparison";
  }
  return "unknown";
}

function buildCompetitorSetHref(setId: string, siteId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  return `/competitors/${setId}?${params.toString()}`;
}

function buildComparisonRunHref(comparisonRunId: string, siteId: string, setId?: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  if (setId) {
    params.set("set_id", setId);
  }
  return `/competitors/comparison-runs/${comparisonRunId}?${params.toString()}`;
}

function buildSnapshotRunHref(snapshotRunId: string, siteId: string, setId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  params.set("set_id", setId);
  return `/competitors/snapshot-runs/${snapshotRunId}?${params.toString()}`;
}

function buildRecommendationDetailHref(recommendationId: string, siteId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  return `/recommendations/${recommendationId}?${params.toString()}`;
}

function buildRecommendationRunHref(recommendationRunId: string, siteId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  return `/recommendations/runs/${recommendationRunId}?${params.toString()}`;
}

function buildNarrativeHistoryHref(recommendationRunId: string, siteId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  return `/recommendations/runs/${recommendationRunId}/narratives?${params.toString()}`;
}

function buildNarrativeDetailHref(recommendationRunId: string, narrativeId: string, siteId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  return `/recommendations/runs/${recommendationRunId}/narratives/${narrativeId}?${params.toString()}`;
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
  const [notFound, setNotFound] = useState(false);

  const [auditRuns, setAuditRuns] = useState<SEOAuditRun[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);

  const [competitorSets, setCompetitorSets] = useState<WorkspaceCompetitorSet[]>([]);
  const [snapshotRuns, setSnapshotRuns] = useState<CompetitorSnapshotRun[]>([]);
  const [comparisonRuns, setComparisonRuns] = useState<CompetitorComparisonRun[]>([]);
  const [competitorError, setCompetitorError] = useState<string | null>(null);

  const [queueResponse, setQueueResponse] = useState<RecommendationListResponse | null>(null);
  const [queueError, setQueueError] = useState<string | null>(null);

  const [recommendationRuns, setRecommendationRuns] = useState<RecommendationRun[]>([]);
  const [recommendationRunError, setRecommendationRunError] = useState<string | null>(null);
  const [latestNarrativesByRunId, setLatestNarrativesByRunId] = useState<Record<string, RecommendationNarrative>>({});
  const [narrativeLookupError, setNarrativeLookupError] = useState<string | null>(null);

  const [competitorProfileGenerationRuns, setCompetitorProfileGenerationRuns] = useState<CompetitorProfileGenerationRun[]>([]);
  const [competitorProfileSummary, setCompetitorProfileSummary] =
    useState<CompetitorProfileGenerationSummaryResponse | null>(null);
  const [latestCompetitorProfileRunId, setLatestCompetitorProfileRunId] = useState<string | null>(null);
  const [competitorProfileDrafts, setCompetitorProfileDrafts] = useState<CompetitorProfileDraft[]>([]);
  const [competitorProfileLoading, setCompetitorProfileLoading] = useState(false);
  const [competitorProfileError, setCompetitorProfileError] = useState<string | null>(null);
  const [competitorProfileSummaryError, setCompetitorProfileSummaryError] = useState<string | null>(null);
  const [competitorProfileActionError, setCompetitorProfileActionError] = useState<string | null>(null);
  const [competitorProfileActionMessage, setCompetitorProfileActionMessage] = useState<string | null>(null);
  const [generationInFlight, setGenerationInFlight] = useState(false);
  const [retryInFlight, setRetryInFlight] = useState(false);
  const [competitorProfilePolling, setCompetitorProfilePolling] = useState(false);
  const [draftActionTargetId, setDraftActionTargetId] = useState<string | null>(null);
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null);
  const [editFormState, setEditFormState] = useState<DraftEditFormState | null>(null);
  const [editActionInFlight, setEditActionInFlight] = useState(false);
  const [acceptTargetSetByDraftId, setAcceptTargetSetByDraftId] = useState<Record<string, string>>({});

  const [activeEventTypes, setActiveEventTypes] = useState<Set<SiteTimelineEventType>>(
    () => new Set(TIMELINE_EVENT_TYPE_OPTIONS.map((option) => option.value)),
  );
  const [activeStatuses, setActiveStatuses] = useState<Set<string>>(() => new Set());
  const [expandedTimeline, setExpandedTimeline] = useState(false);

  const latestCompetitorProfileRun = useMemo(
    () => competitorProfileGenerationRuns[0] || null,
    [competitorProfileGenerationRuns],
  );
  const latestCompetitorProfileRunStatus = latestCompetitorProfileRun?.status || null;

  function toEditFormState(draft: CompetitorProfileDraft): DraftEditFormState {
    return {
      suggested_name: draft.suggested_name,
      suggested_domain: draft.suggested_domain,
      competitor_type: draft.competitor_type,
      summary: draft.summary || "",
      why_competitor: draft.why_competitor || "",
      evidence: draft.evidence || "",
      confidence_score: String(draft.confidence_score),
    };
  }

  function buildDraftEditPayloadFromFormState(formState: DraftEditFormState) {
    const parsedConfidence = Number.parseFloat(formState.confidence_score);
    return {
      suggested_name: formState.suggested_name,
      suggested_domain: formState.suggested_domain,
      competitor_type: formState.competitor_type as
        | "direct"
        | "indirect"
        | "local"
        | "marketplace"
        | "informational"
        | "unknown",
      summary: formState.summary || null,
      why_competitor: formState.why_competitor || null,
      evidence: formState.evidence || null,
      confidence_score: Number.isFinite(parsedConfidence) ? parsedConfidence : 0.5,
    };
  }

  const activeCompetitorSetCount = useMemo(
    () => competitorSets.filter((item) => item.is_active).length,
    [competitorSets],
  );
  const competitorDomainCount = useMemo(
    () => competitorSets.reduce((total, item) => total + item.domain_count, 0),
    [competitorSets],
  );
  const activeCompetitorDomainCount = useMemo(
    () => competitorSets.reduce((total, item) => total + item.active_domain_count, 0),
    [competitorSets],
  );
  const latestSnapshotRun = useMemo(() => latestByActivity(snapshotRuns), [snapshotRuns]);
  const latestComparisonRun = useMemo(() => latestByActivity(comparisonRuns), [comparisonRuns]);

  const recommendationQueueSummary = useMemo(() => {
    const response = queueResponse;
    if (!response) {
      return {
        total: 0,
        open: 0,
        accepted: 0,
        dismissed: 0,
        highPriority: 0,
      };
    }
    if (response.filtered_summary) {
      return {
        total: response.filtered_summary.total,
        open: response.filtered_summary.open,
        accepted: response.filtered_summary.accepted,
        dismissed: response.filtered_summary.dismissed,
        highPriority: response.filtered_summary.high_priority,
      };
    }
    const byStatus = response.by_status || {};
    const byPriorityBand = response.by_priority_band || {};
    return {
      total: response.total,
      open: Number(byStatus.open || 0),
      accepted: Number(byStatus.accepted || 0),
      dismissed: Number(byStatus.dismissed || 0),
      highPriority: Number(byPriorityBand.high || 0) + Number(byPriorityBand.critical || 0),
    };
  }, [queueResponse]);

  const workspaceReadinessMessage = useMemo(() => {
    if (!selectedSite) {
      return "This site is not available in your tenant scope.";
    }
    if (!selectedSite.is_active) {
      return "This site is currently inactive.";
    }
    if (competitorSets.length === 0) {
      return "No competitor sets are configured for this site yet.";
    }
    if (competitorDomainCount === 0) {
      return "Competitor sets exist, but no competitor domains are configured yet.";
    }
    if (!latestSnapshotRun) {
      return "Competitor domains exist, but no snapshot run has completed yet.";
    }
    if (!latestComparisonRun) {
      return "Snapshot activity exists, but no comparison run is available yet.";
    }
    return "This site has competitor and recommendation activity ready for investigation.";
  }, [competitorDomainCount, competitorSets.length, latestComparisonRun, latestSnapshotRun, selectedSite]);

  const competitorSetNameById = useMemo(
    () => Object.fromEntries(competitorSets.map((item) => [item.id, item.name] as const)),
    [competitorSets],
  );

  const timelineEvents = useMemo<SiteTimelineEvent[]>(() => {
    if (!selectedSite) {
      return [];
    }
    const events: SiteTimelineEvent[] = [];

    for (const run of auditRuns) {
      const eventTimestamp = deriveLifecycleTimestamp(run);
      events.push({
        id: `audit-${run.id}`,
        event_type: "audit_run",
        type_label: "Audit Run",
        status: normalizeTimelineStatus(run.status),
        timestamp: eventTimestamp.value,
        timestamp_label: eventTimestamp.label,
        timestamp_ms: timestampToMs(eventTimestamp.value),
        title: `Audit ${run.id}`,
        context: `${run.pages_crawled} page(s) crawled; ${run.errors_encountered} error(s)`,
        href: `/audits/${run.id}`,
      });
    }

    for (const run of snapshotRuns) {
      const eventTimestamp = deriveLifecycleTimestamp(run);
      const setName = competitorSetNameById[run.competitor_set_id] || run.competitor_set_id;
      events.push({
        id: `snapshot-${run.id}`,
        event_type: "snapshot_run",
        type_label: "Snapshot Run",
        status: normalizeTimelineStatus(run.status),
        timestamp: eventTimestamp.value,
        timestamp_label: eventTimestamp.label,
        timestamp_ms: timestampToMs(eventTimestamp.value),
        title: `Snapshot ${run.id}`,
        context: `Set ${setName}; ${run.pages_captured} page(s) captured`,
        href: buildSnapshotRunHref(run.id, selectedSite.id, run.competitor_set_id),
      });
    }

    for (const run of comparisonRuns) {
      const eventTimestamp = deriveLifecycleTimestamp(run);
      const setName = competitorSetNameById[run.competitor_set_id] || run.competitor_set_id;
      events.push({
        id: `comparison-${run.id}`,
        event_type: "comparison_run",
        type_label: "Comparison Run",
        status: normalizeTimelineStatus(run.status),
        timestamp: eventTimestamp.value,
        timestamp_label: eventTimestamp.label,
        timestamp_ms: timestampToMs(eventTimestamp.value),
        title: `Comparison ${run.id}`,
        context: `Set ${setName}; ${run.total_findings} finding(s)`,
        href: buildComparisonRunHref(run.id, selectedSite.id, run.competitor_set_id),
      });
    }

    for (const run of recommendationRuns) {
      const eventTimestamp = deriveLifecycleTimestamp(run);
      events.push({
        id: `recommendation-run-${run.id}`,
        event_type: "recommendation_run",
        type_label: "Recommendation Run",
        status: normalizeTimelineStatus(run.status),
        timestamp: eventTimestamp.value,
        timestamp_label: eventTimestamp.label,
        timestamp_ms: timestampToMs(eventTimestamp.value),
        title: `Recommendation Run ${run.id}`,
        context: `${run.total_recommendations} recommendation(s)`,
        href: buildRecommendationRunHref(run.id, selectedSite.id),
      });
    }

    for (const narrative of Object.values(latestNarrativesByRunId)) {
      const timestamp = narrative.created_at || narrative.updated_at;
      events.push({
        id: `narrative-${narrative.id}`,
        event_type: "narrative",
        type_label: "Recommendation Narrative",
        status: normalizeTimelineStatus(narrative.status),
        timestamp,
        timestamp_label: "created",
        timestamp_ms: timestampToMs(timestamp),
        title: `Narrative v${narrative.version} (${narrative.recommendation_run_id})`,
        context: `${narrative.provider_name}/${narrative.model_name}`,
        href: buildNarrativeDetailHref(
          narrative.recommendation_run_id,
          narrative.id,
          selectedSite.id,
        ),
      });
    }

    return events
      .sort((left, right) => {
        if (right.timestamp_ms !== left.timestamp_ms) {
          return right.timestamp_ms - left.timestamp_ms;
        }
        return right.id.localeCompare(left.id);
      })
      .slice(0, MAX_TIMELINE_EVENTS);
  }, [
    auditRuns,
    comparisonRuns,
    competitorSetNameById,
    latestNarrativesByRunId,
    recommendationRuns,
    selectedSite,
    snapshotRuns,
  ]);

  const availableTimelineStatuses = useMemo(() => {
    return [...new Set(timelineEvents.map((item) => item.status))]
      .sort((left, right) => left.localeCompare(right));
  }, [timelineEvents]);

  const availableTimelineStatusesKey = useMemo(
    () => availableTimelineStatuses.join("||"),
    [availableTimelineStatuses],
  );

  useEffect(() => {
    setActiveStatuses((current) => {
      if (availableTimelineStatuses.length === 0) {
        return new Set();
      }
      if (current.size === 0) {
        return new Set(availableTimelineStatuses);
      }
      const next = new Set(
        [...current].filter((status) => availableTimelineStatuses.includes(status)),
      );
      if (next.size === 0) {
        return new Set(availableTimelineStatuses);
      }
      return next;
    });
  }, [availableTimelineStatuses, availableTimelineStatusesKey]);

  const filteredTimelineEvents = useMemo(() => {
    return timelineEvents
      .filter((item) => activeEventTypes.has(item.event_type))
      .filter((item) => activeStatuses.has(item.status));
  }, [activeEventTypes, activeStatuses, timelineEvents]);

  const visibleTimelineEvents = useMemo(() => {
    if (expandedTimeline) {
      return filteredTimelineEvents;
    }
    return filteredTimelineEvents.slice(0, TIMELINE_INITIAL_VISIBLE_COUNT);
  }, [expandedTimeline, filteredTimelineEvents]);

  const groupedVisibleTimelineEvents = useMemo<SiteTimelineDayGroup[]>(() => {
    if (visibleTimelineEvents.length === 0) {
      return [];
    }
    const nowMs = Date.now();
    const grouped: SiteTimelineDayGroup[] = [];
    for (const event of visibleTimelineEvents) {
      const dayKey = dayKeyFromTimestampMs(event.timestamp_ms);
      const lastGroup = grouped[grouped.length - 1];
      if (!lastGroup || lastGroup.key !== dayKey) {
        grouped.push({
          key: dayKey,
          label: formatTimelineDayLabel(event.timestamp_ms, nowMs),
          events: [event],
        });
      } else {
        lastGroup.events.push(event);
      }
    }
    return grouped;
  }, [visibleTimelineEvents]);

  const shouldShowTimelineExpansionToggle = filteredTimelineEvents.length > TIMELINE_INITIAL_VISIBLE_COUNT;

  function handleEventTypeToggle(eventType: SiteTimelineEventType): void {
    setActiveEventTypes((current) => {
      const next = new Set(current);
      if (next.has(eventType)) {
        next.delete(eventType);
      } else {
        next.add(eventType);
      }
      return next;
    });
  }

  function handleStatusToggle(statusValue: string): void {
    setActiveStatuses((current) => {
      const next = new Set(current);
      if (next.has(statusValue)) {
        next.delete(statusValue);
      } else {
        next.add(statusValue);
      }
      return next;
    });
  }

  function upsertDraft(nextDraft: CompetitorProfileDraft): void {
    setCompetitorProfileDrafts((current) =>
      current.map((item) => (item.id === nextDraft.id ? nextDraft : item)),
    );
  }

  async function handleGenerateCompetitorProfiles(): Promise<void> {
    if (!context.token || !context.businessId || !siteId) {
      return;
    }
    setGenerationInFlight(true);
    setCompetitorProfileActionError(null);
    setCompetitorProfileActionMessage(null);
    try {
      const detail = await createCompetitorProfileGenerationRun(
        context.token,
        context.businessId,
        siteId,
        { candidate_count: COMPETITOR_PROFILE_DRAFT_CANDIDATE_COUNT },
      );
      setCompetitorProfileGenerationRuns((current) => {
        const next = [detail.run, ...current.filter((item) => item.id !== detail.run.id)];
        return next.sort((left, right) => right.created_at.localeCompare(left.created_at));
      });
      setLatestCompetitorProfileRunId(detail.run.id);
      setCompetitorProfileDrafts(detail.drafts);
      setCompetitorProfileActionMessage(
        "Competitor profile generation queued. Drafts will appear after the run completes.",
      );
      setEditingDraftId(null);
      setEditFormState(null);
    } catch (error) {
      setCompetitorProfileActionError(safeActionErrorMessage("generate competitor profile drafts", error));
    } finally {
      setGenerationInFlight(false);
    }
  }

  async function handleRetryCompetitorProfileRun(): Promise<void> {
    if (
      !context.token ||
      !context.businessId ||
      !siteId ||
      !latestCompetitorProfileRun ||
      latestCompetitorProfileRun.status !== "failed"
    ) {
      return;
    }
    setRetryInFlight(true);
    setCompetitorProfileActionError(null);
    setCompetitorProfileActionMessage(null);
    try {
      const detail = await retryCompetitorProfileGenerationRun(
        context.token,
        context.businessId,
        siteId,
        latestCompetitorProfileRun.id,
      );
      setCompetitorProfileGenerationRuns((current) => {
        const next = [detail.run, ...current.filter((item) => item.id !== detail.run.id)];
        return next.sort((left, right) => right.created_at.localeCompare(left.created_at));
      });
      setLatestCompetitorProfileRunId(detail.run.id);
      setCompetitorProfileDrafts(detail.drafts);
      setCompetitorProfileActionMessage(
        "Retry queued. Drafts will appear after the run completes.",
      );
      setEditingDraftId(null);
      setEditFormState(null);
    } catch (error) {
      setCompetitorProfileActionError(
        safeActionErrorMessage("retry competitor profile generation", error),
      );
    } finally {
      setRetryInFlight(false);
    }
  }

  async function handleRejectCompetitorProfileDraft(draftId: string): Promise<void> {
    if (!context.token || !context.businessId || !siteId || !latestCompetitorProfileRunId) {
      return;
    }
    setDraftActionTargetId(draftId);
    setCompetitorProfileActionError(null);
    setCompetitorProfileActionMessage(null);
    try {
      const updated = await rejectCompetitorProfileDraft(
        context.token,
        context.businessId,
        siteId,
        latestCompetitorProfileRunId,
        draftId,
      );
      upsertDraft(updated);
      setCompetitorProfileActionMessage("Draft rejected. No competitor record was created.");
      if (editingDraftId === draftId) {
        setEditingDraftId(null);
        setEditFormState(null);
      }
    } catch (error) {
      setCompetitorProfileActionError(safeActionErrorMessage("reject this draft", error));
    } finally {
      setDraftActionTargetId(null);
    }
  }

  async function handleAcceptCompetitorProfileDraft(
    draftId: string,
    overrides?: ReturnType<typeof buildDraftEditPayloadFromFormState>,
  ): Promise<void> {
    if (!context.token || !context.businessId || !siteId || !latestCompetitorProfileRunId) {
      return;
    }
    setDraftActionTargetId(draftId);
    setCompetitorProfileActionError(null);
    setCompetitorProfileActionMessage(null);
    try {
      const selectedSetId = (acceptTargetSetByDraftId[draftId] || "").trim();
      const updated = await acceptCompetitorProfileDraft(
        context.token,
        context.businessId,
        siteId,
        latestCompetitorProfileRunId,
        draftId,
        {
          ...(overrides || {}),
          ...(selectedSetId ? { competitor_set_id: selectedSetId } : {}),
        },
      );
      upsertDraft(updated);
      setCompetitorProfileActionMessage("Draft accepted and added to competitors.");
      if (editingDraftId === draftId) {
        setEditingDraftId(null);
        setEditFormState(null);
      }
    } catch (error) {
      setCompetitorProfileActionError(safeActionErrorMessage("accept this draft", error));
    } finally {
      setDraftActionTargetId(null);
    }
  }

  function handleStartDraftEdit(draft: CompetitorProfileDraft): void {
    setEditingDraftId(draft.id);
    setEditFormState(toEditFormState(draft));
    setCompetitorProfileActionError(null);
    setCompetitorProfileActionMessage(null);
  }

  function handleCancelDraftEdit(): void {
    setEditingDraftId(null);
    setEditFormState(null);
    setEditActionInFlight(false);
  }

  async function handleSaveDraftEdit(draftId: string): Promise<void> {
    if (!context.token || !context.businessId || !siteId || !latestCompetitorProfileRunId || !editFormState) {
      return;
    }
    setEditActionInFlight(true);
    setCompetitorProfileActionError(null);
    setCompetitorProfileActionMessage(null);
    try {
      const payload = buildDraftEditPayloadFromFormState(editFormState);
      const updated = await editCompetitorProfileDraft(
        context.token,
        context.businessId,
        siteId,
        latestCompetitorProfileRunId,
        draftId,
        payload,
      );
      upsertDraft(updated);
      setEditingDraftId(null);
      setEditFormState(null);
      setCompetitorProfileActionMessage("Draft edits saved. Accept explicitly to create competitor records.");
    } catch (error) {
      setCompetitorProfileActionError(safeActionErrorMessage("save draft edits", error));
    } finally {
      setEditActionInFlight(false);
    }
  }

  const timelineWarning = useMemo(() => {
    const possibleIssues = [auditError, competitorError, recommendationRunError, narrativeLookupError];
    return possibleIssues.find((value) => Boolean(value)) || null;
  }, [auditError, competitorError, narrativeLookupError, recommendationRunError]);

  useEffect(() => {
    if (context.loading || context.error || !selectedSite) {
      return;
    }
    if (context.selectedSiteId !== selectedSite.id) {
      context.setSelectedSiteId(selectedSite.id);
    }
  }, [
    context,
    context.error,
    context.loading,
    context.selectedSiteId,
    context.setSelectedSiteId,
    selectedSite,
  ]);

  useEffect(() => {
    if (context.loading || context.error || !siteId) {
      setLoadingWorkspace(false);
      setNotFound(false);
      setAuditRuns([]);
      setAuditError(null);
      setCompetitorSets([]);
      setSnapshotRuns([]);
      setComparisonRuns([]);
      setCompetitorError(null);
      setQueueResponse(null);
      setQueueError(null);
      setRecommendationRuns([]);
      setRecommendationRunError(null);
      setLatestNarrativesByRunId({});
      setNarrativeLookupError(null);
      setCompetitorProfileGenerationRuns([]);
      setCompetitorProfileSummary(null);
      setLatestCompetitorProfileRunId(null);
      setCompetitorProfileDrafts([]);
      setCompetitorProfileLoading(false);
      setCompetitorProfileError(null);
      setCompetitorProfileSummaryError(null);
      setCompetitorProfileActionError(null);
      setCompetitorProfileActionMessage(null);
      setGenerationInFlight(false);
      setRetryInFlight(false);
      setCompetitorProfilePolling(false);
      setDraftActionTargetId(null);
      setEditingDraftId(null);
      setEditFormState(null);
      setEditActionInFlight(false);
      setAcceptTargetSetByDraftId({});
      return;
    }

    if (!selectedSite) {
      setNotFound(true);
      setLoadingWorkspace(false);
      setCompetitorProfileGenerationRuns([]);
      setCompetitorProfileSummary(null);
      setLatestCompetitorProfileRunId(null);
      setCompetitorProfileDrafts([]);
      setCompetitorProfileLoading(false);
      setCompetitorProfileError(null);
      setCompetitorProfileSummaryError(null);
      setRetryInFlight(false);
      setCompetitorProfilePolling(false);
      return;
    }

    let cancelled = false;

    async function loadWorkspace() {
      setLoadingWorkspace(true);
      setNotFound(false);
      setAuditError(null);
      setCompetitorError(null);
      setQueueError(null);
      setRecommendationRunError(null);
      setNarrativeLookupError(null);
      setCompetitorProfileSummaryError(null);

      const [
        auditResult,
        competitorSetsResult,
        comparisonRunsResult,
        queueResult,
        recommendationRunsResult,
        competitorProfileRunsResult,
        competitorProfileSummaryResult,
      ] =
        await Promise.allSettled([
          fetchAuditRuns(context.token, context.businessId, siteId),
          fetchCompetitorSets(context.token, context.businessId, siteId),
          fetchSiteCompetitorComparisonRuns(context.token, context.businessId, siteId),
          fetchRecommendations(context.token, context.businessId, siteId, {
            page: 1,
            page_size: MAX_RECOMMENDATION_ROWS,
            sort_by: "updated_at",
            sort_order: "desc",
          }),
          fetchRecommendationRuns(context.token, context.businessId, siteId),
          fetchCompetitorProfileGenerationRuns(context.token, context.businessId, siteId),
          fetchCompetitorProfileGenerationSummary(context.token, context.businessId, siteId),
        ]);

      if (cancelled) {
        return;
      }

      if (auditResult.status === "fulfilled") {
        setAuditRuns(auditResult.value.items.slice(0, MAX_AUDIT_ROWS));
      } else {
        setAuditRuns([]);
        setAuditError(safeSectionErrorMessage("audit runs", auditResult.reason));
      }

      let nextCompetitorError: string | null = null;
      if (competitorSetsResult.status === "fulfilled") {
        const setItems = competitorSetsResult.value.items;
        const allSnapshotRuns: CompetitorSnapshotRun[] = [];
        const competitorErrors: unknown[] = [];
        const detailedSets = await Promise.all(
          setItems.map(async (setItem) => {
            let domainCount = 0;
            let activeDomainCount = 0;
            let latestSnapshot: CompetitorSnapshotRun | null = null;
            try {
              const domainResponse = await fetchCompetitorDomains(context.token, context.businessId, setItem.id);
              domainCount = domainResponse.total;
              activeDomainCount = domainResponse.items.filter((item) => item.is_active).length;
            } catch (error) {
              competitorErrors.push(error);
            }
            try {
              const snapshotRunsResponse = await fetchCompetitorSnapshotRuns(
                context.token,
                context.businessId,
                setItem.id,
              );
              allSnapshotRuns.push(...snapshotRunsResponse.items);
              latestSnapshot = latestByActivity(snapshotRunsResponse.items);
            } catch (error) {
              competitorErrors.push(error);
            }
            return {
              ...setItem,
              domain_count: domainCount,
              active_domain_count: activeDomainCount,
              latest_snapshot_run: latestSnapshot,
            };
          }),
        );
        if (cancelled) {
          return;
        }
        setCompetitorSets(detailedSets);
        setSnapshotRuns(
          allSnapshotRuns.sort((left, right) => right.created_at.localeCompare(left.created_at)),
        );
        if (competitorErrors.length > 0) {
          nextCompetitorError = safeSectionErrorMessage("competitor readiness", competitorErrors[0]);
        }
      } else {
        setCompetitorSets([]);
        setSnapshotRuns([]);
        nextCompetitorError = safeSectionErrorMessage("competitor readiness", competitorSetsResult.reason);
      }

      if (comparisonRunsResult.status === "fulfilled") {
        setComparisonRuns(comparisonRunsResult.value.items);
      } else {
        setComparisonRuns([]);
        if (!nextCompetitorError) {
          nextCompetitorError = safeSectionErrorMessage("comparison activity", comparisonRunsResult.reason);
        }
      }
      setCompetitorError(nextCompetitorError);

      if (queueResult.status === "fulfilled") {
        setQueueResponse(queueResult.value);
      } else {
        setQueueResponse(null);
        setQueueError(safeSectionErrorMessage("recommendation queue", queueResult.reason));
      }

      if (recommendationRunsResult.status === "fulfilled") {
        const sortedRuns = [...recommendationRunsResult.value.items]
          .sort((left, right) => right.created_at.localeCompare(left.created_at))
          .slice(0, MAX_RECOMMENDATION_RUN_ROWS);
        setRecommendationRuns(sortedRuns);

        const runsForNarrativeLookup = sortedRuns.slice(0, NARRATIVE_LOOKUP_LIMIT);
        if (runsForNarrativeLookup.length > 0) {
          const narrativeResults = await Promise.allSettled(
            runsForNarrativeLookup.map((run) =>
              fetchLatestRecommendationRunNarrative(
                context.token,
                context.businessId,
                siteId,
                run.id,
              ),
            ),
          );
          if (cancelled) {
            return;
          }
          const nextNarrativesByRunId: Record<string, RecommendationNarrative> = {};
          const narrativeErrors: unknown[] = [];
          for (let index = 0; index < narrativeResults.length; index += 1) {
            const run = runsForNarrativeLookup[index];
            const result = narrativeResults[index];
            if (result.status === "fulfilled") {
              nextNarrativesByRunId[run.id] = result.value;
            } else if (!isNotFoundError(result.reason)) {
              narrativeErrors.push(result.reason);
            }
          }
          setLatestNarrativesByRunId(nextNarrativesByRunId);
          if (narrativeErrors.length > 0) {
            setNarrativeLookupError(safeSectionErrorMessage("narrative metadata", narrativeErrors[0]));
          } else {
            setNarrativeLookupError(null);
          }
        } else {
          setLatestNarrativesByRunId({});
          setNarrativeLookupError(null);
        }
      } else {
        setRecommendationRuns([]);
        setLatestNarrativesByRunId({});
        setRecommendationRunError(safeSectionErrorMessage("recommendation runs", recommendationRunsResult.reason));
      }

      if (competitorProfileSummaryResult.status === "fulfilled") {
        setCompetitorProfileSummary(competitorProfileSummaryResult.value);
        setCompetitorProfileSummaryError(null);
      } else {
        setCompetitorProfileSummary(null);
        setCompetitorProfileSummaryError(
          safeSectionErrorMessage("AI competitor profile summary", competitorProfileSummaryResult.reason),
        );
      }

      if (competitorProfileRunsResult.status === "fulfilled") {
        const sortedRuns = [...competitorProfileRunsResult.value.items].sort((left, right) =>
          right.created_at.localeCompare(left.created_at),
        );
        setCompetitorProfileGenerationRuns(sortedRuns);
        setCompetitorProfileError(null);
        const latestRun = sortedRuns[0] || null;
        setLatestCompetitorProfileRunId(latestRun ? latestRun.id : null);
        if (latestRun) {
          setCompetitorProfileLoading(true);
          try {
            const detail = await fetchCompetitorProfileGenerationRunDetail(
              context.token,
              context.businessId,
              siteId,
              latestRun.id,
            );
            if (cancelled) {
              return;
            }
            setCompetitorProfileDrafts(detail.drafts);
            setCompetitorProfileError(null);
          } catch (error) {
            if (cancelled) {
              return;
            }
            setCompetitorProfileDrafts([]);
            setCompetitorProfileError(safeSectionErrorMessage("AI competitor profiles", error));
          } finally {
            if (!cancelled) {
              setCompetitorProfileLoading(false);
            }
          }
        } else {
          setCompetitorProfileDrafts([]);
          setCompetitorProfileLoading(false);
        }
      } else {
        setCompetitorProfileGenerationRuns([]);
        setLatestCompetitorProfileRunId(null);
        setCompetitorProfileDrafts([]);
        setCompetitorProfileLoading(false);
        setCompetitorProfileError(safeSectionErrorMessage("AI competitor profiles", competitorProfileRunsResult.reason));
      }

      setLoadingWorkspace(false);
    }

    void loadWorkspace().catch((error) => {
      if (!cancelled) {
        setLoadingWorkspace(false);
        setAuditError(safeSectionErrorMessage("workspace data", error));
      }
    });

    return () => {
      cancelled = true;
    };
  }, [
    context.businessId,
    context.error,
    context.loading,
    context.token,
    siteId,
    selectedSite,
  ]);

  useEffect(() => {
    if (
      !context.token ||
      !context.businessId ||
      !siteId ||
      !latestCompetitorProfileRunId ||
      !latestCompetitorProfileRunStatus ||
      isCompetitorProfileRunTerminalStatus(latestCompetitorProfileRunStatus)
    ) {
      setCompetitorProfilePolling(false);
      return;
    }

    let cancelled = false;
    let inFlight = false;
    let attempts = 0;
    setCompetitorProfilePolling(true);

    const pollOnce = async () => {
      if (cancelled || inFlight) {
        return;
      }
      if (attempts >= COMPETITOR_PROFILE_POLL_MAX_ATTEMPTS) {
        setCompetitorProfilePolling(false);
        return;
      }
      attempts += 1;
      inFlight = true;
      try {
        const runsResponse = await fetchCompetitorProfileGenerationRuns(
          context.token,
          context.businessId,
          siteId,
        );
        if (cancelled) {
          return;
        }
        try {
          const summary = await fetchCompetitorProfileGenerationSummary(
            context.token,
            context.businessId,
            siteId,
          );
          if (!cancelled) {
            setCompetitorProfileSummary(summary);
            setCompetitorProfileSummaryError(null);
          }
        } catch (summaryError) {
          if (!cancelled) {
            setCompetitorProfileSummary(null);
            setCompetitorProfileSummaryError(
              safeSectionErrorMessage("AI competitor profile summary", summaryError),
            );
          }
        }
        const sortedRuns = [...runsResponse.items].sort((left, right) =>
          right.created_at.localeCompare(left.created_at),
        );
        setCompetitorProfileGenerationRuns(sortedRuns);
        const latestRun = sortedRuns[0] || null;
        setLatestCompetitorProfileRunId(latestRun ? latestRun.id : null);
        if (!latestRun) {
          setCompetitorProfileDrafts([]);
          setCompetitorProfilePolling(false);
          return;
        }

        setCompetitorProfileLoading(true);
        const detail = await fetchCompetitorProfileGenerationRunDetail(
          context.token,
          context.businessId,
          siteId,
          latestRun.id,
        );
        if (cancelled) {
          return;
        }
        setCompetitorProfileDrafts(detail.drafts);
        setCompetitorProfileError(null);
        if (isCompetitorProfileRunTerminalStatus(detail.run.status)) {
          setCompetitorProfilePolling(false);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        setCompetitorProfileError(safeSectionErrorMessage("AI competitor profiles", error));
        setCompetitorProfilePolling(false);
      } finally {
        inFlight = false;
        if (!cancelled) {
          setCompetitorProfileLoading(false);
        }
      }
    };

    void pollOnce();
    const intervalId = window.setInterval(() => {
      void pollOnce();
    }, COMPETITOR_PROFILE_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [
    context.businessId,
    context.token,
    latestCompetitorProfileRunId,
    latestCompetitorProfileRunStatus,
    siteId,
  ]);

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div">Loading site workspace...</SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer>
        <SectionCard as="div">Unable to load tenant context. Refresh and sign in again.</SectionCard>
      </PageContainer>
    );
  }
  if (!siteId) {
    return (
      <PageContainer>
        <SectionCard>
          <h1>Site SEO Workspace</h1>
          <p className="hint warning">Site identifier is missing.</p>
          <p>
            <Link href="/sites">Back to Sites</Link>
          </p>
        </SectionCard>
      </PageContainer>
    );
  }
  if (notFound || !selectedSite) {
    return (
      <PageContainer>
        <SectionCard>
          <p>
            <Link href="/sites">Back to Sites</Link>
          </p>
          <h1>Site SEO Workspace</h1>
          <p className="hint warning">This site was not found or is not accessible in your tenant scope.</p>
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <SectionCard>
        <p>
          <Link href="/sites">Back to Sites</Link>
        </p>
        <h1>Site SEO Workspace</h1>
        <p>
          Site: <strong>{selectedSite.display_name}</strong>
        </p>
        <p>
          Business ID: <code>{selectedSite.business_id}</code>
        </p>
        <p>
          Site ID: <code>{selectedSite.id}</code>
        </p>
        <p>Base URL: {selectedSite.base_url}</p>
        <p>Domain: {selectedSite.normalized_domain}</p>
        <p>Active: {selectedSite.is_active ? "yes" : "no"}</p>
        <p>Primary: {selectedSite.is_primary ? "yes" : "no"}</p>
        <p>
          Last Audit Status: {selectedSite.last_audit_status || "-"} ({formatDateTime(selectedSite.last_audit_completed_at)})
        </p>
        <p>
          Operator Context:{" "}
          {context.selectedSiteId === selectedSite.id
            ? "This site is currently selected in operator context."
            : "This page is scoped to this site even if a different site is selected elsewhere."}
        </p>
        <div className="link-row">
          <Link href="/audits">Audit Runs</Link>
          <Link href={`/competitors?site_id=${encodeURIComponent(selectedSite.id)}`}>Competitor Workspace</Link>
          <Link href="/recommendations">Recommendation Queue</Link>
        </div>
        {loadingWorkspace ? <p className="hint muted">Loading workspace data...</p> : null}
      </SectionCard>

      <SectionCard>
        <h2>Site Activity Timeline</h2>
        {loadingWorkspace ? <p className="hint muted">Loading recent site activity...</p> : null}
        {timelineWarning ? (
          <p className="hint warning">Some activity data could not be loaded. Available events are still shown.</p>
        ) : null}
        {!loadingWorkspace && timelineEvents.length === 0 ? (
          <p className="hint muted">No recent site activity events are available for this site yet.</p>
        ) : null}
        {!loadingWorkspace && timelineEvents.length > 0 ? (
          <>
            <div className="stack timeline-controls" data-testid="timeline-controls">
              <div className="timeline-filter-row">
                <span className="hint muted">Event Types:</span>
                {TIMELINE_EVENT_TYPE_OPTIONS.map((option) => (
                  <label key={option.value} className="checkbox-chip">
                    <input
                      type="checkbox"
                      checked={activeEventTypes.has(option.value)}
                      onChange={() => handleEventTypeToggle(option.value)}
                    />
                    {option.label}
                  </label>
                ))}
              </div>

              <div className="timeline-filter-row">
                <span className="hint muted">Statuses:</span>
                {availableTimelineStatuses.map((statusValue) => (
                  <label key={statusValue} className="checkbox-chip">
                    <input
                      type="checkbox"
                      checked={activeStatuses.has(statusValue)}
                      onChange={() => handleStatusToggle(statusValue)}
                    />
                    {statusValue}
                  </label>
                ))}
              </div>

              <p className="hint muted">
                Showing {visibleTimelineEvents.length} of {filteredTimelineEvents.length} events
              </p>
            </div>

            {filteredTimelineEvents.length === 0 ? (
              <p className="hint muted">No timeline events match the selected filters.</p>
            ) : (
              <>
                <div className="table-container">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Event</th>
                      </tr>
                    </thead>
                    <tbody>
                      {groupedVisibleTimelineEvents.map((group) => (
                        <Fragment key={group.key}>
                          <tr data-testid="site-activity-day-header">
                            <td colSpan={4} className="timeline-day-header-cell">
                              {group.label}
                            </td>
                          </tr>
                          {group.events.map((event) => (
                            <tr key={event.id} data-testid="site-activity-row">
                              <td>
                                {formatDateTime(event.timestamp)}
                                <br />
                                <span className="hint muted">{event.timestamp_label}</span>
                              </td>
                              <td>{event.type_label}</td>
                              <td>{event.status}</td>
                              <td className="table-cell-wrap">
                                <Link href={event.href}>{event.title}</Link>
                                <br />
                                <span className="hint muted">{event.context}</span>
                              </td>
                            </tr>
                          ))}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>

                {shouldShowTimelineExpansionToggle ? (
                  <div className="form-actions">
                    <button
                      type="button"
                      onClick={() => setExpandedTimeline((current) => !current)}
                    >
                      {expandedTimeline ? "Show less" : "Show more"}
                    </button>
                  </div>
                ) : null}
              </>
            )}
          </>
        ) : null}
      </SectionCard>

      <SectionCard>
        <h2>Recent Audit Runs</h2>
        {auditError ? <p className="hint error">{auditError}</p> : null}
        {auditRuns.length === 0 && !auditError ? (
          <p className="hint muted">No audit runs have been recorded for this site yet.</p>
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Started</th>
                  <th>Completed</th>
                  <th>Pages Crawled</th>
                  <th>Errors</th>
                </tr>
              </thead>
              <tbody>
                {auditRuns.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <Link href={`/audits/${run.id}`}>{run.id}</Link>
                    </td>
                    <td>{run.status}</td>
                    <td>{formatDateTime(run.created_at)}</td>
                    <td>{formatDateTime(run.started_at)}</td>
                    <td>{formatDateTime(run.completed_at)}</td>
                    <td>{run.pages_crawled}</td>
                    <td>{run.errors_encountered}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      <SectionCard>
        <h2>Competitor Readiness</h2>
        {competitorError ? <p className="hint error">{competitorError}</p> : null}
        <p>{workspaceReadinessMessage}</p>
        <p>Active Competitor Sets: {activeCompetitorSetCount}</p>
        <p>Total Competitor Domains: {competitorDomainCount}</p>
        <p>Active Competitor Domains: {activeCompetitorDomainCount}</p>
        <p>
          Latest Snapshot Run:{" "}
          {latestSnapshotRun ? (
            <Link
              href={buildSnapshotRunHref(
                latestSnapshotRun.id,
                selectedSite.id,
                latestSnapshotRun.competitor_set_id,
              )}
            >
              {latestSnapshotRun.status} ({formatDateTime(latestSnapshotRun.completed_at || latestSnapshotRun.updated_at)})
            </Link>
          ) : (
            "-"
          )}
        </p>
        <p>
          Latest Comparison Run:{" "}
          {latestComparisonRun ? (
            <Link
              href={buildComparisonRunHref(
                latestComparisonRun.id,
                selectedSite.id,
                latestComparisonRun.competitor_set_id,
              )}
            >
              {latestComparisonRun.status} ({formatDateTime(latestComparisonRun.completed_at || latestComparisonRun.updated_at)})
            </Link>
          ) : (
            "-"
          )}
        </p>
        <p>
          <Link href={`/competitors?site_id=${encodeURIComponent(selectedSite.id)}`}>Open Competitor Surfaces</Link>
        </p>
        {competitorSets.length === 0 ? (
          <p className="hint muted">No competitor sets are currently configured for this site.</p>
        ) : (
          <>
            <div className="table-container">
              <table className="table">
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
                  {competitorSets.slice(0, MAX_COMPETITOR_ROWS).map((setItem) => (
                    <tr key={setItem.id}>
                      <td className="table-cell-wrap">
                        <Link href={buildCompetitorSetHref(setItem.id, selectedSite.id)}>{setItem.name}</Link>
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
                            href={buildSnapshotRunHref(
                              setItem.latest_snapshot_run.id,
                              selectedSite.id,
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
            </div>
            {competitorSets.length > MAX_COMPETITOR_ROWS ? (
              <p className="hint muted">
                Showing the {MAX_COMPETITOR_ROWS} most recently updated competitor sets for this site.
              </p>
            ) : null}
          </>
        )}
      </SectionCard>

      <SectionCard>
        <h2>AI Competitor Profiles</h2>
        <p className="hint muted">
          Generate AI-produced competitor profile drafts, then review and explicitly accept or reject each candidate.
        </p>
        {competitorProfileError ? <p className="hint error">{competitorProfileError}</p> : null}
        {competitorProfileSummaryError ? <p className="hint warning">{competitorProfileSummaryError}</p> : null}
        {competitorProfileActionError ? <p className="hint error">{competitorProfileActionError}</p> : null}
        {competitorProfileActionMessage ? <p className="hint success">{competitorProfileActionMessage}</p> : null}
        <div className="form-actions">
          <button
            type="button"
            onClick={() => void handleGenerateCompetitorProfiles()}
            disabled={loadingWorkspace || generationInFlight || retryInFlight || competitorProfileLoading}
          >
            {generationInFlight ? "Queuing..." : "Generate Competitor Profiles"}
          </button>
          {latestCompetitorProfileRun?.status === "failed" ? (
            <button
              type="button"
              onClick={() => void handleRetryCompetitorProfileRun()}
              disabled={loadingWorkspace || generationInFlight || retryInFlight || competitorProfileLoading}
            >
              {retryInFlight ? "Retrying..." : "Retry"}
            </button>
          ) : null}
        </div>
        {latestCompetitorProfileRun ? (
          <p>
            Latest Run: <code>{latestCompetitorProfileRun.id}</code> ({latestCompetitorProfileRun.status}){" "}
            {latestCompetitorProfileRun.completed_at
              ? `completed ${formatDateTime(latestCompetitorProfileRun.completed_at)}`
              : `created ${formatDateTime(latestCompetitorProfileRun.created_at)}`}
          </p>
        ) : (
          <p className="hint muted">No competitor profile generation runs have been created for this site yet.</p>
        )}
        {latestCompetitorProfileRun ? (
          <p className="hint muted">
            Provider: <code>{latestCompetitorProfileRun.provider_name}</code> | Model:{" "}
            <code>{latestCompetitorProfileRun.model_name}</code> | Prompt:{" "}
            <code>{latestCompetitorProfileRun.prompt_version}</code>
          </p>
        ) : null}
        {competitorProfileSummary ? (
          <Fragment>
            <p className="hint muted">
              Last {competitorProfileSummary.lookback_days}d: queued {competitorProfileSummary.queued_count} |
              running {competitorProfileSummary.running_count} | completed {competitorProfileSummary.completed_count} |
              failed {competitorProfileSummary.failed_count}
            </p>
            <p className="hint muted">
              Retry runs: {competitorProfileSummary.retry_child_runs} | retried parents:{" "}
              {competitorProfileSummary.retried_parent_runs} | failed runs later retried:{" "}
              {competitorProfileSummary.failed_runs_retried}
            </p>
            <p className="hint muted">
              Candidate telemetry ({competitorProfileSummary.total_runs} runs): raw{" "}
              {competitorProfileSummary.total_raw_candidate_count} | included{" "}
              {competitorProfileSummary.total_included_candidate_count} | excluded{" "}
              {competitorProfileSummary.total_excluded_candidate_count}
            </p>
            {Object.keys(competitorProfileSummary.failure_category_counts).length > 0 ? (
              <p className="hint muted">
                Failure categories:{" "}
                {Object.entries(competitorProfileSummary.failure_category_counts)
                  .sort(([left], [right]) => left.localeCompare(right))
                  .map(([key, value]) => `${formatFailureCategory(key)}=${value}`)
                  .join(", ")}
              </p>
            ) : null}
            {Object.values(competitorProfileSummary.exclusion_counts_by_reason).some((count) => count > 0) ? (
              <p className="hint muted">
                Exclusion reasons:{" "}
                {Object.entries(competitorProfileSummary.exclusion_counts_by_reason)
                  .filter(([, value]) => value > 0)
                  .sort(([left], [right]) => left.localeCompare(right))
                  .map(([key, value]) => `${formatFailureCategory(key)}=${value}`)
                  .join(", ")}
              </p>
            ) : null}
          </Fragment>
        ) : null}
        {latestCompetitorProfileRun?.parent_run_id ? (
          <p className="hint muted">
            Retry of run <code>{latestCompetitorProfileRun.parent_run_id}</code>.
          </p>
        ) : null}
        {latestCompetitorProfileRun?.failure_category ? (
          <p className="hint muted">
            Failure Category: <code>{formatFailureCategory(latestCompetitorProfileRun.failure_category)}</code>
          </p>
        ) : null}
        {latestCompetitorProfileRun?.error_summary ? (
          <p className="hint warning">{latestCompetitorProfileRun.error_summary}</p>
        ) : null}
        {competitorProfileLoading || competitorProfilePolling ? (
          <p className="hint muted">Refreshing generated draft status...</p>
        ) : null}
        {latestCompetitorProfileRun &&
        !isCompetitorProfileRunTerminalStatus(latestCompetitorProfileRun.status) ? (
          <p className="hint muted">Generation is in progress for this run.</p>
        ) : null}
        {!competitorProfileLoading &&
        latestCompetitorProfileRun &&
        isCompetitorProfileRunTerminalStatus(latestCompetitorProfileRun.status) &&
        competitorProfileDrafts.length === 0 ? (
          <p className="hint muted">This run did not produce any reviewable drafts.</p>
        ) : null}
        {!competitorProfileLoading && competitorProfileDrafts.length > 0 ? (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Suggested Competitor</th>
                  <th>Type</th>
                  <th>Confidence</th>
                  <th>Summary</th>
                  <th>Review Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {competitorProfileDrafts.map((draft) => {
                  const isEditing = editingDraftId === draft.id && editFormState !== null;
                  const actionDisabled =
                    draftActionTargetId === draft.id || editActionInFlight || generationInFlight || retryInFlight;
                  const editable = draft.review_status === "pending" || draft.review_status === "edited";
                  return (
                    <Fragment key={draft.id}>
                      <tr data-testid="competitor-profile-draft-row">
                        <td className="table-cell-wrap">
                          <strong>{draft.suggested_name}</strong>
                          <br />
                          <code>{draft.suggested_domain}</code>
                        </td>
                        <td>{draft.competitor_type}</td>
                        <td>{draft.confidence_score.toFixed(2)}</td>
                        <td className="table-cell-wrap">
                          {truncateText(draft.summary, 140)}
                          <br />
                          <span className="hint muted">{truncateText(draft.why_competitor, 140)}</span>
                        </td>
                        <td>{draft.review_status}</td>
                        <td>
                          <div className="stack">
                            <label className="stack">
                              <span className="hint muted">Target Set</span>
                              <select
                                value={acceptTargetSetByDraftId[draft.id] || ""}
                                onChange={(event) =>
                                  setAcceptTargetSetByDraftId((current) => ({
                                    ...current,
                                    [draft.id]: event.target.value,
                                  }))
                                }
                                disabled={!editable || actionDisabled}
                              >
                                <option value="">Auto-select</option>
                                {competitorSets.map((setItem) => (
                                  <option key={setItem.id} value={setItem.id}>
                                    {setItem.name}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <div className="form-actions">
                              <button
                                type="button"
                                onClick={() => void handleAcceptCompetitorProfileDraft(draft.id)}
                                disabled={!editable || actionDisabled}
                              >
                                {draftActionTargetId === draft.id ? "Applying..." : "Accept"}
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleRejectCompetitorProfileDraft(draft.id)}
                                disabled={!editable || actionDisabled}
                              >
                                {draftActionTargetId === draft.id ? "Applying..." : "Reject"}
                              </button>
                              <button
                                type="button"
                                onClick={() => handleStartDraftEdit(draft)}
                                disabled={!editable || actionDisabled}
                              >
                                Edit
                              </button>
                            </div>
                          </div>
                        </td>
                      </tr>
                      {isEditing ? (
                        <tr>
                          <td colSpan={6}>
                            <div className="stack">
                              <h3>Edit Draft</h3>
                              <label className="stack">
                                Suggested Name
                                <input
                                  type="text"
                                  value={editFormState.suggested_name}
                                  onChange={(event) =>
                                    setEditFormState((current) =>
                                      current
                                        ? { ...current, suggested_name: event.target.value }
                                        : current,
                                    )
                                  }
                                />
                              </label>
                              <label className="stack">
                                Suggested Domain
                                <input
                                  type="text"
                                  value={editFormState.suggested_domain}
                                  onChange={(event) =>
                                    setEditFormState((current) =>
                                      current
                                        ? { ...current, suggested_domain: event.target.value }
                                        : current,
                                    )
                                  }
                                />
                              </label>
                              <label className="stack">
                                Competitor Type
                                <select
                                  value={editFormState.competitor_type}
                                  onChange={(event) =>
                                    setEditFormState((current) =>
                                      current
                                        ? { ...current, competitor_type: event.target.value }
                                        : current,
                                    )
                                  }
                                >
                                  <option value="direct">direct</option>
                                  <option value="indirect">indirect</option>
                                  <option value="local">local</option>
                                  <option value="marketplace">marketplace</option>
                                  <option value="informational">informational</option>
                                  <option value="unknown">unknown</option>
                                </select>
                              </label>
                              <label className="stack">
                                Summary
                                <textarea
                                  value={editFormState.summary}
                                  onChange={(event) =>
                                    setEditFormState((current) =>
                                      current
                                        ? { ...current, summary: event.target.value }
                                        : current,
                                    )
                                  }
                                />
                              </label>
                              <label className="stack">
                                Why Competitor
                                <textarea
                                  value={editFormState.why_competitor}
                                  onChange={(event) =>
                                    setEditFormState((current) =>
                                      current
                                        ? { ...current, why_competitor: event.target.value }
                                        : current,
                                    )
                                  }
                                />
                              </label>
                              <label className="stack">
                                Evidence
                                <textarea
                                  value={editFormState.evidence}
                                  onChange={(event) =>
                                    setEditFormState((current) =>
                                      current
                                        ? { ...current, evidence: event.target.value }
                                        : current,
                                    )
                                  }
                                />
                              </label>
                              <label className="stack">
                                Confidence Score (0-1)
                                <input
                                  type="number"
                                  min={0}
                                  max={1}
                                  step={0.01}
                                  value={editFormState.confidence_score}
                                  onChange={(event) =>
                                    setEditFormState((current) =>
                                      current
                                        ? { ...current, confidence_score: event.target.value }
                                        : current,
                                    )
                                  }
                                />
                              </label>
                              <div className="form-actions">
                                <button
                                  type="button"
                                  onClick={() => void handleSaveDraftEdit(draft.id)}
                                  disabled={editActionInFlight || draftActionTargetId === draft.id}
                                >
                                  {editActionInFlight ? "Saving..." : "Save Edits"}
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    void handleAcceptCompetitorProfileDraft(
                                      draft.id,
                                      buildDraftEditPayloadFromFormState(editFormState),
                                    )
                                  }
                                  disabled={editActionInFlight || draftActionTargetId === draft.id}
                                >
                                  {draftActionTargetId === draft.id ? "Applying..." : "Accept Edited"}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleCancelDraftEdit()}
                                  disabled={editActionInFlight || draftActionTargetId === draft.id}
                                >
                                  Cancel
                                </button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </SectionCard>

      <SectionCard>
        <h2>Recommendation Queue</h2>
        {queueError ? <p className="hint error">{queueError}</p> : null}
        <p>Total: {recommendationQueueSummary.total}</p>
        <p>Open: {recommendationQueueSummary.open}</p>
        <p>Accepted: {recommendationQueueSummary.accepted}</p>
        <p>Dismissed: {recommendationQueueSummary.dismissed}</p>
        <p>High Priority: {recommendationQueueSummary.highPriority}</p>
        <p>
          <Link href="/recommendations">Open Recommendation Queue</Link>
        </p>
        {!queueError && (!queueResponse || queueResponse.items.length === 0) ? (
          <p className="hint muted">No recommendations are currently visible for this site.</p>
        ) : null}
        {queueResponse && queueResponse.items.length > 0 ? (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Category</th>
                  <th>Source</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {queueResponse.items.map((item) => (
                  <tr key={item.id}>
                    <td className="table-cell-wrap">
                      <Link href={buildRecommendationDetailHref(item.id, selectedSite.id)}>{item.title}</Link>
                      <br />
                      <span className="hint muted"><code>{item.id}</code></span>
                    </td>
                    <td>
                      {item.priority_score} ({item.priority_band})
                    </td>
                    <td>{item.status}</td>
                    <td>{item.category}</td>
                    <td>{recommendationSourceType(item)}</td>
                    <td>{formatDateTime(item.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </SectionCard>

      <SectionCard>
        <h2>Recommendation Runs and Narratives</h2>
        {recommendationRunError ? <p className="hint error">{recommendationRunError}</p> : null}
        {narrativeLookupError ? <p className="hint warning">{narrativeLookupError}</p> : null}
        {recommendationRuns.length === 0 && !recommendationRunError ? (
          <p className="hint muted">No recommendation runs have been recorded for this site yet.</p>
        ) : (
          <div className="table-container">
            <table className="table">
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
                        <Link href={buildRecommendationRunHref(run.id, selectedSite.id)}>{run.id}</Link>
                      </td>
                      <td>{run.status}</td>
                      <td>{formatDateTime(run.created_at)}</td>
                      <td>{formatDateTime(run.completed_at)}</td>
                      <td>{run.total_recommendations}</td>
                      <td>
                        <div className="stack">
                          <Link href={buildNarrativeHistoryHref(run.id, selectedSite.id)}>History</Link>
                          {latestNarrative ? (
                            <Link
                              href={buildNarrativeDetailHref(run.id, latestNarrative.id, selectedSite.id)}
                            >
                              Latest v{latestNarrative.version} ({latestNarrative.status})
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
        )}
      </SectionCard>
    </PageContainer>
  );
}
