"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../../../components/layout/PageContainer";
import { DetailFocusPanel, type DetailFocusFact } from "../../../../components/layout/DetailFocusPanel";
import { SectionCard } from "../../../../components/layout/SectionCard";
import { SectionHeader } from "../../../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../../../components/layout/SummaryStatCard";
import { WorkflowContextPanel } from "../../../../components/layout/WorkflowContextPanel";
import { useOperatorContext } from "../../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchAutomationRuns,
  fetchCompetitorComparisonReport,
  fetchLatestRecommendationRunNarrative,
  fetchRecommendationRunReport,
} from "../../../../lib/api/client";
import { deriveRecommendationRunOperatorActionState } from "../../../../lib/operatorActionState";
import type {
  AutomationRun,
  CompetitorComparisonReport,
  Recommendation,
  RecommendationNarrative,
  RecommendationRun,
  RecommendationRunReport,
} from "../../../../lib/api/types";

const RECOMMENDATION_PREVIEW_LIMIT = 150;
const RECOMMENDATION_RATIONALE_PREVIEW_LIMIT = 160;

const RECOMMENDATION_PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

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

function truncateText(value: string, limit: number): string {
  const normalized = value.trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit - 1)}…`;
}

function truncateEvidenceText(value: string, maxChars: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
}

function deriveRecommendationEvidencePreview(item: Recommendation): string {
  const firstCompetitorEvidence = (item.competitor_evidence_links || [])
    .map((link) => (link.evidence_summary || "").trim())
    .find((value) => value.length > 0);
  const candidates = [
    item.recommendation_evidence_summary || "",
    item.recommendation_observed_gap_summary || "",
    item.recommendation_action_delta?.observed_site_gap || "",
    firstCompetitorEvidence || "",
    (item.recommendation_evidence_trace || [])[0] || "",
    item.rationale || "",
  ]
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
  if (candidates.length === 0) {
    return "No supporting proof captured yet.";
  }
  return truncateEvidenceText(candidates[0], 128);
}

function deriveRecommendationEvidenceTrustCue(item: Recommendation): string {
  const tiers = (item.competitor_evidence_links || []).map((link) => link.trust_tier || link.evidence_trust_tier || null);
  if (tiers.includes("trusted_verified")) {
    return "Support cue: verified linkage evidence";
  }
  if (tiers.includes("informational_unverified") || tiers.includes("informational_candidate")) {
    return "Support cue: informational linkage evidence";
  }
  if ((item.recommendation_evidence_summary || "").trim().length > 0 || (item.recommendation_evidence_trace || []).length > 0) {
    return "Support cue: recommendation-context evidence";
  }
  return "Support cue: operator review required";
}

function deriveRecommendationEffortCue(item: Recommendation): string {
  const effortHint = item.recommendation_priority?.effort_hint || null;
  if (effortHint === "quick_win") {
    return "Quick win";
  }
  if (effortHint === "larger_change") {
    return "More involved";
  }
  if (effortHint === "moderate") {
    return "Moderate lift";
  }
  const effortBucket = (item.effort_bucket || "").trim().toLowerCase();
  if (effortBucket === "small") {
    return "Quick win";
  }
  if (effortBucket === "large" || effortBucket === "xlarge") {
    return "More involved";
  }
  if (effortBucket.length > 0) {
    return "Moderate lift";
  }
  return "Effort not specified";
}

function deriveRecommendationChoiceCue(item: Recommendation, topRecommendationId: string | null): string {
  if (item.id === topRecommendationId && (item.status === "open" || item.status === "in_progress")) {
    return "Best immediate move";
  }
  if (item.status === "accepted") {
    return "Waiting on visibility";
  }
  if (item.status === "dismissed" || item.status === "resolved" || item.status === "snoozed") {
    return "Lower-immediacy background item";
  }
  if (item.status === "open" || item.status === "in_progress") {
    if (item.priority_band === "high" || item.priority_band === "critical") {
      return "High-value next step";
    }
    return "Ready-now alternative";
  }
  return "Review before applying";
}

function deriveRecommendationBlockerCue(item: Recommendation): string {
  if (item.status === "accepted") {
    return "Manual follow-up required";
  }
  if (item.status === "open" || item.status === "in_progress") {
    return "Blocked by operator review";
  }
  if (item.status === "dismissed" || item.status === "resolved" || item.status === "snoozed") {
    return "No blocker";
  }
  return "Review required";
}

function deriveRecommendationLifecycleSupport(item: Recommendation): {
  stage: string;
  stageTone: "neutral" | "success" | "warning";
  revisit: string;
  revisitTone: "neutral" | "success" | "warning";
} {
  if (item.status === "accepted") {
    return {
      stage: "Applied / completed",
      stageTone: "success",
      revisit: "Revisit after visibility refresh.",
      revisitTone: "warning",
    };
  }
  if (item.status === "dismissed" || item.status === "resolved" || item.status === "snoozed") {
    return {
      stage: "Background item / revisit later",
      stageTone: "neutral",
      revisit: "Ignore for now unless context changes.",
      revisitTone: "neutral",
    };
  }
  if (item.status === "open" || item.status === "in_progress") {
    return {
      stage: "Needs review / pending",
      stageTone: "warning",
      revisit: "Revisit now.",
      revisitTone: "success",
    };
  }
  return {
    stage: "Needs review / pending",
    stageTone: "warning",
    revisit: "Revisit now.",
    revisitTone: "warning",
  };
}

function deriveRecommendationFreshnessSupport(item: Recommendation): {
  freshness: string;
  freshnessTone: "neutral" | "success" | "warning";
  refreshCheck: string;
  refreshCheckTone: "neutral" | "success" | "warning";
} {
  const hasTimestamp = (item.updated_at || item.created_at || "").trim().length > 0;
  if (!hasTimestamp) {
    return {
      freshness: "Possibly outdated",
      freshnessTone: "warning",
      refreshCheck: "Refresh likely needed before acting.",
      refreshCheckTone: "warning",
    };
  }
  if (item.status === "accepted") {
    return {
      freshness: "Pending refresh",
      freshnessTone: "warning",
      refreshCheck: "Refresh not required before acting. Validate visibility after next refresh.",
      refreshCheckTone: "warning",
    };
  }
  if (item.status === "dismissed" || item.status === "resolved" || item.status === "snoozed") {
    return {
      freshness: "Review soon",
      freshnessTone: "neutral",
      refreshCheck: "No immediate refresh needed while deferred.",
      refreshCheckTone: "neutral",
    };
  }
  if (item.status === "open" || item.status === "in_progress") {
    return {
      freshness: "Fresh enough to act",
      freshnessTone: "success",
      refreshCheck: "No refresh required before acting.",
      refreshCheckTone: "success",
    };
  }
  return {
    freshness: "Possibly outdated",
    freshnessTone: "warning",
    refreshCheck: "Refresh likely needed before acting.",
    refreshCheckTone: "warning",
  };
}

function isNotFoundError(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 404;
}

function safeRecommendationRunDetailErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view this recommendation run.";
    }
    if (error.status === 404) {
      return "Recommendation run was not found in your tenant scope.";
    }
  }
  return "Unable to load recommendation run details right now. Please try again.";
}

function safeRecommendationRunRelatedErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view one or more related resources.";
    }
    if (error.status === 404) {
      return "Some related resources were not found in your tenant scope.";
    }
  }
  return "Some related recommendation-run context could not be loaded. The available data is still shown.";
}

type RecommendationRunAutomationOrigin = {
  automationRunId: string;
  triggerSource: string;
  runStatus: string;
  recommendationRunOutputId: string;
  recommendationNarrativeOutputId: string | null;
  startedAt: string | null;
  finishedAt: string | null;
};

function deriveRecommendationRunAutomationOrigin(
  automationRuns: AutomationRun[],
  recommendationRunId: string,
): RecommendationRunAutomationOrigin | null {
  const sortedRuns = [...automationRuns].sort((left, right) => {
    const leftMs = Date.parse(left.created_at || left.started_at || "");
    const rightMs = Date.parse(right.created_at || right.started_at || "");
    if (Number.isNaN(leftMs) || Number.isNaN(rightMs)) {
      return right.id.localeCompare(left.id);
    }
    return rightMs - leftMs;
  });

  for (const run of sortedRuns) {
    if (!Array.isArray(run.steps_json)) {
      continue;
    }
    const recommendationRunStep = run.steps_json.find((step) => {
      if (!step || typeof step !== "object") {
        return false;
      }
      const stepName = typeof step.step_name === "string" ? step.step_name : "";
      const stepStatus = typeof step.status === "string" ? step.status.toLowerCase() : "";
      const linkedOutputId = typeof step.linked_output_id === "string" ? step.linked_output_id.trim() : "";
      return stepName === "recommendation_run" && stepStatus === "completed" && linkedOutputId === recommendationRunId;
    });

    if (!recommendationRunStep) {
      continue;
    }

    const recommendationNarrativeStep = run.steps_json.find((step) => {
      if (!step || typeof step !== "object") {
        return false;
      }
      const stepName = typeof step.step_name === "string" ? step.step_name : "";
      const stepStatus = typeof step.status === "string" ? step.status.toLowerCase() : "";
      return stepName === "recommendation_narrative" && stepStatus === "completed";
    });

    return {
      automationRunId: run.id,
      triggerSource: run.trigger_source,
      runStatus: run.status,
      recommendationRunOutputId: recommendationRunId,
      recommendationNarrativeOutputId:
        recommendationNarrativeStep && typeof recommendationNarrativeStep.linked_output_id === "string"
          ? recommendationNarrativeStep.linked_output_id
          : null,
      startedAt: run.started_at || null,
      finishedAt: run.finished_at || null,
    };
  }

  return null;
}

function deriveRecommendationSourceType(item: Recommendation): string {
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

function toSortedCountEntries(countMap: Record<string, number> | undefined): Array<[string, number]> {
  if (!countMap) {
    return [];
  }
  return Object.entries(countMap).sort((left, right) => left[0].localeCompare(right[0]));
}

function buildRecommendationDetailHref(item: Recommendation): string {
  const params = new URLSearchParams();
  params.set("site_id", item.site_id);
  return `/recommendations/${item.id}?${params.toString()}`;
}

function buildNarrativeHistoryHref(
  recommendationRunId: string,
  siteId: string,
  queueContextParams: URLSearchParams,
): string {
  const params = new URLSearchParams(queueContextParams);
  if (siteId) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query
    ? `/recommendations/runs/${recommendationRunId}/narratives?${query}`
    : `/recommendations/runs/${recommendationRunId}/narratives`;
}

function buildNarrativeDetailHref(
  recommendationRunId: string,
  narrativeId: string,
  siteId: string,
  queueContextParams: URLSearchParams,
): string {
  const params = new URLSearchParams(queueContextParams);
  if (siteId) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query
    ? `/recommendations/runs/${recommendationRunId}/narratives/${narrativeId}?${query}`
    : `/recommendations/runs/${recommendationRunId}/narratives/${narrativeId}`;
}

function parseQueueContextSearchParams(searchParams: URLSearchParams): URLSearchParams {
  const nextParams = new URLSearchParams();
  const status = (searchParams.get("status") || "").trim().toLowerCase();
  if (["open", "in_progress", "accepted", "dismissed", "snoozed", "resolved"].includes(status)) {
    nextParams.set("status", status);
  }
  const priority = (searchParams.get("priority") || searchParams.get("priority_band") || "").trim().toLowerCase();
  if (["low", "medium", "high", "critical"].includes(priority)) {
    nextParams.set("priority", priority);
  }
  const category = (searchParams.get("category") || "").trim().toUpperCase();
  if (["SEO", "CONTENT", "STRUCTURE", "TECHNICAL"].includes(category)) {
    nextParams.set("category", category);
  }
  const sort = (searchParams.get("sort") || "").trim().toLowerCase();
  if (["priority_asc", "priority_desc", "newest", "oldest"].includes(sort)) {
    if (sort !== "priority_desc") {
      nextParams.set("sort", sort);
    }
  } else {
    const sortBy = (searchParams.get("sort_by") || "").trim().toLowerCase();
    const sortOrder = (searchParams.get("sort_order") || "").trim().toLowerCase();
    if (sortBy === "created_at" && sortOrder === "asc") {
      nextParams.set("sort", "oldest");
    } else if (sortBy === "created_at" && sortOrder === "desc") {
      nextParams.set("sort", "newest");
    } else if (sortBy === "priority_score" && sortOrder === "asc") {
      nextParams.set("sort", "priority_asc");
    }
  }
  const page = Number.parseInt((searchParams.get("page") || "").trim(), 10);
  if (Number.isFinite(page) && page > 1) {
    nextParams.set("page", String(page));
  }
  const pageSize = Number.parseInt((searchParams.get("page_size") || "").trim(), 10);
  if (
    Number.isFinite(pageSize) &&
    RECOMMENDATION_PAGE_SIZE_OPTIONS.includes(pageSize as (typeof RECOMMENDATION_PAGE_SIZE_OPTIONS)[number])
  ) {
    nextParams.set("page_size", String(pageSize));
  }
  return nextParams;
}

export default function RecommendationRunDetailPage() {
  const params = useParams<{ run_id: string }>();
  const searchParams = useSearchParams();
  const recommendationRunId = (params?.run_id || "").trim();
  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const context = useOperatorContext();

  const queueContextParams = useMemo(
    () => parseQueueContextSearchParams(searchParams),
    [searchParams],
  );

  const backToRecommendationsHref = useMemo(() => {
    const query = queueContextParams.toString();
    return query ? `/recommendations?${query}` : "/recommendations";
  }, [queueContextParams]);

  const candidateSiteIds = useMemo(() => {
    const candidates = [
      requestedSiteId,
      context.selectedSiteId || "",
      ...context.sites.map((site) => site.id),
    ].filter((value) => value.trim().length > 0);
    return [...new Set(candidates)];
  }, [context.selectedSiteId, context.sites, requestedSiteId]);

  const [report, setReport] = useState<RecommendationRunReport | null>(null);
  const [latestNarrative, setLatestNarrative] = useState<RecommendationNarrative | null>(null);
  const [comparisonReport, setComparisonReport] = useState<CompetitorComparisonReport | null>(null);
  const [automationOrigin, setAutomationOrigin] = useState<RecommendationRunAutomationOrigin | null>(null);
  const [resolvedSiteId, setResolvedSiteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [relatedError, setRelatedError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const run: RecommendationRun | null = report?.recommendation_run || null;
  const runOriginLabel = automationOrigin ? "Automation-triggered" : run ? "Manual / direct" : "Loading";
  const runOriginDetail = automationOrigin
    ? `Automation run ${automationOrigin.automationRunId} (${automationOrigin.triggerSource})`
    : run
      ? "No linked automation run found for this recommendation run."
      : "Run origin is loading.";

  const selectedSiteDisplayName = useMemo(() => {
    if (!run) {
      return null;
    }
    const match = context.sites.find((site) => site.id === run.site_id);
    return match?.display_name || null;
  }, [context.sites, run]);

  const recommendationRunNarrativeHistoryHref = useMemo(() => {
    if (!recommendationRunId) {
      return "/recommendations";
    }
    const siteId = run?.site_id || resolvedSiteId || requestedSiteId;
    return buildNarrativeHistoryHref(recommendationRunId, siteId || "", queueContextParams);
  }, [queueContextParams, recommendationRunId, requestedSiteId, resolvedSiteId, run?.site_id]);

  const latestNarrativeDetailHref = useMemo(() => {
    if (!latestNarrative || !recommendationRunId) {
      return null;
    }
    const siteId = run?.site_id || resolvedSiteId || requestedSiteId;
    return buildNarrativeDetailHref(
      recommendationRunId,
      latestNarrative.id,
      siteId || "",
      queueContextParams,
    );
  }, [
    latestNarrative,
    queueContextParams,
    recommendationRunId,
    requestedSiteId,
    resolvedSiteId,
    run?.site_id,
  ]);

  const recommendations = useMemo(() => {
    const items = report?.recommendations.items || [];
    return [...items]
      .sort((left, right) => {
        if (right.priority_score !== left.priority_score) {
          return right.priority_score - left.priority_score;
        }
        return right.created_at.localeCompare(left.created_at);
      })
      .slice(0, RECOMMENDATION_PREVIEW_LIMIT);
  }, [report?.recommendations.items]);
  const strongestRecommendationEvidencePreview = useMemo(() => {
    const topRecommendation = recommendations[0];
    if (!topRecommendation) {
      return "No recommendation evidence preview is available for this run yet.";
    }
    return deriveRecommendationEvidencePreview(topRecommendation);
  }, [recommendations]);
  const strongestRecommendationEvidenceTrust = useMemo(() => {
    const topRecommendation = recommendations[0];
    if (!topRecommendation) {
      return "Support cue: no evidence signal available";
    }
    return deriveRecommendationEvidenceTrustCue(topRecommendation);
  }, [recommendations]);
  const strongestRecommendationChoiceCue = useMemo(() => {
    const topRecommendation = recommendations[0];
    if (!topRecommendation) {
      return "No immediate recommendation choice is available.";
    }
    return deriveRecommendationChoiceCue(topRecommendation, topRecommendation.id);
  }, [recommendations]);
  const strongestRecommendationEffortCue = useMemo(() => {
    const topRecommendation = recommendations[0];
    if (!topRecommendation) {
      return "Effort signal unavailable.";
    }
    return deriveRecommendationEffortCue(topRecommendation);
  }, [recommendations]);
  const strongestRecommendationLifecycleStage = useMemo(() => {
    const topRecommendation = recommendations[0];
    if (!topRecommendation) {
      return "No lifecycle stage is available for this run yet.";
    }
    return deriveRecommendationLifecycleSupport(topRecommendation).stage;
  }, [recommendations]);
  const strongestRecommendationRevisitTiming = useMemo(() => {
    const topRecommendation = recommendations[0];
    if (!topRecommendation) {
      return "No revisit timing is available for this run yet.";
    }
    return deriveRecommendationLifecycleSupport(topRecommendation).revisit;
  }, [recommendations]);
  const strongestRecommendationFreshnessPosture = useMemo(() => {
    const topRecommendation = recommendations[0];
    if (!topRecommendation) {
      return "No freshness posture is available for this run yet.";
    }
    return deriveRecommendationFreshnessSupport(topRecommendation).freshness;
  }, [recommendations]);
  const strongestRecommendationRefreshCheck = useMemo(() => {
    const topRecommendation = recommendations[0];
    if (!topRecommendation) {
      return "No refresh check is available for this run yet.";
    }
    return deriveRecommendationFreshnessSupport(topRecommendation).refreshCheck;
  }, [recommendations]);

  const recommendationsByStatus = useMemo(
    () => toSortedCountEntries(report?.recommendations.by_status),
    [report?.recommendations.by_status],
  );
  const recommendationsByCategory = useMemo(
    () => toSortedCountEntries(report?.rollups.by_category),
    [report?.rollups.by_category],
  );
  const recommendationsBySeverity = useMemo(
    () => toSortedCountEntries(report?.rollups.by_severity),
    [report?.rollups.by_severity],
  );
  const recommendationsByEffort = useMemo(
    () => toSortedCountEntries(report?.rollups.by_effort_bucket),
    [report?.rollups.by_effort_bucket],
  );

  const runStatus = (run?.status || "").trim().toLowerCase();
  const runCompleted = runStatus === "completed";
  const runFailed = runStatus === "failed";
  const runActionState = useMemo(
    () =>
      deriveRecommendationRunOperatorActionState({
        runStatus: run?.status || null,
        producedRecommendationCount: report?.recommendations.total || 0,
        automationLinkedOutput: Boolean(automationOrigin),
      }),
    [automationOrigin, report?.recommendations.total, run?.status],
  );

  const comparisonRun = comparisonReport?.run || null;

  const comparisonRunHref = useMemo(() => {
    if (!run?.comparison_run_id) {
      return null;
    }
    const query = new URLSearchParams();
    const siteId = run.site_id;
    if (siteId) {
      query.set("site_id", siteId);
    }
    if (comparisonRun?.competitor_set_id) {
      query.set("set_id", comparisonRun.competitor_set_id);
    }
    const queryText = query.toString();
    return queryText
      ? `/competitors/comparison-runs/${run.comparison_run_id}?${queryText}`
      : `/competitors/comparison-runs/${run.comparison_run_id}`;
  }, [comparisonRun?.competitor_set_id, run?.comparison_run_id, run?.site_id]);

  const competitorSetHref = useMemo(() => {
    if (!comparisonRun) {
      return null;
    }
    const query = new URLSearchParams();
    query.set("site_id", comparisonRun.site_id);
    return `/competitors/${comparisonRun.competitor_set_id}?${query.toString()}`;
  }, [comparisonRun]);

  const snapshotRunHref = useMemo(() => {
    if (!comparisonRun) {
      return null;
    }
    const query = new URLSearchParams();
    query.set("site_id", comparisonRun.site_id);
    query.set("set_id", comparisonRun.competitor_set_id);
    return `/competitors/snapshot-runs/${comparisonRun.snapshot_run_id}?${query.toString()}`;
  }, [comparisonRun]);

  const workflowContextLinks = useMemo(() => {
    const links: Array<{ href: string; label: string }> = [
      { href: backToRecommendationsHref, label: "Recommendation Queue" },
      { href: recommendationRunNarrativeHistoryHref, label: "Narrative History" },
      { href: "/audits", label: "Audit Runs" },
      { href: run ? `/competitors?site_id=${encodeURIComponent(run.site_id)}` : "/competitors", label: "Competitor Sets" },
    ];
    if (run?.audit_run_id) {
      links.push({ href: `/audits/${run.audit_run_id}`, label: "Linked Audit Run" });
    }
    if (comparisonRunHref) {
      links.push({ href: comparisonRunHref, label: "Linked Comparison Run" });
    }
    if (automationOrigin && run?.site_id) {
      links.push({
        href: `/automation?site_id=${encodeURIComponent(run.site_id)}`,
        label: "Linked Automation Run",
      });
    }
    if (latestNarrativeDetailHref) {
      links.push({ href: latestNarrativeDetailHref, label: "Latest Narrative Detail" });
    }
    return links;
  }, [
    backToRecommendationsHref,
    automationOrigin,
    comparisonRunHref,
    latestNarrativeDetailHref,
    recommendationRunNarrativeHistoryHref,
    run,
  ]);

  const workflowNextStep = useMemo(() => {
    if (latestNarrativeDetailHref) {
      return {
        href: latestNarrativeDetailHref,
        label: "Review narrative detail",
        note: "Confirm reasoning before applying recommendation actions.",
      };
    }
    return {
      href: recommendationRunNarrativeHistoryHref,
      label: "Open narrative history",
      note: "Compare versions and identify the strongest narrative guidance.",
    };
  }, [latestNarrativeDetailHref, recommendationRunNarrativeHistoryHref]);

  const detailFocusTakeaway = useMemo(() => {
    if (!run) {
      return "Run context is still loading.";
    }
    if (runCompleted) {
      return `Run completed with ${run.total_recommendations} recommendation${run.total_recommendations === 1 ? "" : "s"}.`;
    }
    if (runFailed) {
      return "Run failed before completion; treat recommendation and narrative context as partial until rerun.";
    }
    return `Run is currently "${run.status}" and recommendation output may still change.`;
  }, [run, runCompleted, runFailed]);

  const detailFocusNextStep = useMemo(() => {
    if (latestNarrativeDetailHref) {
      return {
        href: latestNarrativeDetailHref,
        label: "Review latest narrative detail",
        note: "Validate reasoning before prioritizing recommendation actions.",
      };
    }
    return {
      href: recommendationRunNarrativeHistoryHref,
      label: "Open narrative history",
      note: "Narrative versions provide run-level reasoning continuity.",
    };
  }, [latestNarrativeDetailHref, recommendationRunNarrativeHistoryHref]);
  const detailFocusFacts = useMemo<DetailFocusFact[]>(() => {
    if (!run) {
      return [];
    }

    const producedCount = report?.recommendations.total || 0;
    const hasActionableOutput = runCompleted && producedCount > 0;
    const runStatusLabel = runCompleted
      ? "Applied / completed"
      : runFailed
        ? "Needs review / pending"
        : "Needs review / pending";
    const whatChangedLabel = runCompleted
      ? producedCount > 0
        ? `Run produced ${producedCount} recommendation${producedCount === 1 ? "" : "s"} for operator review.`
        : "Run completed with no generated recommendations."
      : runFailed
        ? "Run stopped before recommendation output completed."
        : "Recommendation output is still processing.";
    const manualFollowUpLabel = runCompleted
      ? producedCount > 0
        ? "Yes. Review and apply high-priority recommendations."
        : "No immediate apply action is required from this run."
      : runFailed
        ? "Yes. Resolve run issues and retry."
        : "Not yet. Wait for run completion before applying actions.";
    const expectedVisibilityLabel = runCompleted
      ? "Run output is visible now; applied impact appears after the next analysis refresh."
      : runFailed
        ? "No new recommendation visibility changes until a successful rerun."
        : "Visibility updates when this run reaches completion.";
    const whyThisMattersLabel = hasActionableOutput
      ? "Run produced actionable recommendations that should be reviewed now."
      : runFailed
        ? "Run requires follow-up before recommendation output can be trusted."
        : runCompleted
          ? "Run completed without actionable output."
          : "Run is still processing and may change.";
    const canActNowLabel = hasActionableOutput
      ? "Yes. Review recommendations and start with the highest-priority items."
      : runFailed
        ? "No. Resolve run issues before taking recommendation actions."
        : runCompleted
          ? "No immediate recommendation action is required."
          : "Not yet. Wait for run completion.";
    const blockingStateLabel = hasActionableOutput
      ? "No blocker detected."
      : runFailed
        ? "Blocked by failed run state."
        : runCompleted
          ? "No active blocker."
          : "Blocked until run processing completes.";
    const sourceContextLabel = latestNarrative
      ? `Narrative v${latestNarrative.version} (${latestNarrative.status})`
      : "Narrative context not generated yet";

    return [
      {
        label: "Action state",
        value: runActionState.label,
        tone: runActionState.summaryTone,
      },
      {
        label: "Next step cue",
        value: runActionState.nextStep,
        tone: runActionState.summaryTone,
      },
      {
        label: "Why this matters now",
        value: whyThisMattersLabel,
        tone: hasActionableOutput ? "warning" : "neutral",
      },
      {
        label: "Can I act now",
        value: canActNowLabel,
        tone: hasActionableOutput ? "success" : "neutral",
      },
      {
        label: "Lifecycle stage",
        value: strongestRecommendationLifecycleStage,
        tone: hasActionableOutput ? "warning" : runCompleted ? "success" : "neutral",
      },
      {
        label: "Freshness posture",
        value: strongestRecommendationFreshnessPosture,
        tone: hasActionableOutput ? "success" : runCompleted ? "warning" : "neutral",
      },
      {
        label: "Blocking state",
        value: blockingStateLabel,
        tone: hasActionableOutput ? "neutral" : "warning",
      },
      {
        label: "Revisit timing",
        value: strongestRecommendationRevisitTiming,
        tone: runCompleted ? "warning" : "neutral",
      },
      {
        label: "Refresh check",
        value: strongestRecommendationRefreshCheck,
        tone: runCompleted ? "warning" : "neutral",
      },
      {
        label: "After action",
        value: expectedVisibilityLabel,
        tone: runCompleted ? "warning" : "neutral",
      },
      {
        label: "Evidence preview",
        value: strongestRecommendationEvidencePreview,
        tone: "neutral",
      },
      {
        label: "Evidence trust",
        value: strongestRecommendationEvidenceTrust,
        tone: "neutral",
      },
      {
        label: "Choice support",
        value: strongestRecommendationChoiceCue,
        tone: hasActionableOutput ? "warning" : "neutral",
      },
      {
        label: "Effort signal",
        value: strongestRecommendationEffortCue,
        tone: "neutral",
      },
      {
        label: "Current status",
        value: runStatusLabel,
        tone: runCompleted ? "success" : "warning",
      },
      {
        label: "What changed",
        value: whatChangedLabel,
        tone: runCompleted ? "success" : "neutral",
      },
      {
        label: "Manual follow-up",
        value: manualFollowUpLabel,
        tone: runCompleted && producedCount === 0 ? "neutral" : "warning",
      },
      {
        label: "Source context",
        value: sourceContextLabel,
        tone: "neutral",
      },
      {
        label: "Automation origin",
        value: runOriginDetail,
        tone: automationOrigin ? "success" : "neutral",
      },
    ];
  }, [
    automationOrigin,
    latestNarrative,
    report?.recommendations.total,
    run,
    runCompleted,
    runFailed,
    runActionState.label,
    runActionState.nextStep,
    runActionState.summaryTone,
    strongestRecommendationChoiceCue,
    strongestRecommendationEvidencePreview,
    strongestRecommendationEffortCue,
    strongestRecommendationEvidenceTrust,
    strongestRecommendationLifecycleStage,
    strongestRecommendationFreshnessPosture,
    strongestRecommendationRefreshCheck,
    strongestRecommendationRevisitTiming,
    runOriginDetail,
  ]);

  useEffect(() => {
    if (context.loading || context.error || !recommendationRunId) {
      setReport(null);
      setLatestNarrative(null);
      setComparisonReport(null);
      setAutomationOrigin(null);
      setResolvedSiteId(null);
      setLoading(false);
      setError(null);
      setRelatedError(null);
      setNotFound(false);
      return;
    }

    if (candidateSiteIds.length === 0) {
      setReport(null);
      setLatestNarrative(null);
      setComparisonReport(null);
      setAutomationOrigin(null);
      setResolvedSiteId(null);
      setLoading(false);
      setError("No site context is available to resolve this recommendation run.");
      setRelatedError(null);
      setNotFound(false);
      return;
    }

    let cancelled = false;

    async function loadDetail() {
      setLoading(true);
      setError(null);
      setRelatedError(null);
      setNotFound(false);
      setReport(null);
      setLatestNarrative(null);
      setComparisonReport(null);
      setAutomationOrigin(null);
      setResolvedSiteId(null);

      try {
        let resolvedReport: RecommendationRunReport | null = null;
        let resolvedSite: string | null = null;

        for (const siteId of candidateSiteIds) {
          try {
            const result = await fetchRecommendationRunReport(
              context.token,
              context.businessId,
              siteId,
              recommendationRunId,
            );
            resolvedReport = result;
            resolvedSite = siteId;
            break;
          } catch (innerError) {
            if (isNotFoundError(innerError)) {
              continue;
            }
            throw innerError;
          }
        }

        if (!resolvedReport || !resolvedSite) {
          if (!cancelled) {
            setNotFound(true);
          }
          return;
        }

        if (cancelled) {
          return;
        }

        setReport(resolvedReport);
        setResolvedSiteId(resolvedSite);

        const relatedErrors: unknown[] = [];

        const [narrativeResult, comparisonResult, automationRunsResult] = await Promise.allSettled([
          fetchLatestRecommendationRunNarrative(
            context.token,
            context.businessId,
            resolvedSite,
            recommendationRunId,
          ),
          resolvedReport.recommendation_run.comparison_run_id
            ? fetchCompetitorComparisonReport(
                context.token,
                context.businessId,
                resolvedReport.recommendation_run.comparison_run_id,
              )
            : Promise.resolve(null),
          fetchAutomationRuns(context.token, context.businessId, resolvedSite),
        ]);

        if (cancelled) {
          return;
        }

        if (narrativeResult.status === "fulfilled") {
          setLatestNarrative(narrativeResult.value);
        } else if (!isNotFoundError(narrativeResult.reason)) {
          relatedErrors.push(narrativeResult.reason);
        }

        if (comparisonResult.status === "fulfilled") {
          if (comparisonResult.value) {
            setComparisonReport(comparisonResult.value);
          }
        } else if (!isNotFoundError(comparisonResult.reason)) {
          relatedErrors.push(comparisonResult.reason);
        }

        if (automationRunsResult.status === "fulfilled") {
          setAutomationOrigin(
            deriveRecommendationRunAutomationOrigin(automationRunsResult.value.items, recommendationRunId),
          );
        } else {
          setAutomationOrigin(null);
        }

        if (relatedErrors.length > 0) {
          setRelatedError(safeRecommendationRunRelatedErrorMessage(relatedErrors[0]));
        }
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (isNotFoundError(loadError)) {
          setNotFound(true);
          return;
        }
        setError(safeRecommendationRunDetailErrorMessage(loadError));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [
    candidateSiteIds,
    context.businessId,
    context.error,
    context.loading,
    context.token,
    recommendationRunId,
  ]);

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Run Detail"
            subtitle="Loading recommendation run detail for the selected business context."
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
            title="Recommendation Run Detail"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (!recommendationRunId) {
    return (
      <PageContainer>
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Run Detail"
            subtitle="Recommendation run identifier is missing."
            headingLevel={1}
            variant="support"
          />
          <p><Link href={backToRecommendationsHref}>Back to Recommendations</Link></p>
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <div className="role-dashboard-landing">
        <SectionCard
          variant="primary"
          className="role-dashboard-hero"
          data-testid="recommendation-run-detail-hero"
        >
          <SectionHeader
            title="Recommendation Run Detail"
            subtitle="Inspect recommendation reasoning lineage, generated narrative context, and run-level output health."
            headingLevel={1}
            variant="hero"
            meta={(
              <span className="hint muted">
                Recommendation run: <code>{recommendationRunId}</code>
              </span>
            )}
            actions={<Link href={backToRecommendationsHref}>Back to Recommendations</Link>}
          />
          <div
            className="workspace-summary-strip role-summary-strip"
            data-testid="recommendation-run-detail-summary-strip"
          >
            <SummaryStatCard
              label="Run status"
              value={run?.status || "Loading"}
              detail={
                runCompleted
                  ? "Completed and stable"
                  : runFailed
                    ? "Failed before completion"
                    : "Pending completion"
              }
              tone={runCompleted ? "success" : runFailed ? "danger" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Run origin"
              value={runOriginLabel}
              detail={runOriginDetail}
              tone={automationOrigin ? "success" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Operator action state"
              value={runActionState.label}
              detail={runActionState.nextStep}
              tone={runActionState.summaryTone}
              variant="elevated"
            />
            <SummaryStatCard
              label="Recommendations"
              value={run ? run.total_recommendations : "-"}
              detail={report ? `${report.recommendations.total} recommendations loaded` : "Run report pending"}
              tone={run && run.total_recommendations > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Narrative context"
              value={latestNarrative ? `v${latestNarrative.version}` : "Not generated"}
              detail={latestNarrative ? latestNarrative.status : "No narrative available yet"}
              tone={latestNarrative ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Comparison lineage"
              value={run?.comparison_run_id ? "Linked" : "Not linked"}
              detail={run?.comparison_run_id ? "Comparison run present" : "No comparison run attached"}
              tone={run?.comparison_run_id ? "neutral" : "warning"}
              variant="elevated"
            />
          </div>
          {resolvedSiteId ? (
            <p className="hint muted">
              Resolved site: <code>{resolvedSiteId}</code>
            </p>
          ) : null}
          {loading ? <p className="hint muted">Loading recommendation run detail...</p> : null}
          {!loading && notFound ? (
            <p className="hint warning">Recommendation run not found or not accessible in your tenant scope.</p>
          ) : null}
          {!loading && error ? <p className="hint error">{error}</p> : null}
        </SectionCard>
      </div>

      {!loading && !notFound && !error && run ? (
        <WorkflowContextPanel
          data-testid="recommendation-run-workflow-context"
          lineage="Recommendations → Recommendation Run → Narrative history/detail → Apply decisions"
          links={workflowContextLinks}
          nextStep={workflowNextStep}
        />
      ) : null}

      {!loading && !notFound && !error && run ? (
        <DetailFocusPanel
          data-testid="recommendation-run-detail-focus"
          title="Run outcome snapshot"
          takeaway={detailFocusTakeaway}
          nextStep={detailFocusNextStep}
          facts={detailFocusFacts}
          detailHint="Run metrics, lineage, narrative context, and produced recommendations appear in the sections below."
        />
      ) : null}

      {!loading && !notFound && !error && run ? (
        <>
          {relatedError ? (
            <SectionCard variant="support" className="role-surface-support">
              <p className="hint warning">{relatedError}</p>
            </SectionCard>
          ) : null}

          <SectionCard variant="summary" className="role-surface-support">
            <h2>Run Context</h2>
            <p>
              Business ID: <code>{run.business_id}</code>
            </p>
            <p>
              Site ID: <code>{run.site_id}</code>
              {selectedSiteDisplayName ? <> ({selectedSiteDisplayName})</> : null}
            </p>
            <p>Status: {run.status}</p>
            <p>Created By: {run.created_by_principal_id || "-"}</p>
            <p>Created: {formatDateTime(run.created_at)}</p>
            <p>Started: {formatDateTime(run.started_at)}</p>
            <p>Completed: {formatDateTime(run.completed_at)}</p>
            <p>Updated: {formatDateTime(run.updated_at)}</p>
            <p>Duration (ms): {run.duration_ms ?? "-"}</p>
            <p>Error Summary: {run.error_summary || "-"}</p>
          </SectionCard>

          <SectionCard variant="summary" className="role-surface-support">
            <h2>Recommendation Metrics</h2>
            <div className="table-container table-container-compact">
              <table className="table">
                <tbody>
                  <tr>
                    <th>Total Recommendations</th>
                    <td>{run.total_recommendations}</td>
                  </tr>
                  <tr>
                    <th>Critical Recommendations</th>
                    <td>{run.critical_recommendations}</td>
                  </tr>
                  <tr>
                    <th>Warning Recommendations</th>
                    <td>{run.warning_recommendations}</td>
                  </tr>
                  <tr>
                    <th>Info Recommendations</th>
                    <td>{run.info_recommendations}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="metrics-grid">
              <div className="panel stack panel-compact">
                <h3>By Category</h3>
                {recommendationsByCategory.length === 0 ? (
                  <p className="hint muted">No category rollups are available.</p>
                ) : (
                  <div className="table-container table-container-compact">
                    <table className="table">
                      <tbody>
                        {recommendationsByCategory.map(([key, value]) => (
                          <tr key={`cat-${key}`}>
                            <th>{key}</th>
                            <td>{value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              <div className="panel stack panel-compact">
                <h3>By Severity</h3>
                {recommendationsBySeverity.length === 0 ? (
                  <p className="hint muted">No severity rollups are available.</p>
                ) : (
                  <div className="table-container table-container-compact">
                    <table className="table">
                      <tbody>
                        {recommendationsBySeverity.map(([key, value]) => (
                          <tr key={`sev-${key}`}>
                            <th>{key}</th>
                            <td>{value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              <div className="panel stack panel-compact">
                <h3>By Effort</h3>
                {recommendationsByEffort.length === 0 ? (
                  <p className="hint muted">No effort rollups are available.</p>
                ) : (
                  <div className="table-container table-container-compact">
                    <table className="table">
                      <tbody>
                        {recommendationsByEffort.map(([key, value]) => (
                          <tr key={`effort-${key}`}>
                            <th>{key}</th>
                            <td>{value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              <div className="panel stack panel-compact">
                <h3>By Workflow Status</h3>
                {recommendationsByStatus.length === 0 ? (
                  <p className="hint muted">No status breakdown is available.</p>
                ) : (
                  <div className="table-container table-container-compact">
                    <table className="table">
                      <tbody>
                        {recommendationsByStatus.map(([key, value]) => (
                          <tr key={`status-${key}`}>
                            <th>{key}</th>
                            <td>{value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Lineage</h2>
            <p>
              Audit Run ID:{" "}
              {run.audit_run_id ? (
                <Link href={`/audits/${run.audit_run_id}`}>
                  <code>{run.audit_run_id}</code>
                </Link>
              ) : (
                <code>-</code>
              )}
            </p>
            <p>
              Comparison Run ID:{" "}
              {run.comparison_run_id && comparisonRunHref ? (
                <Link href={comparisonRunHref}>
                  <code>{run.comparison_run_id}</code>
                </Link>
              ) : run.comparison_run_id ? (
                <code>{run.comparison_run_id}</code>
              ) : (
                <code>-</code>
              )}
            </p>
            {comparisonRun && competitorSetHref ? (
              <p>
                Competitor Set: <Link href={competitorSetHref}><code>{comparisonRun.competitor_set_id}</code></Link>
              </p>
            ) : null}
            {comparisonRun && snapshotRunHref ? (
              <p>
                Snapshot Run: <Link href={snapshotRunHref}><code>{comparisonRun.snapshot_run_id}</code></Link>
              </p>
            ) : null}
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Latest Narrative</h2>
            <p>
              <Link href={recommendationRunNarrativeHistoryHref}>View Narrative History</Link>
            </p>
            {!latestNarrative ? (
              <p className="hint muted">No generated narrative is currently available for this recommendation run.</p>
            ) : (
              <>
                <p>
                  Narrative ID: <code>{latestNarrative.id}</code>
                </p>
                <p>
                  Version: {latestNarrative.version} ({latestNarrative.status})
                </p>
                <p>
                  Provider: {latestNarrative.provider_name} / {latestNarrative.model_name}
                </p>
                <p>Prompt Version: {latestNarrative.prompt_version}</p>
                <p>Created: {formatDateTime(latestNarrative.created_at)}</p>
                <p>Updated: {formatDateTime(latestNarrative.updated_at)}</p>
                <p>Error: {latestNarrative.error_message || "-"}</p>
                <p>
                  Top Themes:{" "}
                  {latestNarrative.top_themes_json.length > 0
                    ? latestNarrative.top_themes_json.join(", ")
                    : "-"}
                </p>
                <p>
                  Sections Exposed: {latestNarrative.sections_json ? Object.keys(latestNarrative.sections_json).length : 0}
                </p>
                {latestNarrativeDetailHref ? (
                  <p>
                    <Link href={latestNarrativeDetailHref}>Open Narrative Detail</Link>
                  </p>
                ) : null}
                <div className="panel stack panel-compact">
                  <h3>Narrative Text</h3>
                  <p className="pre-wrap">{latestNarrative.narrative_text || "No narrative text returned."}</p>
                </div>
              </>
            )}
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Produced Recommendations ({report?.recommendations.total || 0})</h2>
            {recommendations.length === 0 ? (
              <p className="hint muted">No recommendations were returned for this recommendation run.</p>
            ) : (
              <>
                <div className="table-container">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Title</th>
                        <th>Choice support</th>
                        <th>Priority</th>
                        <th>Status</th>
                        <th>Category</th>
                        <th>Source</th>
                        <th>Rationale</th>
                        <th>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recommendations.map((item) => {
                        const lifecycleSupport = deriveRecommendationLifecycleSupport(item);
                        const freshnessSupport = deriveRecommendationFreshnessSupport(item);
                        return (
                        <tr key={item.id}>
                          <td className="table-cell-wrap">
                            <Link href={buildRecommendationDetailHref(item)}>{item.title}</Link>
                            <br />
                            <span className="hint muted"><code>{item.id}</code></span>
                          </td>
                          <td className="table-cell-wrap">
                            <div className="recommendation-decisiveness">
                              <div className="recommendation-decisiveness-badges">
                                <span className="badge badge-warn">
                                  {deriveRecommendationChoiceCue(item, recommendations[0]?.id || null)}
                                </span>
                                <span className="badge badge-muted">{deriveRecommendationEffortCue(item)}</span>
                                <span className={`badge ${lifecycleSupport.stageTone === "success" ? "badge-success" : lifecycleSupport.stageTone === "warning" ? "badge-warn" : "badge-muted"}`}>
                                  {lifecycleSupport.stage}
                                </span>
                                <span className={`badge ${freshnessSupport.freshnessTone === "success" ? "badge-success" : freshnessSupport.freshnessTone === "warning" ? "badge-warn" : "badge-muted"}`}>
                                  {freshnessSupport.freshness}
                                </span>
                              </div>
                              <p className="hint muted">
                                <span className="text-strong">Blocking:</span> {deriveRecommendationBlockerCue(item)}
                              </p>
                              <p className="hint muted">
                                <span className="text-strong">Freshness:</span> {freshnessSupport.refreshCheck}
                              </p>
                              <p className="hint muted">
                                <span className="text-strong">Revisit:</span> {lifecycleSupport.revisit}
                              </p>
                              <p className="hint muted">
                                <span className="text-strong">After action:</span>{" "}
                                {item.status === "accepted"
                                  ? "Validate visibility after the next refresh."
                                  : item.status === "open" || item.status === "in_progress"
                                    ? "Apply decision now, then verify visibility on refresh."
                                    : "No immediate after-action step is required."}
                              </p>
                            </div>
                          </td>
                          <td>
                            {item.priority_score} ({item.priority_band})
                          </td>
                          <td>{item.status}</td>
                          <td>{item.category}</td>
                          <td>{deriveRecommendationSourceType(item)}</td>
                          <td>{truncateText(item.rationale, RECOMMENDATION_RATIONALE_PREVIEW_LIMIT)}</td>
                          <td>{formatDateTime(item.created_at)}</td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {(report?.recommendations.total || 0) > recommendations.length ? (
                  <p className="hint muted">
                    Showing the top {recommendations.length} recommendations by priority out of {report?.recommendations.total || 0}.
                  </p>
                ) : null}
              </>
            )}
          </SectionCard>
        </>
      ) : null}
    </PageContainer>
  );
}
