"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../../components/layout/PageContainer";
import { SectionCard } from "../../../components/layout/SectionCard";
import { useOperatorContext } from "../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchAuditRuns,
  fetchCompetitorDomains,
  fetchCompetitorSets,
  fetchCompetitorSnapshotRuns,
  fetchLatestRecommendationRunNarrative,
  fetchRecommendationRuns,
  fetchRecommendations,
  fetchSiteCompetitorComparisonRuns,
} from "../../../lib/api/client";
import type {
  CompetitorComparisonRun,
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
  const [activeEventTypes, setActiveEventTypes] = useState<Set<SiteTimelineEventType>>(
    () => new Set(TIMELINE_EVENT_TYPE_OPTIONS.map((option) => option.value)),
  );
  const [activeStatuses, setActiveStatuses] = useState<Set<string>>(() => new Set());
  const [expandedTimeline, setExpandedTimeline] = useState(false);

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
      return;
    }

    if (!selectedSite) {
      setNotFound(true);
      setLoadingWorkspace(false);
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

      const [auditResult, competitorSetsResult, comparisonRunsResult, queueResult, recommendationRunsResult] =
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
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
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
            <div className="stack" data-testid="timeline-controls" style={{ gap: "0.5rem" }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
                <span className="hint muted">Event Types:</span>
                {TIMELINE_EVENT_TYPE_OPTIONS.map((option) => (
                  <label key={option.value} style={{ display: "inline-flex", gap: "0.35rem", alignItems: "center" }}>
                    <input
                      type="checkbox"
                      checked={activeEventTypes.has(option.value)}
                      onChange={() => handleEventTypeToggle(option.value)}
                    />
                    {option.label}
                  </label>
                ))}
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
                <span className="hint muted">Statuses:</span>
                {availableTimelineStatuses.map((statusValue) => (
                  <label key={statusValue} style={{ display: "inline-flex", gap: "0.35rem", alignItems: "center" }}>
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
                            <td colSpan={4} style={{ fontWeight: 600, background: "rgba(255,255,255,0.03)" }}>
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
                              <td>
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
                  <p>
                    <button
                      type="button"
                      onClick={() => setExpandedTimeline((current) => !current)}
                    >
                      {expandedTimeline ? "Show less" : "Show more"}
                    </button>
                  </p>
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
                      <td>
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
                    <td>
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
