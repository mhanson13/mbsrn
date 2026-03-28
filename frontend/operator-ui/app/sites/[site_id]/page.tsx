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
  createRecommendationRun,
  editCompetitorProfileDraft,
  fetchAuditRuns,
  fetchBusinessSettings,
  fetchCompetitorProfileGenerationRunDetail,
  fetchCompetitorProfileGenerationRuns,
  fetchCompetitorProfileGenerationSummary,
  fetchCompetitorDomains,
  fetchCompetitorSets,
  fetchCompetitorSnapshotRuns,
  fetchLatestRecommendationRunNarrative,
  fetchRecommendationWorkspaceSummary,
  previewRecommendationTuningImpact,
  fetchRecommendationRuns,
  fetchRecommendations,
  fetchSiteCompetitorComparisonRuns,
  rejectCompetitorProfileDraft,
  retryCompetitorProfileGenerationRun,
  updateSite,
  updateBusinessSettings,
} from "../../../lib/api/client";
import type {
  AIPromptPreview,
  BusinessSettings,
  CompetitorCandidatePipelineSummary,
  CompetitorContextHealth,
  CompetitorComparisonRun,
  CompetitorProviderAttemptDebug,
  CompetitorProfileDraft,
  CompetitorProfileGenerationRun,
  CompetitorRunOutcomeSummary,
  CompetitorProfileGenerationSummaryResponse,
  RejectedCompetitorCandidateDebug,
  TuningRejectedCompetitorCandidateDebug,
  CompetitorSet,
  CompetitorSnapshotRun,
  RecommendationAnalysisFreshness,
  RecommendationApplyOutcome,
  RecommendationEEATCategory,
  RecommendationEEATGapSummary,
  RecommendationOrderingExplanation,
  RecommendationLifecycleState,
  RecommendationProgressStatus,
  RecommendationPriorityReason,
  RecommendationStartHere,
  RecommendationTargetContext,
  RecommendationTheme,
  RecommendationThemeGroup,
  Recommendation,
  RecommendationListResponse,
  RecommendationNarrative,
  RecommendationRunCreateRequest,
  RecommendationTuningImpactPreview,
  RecommendationRun,
  RecommendationTuningSuggestion,
  RecommendationWorkspaceSummaryResponse,
  SEOAuditRun,
} from "../../../lib/api/types";

const MAX_AUDIT_ROWS = 8;
const MAX_COMPETITOR_ROWS = 8;
const MAX_RECOMMENDATION_ROWS = 8;
const MAX_RECOMMENDATION_RUN_ROWS = 8;
const NARRATIVE_LOOKUP_LIMIT = 5;
const MAX_TIMELINE_EVENTS = 20;
const TIMELINE_INITIAL_VISIBLE_COUNT = 10;
const AI_OPPORTUNITY_INITIAL_COUNT = 3;
const AI_ACTION_HIGHLIGHT_DURATION_MS = 1800;
const MAX_RECENT_TUNING_CHANGES = 8;
const COMPETITOR_PROFILE_DRAFT_CANDIDATE_COUNT = 5;
const COMPETITOR_PROFILE_POLL_INTERVAL_MS = 3000;
const COMPETITOR_PROFILE_POLL_MAX_ATTEMPTS = 30;
const MAX_REJECTED_CANDIDATE_DEBUG_ROWS = 8;
const MAX_TUNING_REJECTED_CANDIDATE_DEBUG_ROWS = 8;
const MAX_PROVIDER_ATTEMPT_DEBUG_ROWS = 2;
const ZIP_PROMPT_SESSION_KEY_PREFIX = "workspace:zip-prompt-dismissed";
const SEARCH_ESCALATION_NOTE =
  "Expanded search was used after the initial pass returned no usable competitors.";
const RELAXED_FILTERING_NOTE =
  "Some competitors were included under relaxed local-service matching rules.";

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

type StartHereAction =
  | {
      kind: "tuning";
      title: string;
      detail: string;
      whyThisFirst: string;
      buttonLabel: string;
      targetId: string;
      recommendationRunId: string;
      narrativeId: string | null;
      suggestion: RecommendationTuningSuggestion;
      hasPreview: boolean;
    }
  | {
      kind: "recommendation";
      title: string;
      detail: string;
      whyThisFirst: string;
      buttonLabel: string;
      targetId: string;
    }
  | {
      kind: "none";
      title: string;
      detail: string;
      whyThisFirst: string;
    };

interface AiOpportunityItem {
  recommendation: Recommendation;
  linkedSuggestions: RecommendationTuningSuggestion[];
  whyThisMatters: string | null;
  isSourceAi: boolean;
}

interface AiOpportunityApplyAttribution {
  recommendation_id: string;
  recommendation_title: string;
}

interface RecentTuningChange {
  id: string;
  applied_at: string;
  setting_label: string;
  previous_value: number;
  next_value: number;
  ai_attribution: AiOpportunityApplyAttribution | null;
}

interface CompetitorRunOutcomeSummaryView {
  proposedCount: number;
  returnedCount: number;
  rejectedCount: number;
  degradedModeUsed: boolean;
  searchBacked: boolean;
  filteringSummary: string | null;
  searchEscalationNote: string | null;
  relaxedFilteringNote: string | null;
  statusNote: string | null;
  lowResultNote: string | null;
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

function formatCompetitorOutcomeStatusLevel(level: CompetitorRunOutcomeSummary["status_level"]): string {
  switch (level) {
    case "recovered":
      return "Recovered";
    case "degraded":
      return "Degraded";
    case "failed":
      return "Failed";
    case "normal":
    default:
      return "Normal";
  }
}

function competitorOutcomeHintClass(level: CompetitorRunOutcomeSummary["status_level"]): string {
  if (level === "failed") {
    return "hint error";
  }
  if (level === "degraded" || level === "recovered") {
    return "hint warning";
  }
  return "hint muted";
}

function formatCompetitorDraftProvenanceLabel(
  classification: CompetitorProfileDraft["provenance_classification"],
): string | null {
  switch (classification) {
    case "places_ai_enriched":
      return "Nearby seed + AI enrichment";
    case "synthetic_fallback":
      return "Synthetic fallback";
    case "ai_only":
      return "AI discovery";
    default:
      return null;
  }
}

function competitorDraftProvenanceHintClass(
  classification: CompetitorProfileDraft["provenance_classification"],
): string {
  if (classification === "synthetic_fallback") {
    return "hint warning";
  }
  return "hint muted";
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

function truncateOptionalText(value: string | null | undefined, limit: number): string | null {
  const normalized = (value || "").trim();
  if (!normalized) {
    return null;
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

function normalizeRejectedCompetitorCandidates(
  value: RejectedCompetitorCandidateDebug[] | null | undefined,
): RejectedCompetitorCandidateDebug[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((candidate) => {
      const domain = (candidate.domain || "").trim().toLowerCase();
      if (!domain) {
        return null;
      }
      const reasons = Array.isArray(candidate.reasons)
        ? candidate.reasons
            .map((reason) => String(reason || "").trim().toLowerCase())
            .filter((reason) => Boolean(reason))
        : [];
      if (reasons.length === 0) {
        return null;
      }
      const uniqueReasons = Array.from(new Set(reasons)).slice(0, 4) as RejectedCompetitorCandidateDebug["reasons"];
      const summary = truncateOptionalText(candidate.summary, 180);
      return {
        domain,
        reasons: uniqueReasons,
        summary,
      };
    })
    .filter((candidate): candidate is RejectedCompetitorCandidateDebug => candidate !== null)
    .slice(0, MAX_REJECTED_CANDIDATE_DEBUG_ROWS);
}

function normalizeTuningRejectedCompetitorCandidates(
  value: TuningRejectedCompetitorCandidateDebug[] | null | undefined,
): TuningRejectedCompetitorCandidateDebug[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((candidate) => {
      const domain = (candidate.domain || "").trim().toLowerCase();
      if (!domain) {
        return null;
      }
      const reasons = Array.isArray(candidate.reasons)
        ? candidate.reasons
            .map((reason) => String(reason || "").trim().toLowerCase())
            .filter((reason) => Boolean(reason))
        : [];
      if (reasons.length === 0) {
        return null;
      }
      const uniqueReasons = Array.from(new Set(reasons)).slice(
        0,
        4,
      ) as TuningRejectedCompetitorCandidateDebug["reasons"];
      const finalScoreRaw = Number(candidate.final_score);
      const finalScore = Number.isFinite(finalScoreRaw) ? Math.max(0, Math.min(100, finalScoreRaw)) : null;
      const summary = truncateOptionalText(candidate.summary, 180);
      return {
        domain,
        reasons: uniqueReasons,
        final_score: finalScore,
        summary,
      };
    })
    .filter((candidate): candidate is TuningRejectedCompetitorCandidateDebug => candidate !== null)
    .slice(0, MAX_TUNING_REJECTED_CANDIDATE_DEBUG_ROWS);
}

function normalizeTuningRejectionReasonCounts(
  value: Record<string, number> | null | undefined,
): Record<string, number> {
  if (!value || typeof value !== "object") {
    return {};
  }
  const normalized: Record<string, number> = {};
  for (const [reason, count] of Object.entries(value)) {
    const key = String(reason || "").trim().toLowerCase();
    if (!key) {
      continue;
    }
    const numericCount = Number(count);
    if (!Number.isFinite(numericCount) || numericCount <= 0) {
      continue;
    }
    normalized[key] = Math.max(0, Math.floor(numericCount));
  }
  return normalized;
}

function normalizeCompetitorCandidatePipelineSummary(
  value: CompetitorCandidatePipelineSummary | null | undefined,
): CompetitorCandidatePipelineSummary | null {
  if (!value) {
    return null;
  }
  const proposed = Math.max(0, Number(value.proposed_candidate_count || 0));
  const rejectedByEligibility = Math.max(0, Number(value.rejected_by_eligibility_count || 0));
  const eligible = Math.max(0, Number(value.eligible_candidate_count || 0));
  const rejectedByTuning = Math.max(0, Number(value.rejected_by_tuning_count || 0));
  const survivedTuning = Math.max(0, Number(value.survived_tuning_count || 0));
  const removedByExistingDomain = Math.max(0, Number(value.removed_by_existing_domain_match_count || 0));
  const removedByDeduplication = Math.max(0, Number(value.removed_by_deduplication_count || 0));
  const removedByFinalLimit = Math.max(0, Number(value.removed_by_final_limit_count || 0));
  const finalCount = Math.max(0, Number(value.final_candidate_count || 0));
  const relaxedFilteringApplied = Boolean(value.relaxed_filtering_applied);
  return {
    proposed_candidate_count: proposed,
    rejected_by_eligibility_count: rejectedByEligibility,
    eligible_candidate_count: eligible,
    rejected_by_tuning_count: rejectedByTuning,
    survived_tuning_count: survivedTuning,
    removed_by_existing_domain_match_count: removedByExistingDomain,
    removed_by_deduplication_count: removedByDeduplication,
    removed_by_final_limit_count: removedByFinalLimit,
    final_candidate_count: finalCount,
    relaxed_filtering_applied: relaxedFilteringApplied,
  };
}

function normalizeCompetitorProviderAttempts(
  value: CompetitorProviderAttemptDebug[] | null | undefined,
): CompetitorProviderAttemptDebug[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((attempt) => {
      const attemptNumber = Math.max(1, Number(attempt.attempt_number || 1));
      const executionMode = truncateOptionalText(attempt.execution_mode, 32);
      const providerCallType = truncateOptionalText(attempt.provider_call_type, 32);
      const requestedCandidateCount = Math.max(1, Number(attempt.requested_candidate_count || 1));
      const outcome = truncateOptionalText(attempt.outcome, 64) || "success";
      const failureKind = truncateOptionalText(attempt.failure_kind, 64);
      const malformedOutputReason = truncateOptionalText(attempt.malformed_output_reason, 64);
      const requestDurationRaw = Number(attempt.request_duration_ms);
      const requestDurationMs = Number.isFinite(requestDurationRaw) ? Math.max(0, requestDurationRaw) : null;
      const timeoutRaw = Number(attempt.timeout_seconds);
      const timeoutSeconds = Number.isFinite(timeoutRaw) ? Math.max(1, timeoutRaw) : null;
      const endpointPath = truncateOptionalText(attempt.endpoint_path, 64);
      const promptSizeRisk = truncateOptionalText(attempt.prompt_size_risk, 32);
      const promptTotalCharsRaw = Number(attempt.prompt_total_chars);
      const promptTotalChars = Number.isFinite(promptTotalCharsRaw) ? Math.max(0, promptTotalCharsRaw) : null;
      const contextJsonCharsRaw = Number(attempt.context_json_chars);
      const contextJsonChars = Number.isFinite(contextJsonCharsRaw) ? Math.max(0, contextJsonCharsRaw) : null;
      const userPromptCharsRaw = Number(attempt.user_prompt_chars);
      const userPromptChars = Number.isFinite(userPromptCharsRaw) ? Math.max(0, userPromptCharsRaw) : null;
      const webSearchEnabled =
        typeof attempt.web_search_enabled === "boolean" ? attempt.web_search_enabled : null;
      const searchEscalationTriggered = Boolean(attempt.search_escalation_triggered);
      const escalationReason = truncateOptionalText(attempt.escalation_reason, 64);
      return {
        attempt_number: attemptNumber,
        execution_mode: executionMode,
        provider_call_type: providerCallType,
        degraded_mode: Boolean(attempt.degraded_mode),
        reduced_context_mode: Boolean(attempt.reduced_context_mode),
        requested_candidate_count: requestedCandidateCount,
        outcome,
        failure_kind: failureKind,
        malformed_output_reason: malformedOutputReason,
        request_duration_ms: requestDurationMs,
        timeout_seconds: timeoutSeconds,
        web_search_enabled: webSearchEnabled,
        prompt_size_risk: promptSizeRisk,
        prompt_total_chars: promptTotalChars,
        context_json_chars: contextJsonChars,
        user_prompt_chars: userPromptChars,
        endpoint_path: endpointPath,
        search_escalation_triggered: searchEscalationTriggered,
        escalation_reason: escalationReason,
      };
    })
    .sort((left, right) => left.attempt_number - right.attempt_number)
    .slice(0, MAX_PROVIDER_ATTEMPT_DEBUG_ROWS);
}

function formatProviderAttemptOutcome(
  outcome: string | null | undefined,
  failureKind: string | null | undefined,
): string {
  const normalizedOutcome = (outcome || "").trim().toLowerCase();
  if (normalizedOutcome === "success") {
    return "Success";
  }
  const normalizedFailureKind = (failureKind || "").trim().toLowerCase();
  if (normalizedFailureKind) {
    return formatFailureCategory(normalizedFailureKind);
  }
  if (normalizedOutcome) {
    return formatFailureCategory(normalizedOutcome);
  }
  return "Unknown";
}

function formatTuningSettingLabel(setting: RecommendationTuningSuggestion["setting"]): string {
  switch (setting) {
    case "competitor_candidate_min_relevance_score":
      return "Minimum relevance score";
    case "competitor_candidate_big_box_penalty":
      return "Big-box mismatch penalty";
    case "competitor_candidate_directory_penalty":
      return "Directory penalty";
    case "competitor_candidate_local_alignment_bonus":
      return "Local alignment bonus";
    default:
      return setting;
  }
}

function formatSignedDelta(value: number): string {
  if (value > 0) {
    return `+${value}`;
  }
  return String(value);
}

function sanitizeDomId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-");
}

function normalizePrimaryBusinessZipInput(value: string): string {
  return value.replace(/\D/g, "").slice(0, 5);
}

function isValidPrimaryBusinessZip(value: string): boolean {
  return /^\d{5}$/.test(value);
}

function zipPromptSessionKey(siteId: string): string {
  return `${ZIP_PROMPT_SESSION_KEY_PREFIX}:${siteId}`;
}

function recommendationImpactLabel(
  item: Recommendation,
  index: number,
): "HIGH IMPACT" | "QUICK WIN" | "NEEDS REVIEW" | null {
  if (index === 0) {
    return "HIGH IMPACT";
  }
  if (index === 1) {
    if (item.effort_bucket === "small" && item.status === "open") {
      return "QUICK WIN";
    }
    if (!["accepted", "dismissed", "resolved"].includes(item.status)) {
      return "NEEDS REVIEW";
    }
  }
  return null;
}

function recommendationImpactBadgeClass(
  label: ReturnType<typeof recommendationImpactLabel>,
): string {
  switch (label) {
    case "HIGH IMPACT":
      return "badge badge-error";
    case "QUICK WIN":
      return "badge badge-success";
    case "NEEDS REVIEW":
      return "badge badge-warn";
    default:
      return "badge badge-muted";
  }
}

const EEAT_CATEGORY_ORDER: RecommendationEEATCategory[] = [
  "experience",
  "expertise",
  "authoritativeness",
  "trustworthiness",
];

function formatEEATCategory(category: RecommendationEEATCategory): string {
  switch (category) {
    case "experience":
      return "Experience";
    case "expertise":
      return "Expertise";
    case "authoritativeness":
      return "Authoritativeness";
    case "trustworthiness":
      return "Trustworthiness";
    default:
      return category;
  }
}

function normalizeEEATCategories(
  categories: RecommendationEEATCategory[] | null | undefined,
  limit = 4,
): RecommendationEEATCategory[] {
  if (!Array.isArray(categories) || limit <= 0) {
    return [];
  }
  const seen = new Set<string>();
  const normalized: RecommendationEEATCategory[] = [];
  for (const category of EEAT_CATEGORY_ORDER) {
    if (!categories.includes(category)) {
      continue;
    }
    if (seen.has(category)) {
      continue;
    }
    seen.add(category);
    normalized.push(category);
    if (normalized.length >= limit) {
      break;
    }
  }
  return normalized;
}

interface RecommendationEEATGapSummaryView {
  categories: RecommendationEEATCategory[];
  supportingSignals: string[];
  message: string;
}

function normalizeRecommendationEEATGapSummary(
  value: RecommendationEEATGapSummary | null | undefined,
): RecommendationEEATGapSummaryView | null {
  if (!value) {
    return null;
  }
  const categories = normalizeEEATCategories(value.top_gap_categories, 4);
  const supportingSignals = normalizeBoundedStringList(value.supporting_signals, 6, 120);
  const message = truncateOptionalText(value.message, 260);
  if (!message || categories.length === 0) {
    return null;
  }
  return {
    categories,
    supportingSignals,
    message,
  };
}

const PRIORITY_REASON_ORDER: RecommendationPriorityReason[] = [
  "competitor_gap",
  "trust_gap",
  "authority_gap",
  "experience_gap",
  "expertise_gap",
  "high_clarity_action",
  "pending_refresh_context",
  "general",
];

function formatPriorityReason(reason: RecommendationPriorityReason): string {
  switch (reason) {
    case "competitor_gap":
      return "Competitor gap";
    case "trust_gap":
      return "Trust gap";
    case "authority_gap":
      return "Authority gap";
    case "experience_gap":
      return "Experience gap";
    case "expertise_gap":
      return "Expertise gap";
    case "high_clarity_action":
      return "Clear next step";
    case "pending_refresh_context":
      return "Pending refresh context";
    case "general":
      return "General";
    default:
      return reason;
  }
}

function normalizeRecommendationPriorityReasons(
  value: RecommendationPriorityReason[] | null | undefined,
  limit = 4,
): RecommendationPriorityReason[] {
  if (!Array.isArray(value) || limit <= 0) {
    return [];
  }
  const seen = new Set<string>();
  const normalized: RecommendationPriorityReason[] = [];
  for (const reason of PRIORITY_REASON_ORDER) {
    if (!value.includes(reason)) {
      continue;
    }
    if (seen.has(reason)) {
      continue;
    }
    seen.add(reason);
    normalized.push(reason);
    if (normalized.length >= limit) {
      break;
    }
  }
  return normalized;
}

interface RecommendationOrderingExplanationView {
  message: string;
  contextReasons: RecommendationPriorityReason[];
}

function normalizeRecommendationOrderingExplanation(
  value: RecommendationOrderingExplanation | null | undefined,
): RecommendationOrderingExplanationView | null {
  if (!value) {
    return null;
  }
  const message = truncateOptionalText(value.message, 320);
  if (!message) {
    return null;
  }
  const contextReasons = normalizeRecommendationPriorityReasons(value.context_reasons, 4);
  return {
    message,
    contextReasons,
  };
}

function formatRecommendationThemeLabel(theme: RecommendationTheme): string {
  switch (theme) {
    case "trust_and_legitimacy":
      return "Trust & legitimacy";
    case "experience_and_proof":
      return "Experience & proof";
    case "authority_and_visibility":
      return "Authority & visibility";
    case "expertise_and_process":
      return "Expertise & process";
    case "general_site_improvement":
      return "General site improvement";
  }
}

function formatRecommendationThemeSummary(theme: RecommendationTheme): string {
  switch (theme) {
    case "trust_and_legitimacy":
      return "Improve visible business trust signals like reviews, verification, and contact legitimacy.";
    case "experience_and_proof":
      return "Show proof of real work with testimonials, project examples, and outcome evidence.";
    case "authority_and_visibility":
      return "Strengthen external credibility through citations, listings, and recognized signals.";
    case "expertise_and_process":
      return "Clarify how you work and what makes your process credible and capable.";
    case "general_site_improvement":
      return "Improve core site clarity and fundamentals that support overall performance.";
  }
}

function formatRecommendationTargetContext(context: RecommendationTargetContext): string {
  switch (context) {
    case "homepage":
      return "Homepage";
    case "service_pages":
      return "Service pages";
    case "contact_about":
      return "Contact/About";
    case "location_pages":
      return "Location pages";
    case "sitewide":
      return "Sitewide";
    case "general":
    default:
      return "General";
  }
}

function formatLocationContextSourceLabel(
  source: "explicit_location" | "service_area" | "zip_capture" | "fallback" | null,
): string | null {
  if (!source) {
    return null;
  }
  switch (source) {
    case "explicit_location":
      return "Explicit location";
    case "service_area":
      return "Service area";
    case "zip_capture":
      return "ZIP provided";
    case "fallback":
      return "Fallback";
  }
}

interface RecommendationThemeSectionView {
  theme: RecommendationTheme;
  label: string;
  items: Recommendation[];
}

function normalizeRecommendationThemeSections(
  recommendations: Recommendation[],
  grouped: RecommendationThemeGroup[] | null | undefined,
): RecommendationThemeSectionView[] {
  if (recommendations.length === 0) {
    return [];
  }

  const byId = new Map<string, Recommendation>();
  recommendations.forEach((recommendation) => {
    byId.set(recommendation.id, recommendation);
  });

  const sections: RecommendationThemeSectionView[] = [];
  const consumed = new Set<string>();
  if (Array.isArray(grouped) && grouped.length > 0) {
    for (const group of grouped) {
      if (!group || !Array.isArray(group.recommendation_ids)) {
        continue;
      }
      const sectionItems: Recommendation[] = [];
      for (const recommendationId of group.recommendation_ids) {
        const item = byId.get(recommendationId);
        if (!item || consumed.has(item.id)) {
          continue;
        }
        consumed.add(item.id);
        sectionItems.push(item);
      }
      if (sectionItems.length === 0) {
        continue;
      }
      sections.push({
        theme: group.theme,
        label: truncateOptionalText(group.label, 80) || formatRecommendationThemeLabel(group.theme),
        items: sectionItems,
      });
    }
  }

  const ungrouped = recommendations.filter((recommendation) => !consumed.has(recommendation.id));
  if (ungrouped.length > 0) {
    sections.push({
      theme: "general_site_improvement",
      label: formatRecommendationThemeLabel("general_site_improvement"),
      items: ungrouped,
    });
  }

  if (sections.length === 0) {
    return [
      {
        theme: "general_site_improvement",
        label: formatRecommendationThemeLabel("general_site_improvement"),
        items: recommendations,
      },
    ];
  }
  return sections;
}

function recommendationHasAiSource(item: Recommendation): boolean {
  const sourceValue = (item as unknown as { source?: unknown }).source;
  return typeof sourceValue === "string" && sourceValue.trim().toLowerCase() === "ai";
}

function recommendationExpectedOutcome(item: Recommendation): string {
  const sourceType = recommendationSourceType(item);
  const normalizedSeverity = item.severity.trim().toLowerCase() || "unknown";
  const normalizedCategory = item.category.trim() || "General";
  let scopeLabel = "site recommendation quality";
  if (sourceType === "audit") {
    scopeLabel = "audit issue coverage";
  } else if (sourceType === "comparison") {
    scopeLabel = "competitive gap coverage";
  } else if (sourceType === "mixed") {
    scopeLabel = "audit and competitive gap coverage";
  }
  return `${normalizedCategory} improvement with ${item.priority_band} priority (${item.priority_score}) and ${item.effort_bucket} effort, likely improving ${scopeLabel} and reducing ${normalizedSeverity} risk.`;
}

function narrativeSummaryText(narrative: RecommendationNarrative | null): string | null {
  if (!narrative) {
    return null;
  }
  const sections = narrative.sections_json;
  if (sections && typeof sections === "object" && !Array.isArray(sections)) {
    const summaryValue = (sections as Record<string, unknown>).summary;
    if (typeof summaryValue === "string" && summaryValue.trim()) {
      return summaryValue.trim();
    }
  }
  const narrativeText = (narrative.narrative_text || "").trim();
  return narrativeText || null;
}

function normalizeBoundedStringList(values: string[] | null | undefined, limit: number, itemLimit: number): string[] {
  if (!Array.isArray(values) || limit <= 0) {
    return [];
  }
  const result: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (typeof value !== "string") {
      continue;
    }
    const normalized = value.replace(/\s+/g, " ").trim();
    if (!normalized) {
      continue;
    }
    const bounded = normalized.length <= itemLimit ? normalized : `${normalized.slice(0, itemLimit - 1)}…`;
    const dedupeKey = bounded.toLowerCase();
    if (seen.has(dedupeKey)) {
      continue;
    }
    result.push(bounded);
    seen.add(dedupeKey);
    if (result.length >= limit) {
      break;
    }
  }
  return result;
}

interface NarrativeActionSummaryView {
  primaryAction: string;
  whyItMatters: string | null;
  firstStep: string | null;
  evidence: string[];
}

function normalizeNarrativeActionSummary(
  narrative: RecommendationNarrative | null,
): NarrativeActionSummaryView | null {
  const rawActionSummary = narrative?.action_summary;
  if (!rawActionSummary) {
    return null;
  }
  const primaryAction = truncateOptionalText(rawActionSummary.primary_action, 180);
  if (!primaryAction) {
    return null;
  }
  const whyItMatters = truncateOptionalText(rawActionSummary.why_it_matters, 220);
  const firstStep = truncateOptionalText(rawActionSummary.first_step, 180);
  const evidence = normalizeBoundedStringList(rawActionSummary.evidence, 4, 120);
  return {
    primaryAction,
    whyItMatters,
    firstStep,
    evidence,
  };
}

interface NarrativeCompetitorInfluenceView {
  summary: string | null;
  topOpportunities: string[];
  competitorNames: string[];
}

function normalizeNarrativeCompetitorInfluence(
  narrative: RecommendationNarrative | null,
): NarrativeCompetitorInfluenceView | null {
  const rawInfluence = narrative?.competitor_influence;
  if (!rawInfluence || !rawInfluence.used) {
    return null;
  }
  const summary = truncateOptionalText(rawInfluence.summary, 220);
  const topOpportunities = normalizeBoundedStringList(rawInfluence.top_opportunities, 3, 100);
  const competitorNames = normalizeBoundedStringList(rawInfluence.competitor_names, 5, 80);
  if (!summary && topOpportunities.length === 0 && competitorNames.length === 0) {
    return null;
  }
  return {
    summary,
    topOpportunities,
    competitorNames,
  };
}

interface NarrativeSignalSummaryView {
  supportLevel: "low" | "medium" | "high";
  evidenceSources: Array<"site" | "competitors" | "references" | "themes">;
  competitorSignalUsed: boolean;
  siteSignalUsed: boolean;
  referenceSignalUsed: boolean;
}

function normalizeNarrativeSignalSummary(
  narrative: RecommendationNarrative | null,
): NarrativeSignalSummaryView | null {
  const rawSignalSummary = narrative?.signal_summary;
  if (!rawSignalSummary) {
    return null;
  }
  const supportLevel =
    rawSignalSummary.support_level === "low" ||
    rawSignalSummary.support_level === "medium" ||
    rawSignalSummary.support_level === "high"
      ? rawSignalSummary.support_level
      : null;
  if (!supportLevel) {
    return null;
  }
  const sourceCandidates = normalizeBoundedStringList(rawSignalSummary.evidence_sources, 4, 32);
  const evidenceSources = sourceCandidates
    .filter(
      (
        value,
      ): value is "site" | "competitors" | "references" | "themes" =>
        value === "site" || value === "competitors" || value === "references" || value === "themes",
    );
  const competitorSignalUsed = Boolean(rawSignalSummary.competitor_signal_used);
  const siteSignalUsed = Boolean(rawSignalSummary.site_signal_used);
  const referenceSignalUsed = Boolean(rawSignalSummary.reference_signal_used);
  if (
    evidenceSources.length === 0 &&
    !competitorSignalUsed &&
    !siteSignalUsed &&
    !referenceSignalUsed
  ) {
    return null;
  }
  return {
    supportLevel,
    evidenceSources,
    competitorSignalUsed,
    siteSignalUsed,
    referenceSignalUsed,
  };
}

interface RecommendationApplyOutcomeView {
  applied: boolean;
  appliedAt: string | null;
  recommendationLabel: string | null;
  expectedChange: string | null;
  reflectedOnNextRun: string | null;
  source: "recommendation" | "manual" | null;
}

function normalizeRecommendationApplyOutcome(
  applyOutcome: RecommendationApplyOutcome | null | undefined,
): RecommendationApplyOutcomeView | null {
  if (!applyOutcome || !applyOutcome.applied) {
    return null;
  }
  const recommendationLabel = truncateOptionalText(applyOutcome.recommendation_label, 180);
  const expectedChange = truncateOptionalText(applyOutcome.expected_change, 240);
  const reflectedOnNextRun = truncateOptionalText(applyOutcome.reflected_on_next_run, 220);
  const appliedAt = truncateOptionalText(applyOutcome.applied_at, 64);
  const source =
    applyOutcome.source === "recommendation" || applyOutcome.source === "manual"
      ? applyOutcome.source
      : null;
  if (!recommendationLabel && !expectedChange && !reflectedOnNextRun && !appliedAt) {
    return null;
  }
  return {
    applied: true,
    appliedAt,
    recommendationLabel,
    expectedChange,
    reflectedOnNextRun,
    source,
  };
}

interface RecommendationAnalysisFreshnessView {
  status: "fresh" | "pending_refresh" | "unknown";
  message: string;
  analysisGeneratedAt: string | null;
  lastApplyAt: string | null;
}

function normalizeRecommendationAnalysisFreshness(
  freshness: RecommendationAnalysisFreshness | null | undefined,
): RecommendationAnalysisFreshnessView | null {
  if (!freshness) {
    return null;
  }
  const status =
    freshness.status === "fresh" || freshness.status === "pending_refresh" || freshness.status === "unknown"
      ? freshness.status
      : null;
  if (!status) {
    return null;
  }
  const message = truncateOptionalText(freshness.message, 220);
  if (!message) {
    return null;
  }
  return {
    status,
    message,
    analysisGeneratedAt: truncateOptionalText(freshness.analysis_generated_at, 64),
    lastApplyAt: truncateOptionalText(freshness.last_apply_at, 64),
  };
}

function analysisFreshnessLabel(status: RecommendationAnalysisFreshnessView["status"]): string {
  switch (status) {
    case "fresh":
      return "Fresh";
    case "pending_refresh":
      return "Pending Refresh";
    case "unknown":
    default:
      return "Unknown";
  }
}

function analysisFreshnessBadgeClass(status: RecommendationAnalysisFreshnessView["status"]): string {
  switch (status) {
    case "fresh":
      return "badge badge-success";
    case "pending_refresh":
      return "badge badge-warn";
    case "unknown":
    default:
      return "badge badge-muted";
  }
}

interface RecommendationProgressView {
  status: RecommendationProgressStatus;
  label: string;
  badgeClass: string;
  summary: string;
}

interface RecommendationLifecycleView {
  state: RecommendationLifecycleState;
  label: string;
  badgeClass: string;
  summary: string;
}

function recommendationProgressLabel(status: RecommendationProgressStatus): string {
  switch (status) {
    case "applied_pending_refresh":
      return "Applied, pending refresh";
    case "reflected_in_latest_analysis":
      return "Reflected in latest analysis";
    case "suggested":
    default:
      return "Suggested";
  }
}

function recommendationProgressBadgeClass(status: RecommendationProgressStatus): string {
  switch (status) {
    case "applied_pending_refresh":
      return "badge badge-warn";
    case "reflected_in_latest_analysis":
      return "badge badge-success";
    case "suggested":
    default:
      return "badge badge-muted";
  }
}

function recommendationProgressDefaultSummary(status: RecommendationProgressStatus): string {
  switch (status) {
    case "applied_pending_refresh":
      return "Applied. Waiting for the next analysis refresh to reflect this change.";
    case "reflected_in_latest_analysis":
      return "Applied and reflected in the latest analysis.";
    case "suggested":
    default:
      return "Suggested action not yet applied.";
  }
}

function normalizeRecommendationProgress(item: Recommendation): RecommendationProgressView {
  const status: RecommendationProgressStatus =
    item.recommendation_progress_status === "applied_pending_refresh"
    || item.recommendation_progress_status === "reflected_in_latest_analysis"
    || item.recommendation_progress_status === "suggested"
      ? item.recommendation_progress_status
      : "suggested";
  const summary = truncateOptionalText(item.recommendation_progress_summary, 220)
    || recommendationProgressDefaultSummary(status);
  return {
    status,
    label: recommendationProgressLabel(status),
    badgeClass: recommendationProgressBadgeClass(status),
    summary,
  };
}

function recommendationLifecycleLabel(state: RecommendationLifecycleState): string {
  switch (state) {
    case "applied_waiting_validation":
      return "Applied, waiting validation";
    case "reflected_still_relevant":
      return "Reflected, still relevant";
    case "likely_resolved":
      return "Likely resolved";
    case "active":
    default:
      return "Active";
  }
}

function recommendationLifecycleBadgeClass(state: RecommendationLifecycleState): string {
  switch (state) {
    case "applied_waiting_validation":
      return "badge badge-warn";
    case "reflected_still_relevant":
      return "badge badge-warn";
    case "likely_resolved":
      return "badge badge-success";
    case "active":
    default:
      return "badge badge-muted";
  }
}

function recommendationLifecycleDefaultSummary(state: RecommendationLifecycleState): string {
  switch (state) {
    case "applied_waiting_validation":
      return "Applied and waiting for refreshed validation.";
    case "reflected_still_relevant":
      return "Reflected in analysis, but still appears relevant.";
    case "likely_resolved":
      return "Likely addressed in the latest analysis.";
    case "active":
    default:
      return "Still an active recommendation.";
  }
}

function normalizeRecommendationLifecycle(item: Recommendation): RecommendationLifecycleView | null {
  if (!item.recommendation_lifecycle_state && !truncateOptionalText(item.recommendation_lifecycle_summary, 220)) {
    return null;
  }
  const state: RecommendationLifecycleState =
    item.recommendation_lifecycle_state === "applied_waiting_validation"
    || item.recommendation_lifecycle_state === "reflected_still_relevant"
    || item.recommendation_lifecycle_state === "likely_resolved"
    || item.recommendation_lifecycle_state === "active"
      ? item.recommendation_lifecycle_state
      : "active";
  const summary = truncateOptionalText(item.recommendation_lifecycle_summary, 220)
    || recommendationLifecycleDefaultSummary(state);
  return {
    state,
    label: recommendationLifecycleLabel(state),
    badgeClass: recommendationLifecycleBadgeClass(state),
    summary,
  };
}

function normalizeRecommendationEvidenceSummary(item: Recommendation): string | null {
  return truncateOptionalText(item.recommendation_evidence_summary, 220);
}

function normalizeRecommendationObservedGapSummary(item: Recommendation): string | null {
  return truncateOptionalText(item.recommendation_observed_gap_summary, 220);
}

function normalizeRecommendationEvidenceTrace(item: Recommendation): string[] {
  return normalizeBoundedStringList(item.recommendation_evidence_trace, 5, 80);
}

function normalizeRecommendationActionClarity(item: Recommendation): string | null {
  return truncateOptionalText(item.recommendation_action_clarity, 220);
}

function normalizeRecommendationExpectedOutcome(item: Recommendation): string | null {
  return truncateOptionalText(item.recommendation_expected_outcome, 220);
}

function normalizeRecommendationTargetContext(item: Recommendation): RecommendationTargetContext | null {
  const value = item.recommendation_target_context;
  if (
    value === "homepage" ||
    value === "service_pages" ||
    value === "contact_about" ||
    value === "location_pages" ||
    value === "sitewide" ||
    value === "general"
  ) {
    return value;
  }
  return null;
}

function normalizeRecommendationTargetPageHints(item: Recommendation): string[] {
  return normalizeBoundedStringList(item.recommendation_target_page_hints, 3, 120);
}

interface CompetitorContextHealthCheckView {
  key: "location_context" | "industry_context" | "service_focus" | "target_customer_context";
  label: string;
  status: "strong" | "weak";
  detail: string;
}

interface CompetitorContextHealthView {
  status: "strong" | "mixed" | "weak";
  checks: CompetitorContextHealthCheckView[];
  message: string;
}

const COMPETITOR_CONTEXT_HEALTH_CHECK_ORDER: CompetitorContextHealthCheckView["key"][] = [
  "location_context",
  "industry_context",
  "service_focus",
  "target_customer_context",
];

function normalizeCompetitorContextHealth(
  value: CompetitorContextHealth | null | undefined,
): CompetitorContextHealthView | null {
  if (!value) {
    return null;
  }
  const status = value.status === "strong" || value.status === "mixed" || value.status === "weak"
    ? value.status
    : null;
  if (!status) {
    return null;
  }
  const message = truncateOptionalText(value.message, 220);
  if (!message) {
    return null;
  }
  const checksRaw = Array.isArray(value.checks) ? value.checks : [];
  const checkMap = new Map<CompetitorContextHealthCheckView["key"], CompetitorContextHealthCheckView>();
  for (const check of checksRaw) {
    const key = check?.key;
    if (
      key !== "location_context" &&
      key !== "industry_context" &&
      key !== "service_focus" &&
      key !== "target_customer_context"
    ) {
      continue;
    }
    const label = truncateOptionalText(check.label, 80);
    const detail = truncateOptionalText(check.detail, 220);
    const checkStatus = check.status === "strong" || check.status === "weak" ? check.status : null;
    if (!label || !detail || !checkStatus) {
      continue;
    }
    checkMap.set(key, {
      key,
      label,
      status: checkStatus,
      detail,
    });
  }
  const checks: CompetitorContextHealthCheckView[] = [];
  for (const key of COMPETITOR_CONTEXT_HEALTH_CHECK_ORDER) {
    const found = checkMap.get(key);
    if (found) {
      checks.push(found);
    }
  }
  return {
    status,
    checks,
    message,
  };
}

function competitorContextHealthLabel(status: CompetitorContextHealthView["status"]): string {
  switch (status) {
    case "strong":
      return "Strong";
    case "mixed":
      return "Mixed";
    case "weak":
    default:
      return "Weak";
  }
}

function competitorContextHealthBadgeClass(status: CompetitorContextHealthView["status"]): string {
  switch (status) {
    case "strong":
      return "badge badge-success";
    case "mixed":
      return "badge badge-warn";
    case "weak":
    default:
      return "badge badge-error";
  }
}

function competitorContextHealthCheckBadgeClass(status: CompetitorContextHealthCheckView["status"]): string {
  return status === "strong" ? "badge badge-success" : "badge badge-warn";
}

type PromptPreviewType = "competitor" | "recommendation";

interface PromptPreviewView {
  promptType: PromptPreviewType;
  systemPrompt: string;
  userPrompt: string;
  model: string | null;
  promptVersion: string | null;
  promptLabel: string | null;
  source: "admin_config" | "env" | "default" | null;
  truncated: boolean;
  promptMetrics: Record<string, number> | null;
}

function normalizePromptPreview(
  preview: AIPromptPreview | null | undefined,
  expectedPromptType: PromptPreviewType,
): PromptPreviewView | null {
  if (!preview || !preview.available) {
    return null;
  }
  if (preview.prompt_type !== expectedPromptType) {
    return null;
  }

  const systemPrompt = preview.system_prompt.replace(/\r\n?/g, "\n").trim();
  const userPrompt = preview.user_prompt.replace(/\r\n?/g, "\n").trim();
  if (!systemPrompt && !userPrompt) {
    return null;
  }

  return {
    promptType: expectedPromptType,
    systemPrompt,
    userPrompt,
    model: truncateOptionalText(preview.model, 128),
    promptVersion: truncateOptionalText(preview.prompt_version, 64),
    promptLabel: truncateOptionalText(preview.prompt_label, 96),
    source:
      preview.source === "admin_config" || preview.source === "env" || preview.source === "default"
        ? preview.source
        : null,
    truncated: Boolean(preview.truncated),
    promptMetrics: normalizePromptMetrics(preview.prompt_metrics),
  };
}

function normalizePromptMetrics(
  rawMetrics: AIPromptPreview["prompt_metrics"],
): Record<string, number> | null {
  if (!rawMetrics || typeof rawMetrics !== "object") {
    return null;
  }
  const normalized: Record<string, number> = {};
  for (const [rawKey, rawValue] of Object.entries(rawMetrics)) {
    const key = truncateOptionalText(rawKey, 48);
    if (!key) {
      continue;
    }
    if (typeof rawValue !== "number" || !Number.isFinite(rawValue)) {
      continue;
    }
    normalized[key] = Math.max(0, Math.trunc(rawValue));
  }
  return Object.keys(normalized).length > 0 ? normalized : null;
}

function promptPreviewTypeLabel(promptType: PromptPreviewType): string {
  if (promptType === "competitor") {
    return "Competitor Analysis";
  }
  return "Recommendation Narrative";
}

function promptPreviewSourceLabel(source: PromptPreviewView["source"]): string {
  switch (source) {
    case "admin_config":
      return "Business admin override";
    case "env":
      return "Deployment fallback";
    case "default":
      return "Built-in default";
    default:
      return "Unknown";
  }
}

function buildPromptPreviewExportText(preview: PromptPreviewView): string {
  const modelLabel = preview.model || "n/a";
  const promptIdentityLabel = preview.promptLabel || "resolved prompt";
  const promptVersionLabel = preview.promptVersion || null;
  const sourceLabel = promptPreviewSourceLabel(preview.source);
  const truncationLine = preview.truncated ? "Truncated: yes" : "Truncated: no";
  const totalChars =
    preview.promptMetrics && typeof preview.promptMetrics.total_prompt_chars === "number"
      ? preview.promptMetrics.total_prompt_chars
      : null;
  const promptSizeLine = typeof totalChars === "number" ? `Prompt size (chars): ${totalChars}` : null;
  const systemPromptBlock = preview.systemPrompt || "(empty)";
  const userPromptBlock = preview.userPrompt || "(empty)";

  return [
    `Prompt Type: ${promptPreviewTypeLabel(preview.promptType)}`,
    `Source: ${sourceLabel}`,
    `Model: ${modelLabel}`,
    `Prompt: ${promptIdentityLabel}`,
    ...(promptVersionLabel ? [`Prompt Version: ${promptVersionLabel}`] : []),
    ...(promptSizeLine ? [promptSizeLine] : []),
    truncationLine,
    "",
    "System Prompt:",
    systemPromptBlock,
    "",
    "User Prompt:",
    userPromptBlock,
  ].join("\n");
}

interface PromptPreviewPanelProps {
  preview: PromptPreviewView;
  copyFeedback: string | null;
  onCopy: () => void;
  onDownload: () => void;
  testId: string;
}

function PromptPreviewPanel({
  preview,
  copyFeedback,
  onCopy,
  onDownload,
  testId,
}: PromptPreviewPanelProps) {
  const promptIdentityLabel = preview.promptLabel || "resolved prompt";
  const promptVersionLabel = preview.promptVersion || null;
  const promptTotalChars =
    preview.promptMetrics && typeof preview.promptMetrics.total_prompt_chars === "number"
      ? preview.promptMetrics.total_prompt_chars
      : null;
  const promptContextChars =
    preview.promptMetrics && typeof preview.promptMetrics.context_json_chars === "number"
      ? preview.promptMetrics.context_json_chars
      : null;

  return (
    <div className="panel panel-compact stack-tight" data-testid={testId}>
      <span className="hint muted">Prompt inspection (debug)</span>
      <span className="hint muted">
        Read-only preview of the current assembled {promptPreviewTypeLabel(preview.promptType).toLowerCase()} prompt.
        This is separate from historical last-run metadata.
      </span>
      <span className="hint muted">
        Source: {promptPreviewSourceLabel(preview.source)} | Model: {preview.model || "n/a"} | Prompt:{" "}
        {promptIdentityLabel}
        {promptVersionLabel ? ` | Prompt Version: ${promptVersionLabel}` : ""}
        {typeof promptTotalChars === "number" ? ` | Size: ${promptTotalChars} chars` : ""}
        {typeof promptContextChars === "number" ? ` | Context: ${promptContextChars} chars` : ""}
        {preview.truncated ? " | Preview is truncated for safety." : ""}
      </span>
      <details>
        <summary className="hint text-strong">View AI prompt</summary>
        <div className="stack-tight">
          <span className="hint muted">System prompt</span>
          <pre className="pre-scroll">{preview.systemPrompt || "(empty)"}</pre>
          <span className="hint muted">User prompt</span>
          <pre className="pre-scroll">{preview.userPrompt || "(empty)"}</pre>
          <div className="form-actions">
            <button type="button" className="button button-secondary button-inline" onClick={onCopy}>
              Copy Prompt
            </button>
            <button type="button" className="button button-tertiary button-inline" onClick={onDownload}>
              Download Prompt (.txt)
            </button>
          </div>
          {copyFeedback ? <span className="hint muted">{copyFeedback}</span> : null}
        </div>
      </details>
    </div>
  );
}

function formatNarrativeSupportLevel(value: "low" | "medium" | "high"): string {
  switch (value) {
    case "low":
      return "Low";
    case "medium":
      return "Medium";
    case "high":
      return "High";
    default:
      return value;
  }
}

function buildTuningPreviewKey(
  recommendationRunId: string,
  suggestion: RecommendationTuningSuggestion,
): string {
  return `${recommendationRunId}:${suggestion.setting}:${suggestion.current_value}:${suggestion.recommended_value}`;
}

function recommendationRowId(recommendationId: string): string {
  return `workspace-recommendation-${sanitizeDomId(recommendationId)}`;
}

function tuningSuggestionCardId(
  recommendationRunId: string,
  suggestion: RecommendationTuningSuggestion,
): string {
  return `workspace-tuning-${sanitizeDomId(buildTuningPreviewKey(recommendationRunId, suggestion))}`;
}

function tuningSettingValueFromBusinessSettings(
  settings: BusinessSettings | null,
  setting: RecommendationTuningSuggestion["setting"],
): number | null {
  if (!settings) {
    return null;
  }
  switch (setting) {
    case "competitor_candidate_min_relevance_score":
      return settings.competitor_candidate_min_relevance_score;
    case "competitor_candidate_big_box_penalty":
      return settings.competitor_candidate_big_box_penalty;
    case "competitor_candidate_directory_penalty":
      return settings.competitor_candidate_directory_penalty;
    case "competitor_candidate_local_alignment_bonus":
      return settings.competitor_candidate_local_alignment_bonus;
    default:
      return null;
  }
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

function competitorProfileTerminalMessage(status: CompetitorProfileGenerationRun["status"]): string | null {
  if (status === "completed") {
    return "Competitor profile generation completed. Results refreshed automatically.";
  }
  if (status === "failed") {
    return "Competitor profile generation failed. Latest run details are shown.";
  }
  return null;
}

function sortCompetitorProfileGenerationRuns(
  runs: CompetitorProfileGenerationRun[],
): CompetitorProfileGenerationRun[] {
  return [...runs].sort((left, right) => {
    const createdAtOrder = right.created_at.localeCompare(left.created_at);
    if (createdAtOrder !== 0) {
      return createdAtOrder;
    }
    return right.id.localeCompare(left.id);
  });
}

function upsertCompetitorProfileGenerationRun(
  runs: CompetitorProfileGenerationRun[],
  run: CompetitorProfileGenerationRun,
): CompetitorProfileGenerationRun[] {
  return sortCompetitorProfileGenerationRuns([run, ...runs.filter((item) => item.id !== run.id)]);
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
  const [recommendationGenerationInFlight, setRecommendationGenerationInFlight] = useState(false);
  const [recommendationGenerationMessage, setRecommendationGenerationMessage] = useState<string | null>(null);
  const [recommendationGenerationError, setRecommendationGenerationError] = useState<string | null>(null);
  const [workspaceRefreshNonce, setWorkspaceRefreshNonce] = useState(0);
  const [latestNarrativesByRunId, setLatestNarrativesByRunId] = useState<Record<string, RecommendationNarrative>>({});
  const [narrativeLookupError, setNarrativeLookupError] = useState<string | null>(null);
  const [latestCompletedRecommendationRun, setLatestCompletedRecommendationRun] = useState<RecommendationRun | null>(null);
  const [latestCompletedRecommendations, setLatestCompletedRecommendations] = useState<Recommendation[]>([]);
  const [latestCompletedRecommendationNarrative, setLatestCompletedRecommendationNarrative] =
    useState<RecommendationNarrative | null>(null);
  const [latestCompletedTuningSuggestions, setLatestCompletedTuningSuggestions] =
    useState<RecommendationTuningSuggestion[]>([]);
  const [latestRecommendationApplyOutcome, setLatestRecommendationApplyOutcome] =
    useState<RecommendationApplyOutcome | null>(null);
  const [latestCompetitorContextHealth, setLatestCompetitorContextHealth] =
    useState<CompetitorContextHealth | null>(null);
  const [latestRecommendationEEATGapSummary, setLatestRecommendationEEATGapSummary] =
    useState<RecommendationEEATGapSummary | null>(null);
  const [latestRecommendationAnalysisFreshness, setLatestRecommendationAnalysisFreshness] =
    useState<RecommendationAnalysisFreshness | null>(null);
  const [latestRecommendationOrderingExplanation, setLatestRecommendationOrderingExplanation] =
    useState<RecommendationOrderingExplanation | null>(null);
  const [latestRecommendationStartHere, setLatestRecommendationStartHere] =
    useState<RecommendationStartHere | null>(null);
  const [latestRecommendationGroupedRecommendations, setLatestRecommendationGroupedRecommendations] = useState<
    RecommendationThemeGroup[]
  >([]);
  const [siteLocationContext, setSiteLocationContext] = useState<string | null>(null);
  const [sitePrimaryLocation, setSitePrimaryLocation] = useState<string | null>(null);
  const [sitePrimaryBusinessZip, setSitePrimaryBusinessZip] = useState<string | null>(null);
  const [siteLocationContextStrength, setSiteLocationContextStrength] = useState<"strong" | "weak" | "unknown">(
    "unknown",
  );
  const [siteLocationContextSource, setSiteLocationContextSource] = useState<
    "explicit_location" | "service_area" | "zip_capture" | "fallback" | null
  >(null);
  const [showZipCaptureModal, setShowZipCaptureModal] = useState(false);
  const [zipCaptureInput, setZipCaptureInput] = useState("");
  const [zipCaptureSaving, setZipCaptureSaving] = useState(false);
  const [zipCaptureError, setZipCaptureError] = useState<string | null>(null);
  const [latestCompetitorPromptPreview, setLatestCompetitorPromptPreview] = useState<PromptPreviewView | null>(null);
  const [latestRecommendationPromptPreview, setLatestRecommendationPromptPreview] =
    useState<PromptPreviewView | null>(null);
  const [promptPreviewCopyFeedbackByType, setPromptPreviewCopyFeedbackByType] = useState<
    Record<PromptPreviewType, string | null>
  >({
    competitor: null,
    recommendation: null,
  });
  const [recommendationWorkspaceSummaryState, setRecommendationWorkspaceSummaryState] =
    useState<RecommendationWorkspaceSummaryResponse["state"] | null>(null);
  const [latestCompletedRecommendationsError, setLatestCompletedRecommendationsError] = useState<string | null>(null);
  const [tuningPreviewByKey, setTuningPreviewByKey] = useState<Record<string, RecommendationTuningImpactPreview>>({});
  const [tuningPreviewErrorByKey, setTuningPreviewErrorByKey] = useState<Record<string, string>>({});
  const [tuningPreviewLoadingKey, setTuningPreviewLoadingKey] = useState<string | null>(null);
  const [tuningSettings, setTuningSettings] = useState<BusinessSettings | null>(null);
  const [tuningApplyMessage, setTuningApplyMessage] = useState<string | null>(null);
  const [tuningApplyErrorByKey, setTuningApplyErrorByKey] = useState<Record<string, string>>({});
  const [tuningApplyLoadingKey, setTuningApplyLoadingKey] = useState<string | null>(null);
  const [startHereFocusedTargetId, setStartHereFocusedTargetId] = useState<string | null>(null);
  const [aiActionFocusedTargetId, setAiActionFocusedTargetId] = useState<string | null>(null);
  const [pendingAiApplyAttributionByPreviewKey, setPendingAiApplyAttributionByPreviewKey] = useState<
    Record<string, AiOpportunityApplyAttribution>
  >({});
  const [recentTuningChanges, setRecentTuningChanges] = useState<RecentTuningChange[]>([]);
  const [showAllAiOpportunities, setShowAllAiOpportunities] = useState(false);
  const [expandedAiOpportunityIds, setExpandedAiOpportunityIds] = useState<Set<string>>(() => new Set());

  const [competitorProfileGenerationRuns, setCompetitorProfileGenerationRuns] = useState<CompetitorProfileGenerationRun[]>([]);
  const [competitorProfileSummary, setCompetitorProfileSummary] =
    useState<CompetitorProfileGenerationSummaryResponse | null>(null);
  const [latestCompetitorProfileRunId, setLatestCompetitorProfileRunId] = useState<string | null>(null);
  const [competitorProfileDrafts, setCompetitorProfileDrafts] = useState<CompetitorProfileDraft[]>([]);
  const [rejectedCompetitorCandidateCount, setRejectedCompetitorCandidateCount] = useState(0);
  const [rejectedCompetitorCandidates, setRejectedCompetitorCandidates] = useState<
    RejectedCompetitorCandidateDebug[]
  >([]);
  const [tuningRejectedCompetitorCandidateCount, setTuningRejectedCompetitorCandidateCount] = useState(0);
  const [tuningRejectedCompetitorCandidates, setTuningRejectedCompetitorCandidates] = useState<
    TuningRejectedCompetitorCandidateDebug[]
  >([]);
  const [tuningRejectionReasonCounts, setTuningRejectionReasonCounts] = useState<Record<string, number>>({});
  const [competitorProviderAttemptCount, setCompetitorProviderAttemptCount] = useState(0);
  const [competitorProviderDegradedRetryUsed, setCompetitorProviderDegradedRetryUsed] = useState(false);
  const [competitorProviderAttempts, setCompetitorProviderAttempts] = useState<CompetitorProviderAttemptDebug[]>([]);
  const [competitorCandidatePipelineSummary, setCompetitorCandidatePipelineSummary] =
    useState<CompetitorCandidatePipelineSummary | null>(null);
  const [competitorOutcomeSummary, setCompetitorOutcomeSummary] = useState<CompetitorRunOutcomeSummary | null>(null);
  const [competitorProfileLoading, setCompetitorProfileLoading] = useState(false);
  const [competitorProfileError, setCompetitorProfileError] = useState<string | null>(null);
  const [competitorProfileSummaryError, setCompetitorProfileSummaryError] = useState<string | null>(null);
  const [competitorProfileActionError, setCompetitorProfileActionError] = useState<string | null>(null);
  const [competitorProfileActionMessage, setCompetitorProfileActionMessage] = useState<string | null>(null);
  const [generationInFlight, setGenerationInFlight] = useState(false);
  const [retryInFlight, setRetryInFlight] = useState(false);
  const [competitorProfilePolling, setCompetitorProfilePolling] = useState(false);
  const [competitorProfilePollingTargetRunId, setCompetitorProfilePollingTargetRunId] = useState<string | null>(null);
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
    () => {
      if (latestCompetitorProfileRunId) {
        const matchingRun = competitorProfileGenerationRuns.find((run) => run.id === latestCompetitorProfileRunId);
        if (matchingRun) {
          return matchingRun;
        }
      }
      return competitorProfileGenerationRuns[0] || null;
    },
    [competitorProfileGenerationRuns, latestCompetitorProfileRunId],
  );
  const competitorRunOutcomeSummary = useMemo<CompetitorRunOutcomeSummaryView | null>(() => {
    if (
      !latestCompetitorProfileRun ||
      !isCompetitorProfileRunTerminalStatus(latestCompetitorProfileRun.status)
    ) {
      return null;
    }

    const proposedCount = Math.max(
      0,
      competitorCandidatePipelineSummary?.proposed_candidate_count ||
        latestCompetitorProfileRun.requested_candidate_count ||
        0,
    );
    const returnedCount = Math.max(
      0,
      competitorCandidatePipelineSummary?.final_candidate_count || competitorProfileDrafts.length,
    );
    const rejectedCount = Math.max(0, proposedCount - returnedCount);
    const filteredOutCount = Math.max(
      0,
      competitorCandidatePipelineSummary
        ? competitorCandidatePipelineSummary.proposed_candidate_count -
            competitorCandidatePipelineSummary.final_candidate_count
        : rejectedCount,
    );
    const duplicatesRemovedCount = Math.max(
      0,
      competitorCandidatePipelineSummary?.removed_by_deduplication_count || 0,
    );
    const degradedModeUsed =
      competitorProviderDegradedRetryUsed || competitorProviderAttempts.some((attempt) => attempt.degraded_mode);
    const hasSearchTelemetry = competitorProviderAttempts.some(
      (attempt) => typeof attempt.web_search_enabled === "boolean",
    );
    const searchBacked = competitorProviderAttempts.some((attempt) => attempt.web_search_enabled === true);
    const searchEscalationTriggered = competitorProviderAttempts.some(
      (attempt) =>
        attempt.search_escalation_triggered ||
        (attempt.escalation_reason || "").trim().toLowerCase() === "zero_valid_competitors",
    );
    const relaxedFilteringApplied = Boolean(competitorCandidatePipelineSummary?.relaxed_filtering_applied);

    const validationRejectedCount = Math.max(
      0,
      competitorCandidatePipelineSummary?.rejected_by_eligibility_count || rejectedCompetitorCandidateCount,
    );
    const tuningRejectedCount = Math.max(
      0,
      competitorCandidatePipelineSummary?.rejected_by_tuning_count || tuningRejectedCompetitorCandidateCount,
    );
    const manyValidationRejections =
      proposedCount > 0 && validationRejectedCount >= Math.max(2, Math.ceil(proposedCount * 0.5));

    const statusNotes: string[] = [];
    if (returnedCount <= 2) {
      statusNotes.push(`few valid competitors returned (${returnedCount}/${proposedCount})`);
    }
    if (manyValidationRejections) {
      statusNotes.push(`${validationRejectedCount} candidates rejected by strict validation`);
    }
    if (degradedModeUsed) {
      statusNotes.push("degraded retry mode used");
    }
    if (hasSearchTelemetry && !searchBacked) {
      statusNotes.push("search-backed discovery unavailable");
    }

    let lowResultNote: string | null = null;
    if (latestCompetitorProfileRun.status === "completed" && returnedCount <= 1) {
      const causes: string[] = [];
      if (validationRejectedCount + tuningRejectedCount > 0) {
        causes.push("strict validation filtered weak candidates");
      }
      if (hasSearchTelemetry && !searchBacked) {
        causes.push("search-backed discovery was unavailable");
      }
      if (degradedModeUsed) {
        causes.push("degraded retry occurred");
      }
      if (causes.length > 0) {
        lowResultNote = `Only ${returnedCount} valid competitor${
          returnedCount === 1 ? "" : "s"
        } remained after filtering. This may indicate ${causes.join(", ")}.`;
      } else {
        lowResultNote = `Only ${returnedCount} valid competitor${
          returnedCount === 1 ? "" : "s"
        } remained after filtering.`;
      }
    }

    return {
      proposedCount,
      returnedCount,
      rejectedCount,
      degradedModeUsed,
      searchBacked,
      filteringSummary:
        proposedCount > 0
          ? `Filtering: proposed ${proposedCount} | filtered out ${filteredOutCount} | duplicates removed ${duplicatesRemovedCount} | final returned ${returnedCount}`
          : null,
      searchEscalationNote: searchEscalationTriggered ? SEARCH_ESCALATION_NOTE : null,
      relaxedFilteringNote: relaxedFilteringApplied ? RELAXED_FILTERING_NOTE : null,
      statusNote: statusNotes.length > 0 ? `Run notes: ${statusNotes.join("; ")}.` : null,
      lowResultNote,
    };
  }, [
    competitorCandidatePipelineSummary,
    competitorProfileDrafts.length,
    competitorProviderAttempts,
    competitorProviderDegradedRetryUsed,
    latestCompetitorProfileRun,
    rejectedCompetitorCandidateCount,
    tuningRejectedCompetitorCandidateCount,
  ]);

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

  const latestRecommendationRun = useMemo(
    () => recommendationRuns[0] || null,
    [recommendationRuns],
  );
  const latestCompletedAuditRun = useMemo(() => {
    const completedRuns = auditRuns.filter((run) => (run.status || "").trim().toLowerCase() === "completed");
    if (completedRuns.length === 0) {
      return null;
    }
    return [...completedRuns].sort((left, right) => {
      return timestampToMs(deriveLifecycleTimestamp(right).value) - timestampToMs(deriveLifecycleTimestamp(left).value);
    })[0];
  }, [auditRuns]);
  const latestCompletedComparisonRunForRecommendations = useMemo(
    () => latestByActivity(comparisonRuns.filter((run) => (run.status || "").trim().toLowerCase() === "completed")),
    [comparisonRuns],
  );
  const recommendationGenerationPrerequisitesMet =
    Boolean(latestCompletedAuditRun) || Boolean(latestCompletedComparisonRunForRecommendations);

  const actionableRecommendationCount = useMemo(
    () =>
      latestCompletedRecommendations.filter(
        (item) => !["accepted", "dismissed", "resolved"].includes(item.status),
      ).length,
    [latestCompletedRecommendations],
  );

  const latestPreviewInsight = useMemo(() => {
    if (!latestCompletedRecommendationRun || latestCompletedTuningSuggestions.length === 0) {
      return null;
    }
    for (const suggestion of latestCompletedTuningSuggestions) {
      const previewKey = buildTuningPreviewKey(latestCompletedRecommendationRun.id, suggestion);
      const preview = tuningPreviewByKey[previewKey];
      if (preview) {
        return `Latest preview suggests ${formatSignedDelta(
          preview.estimated_impact.estimated_included_candidate_delta,
        )} included competitors`;
      }
    }
    return null;
  }, [
    latestCompletedRecommendationRun,
    latestCompletedTuningSuggestions,
    tuningPreviewByKey,
  ]);

  // AI opportunities are an advisory overlay built from existing recommendation payload fields.
  const aiOpportunities = useMemo<AiOpportunityItem[]>(() => {
    const narrativeSummary = narrativeSummaryText(latestCompletedRecommendationNarrative);
    return latestCompletedRecommendations
      .map((recommendation) => {
        const linkedSuggestions = latestCompletedTuningSuggestions.filter((suggestion) =>
          suggestion.linked_recommendation_ids.includes(recommendation.id),
        );
        const isSourceAi = recommendationHasAiSource(recommendation);
        const hasNarrativeContext = narrativeSummary !== null;
        const hasAiSignals = isSourceAi || linkedSuggestions.length > 0 || hasNarrativeContext;
        if (!hasAiSignals) {
          return null;
        }
        const linkedReason = linkedSuggestions
          .map((suggestion) => suggestion.reason.trim())
          .find((value) => Boolean(value));
        return {
          recommendation,
          linkedSuggestions,
          whyThisMatters: linkedReason || narrativeSummary,
          isSourceAi,
        };
      })
      .filter((value): value is AiOpportunityItem => value !== null);
  }, [
    latestCompletedRecommendationNarrative,
    latestCompletedRecommendations,
    latestCompletedTuningSuggestions,
  ]);

  const visibleAiOpportunities = useMemo(() => {
    if (showAllAiOpportunities) {
      return aiOpportunities;
    }
    return aiOpportunities.slice(0, AI_OPPORTUNITY_INITIAL_COUNT);
  }, [aiOpportunities, showAllAiOpportunities]);

  const hiddenAiOpportunityCount = aiOpportunities.length - visibleAiOpportunities.length;

  const startHereAction = useMemo<StartHereAction>(() => {
    const confidenceWeight: Record<RecommendationTuningSuggestion["confidence"], number> = {
      low: 0,
      medium: 1,
      high: 2,
    };

    if (
      latestCompletedRecommendationRun &&
      latestCompletedRecommendationNarrative &&
      latestCompletedTuningSuggestions.length > 0
    ) {
      const ranked = [...latestCompletedTuningSuggestions]
        .map((suggestion) => {
          const previewKey = buildTuningPreviewKey(latestCompletedRecommendationRun.id, suggestion);
          const preview = tuningPreviewByKey[previewKey] || null;
          return {
            suggestion,
            preview,
            previewIncludedDelta: preview
              ? preview.estimated_impact.estimated_included_candidate_delta
              : Number.NEGATIVE_INFINITY,
            linkedRecommendationCount: suggestion.linked_recommendation_ids.length,
            confidence: confidenceWeight[suggestion.confidence],
          };
        })
        .sort((left, right) => {
          if (right.previewIncludedDelta !== left.previewIncludedDelta) {
            return right.previewIncludedDelta - left.previewIncludedDelta;
          }
          if (right.linkedRecommendationCount !== left.linkedRecommendationCount) {
            return right.linkedRecommendationCount - left.linkedRecommendationCount;
          }
          if (right.confidence !== left.confidence) {
            return right.confidence - left.confidence;
          }
          return formatTuningSettingLabel(left.suggestion.setting).localeCompare(
            formatTuningSettingLabel(right.suggestion.setting),
          );
        });

      const best = ranked[0];
      if (best) {
        const settingLabel = formatTuningSettingLabel(best.suggestion.setting);
        const hasPreview = Boolean(best.preview);
        let whyThisFirst = "strongest available tuning signal in the latest completed run.";
        if (hasPreview) {
          whyThisFirst = "highest estimated impact on included competitors.";
        } else if (best.linkedRecommendationCount > 1) {
          whyThisFirst = "linked to multiple recommendations in the latest completed run.";
        } else if (best.suggestion.confidence === "high") {
          whyThisFirst = "high-confidence tuning adjustment for the latest completed run.";
        }
        const detail = hasPreview
          ? `Expected: ${formatSignedDelta(
              best.preview!.estimated_impact.estimated_included_candidate_delta,
            )} included competitors`
          : "Preview impact to estimate included competitor change.";
        return {
          kind: "tuning",
          title: `Adjust ${settingLabel.toLowerCase()} from ${best.suggestion.current_value} -> ${best.suggestion.recommended_value}`,
          detail,
          whyThisFirst,
          buttonLabel: hasPreview ? "Focus Tuning Suggestion" : "Preview and Focus",
          targetId: tuningSuggestionCardId(latestCompletedRecommendationRun.id, best.suggestion),
          recommendationRunId: latestCompletedRecommendationRun.id,
          narrativeId: latestCompletedRecommendationNarrative.id,
          suggestion: best.suggestion,
          hasPreview,
        };
      }
    }

    if (latestCompletedRecommendations.length > 0) {
      const highestPriorityRecommendation =
        [...latestCompletedRecommendations].sort((left, right) => {
          if (right.priority_score !== left.priority_score) {
            return right.priority_score - left.priority_score;
          }
          return right.updated_at.localeCompare(left.updated_at);
        })[0] || latestCompletedRecommendations[0];
      const highestPriorityScore = highestPriorityRecommendation.priority_score;
      const tiedTopPriorityRecommendations = latestCompletedRecommendations.filter(
        (item) => item.priority_score === highestPriorityScore,
      ).length;

      const impact =
        highestPriorityRecommendation.priority_band === "critical" ||
        highestPriorityRecommendation.priority_band === "high"
          ? "HIGH IMPACT"
          : highestPriorityRecommendation.effort_bucket === "small"
            ? "QUICK WIN"
            : "NEEDS REVIEW";

      return {
        kind: "recommendation",
        title: highestPriorityRecommendation.title,
        detail: `Marked ${impact}`,
        whyThisFirst:
          tiedTopPriorityRecommendations > 1
            ? `tied for highest priority score (${highestPriorityScore}) and updated most recently.`
            : `highest priority score (${highestPriorityScore}) in the latest completed run.`,
        buttonLabel: "Focus Recommendation",
        targetId: recommendationRowId(highestPriorityRecommendation.id),
      };
    }

    return {
      kind: "none",
      title: "No immediate action available",
      detail: "Run analysis to generate recommendations and tuning guidance.",
      whyThisFirst: "no completed recommendation run or tuning suggestion is available yet.",
    };
  }, [
    latestCompletedRecommendationRun,
    latestCompletedRecommendations,
    latestCompletedRecommendationNarrative,
    latestCompletedTuningSuggestions,
    tuningPreviewByKey,
  ]);

  const narrativeActionSummary = useMemo(
    () => normalizeNarrativeActionSummary(latestCompletedRecommendationNarrative),
    [latestCompletedRecommendationNarrative],
  );

  const narrativeCompetitorInfluence = useMemo(
    () => normalizeNarrativeCompetitorInfluence(latestCompletedRecommendationNarrative),
    [latestCompletedRecommendationNarrative],
  );

  const narrativeSignalSummary = useMemo(
    () => normalizeNarrativeSignalSummary(latestCompletedRecommendationNarrative),
    [latestCompletedRecommendationNarrative],
  );

  const recommendationApplyOutcome = useMemo(
    () => normalizeRecommendationApplyOutcome(latestRecommendationApplyOutcome),
    [latestRecommendationApplyOutcome],
  );
  const competitorContextHealth = useMemo(
    () => normalizeCompetitorContextHealth(latestCompetitorContextHealth),
    [latestCompetitorContextHealth],
  );
  const recommendationEEATGapSummary = useMemo(
    () => normalizeRecommendationEEATGapSummary(latestRecommendationEEATGapSummary),
    [latestRecommendationEEATGapSummary],
  );

  const recommendationAnalysisFreshness = useMemo(
    () => normalizeRecommendationAnalysisFreshness(latestRecommendationAnalysisFreshness),
    [latestRecommendationAnalysisFreshness],
  );
  const recommendationOrderingExplanation = useMemo(
    () => normalizeRecommendationOrderingExplanation(latestRecommendationOrderingExplanation),
    [latestRecommendationOrderingExplanation],
  );
  const recommendationThemeStartHere = useMemo(() => {
    if (!latestRecommendationStartHere) {
      return null;
    }
    const fallbackTheme = latestRecommendationStartHere.theme;
    const themeLabel = truncateOptionalText(latestRecommendationStartHere.theme_label, 80)
      || formatRecommendationThemeLabel(fallbackTheme);
    return {
      ...latestRecommendationStartHere,
      themeLabel,
      title: truncateOptionalText(latestRecommendationStartHere.title, 180) || latestRecommendationStartHere.title,
      reason: truncateOptionalText(latestRecommendationStartHere.reason, 320) || latestRecommendationStartHere.reason,
      hasPendingRefreshContext: latestRecommendationStartHere.context_flags.includes("pending_refresh_context"),
      hasCompetitorBackedContext: latestRecommendationStartHere.context_flags.includes("competitor_backed"),
    };
  }, [latestRecommendationStartHere]);
  const recommendationThemeSections = useMemo(
    () =>
      normalizeRecommendationThemeSections(
        latestCompletedRecommendations,
        latestRecommendationGroupedRecommendations,
      ),
    [latestCompletedRecommendations, latestRecommendationGroupedRecommendations],
  );
  const recommendationRankById = useMemo(() => {
    const rank = new Map<string, number>();
    latestCompletedRecommendations.forEach((recommendation, index) => {
      rank.set(recommendation.id, index);
    });
    return rank;
  }, [latestCompletedRecommendations]);
  const narrativeEEATFocusCategories = useMemo(() => {
    const ranked = [...latestCompletedRecommendations].sort((left, right) => {
      if (right.priority_score !== left.priority_score) {
        return right.priority_score - left.priority_score;
      }
      return right.updated_at.localeCompare(left.updated_at);
    });
    for (const recommendation of ranked) {
      const categories = normalizeEEATCategories(recommendation.eeat_categories);
      if (categories.length > 0) {
        return categories;
      }
    }
    return [] as RecommendationEEATCategory[];
  }, [latestCompletedRecommendations]);

  useEffect(() => {
    setShowAllAiOpportunities(false);
    setExpandedAiOpportunityIds(new Set());
  }, [latestCompletedRecommendationRun?.id]);

  useEffect(() => {
    if (!aiActionFocusedTargetId) {
      return;
    }
    const timerId = window.setTimeout(() => {
      setAiActionFocusedTargetId((current) =>
        current === aiActionFocusedTargetId ? null : current,
      );
    }, AI_ACTION_HIGHLIGHT_DURATION_MS);
    return () => window.clearTimeout(timerId);
  }, [aiActionFocusedTargetId]);

  function toggleAiOpportunityExpansion(recommendationId: string): void {
    setExpandedAiOpportunityIds((current) => {
      const next = new Set(current);
      if (next.has(recommendationId)) {
        next.delete(recommendationId);
      } else {
        next.add(recommendationId);
      }
      return next;
    });
  }

  function scrollToTarget(targetId: string): boolean {
    const target = document.getElementById(targetId);
    if (!target) {
      return false;
    }
    if (typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    return true;
  }

  function focusActionTarget(targetId: string): void {
    const didFocus = scrollToTarget(targetId);
    if (!didFocus) {
      return;
    }
    setStartHereFocusedTargetId(targetId);
  }

  function focusAiActionTarget(targetId: string): void {
    const didFocus = scrollToTarget(targetId);
    if (!didFocus) {
      return;
    }
    setAiActionFocusedTargetId(targetId);
  }

  function registerAiApplyAttribution(
    recommendationRunId: string,
    suggestion: RecommendationTuningSuggestion,
    recommendation: Recommendation,
  ): string {
    const previewKey = buildTuningPreviewKey(recommendationRunId, suggestion);
    // Frontend-only attribution to connect AI opportunity guidance to later manual apply actions.
    setPendingAiApplyAttributionByPreviewKey((current) => ({
      ...current,
      [previewKey]: {
        recommendation_id: recommendation.id,
        recommendation_title: recommendation.title,
      },
    }));
    return previewKey;
  }

  function focusLinkedTuningSuggestion(
    recommendationRunId: string,
    suggestion: RecommendationTuningSuggestion,
    recommendation: Recommendation,
  ): void {
    registerAiApplyAttribution(recommendationRunId, suggestion, recommendation);
    focusAiActionTarget(tuningSuggestionCardId(recommendationRunId, suggestion));
  }

  async function handleStartHereAction(): Promise<void> {
    if (startHereAction.kind === "tuning") {
      if (!startHereAction.hasPreview) {
        await handlePreviewTuningSuggestion(
          startHereAction.recommendationRunId,
          startHereAction.narrativeId,
          startHereAction.suggestion,
        );
      }
      focusActionTarget(startHereAction.targetId);
      return;
    }
    if (startHereAction.kind === "recommendation") {
      focusActionTarget(startHereAction.targetId);
    }
  }

  function currentSuggestionValue(suggestion: RecommendationTuningSuggestion): number {
    const persistedValue = tuningSettingValueFromBusinessSettings(tuningSettings, suggestion.setting);
    if (typeof persistedValue === "number" && Number.isFinite(persistedValue)) {
      return persistedValue;
    }
    return suggestion.current_value;
  }

  function applyWorkspaceSummary(summary: RecommendationWorkspaceSummaryResponse): void {
    setRecommendationWorkspaceSummaryState(summary.state);
    setLatestCompletedRecommendationRun(summary.latest_completed_run);
    setLatestCompletedRecommendations(summary.recommendations.items);
    setLatestCompletedRecommendationNarrative(summary.latest_narrative);
    setLatestCompletedTuningSuggestions(summary.tuning_suggestions);
    setLatestRecommendationApplyOutcome(summary.apply_outcome || null);
    setLatestCompetitorContextHealth(summary.competitor_context_health || null);
    setLatestRecommendationEEATGapSummary(summary.eeat_gap_summary || null);
    setLatestRecommendationAnalysisFreshness(summary.analysis_freshness || null);
    setLatestRecommendationOrderingExplanation(summary.ordering_explanation || null);
    setLatestRecommendationStartHere(summary.start_here || null);
    setLatestRecommendationGroupedRecommendations(summary.grouped_recommendations || []);
    setSiteLocationContext(summary.site_location_context || null);
    setSitePrimaryLocation(summary.site_primary_location || null);
    setSitePrimaryBusinessZip(summary.site_primary_business_zip || null);
    setSiteLocationContextStrength(summary.site_location_context_strength || "unknown");
    setSiteLocationContextSource(summary.site_location_context_source || null);
    setLatestCompetitorPromptPreview(
      normalizePromptPreview(summary.competitor_prompt_preview, "competitor"),
    );
    setLatestRecommendationPromptPreview(
      normalizePromptPreview(summary.recommendation_prompt_preview, "recommendation"),
    );
    setPromptPreviewCopyFeedbackByType({ competitor: null, recommendation: null });
    setLatestCompletedRecommendationsError(null);
  }

  useEffect(() => {
    if (!selectedSite) {
      return;
    }
    if (siteLocationContextStrength !== "weak" || Boolean(sitePrimaryBusinessZip)) {
      setShowZipCaptureModal(false);
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    const dismissed = window.sessionStorage.getItem(zipPromptSessionKey(selectedSite.id)) === "true";
    if (dismissed) {
      return;
    }
    setZipCaptureInput("");
    setZipCaptureError(null);
    setShowZipCaptureModal(true);
  }, [selectedSite, siteLocationContextStrength, sitePrimaryBusinessZip]);

  function handleSkipZipCapture(): void {
    if (selectedSite && typeof window !== "undefined") {
      window.sessionStorage.setItem(zipPromptSessionKey(selectedSite.id), "true");
    }
    setShowZipCaptureModal(false);
    setZipCaptureError(null);
  }

  async function handleSavePrimaryBusinessZip(): Promise<void> {
    if (!selectedSite) {
      return;
    }
    const normalizedZip = normalizePrimaryBusinessZipInput(zipCaptureInput);
    if (!isValidPrimaryBusinessZip(normalizedZip)) {
      setZipCaptureError("Enter a valid 5-digit ZIP code.");
      return;
    }

    setZipCaptureSaving(true);
    setZipCaptureError(null);
    try {
      await updateSite(context.token, context.businessId, selectedSite.id, {
        primary_business_zip: normalizedZip,
      });
      setSitePrimaryBusinessZip(normalizedZip);
      setSiteLocationContextStrength("strong");
      if (typeof window !== "undefined") {
        window.sessionStorage.setItem(zipPromptSessionKey(selectedSite.id), "true");
      }
      setShowZipCaptureModal(false);
      await context.refreshSites();
      try {
        const refreshedSummary = await fetchRecommendationWorkspaceSummary(
          context.token,
          context.businessId,
          selectedSite.id,
        );
        applyWorkspaceSummary(refreshedSummary);
      } catch {
        // Keep workspace non-blocking if summary refresh fails after ZIP save.
      }
    } catch {
      setZipCaptureError("Unable to save ZIP right now. Try again or skip for now.");
    } finally {
      setZipCaptureSaving(false);
    }
  }

  function previewForType(promptType: PromptPreviewType): PromptPreviewView | null {
    return promptType === "competitor" ? latestCompetitorPromptPreview : latestRecommendationPromptPreview;
  }

  async function handleCopyPromptPreview(promptType: PromptPreviewType): Promise<void> {
    const preview = previewForType(promptType);
    if (!preview) {
      return;
    }
    const exportText = buildPromptPreviewExportText(preview);
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        throw new Error("clipboard_unavailable");
      }
      await navigator.clipboard.writeText(exportText);
      setPromptPreviewCopyFeedbackByType((current) => ({
        ...current,
        [promptType]: "Prompt copied.",
      }));
    } catch {
      setPromptPreviewCopyFeedbackByType((current) => ({
        ...current,
        [promptType]: "Prompt copy failed in this browser context.",
      }));
    }
  }

  function handleDownloadPromptPreview(promptType: PromptPreviewType): void {
    const preview = previewForType(promptType);
    if (!preview || typeof document === "undefined") {
      return;
    }
    const exportText = buildPromptPreviewExportText(preview);
    const blob = new Blob([exportText], { type: "text/plain;charset=utf-8" });
    const blobUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const timestamp = new Date().toISOString().replace(/[:]/g, "-");
    anchor.href = blobUrl;
    anchor.download = `${promptType}-ai-prompt-${timestamp}.txt`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(blobUrl);
  }

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

  async function handleGenerateRecommendations(): Promise<void> {
    if (!context.token || !context.businessId || !siteId) {
      return;
    }

    const payload: RecommendationRunCreateRequest = {};
    if (latestCompletedAuditRun) {
      payload.audit_run_id = latestCompletedAuditRun.id;
    }
    if (latestCompletedComparisonRunForRecommendations) {
      payload.comparison_run_id = latestCompletedComparisonRunForRecommendations.id;
    }

    if (!payload.audit_run_id && !payload.comparison_run_id) {
      setRecommendationGenerationError(
        "Run site audit before generating recommendations.",
      );
      setRecommendationGenerationMessage(null);
      return;
    }

    setRecommendationGenerationInFlight(true);
    setRecommendationGenerationError(null);
    setRecommendationGenerationMessage(null);
    try {
      const run = await createRecommendationRun(
        context.token,
        context.businessId,
        siteId,
        payload,
      );
      setRecommendationRuns((current) => {
        const next = [run, ...current.filter((item) => item.id !== run.id)];
        return next
          .sort((left, right) => right.created_at.localeCompare(left.created_at))
          .slice(0, MAX_RECOMMENDATION_RUN_ROWS);
      });
      const normalizedStatus = (run.status || "").trim().toLowerCase();
      if (normalizedStatus === "completed") {
        setRecommendationGenerationMessage(
          "Recommendation run completed. Refreshing workspace state.",
        );
      } else if (normalizedStatus === "failed") {
        setRecommendationGenerationMessage(
          "Recommendation run failed. Refreshing workspace state for latest details.",
        );
      } else {
        setRecommendationGenerationMessage(
          `Recommendation run ${normalizedStatus || "queued"}. Refreshing workspace state.`,
        );
      }
      setWorkspaceRefreshNonce((current) => current + 1);
    } catch (error) {
      setRecommendationGenerationError(
        safeActionErrorMessage("generate recommendations", error),
      );
    } finally {
      setRecommendationGenerationInFlight(false);
    }
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
        return upsertCompetitorProfileGenerationRun(current, detail.run);
      });
      setLatestCompetitorProfileRunId(detail.run.id);
      if (!isCompetitorProfileRunTerminalStatus(detail.run.status)) {
        setCompetitorProfilePollingTargetRunId(detail.run.id);
      } else {
        setCompetitorProfilePollingTargetRunId(null);
      }
      setCompetitorProfileDrafts(detail.drafts);
      setRejectedCompetitorCandidateCount(Math.max(0, detail.rejected_candidate_count || 0));
      setRejectedCompetitorCandidates(normalizeRejectedCompetitorCandidates(detail.rejected_candidates));
      setTuningRejectedCompetitorCandidateCount(Math.max(0, detail.tuning_rejected_candidate_count || 0));
      setTuningRejectedCompetitorCandidates(
        normalizeTuningRejectedCompetitorCandidates(detail.tuning_rejected_candidates),
      );
      setTuningRejectionReasonCounts(
        normalizeTuningRejectionReasonCounts(detail.tuning_rejection_reason_counts || null),
      );
      setCompetitorCandidatePipelineSummary(
        normalizeCompetitorCandidatePipelineSummary(detail.candidate_pipeline_summary),
      );
      setCompetitorProviderAttemptCount(Math.max(0, detail.provider_attempt_count || 0));
      setCompetitorProviderDegradedRetryUsed(Boolean(detail.provider_degraded_retry_used));
      setCompetitorProviderAttempts(normalizeCompetitorProviderAttempts(detail.provider_attempts));
      setCompetitorOutcomeSummary(detail.outcome_summary || null);
      const terminalMessage = competitorProfileTerminalMessage(detail.run.status);
      setCompetitorProfileActionMessage(
        terminalMessage ||
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
        return upsertCompetitorProfileGenerationRun(current, detail.run);
      });
      setLatestCompetitorProfileRunId(detail.run.id);
      if (!isCompetitorProfileRunTerminalStatus(detail.run.status)) {
        setCompetitorProfilePollingTargetRunId(detail.run.id);
      } else {
        setCompetitorProfilePollingTargetRunId(null);
      }
      setCompetitorProfileDrafts(detail.drafts);
      setRejectedCompetitorCandidateCount(Math.max(0, detail.rejected_candidate_count || 0));
      setRejectedCompetitorCandidates(normalizeRejectedCompetitorCandidates(detail.rejected_candidates));
      setTuningRejectedCompetitorCandidateCount(Math.max(0, detail.tuning_rejected_candidate_count || 0));
      setTuningRejectedCompetitorCandidates(
        normalizeTuningRejectedCompetitorCandidates(detail.tuning_rejected_candidates),
      );
      setTuningRejectionReasonCounts(
        normalizeTuningRejectionReasonCounts(detail.tuning_rejection_reason_counts || null),
      );
      setCompetitorCandidatePipelineSummary(
        normalizeCompetitorCandidatePipelineSummary(detail.candidate_pipeline_summary),
      );
      setCompetitorProviderAttemptCount(Math.max(0, detail.provider_attempt_count || 0));
      setCompetitorProviderDegradedRetryUsed(Boolean(detail.provider_degraded_retry_used));
      setCompetitorProviderAttempts(normalizeCompetitorProviderAttempts(detail.provider_attempts));
      setCompetitorOutcomeSummary(detail.outcome_summary || null);
      const terminalMessage = competitorProfileTerminalMessage(detail.run.status);
      setCompetitorProfileActionMessage(
        terminalMessage ||
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

  async function handlePreviewTuningSuggestion(
    recommendationRunId: string,
    narrativeId: string | null,
    suggestion: RecommendationTuningSuggestion,
  ): Promise<void> {
    if (!context.token || !context.businessId || !siteId) {
      return;
    }
    const previewKey = buildTuningPreviewKey(recommendationRunId, suggestion);
    const currentValue = currentSuggestionValue(suggestion);
    setTuningPreviewLoadingKey(previewKey);
    setTuningApplyMessage(null);
    setTuningApplyErrorByKey((current) => {
      if (!current[previewKey]) {
        return current;
      }
      const next = { ...current };
      delete next[previewKey];
      return next;
    });
    setTuningPreviewErrorByKey((current) => {
      if (!current[previewKey]) {
        return current;
      }
      const next = { ...current };
      delete next[previewKey];
      return next;
    });
    try {
      const preview = await previewRecommendationTuningImpact(
        context.token,
        context.businessId,
        siteId,
        {
          recommendation_run_id: recommendationRunId,
          narrative_id: narrativeId || undefined,
          current_values: {
            [suggestion.setting]: currentValue,
          },
          proposed_values: {
            [suggestion.setting]: suggestion.recommended_value,
          },
        },
      );
      setTuningPreviewByKey((current) => ({ ...current, [previewKey]: preview }));
    } catch (error) {
      setTuningPreviewErrorByKey((current) => ({
        ...current,
        [previewKey]: safeActionErrorMessage("preview tuning impact", error),
      }));
    } finally {
      setTuningPreviewLoadingKey((current) => (current === previewKey ? null : current));
    }
  }

  async function handleApplyTuningSuggestion(
    recommendationRunId: string,
    suggestion: RecommendationTuningSuggestion,
  ): Promise<void> {
    if (!context.token || !context.businessId || !siteId) {
      return;
    }
    const previewKey = buildTuningPreviewKey(recommendationRunId, suggestion);
    const currentValue = currentSuggestionValue(suggestion);
    const preview = tuningPreviewByKey[previewKey];
    const pendingAiAttribution = pendingAiApplyAttributionByPreviewKey[previewKey] || null;
    const confirmationLines = [
      `Apply tuning suggestion to business settings?`,
      `${formatTuningSettingLabel(suggestion.setting)}: ${currentValue} -> ${suggestion.recommended_value}`,
      "This updates the business-level setting for all sites in this business.",
      "No automatic changes will be made without this confirmation.",
    ];
    if (preview?.estimated_impact?.summary) {
      confirmationLines.push(`Preview summary: ${preview.estimated_impact.summary}`);
    }
    const confirmed = window.confirm(confirmationLines.join("\n"));
    if (!confirmed) {
      return;
    }

    setTuningApplyLoadingKey(previewKey);
    setTuningApplyMessage(null);
    setTuningApplyErrorByKey((current) => {
      if (!current[previewKey]) {
        return current;
      }
      const next = { ...current };
      delete next[previewKey];
      return next;
    });
    try {
      const payload: {
        competitor_candidate_min_relevance_score?: number;
        competitor_candidate_big_box_penalty?: number;
        competitor_candidate_directory_penalty?: number;
        competitor_candidate_local_alignment_bonus?: number;
        competitor_tuning_preview_event_id?: string;
      } = {
        [suggestion.setting]: suggestion.recommended_value,
      };
      if (preview?.preview_event_id) {
        payload.competitor_tuning_preview_event_id = preview.preview_event_id;
      }

      const updated = await updateBusinessSettings(
        context.token,
        context.businessId,
        payload,
      );
      setTuningSettings(updated);
      // Record a local recent-change entry so operators can trace apply outcomes from this workspace session.
      setRecentTuningChanges((current) => [
        {
          id: `${previewKey}:${Date.now()}`,
          applied_at: new Date().toISOString(),
          setting_label: formatTuningSettingLabel(suggestion.setting),
          previous_value: currentValue,
          next_value: suggestion.recommended_value,
          ai_attribution: pendingAiAttribution,
        },
        ...current,
      ].slice(0, MAX_RECENT_TUNING_CHANGES));
      setPendingAiApplyAttributionByPreviewKey((current) => {
        if (!current[previewKey]) {
          return current;
        }
        const next = { ...current };
        delete next[previewKey];
        return next;
      });

      try {
        const summary = await fetchRecommendationWorkspaceSummary(
          context.token,
          context.businessId,
          siteId,
        );
        applyWorkspaceSummary(summary);
      } catch (refreshError) {
        setLatestCompletedRecommendationsError(
          safeSectionErrorMessage("recommendation workspace summary", refreshError),
        );
      }

      setTuningPreviewByKey({});
      setTuningPreviewErrorByKey({});
      setTuningPreviewLoadingKey(null);
      setTuningApplyErrorByKey({});
      setTuningApplyMessage(
        `Setting updated: ${formatTuningSettingLabel(suggestion.setting)} is now ${suggestion.recommended_value}. New run will reflect this change.`,
      );
    } catch (error) {
      setTuningApplyErrorByKey((current) => ({
        ...current,
        [previewKey]: safeActionErrorMessage("apply this tuning suggestion", error),
      }));
    } finally {
      setTuningApplyLoadingKey((current) => (current === previewKey ? null : current));
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
    const possibleIssues = [
      auditError,
      competitorError,
      recommendationRunError,
      narrativeLookupError,
      latestCompletedRecommendationsError,
    ];
    return possibleIssues.find((value) => Boolean(value)) || null;
  }, [auditError, competitorError, latestCompletedRecommendationsError, narrativeLookupError, recommendationRunError]);

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
      setRecommendationGenerationInFlight(false);
      setRecommendationGenerationMessage(null);
      setRecommendationGenerationError(null);
      setLatestNarrativesByRunId({});
      setNarrativeLookupError(null);
      setLatestCompletedRecommendationRun(null);
      setLatestCompletedRecommendations([]);
      setLatestCompletedRecommendationNarrative(null);
      setLatestCompletedTuningSuggestions([]);
      setLatestRecommendationApplyOutcome(null);
      setLatestCompetitorContextHealth(null);
      setLatestRecommendationEEATGapSummary(null);
      setLatestRecommendationAnalysisFreshness(null);
      setLatestRecommendationOrderingExplanation(null);
      setLatestRecommendationStartHere(null);
      setLatestRecommendationGroupedRecommendations([]);
      setSiteLocationContext(null);
      setSitePrimaryLocation(null);
      setSitePrimaryBusinessZip(null);
      setSiteLocationContextStrength("unknown");
      setSiteLocationContextSource(null);
      setShowZipCaptureModal(false);
      setZipCaptureInput("");
      setZipCaptureSaving(false);
      setZipCaptureError(null);
      setRecommendationWorkspaceSummaryState(null);
      setLatestCompletedRecommendationsError(null);
      setTuningPreviewByKey({});
      setTuningPreviewErrorByKey({});
      setTuningPreviewLoadingKey(null);
      setTuningSettings(null);
      setTuningApplyMessage(null);
      setTuningApplyErrorByKey({});
      setTuningApplyLoadingKey(null);
      setAiActionFocusedTargetId(null);
      setPendingAiApplyAttributionByPreviewKey({});
      setRecentTuningChanges([]);
      setCompetitorProfileGenerationRuns([]);
      setCompetitorProfileSummary(null);
      setLatestCompetitorProfileRunId(null);
      setCompetitorProfileDrafts([]);
      setRejectedCompetitorCandidateCount(0);
      setRejectedCompetitorCandidates([]);
      setTuningRejectedCompetitorCandidateCount(0);
      setTuningRejectedCompetitorCandidates([]);
      setTuningRejectionReasonCounts({});
      setCompetitorCandidatePipelineSummary(null);
      setCompetitorProviderAttemptCount(0);
      setCompetitorProviderDegradedRetryUsed(false);
      setCompetitorProviderAttempts([]);
      setCompetitorOutcomeSummary(null);
      setCompetitorProfileLoading(false);
      setCompetitorProfileError(null);
      setCompetitorProfileSummaryError(null);
      setCompetitorProfileActionError(null);
      setCompetitorProfileActionMessage(null);
      setGenerationInFlight(false);
      setRetryInFlight(false);
      setCompetitorProfilePolling(false);
      setCompetitorProfilePollingTargetRunId(null);
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
      setRecommendationRuns([]);
      setRecommendationRunError(null);
      setRecommendationGenerationInFlight(false);
      setRecommendationGenerationMessage(null);
      setRecommendationGenerationError(null);
      setLatestNarrativesByRunId({});
      setNarrativeLookupError(null);
      setLatestCompletedRecommendationRun(null);
      setLatestCompletedRecommendations([]);
      setLatestCompletedRecommendationNarrative(null);
      setLatestCompletedTuningSuggestions([]);
      setLatestRecommendationApplyOutcome(null);
      setLatestCompetitorContextHealth(null);
      setLatestRecommendationEEATGapSummary(null);
      setLatestRecommendationAnalysisFreshness(null);
      setLatestRecommendationOrderingExplanation(null);
      setLatestRecommendationStartHere(null);
      setLatestRecommendationGroupedRecommendations([]);
      setSiteLocationContext(null);
      setSitePrimaryLocation(null);
      setSitePrimaryBusinessZip(null);
      setSiteLocationContextStrength("unknown");
      setSiteLocationContextSource(null);
      setShowZipCaptureModal(false);
      setZipCaptureInput("");
      setZipCaptureSaving(false);
      setZipCaptureError(null);
      setRecommendationWorkspaceSummaryState(null);
      setLatestCompletedRecommendationsError(null);
      setTuningPreviewByKey({});
      setTuningPreviewErrorByKey({});
      setTuningPreviewLoadingKey(null);
      setTuningSettings(null);
      setTuningApplyMessage(null);
      setTuningApplyErrorByKey({});
      setTuningApplyLoadingKey(null);
      setAiActionFocusedTargetId(null);
      setPendingAiApplyAttributionByPreviewKey({});
      setRecentTuningChanges([]);
      setCompetitorProfileGenerationRuns([]);
      setCompetitorProfileSummary(null);
      setLatestCompetitorProfileRunId(null);
      setCompetitorProfileDrafts([]);
      setRejectedCompetitorCandidateCount(0);
      setRejectedCompetitorCandidates([]);
      setTuningRejectedCompetitorCandidateCount(0);
      setTuningRejectedCompetitorCandidates([]);
      setTuningRejectionReasonCounts({});
      setCompetitorCandidatePipelineSummary(null);
      setCompetitorProviderAttemptCount(0);
      setCompetitorProviderDegradedRetryUsed(false);
      setCompetitorProviderAttempts([]);
      setCompetitorOutcomeSummary(null);
      setCompetitorProfileLoading(false);
      setCompetitorProfileError(null);
      setCompetitorProfileSummaryError(null);
      setRetryInFlight(false);
      setCompetitorProfilePolling(false);
      setCompetitorProfilePollingTargetRunId(null);
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
      setLatestCompletedRecommendationRun(null);
      setLatestCompletedRecommendations([]);
      setLatestCompletedRecommendationNarrative(null);
      setLatestCompletedTuningSuggestions([]);
      setLatestRecommendationApplyOutcome(null);
      setLatestCompetitorContextHealth(null);
      setLatestRecommendationEEATGapSummary(null);
      setLatestRecommendationAnalysisFreshness(null);
      setLatestRecommendationOrderingExplanation(null);
      setLatestRecommendationStartHere(null);
      setLatestRecommendationGroupedRecommendations([]);
      setSiteLocationContext(null);
      setSitePrimaryLocation(null);
      setSitePrimaryBusinessZip(null);
      setSiteLocationContextStrength("unknown");
      setSiteLocationContextSource(null);
      setShowZipCaptureModal(false);
      setZipCaptureInput("");
      setZipCaptureSaving(false);
      setZipCaptureError(null);
      setRecommendationWorkspaceSummaryState(null);
      setLatestCompletedRecommendationsError(null);
      setTuningPreviewByKey({});
      setTuningPreviewErrorByKey({});
      setTuningPreviewLoadingKey(null);
      setTuningSettings(null);
      setTuningApplyMessage(null);
      setTuningApplyErrorByKey({});
      setTuningApplyLoadingKey(null);
      setAiActionFocusedTargetId(null);
      setPendingAiApplyAttributionByPreviewKey({});
      setRecentTuningChanges([]);
      setCompetitorProfilePollingTargetRunId(null);
      setCompetitorProfilePolling(false);
      setCompetitorProfileSummaryError(null);
      setCompetitorProfileActionError(null);
      setCompetitorProfileActionMessage(null);
      setRejectedCompetitorCandidateCount(0);
      setRejectedCompetitorCandidates([]);
      setTuningRejectedCompetitorCandidateCount(0);
      setTuningRejectedCompetitorCandidates([]);
      setTuningRejectionReasonCounts({});
      setCompetitorCandidatePipelineSummary(null);
      setCompetitorProviderAttemptCount(0);
      setCompetitorProviderDegradedRetryUsed(false);
      setCompetitorProviderAttempts([]);
      setCompetitorOutcomeSummary(null);

      const [
        auditResult,
        competitorSetsResult,
        comparisonRunsResult,
        queueResult,
        recommendationRunsResult,
        recommendationWorkspaceSummaryResult,
        businessSettingsResult,
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
          fetchRecommendationWorkspaceSummary(context.token, context.businessId, siteId),
          fetchBusinessSettings(context.token, context.businessId),
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
          setTuningPreviewByKey({});
          setTuningPreviewErrorByKey({});
          setTuningPreviewLoadingKey(null);
          if (narrativeErrors.length > 0) {
            setNarrativeLookupError(safeSectionErrorMessage("narrative metadata", narrativeErrors[0]));
          } else {
            setNarrativeLookupError(null);
          }
        } else {
          setLatestNarrativesByRunId({});
          setNarrativeLookupError(null);
          setTuningPreviewByKey({});
          setTuningPreviewErrorByKey({});
          setTuningPreviewLoadingKey(null);
        }
      } else {
        setRecommendationRuns([]);
        setLatestNarrativesByRunId({});
        setTuningPreviewByKey({});
        setTuningPreviewErrorByKey({});
        setTuningPreviewLoadingKey(null);
        setRecommendationRunError(safeSectionErrorMessage("recommendation runs", recommendationRunsResult.reason));
      }

      if (recommendationWorkspaceSummaryResult.status === "fulfilled") {
        applyWorkspaceSummary(recommendationWorkspaceSummaryResult.value);
      } else {
        setRecommendationWorkspaceSummaryState(null);
        setLatestCompletedRecommendationRun(null);
        setLatestCompletedRecommendations([]);
        setLatestCompletedRecommendationNarrative(null);
        setLatestCompletedTuningSuggestions([]);
        setLatestRecommendationApplyOutcome(null);
        setLatestCompetitorContextHealth(null);
        setLatestRecommendationEEATGapSummary(null);
        setLatestRecommendationAnalysisFreshness(null);
        setLatestRecommendationOrderingExplanation(null);
        setLatestRecommendationStartHere(null);
        setLatestRecommendationGroupedRecommendations([]);
        setSiteLocationContext(null);
        setSitePrimaryLocation(null);
        setSitePrimaryBusinessZip(null);
        setSiteLocationContextStrength("unknown");
        setSiteLocationContextSource(null);
        setShowZipCaptureModal(false);
        setZipCaptureInput("");
        setZipCaptureSaving(false);
        setZipCaptureError(null);
        setLatestCompetitorPromptPreview(null);
        setLatestRecommendationPromptPreview(null);
        setPromptPreviewCopyFeedbackByType({ competitor: null, recommendation: null });
        setLatestCompletedRecommendationsError(
          safeSectionErrorMessage("recommendation workspace summary", recommendationWorkspaceSummaryResult.reason),
        );
      }

      if (businessSettingsResult.status === "fulfilled") {
        setTuningSettings(businessSettingsResult.value);
      } else {
        setTuningSettings(null);
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
        const sortedRuns = sortCompetitorProfileGenerationRuns(competitorProfileRunsResult.value.items);
        setCompetitorProfileGenerationRuns(sortedRuns);
        setCompetitorProfileError(null);
        const latestRun = sortedRuns[0] || null;
        setLatestCompetitorProfileRunId(latestRun ? latestRun.id : null);
        setCompetitorProfilePollingTargetRunId(
          latestRun && !isCompetitorProfileRunTerminalStatus(latestRun.status) ? latestRun.id : null,
        );
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
            setCompetitorProfileGenerationRuns((current) =>
              upsertCompetitorProfileGenerationRun(current, detail.run),
            );
            setLatestCompetitorProfileRunId(detail.run.id);
            setCompetitorProfilePollingTargetRunId(
              !isCompetitorProfileRunTerminalStatus(detail.run.status) ? detail.run.id : null,
            );
            setCompetitorProfileDrafts(detail.drafts);
            setRejectedCompetitorCandidateCount(Math.max(0, detail.rejected_candidate_count || 0));
            setRejectedCompetitorCandidates(normalizeRejectedCompetitorCandidates(detail.rejected_candidates));
            setTuningRejectedCompetitorCandidateCount(Math.max(0, detail.tuning_rejected_candidate_count || 0));
            setTuningRejectedCompetitorCandidates(
              normalizeTuningRejectedCompetitorCandidates(detail.tuning_rejected_candidates),
            );
            setTuningRejectionReasonCounts(
              normalizeTuningRejectionReasonCounts(detail.tuning_rejection_reason_counts || null),
            );
            setCompetitorCandidatePipelineSummary(
              normalizeCompetitorCandidatePipelineSummary(detail.candidate_pipeline_summary),
            );
            setCompetitorProviderAttemptCount(Math.max(0, detail.provider_attempt_count || 0));
            setCompetitorProviderDegradedRetryUsed(Boolean(detail.provider_degraded_retry_used));
            setCompetitorProviderAttempts(normalizeCompetitorProviderAttempts(detail.provider_attempts));
            setCompetitorOutcomeSummary(detail.outcome_summary || null);
            setCompetitorProfileError(null);
          } catch (error) {
            if (cancelled) {
              return;
            }
            setCompetitorProfileDrafts([]);
            setRejectedCompetitorCandidateCount(0);
            setRejectedCompetitorCandidates([]);
            setTuningRejectedCompetitorCandidateCount(0);
            setTuningRejectedCompetitorCandidates([]);
            setTuningRejectionReasonCounts({});
            setCompetitorCandidatePipelineSummary(null);
            setCompetitorProviderAttemptCount(0);
            setCompetitorProviderDegradedRetryUsed(false);
            setCompetitorProviderAttempts([]);
            setCompetitorOutcomeSummary(null);
            setCompetitorProfileError(safeSectionErrorMessage("AI competitor profiles", error));
          } finally {
            if (!cancelled) {
              setCompetitorProfileLoading(false);
            }
          }
        } else {
          setCompetitorProfileDrafts([]);
          setRejectedCompetitorCandidateCount(0);
          setRejectedCompetitorCandidates([]);
          setTuningRejectedCompetitorCandidateCount(0);
          setTuningRejectedCompetitorCandidates([]);
          setTuningRejectionReasonCounts({});
          setCompetitorCandidatePipelineSummary(null);
          setCompetitorProviderAttemptCount(0);
          setCompetitorProviderDegradedRetryUsed(false);
          setCompetitorProviderAttempts([]);
          setCompetitorOutcomeSummary(null);
          setCompetitorProfileLoading(false);
        }
      } else {
        setCompetitorProfileGenerationRuns([]);
        setLatestCompetitorProfileRunId(null);
        setCompetitorProfilePollingTargetRunId(null);
        setCompetitorProfileDrafts([]);
        setRejectedCompetitorCandidateCount(0);
        setRejectedCompetitorCandidates([]);
        setTuningRejectedCompetitorCandidateCount(0);
        setTuningRejectedCompetitorCandidates([]);
        setTuningRejectionReasonCounts({});
        setCompetitorCandidatePipelineSummary(null);
        setCompetitorProviderAttemptCount(0);
        setCompetitorProviderDegradedRetryUsed(false);
        setCompetitorProviderAttempts([]);
        setCompetitorOutcomeSummary(null);
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
    workspaceRefreshNonce,
  ]);

  useEffect(() => {
    if (
      !context.token ||
      !context.businessId ||
      !siteId ||
      !competitorProfilePollingTargetRunId
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
        setCompetitorProfilePollingTargetRunId(null);
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
        const sortedRuns = sortCompetitorProfileGenerationRuns(runsResponse.items);
        setCompetitorProfileGenerationRuns(sortedRuns);

        const latestRun = sortedRuns[0] || null;
        const detailRunId = latestRun?.id || competitorProfilePollingTargetRunId;
        if (!detailRunId) {
          setCompetitorProfilePolling(false);
          setCompetitorProfilePollingTargetRunId(null);
          return;
        }

        setCompetitorProfileLoading(true);
        const detail = await fetchCompetitorProfileGenerationRunDetail(
          context.token,
          context.businessId,
          siteId,
          detailRunId,
        );
        if (cancelled) {
          return;
        }
        setCompetitorProfileGenerationRuns(upsertCompetitorProfileGenerationRun(sortedRuns, detail.run));
        setLatestCompetitorProfileRunId(detail.run.id);
        setCompetitorProfilePollingTargetRunId(
          !isCompetitorProfileRunTerminalStatus(detail.run.status) ? detail.run.id : null,
        );
        setCompetitorProfileDrafts(detail.drafts);
        setRejectedCompetitorCandidateCount(Math.max(0, detail.rejected_candidate_count || 0));
        setRejectedCompetitorCandidates(normalizeRejectedCompetitorCandidates(detail.rejected_candidates));
        setTuningRejectedCompetitorCandidateCount(Math.max(0, detail.tuning_rejected_candidate_count || 0));
        setTuningRejectedCompetitorCandidates(
          normalizeTuningRejectedCompetitorCandidates(detail.tuning_rejected_candidates),
        );
        setTuningRejectionReasonCounts(
          normalizeTuningRejectionReasonCounts(detail.tuning_rejection_reason_counts || null),
        );
        setCompetitorCandidatePipelineSummary(
          normalizeCompetitorCandidatePipelineSummary(detail.candidate_pipeline_summary),
        );
        setCompetitorProviderAttemptCount(Math.max(0, detail.provider_attempt_count || 0));
        setCompetitorProviderDegradedRetryUsed(Boolean(detail.provider_degraded_retry_used));
        setCompetitorProviderAttempts(normalizeCompetitorProviderAttempts(detail.provider_attempts));
        setCompetitorOutcomeSummary(detail.outcome_summary || null);
        setCompetitorProfileError(null);
        if (isCompetitorProfileRunTerminalStatus(detail.run.status)) {
          const terminalMessage = competitorProfileTerminalMessage(detail.run.status);
          if (terminalMessage) {
            setCompetitorProfileActionError(null);
            setCompetitorProfileActionMessage(terminalMessage);
          }
          setCompetitorProfilePolling(false);
          setCompetitorProfilePollingTargetRunId(null);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        setCompetitorProfileError(safeSectionErrorMessage("AI competitor profiles", error));
        setRejectedCompetitorCandidateCount(0);
        setRejectedCompetitorCandidates([]);
        setTuningRejectedCompetitorCandidateCount(0);
        setTuningRejectedCompetitorCandidates([]);
        setTuningRejectionReasonCounts({});
        setCompetitorCandidatePipelineSummary(null);
        setCompetitorProviderAttemptCount(0);
        setCompetitorProviderDegradedRetryUsed(false);
        setCompetitorProviderAttempts([]);
        setCompetitorOutcomeSummary(null);
        setCompetitorProfilePolling(false);
        setCompetitorProfilePollingTargetRunId(null);
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
    competitorProfilePollingTargetRunId,
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
        <h2>Top Insights</h2>
        <div className="metrics-grid">
          <div className="panel panel-compact">
            <strong>You have {actionableRecommendationCount} actionable improvements</strong>
          </div>
          <div className="panel panel-compact">
            <strong>{latestCompletedTuningSuggestions.length} tuning opportunities identified</strong>
          </div>
          <div className="panel panel-compact">
            <strong>
              {latestPreviewInsight || "Preview a tuning suggestion to estimate included-candidate impact"}
            </strong>
          </div>
        </div>
        <div className="panel panel-compact stack" data-testid="start-here-section">
          <span className="hint muted">Start Here</span>
          <strong>{startHereAction.title}</strong>
          <span className="hint">{startHereAction.detail}</span>
          <span className="hint muted">Why this first: {startHereAction.whyThisFirst}</span>
          {startHereAction.kind !== "none" ? (
            <button type="button" className="button button-primary" onClick={() => void handleStartHereAction()}>
              {startHereAction.buttonLabel}
            </button>
          ) : null}
        </div>
        {recommendationThemeStartHere ? (
          <div className="panel panel-compact stack-tight" data-testid="start-here-theme-helper">
            <span className="hint muted">Start here by theme</span>
            <strong>{recommendationThemeStartHere.themeLabel}</strong>
            <span className="hint">{recommendationThemeStartHere.title}</span>
            <span className="hint muted">{recommendationThemeStartHere.reason}</span>
            <div className="link-row">
              {recommendationThemeStartHere.hasCompetitorBackedContext ? (
                <span className="badge badge-muted">Competitor-backed</span>
              ) : null}
              {recommendationThemeStartHere.hasPendingRefreshContext ? (
                <span className="badge badge-warn">Refresh pending</span>
              ) : null}
            </div>
            <button
              type="button"
              className="button button-secondary button-inline"
              onClick={() => focusActionTarget(recommendationRowId(recommendationThemeStartHere.recommendation_id))}
            >
              Jump to recommendation
            </button>
          </div>
        ) : null}
      </SectionCard>

      {showZipCaptureModal ? (
        <div className="workspace-modal-backdrop" data-testid="zip-capture-modal">
          <div className="workspace-modal panel stack">
            <h3>Where do you primarily do business?</h3>
            <p className="hint">
              Enter your ZIP code so we can find the most relevant local competitors and recommendations.
            </p>
            <label className="stack-tight">
              <span className="hint muted">Primary business ZIP code</span>
              <input
                type="text"
                inputMode="numeric"
                autoComplete="postal-code"
                maxLength={5}
                value={zipCaptureInput}
                onChange={(event) => {
                  setZipCaptureInput(normalizePrimaryBusinessZipInput(event.target.value));
                  setZipCaptureError(null);
                }}
                placeholder="80538"
              />
            </label>
            {zipCaptureError ? <p className="hint warning">{zipCaptureError}</p> : null}
            <div className="form-actions">
              <button
                type="button"
                className="button button-primary"
                onClick={() => void handleSavePrimaryBusinessZip()}
                disabled={zipCaptureSaving}
              >
                {zipCaptureSaving ? "Saving..." : "Save"}
              </button>
              <button
                type="button"
                className="button button-secondary"
                onClick={handleSkipZipCapture}
                disabled={zipCaptureSaving}
              >
                Skip for now
              </button>
            </div>
            <p className="hint muted">
              Current location context:{" "}
              {sitePrimaryLocation || siteLocationContext || "Location not yet established from available data."}
            </p>
          </div>
        </div>
      ) : null}

      {aiOpportunities.length > 0 ? (
        <SectionCard>
          <h2>AI Opportunities</h2>
          <p className="hint muted">AI suggestions are advisory and should be reviewed.</p>
          <div className="stack" data-testid="ai-opportunities-section">
            {/* AI opportunity cards keep deterministic recommendations authoritative while exposing advisory AI context. */}
            {visibleAiOpportunities.map((opportunity) => {
              const { recommendation, linkedSuggestions, whyThisMatters, isSourceAi } = opportunity;
              const isExpanded = expandedAiOpportunityIds.has(recommendation.id);
              const recommendationRunId = latestCompletedRecommendationRun?.id || null;
              const primaryLinkedSuggestion = linkedSuggestions[0] || null;
              const linkedSuggestionWithPreview =
                recommendationRunId
                  ? linkedSuggestions.find((suggestion) =>
                      Boolean(tuningPreviewByKey[buildTuningPreviewKey(recommendationRunId, suggestion)]),
                    ) || null
                  : null;
              const hasDirectAction = Boolean(recommendationRunId && primaryLinkedSuggestion);
              const previewSuggestion = linkedSuggestionWithPreview || null;
              const previewKey =
                recommendationRunId && previewSuggestion
                  ? buildTuningPreviewKey(recommendationRunId, previewSuggestion)
                  : null;
              const preview = previewKey ? tuningPreviewByKey[previewKey] : null;
              const whyText =
                whyThisMatters || "AI narrative guidance is available for this recommendation run.";
              const collapsedWhyText = truncateOptionalText(whyText, 180) || whyText;
              return (
                <article key={recommendation.id} className="panel panel-compact stack" data-testid="ai-opportunity-card">
                  <div className="stack-tight">
                    <div className="link-row">
                      <strong>
                        <Link href={buildRecommendationDetailHref(recommendation.id, selectedSite.id)}>
                          {recommendation.title}
                        </Link>
                      </strong>
                      <span className="badge badge-success">AI Suggested</span>
                    </div>
                    <span className="hint muted">
                      {recommendation.category} • {recommendation.severity} • {recommendation.priority_band} priority
                    </span>
                    {isSourceAi ? <span className="hint muted">AI source flag present on this recommendation.</span> : null}
                  </div>

                  <div className="stack-tight">
                    <span className="hint muted">Why this matters</span>
                    <span className="hint">{isExpanded ? whyText : collapsedWhyText}</span>
                  </div>

                  <div className="stack-tight">
                    <span className="hint muted">Expected outcome</span>
                    <span className="hint">{recommendationExpectedOutcome(recommendation)}</span>
                  </div>

                  <div className="stack-tight">
                    <span className="hint muted">Action bridge</span>
                    <span className="hint muted">Action is executed through tuning suggestions.</span>
                    {hasDirectAction ? (
                      <span className="hint success">Backed by tuning suggestion</span>
                    ) : (
                      <span className="hint muted">No direct action available yet.</span>
                    )}
                  </div>

                  {hasDirectAction && primaryLinkedSuggestion && recommendationRunId ? (
                    <div className="stack-tight">
                      <div className="form-actions">
                        <button
                          type="button"
                          className="button button-primary button-inline"
                          onClick={() =>
                            focusLinkedTuningSuggestion(
                              recommendationRunId,
                              primaryLinkedSuggestion,
                              recommendation,
                            )
                          }
                        >
                          View Recommended Action
                        </button>
                        {preview && previewSuggestion ? (
                          <button
                            type="button"
                            className="button button-secondary button-inline"
                            onClick={() =>
                              focusLinkedTuningSuggestion(
                                recommendationRunId,
                                previewSuggestion,
                                recommendation,
                              )
                            }
                          >
                            View Preview
                          </button>
                        ) : null}
                      </div>
                      {preview ? (
                        <>
                          <span className="hint muted">Expected impact (from preview):</span>
                          <span className="hint">{preview.estimated_impact.summary}</span>
                        </>
                      ) : (
                        <span className="hint muted">Impact will be reflected in next run.</span>
                      )}
                    </div>
                  ) : null}

                  {isExpanded ? (
                    <div className="stack-tight">
                      <span className="hint muted">How to act on this</span>
                      {hasDirectAction ? (
                        <span className="hint">Use the recommended tuning below.</span>
                      ) : (
                        <span className="hint">No direct tuning action is currently available.</span>
                      )}
                      {preview ? (
                        <span className="hint">Preview shows expected impact before applying.</span>
                      ) : null}
                      {linkedSuggestions.length > 0 ? (
                        <>
                          <span className="hint muted">Supporting signals</span>
                          <ul>
                            {linkedSuggestions.map((suggestion) => (
                              <li key={`${recommendation.id}-${suggestion.setting}-${suggestion.recommended_value}`}>
                                <span className="hint">
                                  {formatTuningSettingLabel(suggestion.setting)}: {suggestion.current_value} -&gt;{" "}
                                  {suggestion.recommended_value} ({suggestion.confidence})
                                </span>
                              </li>
                            ))}
                          </ul>
                        </>
                      ) : null}
                      {latestCompletedRecommendationNarrative?.top_themes_json.length ? (
                        <span className="hint muted">
                          Related context: {latestCompletedRecommendationNarrative.top_themes_json.join(", ")}
                        </span>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="form-actions">
                    <button
                      type="button"
                      className="button button-tertiary button-inline"
                      onClick={() => toggleAiOpportunityExpansion(recommendation.id)}
                    >
                      {isExpanded ? "Hide details" : "View details"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
          {aiOpportunities.length > AI_OPPORTUNITY_INITIAL_COUNT ? (
            <div className="form-actions">
              <button
                type="button"
                className="button button-secondary button-inline"
                onClick={() => setShowAllAiOpportunities((current) => !current)}
              >
                {showAllAiOpportunities
                  ? "Show fewer AI opportunities"
                  : `View more AI opportunities (${hiddenAiOpportunityCount} more)`}
              </button>
            </div>
          ) : null}
        </SectionCard>
      ) : null}

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
                      className="button button-secondary button-inline"
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
            className="button button-primary"
            onClick={() => void handleGenerateCompetitorProfiles()}
            disabled={loadingWorkspace || generationInFlight || retryInFlight || competitorProfileLoading}
          >
            {generationInFlight ? "Queuing..." : "Generate Competitor Profiles"}
          </button>
          {latestCompetitorProfileRun?.status === "failed" ? (
            <button
              type="button"
              className="button button-secondary"
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
            <code>{latestCompetitorProfileRun.model_name}</code> | Prompt Version:{" "}
            <code>{latestCompetitorProfileRun.prompt_version}</code>
          </p>
        ) : null}
        {competitorRunOutcomeSummary ? (
          <div className="stack" data-testid="competitor-run-outcome-summary">
            <p className="hint muted">
              <strong>Run quality</strong>: proposed {competitorRunOutcomeSummary.proposedCount} | returned{" "}
              {competitorRunOutcomeSummary.returnedCount} | rejected {competitorRunOutcomeSummary.rejectedCount} |
              degraded mode {competitorRunOutcomeSummary.degradedModeUsed ? "yes" : "no"} | search-backed{" "}
              {competitorRunOutcomeSummary.searchBacked ? "yes" : "no"}
            </p>
            {competitorOutcomeSummary ? (
              <p
                className={competitorOutcomeHintClass(competitorOutcomeSummary.status_level)}
                data-testid="competitor-operator-outcome-summary"
              >
                <strong>Outcome:</strong> {formatCompetitorOutcomeStatusLevel(competitorOutcomeSummary.status_level)}
                {competitorOutcomeSummary.used_synthetic_fallback ? " (synthetic fallback)" : ""}.{" "}
                {competitorOutcomeSummary.message}
              </p>
            ) : null}
            {competitorOutcomeSummary?.used_timeout_recovery ? (
              <p className="hint muted">Recovered after provider timeout during this run.</p>
            ) : null}
            {competitorOutcomeSummary?.used_google_places_seeds ? (
              <p className="hint muted">
                Nearby business seed discovery was used before AI enrichment in this run.
              </p>
            ) : null}
            {competitorOutcomeSummary?.had_schema_repair_or_discard ? (
              <p className="hint muted">
                Some malformed provider candidate entries were safely discarded during parsing.
              </p>
            ) : null}
            {competitorRunOutcomeSummary.statusNote ? (
              <p className="hint muted">{competitorRunOutcomeSummary.statusNote}</p>
            ) : null}
            {competitorRunOutcomeSummary.filteringSummary ? (
              <p className="hint muted">{competitorRunOutcomeSummary.filteringSummary}</p>
            ) : null}
            {competitorRunOutcomeSummary.searchEscalationNote ? (
              <p className="hint muted">{competitorRunOutcomeSummary.searchEscalationNote}</p>
            ) : null}
            {competitorRunOutcomeSummary.relaxedFilteringNote ? (
              <p className="hint muted">{competitorRunOutcomeSummary.relaxedFilteringNote}</p>
            ) : null}
            {competitorRunOutcomeSummary.lowResultNote ? (
              <p className="hint warning">{competitorRunOutcomeSummary.lowResultNote}</p>
            ) : null}
          </div>
        ) : null}
        {latestCompetitorPromptPreview ? (
          <PromptPreviewPanel
            preview={latestCompetitorPromptPreview}
            copyFeedback={promptPreviewCopyFeedbackByType.competitor}
            onCopy={() => void handleCopyPromptPreview("competitor")}
            onDownload={() => handleDownloadPromptPreview("competitor")}
            testId="competitor-prompt-preview"
          />
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
            {competitorProfileSummary.last_n_preview_accuracy &&
            competitorProfileSummary.last_n_preview_accuracy.sample_size > 0 ? (
              <p className="hint muted">
                Preview accuracy (last {competitorProfileSummary.last_n_preview_accuracy.sample_size}):{" "}
                {Math.round(
                  (competitorProfileSummary.last_n_preview_accuracy.accuracy_rate || 0) * 100,
                )}
                % directionally correct
                {typeof competitorProfileSummary.last_n_preview_accuracy.avg_error_margin === "number"
                  ? ` | avg error margin ${competitorProfileSummary.last_n_preview_accuracy.avg_error_margin.toFixed(1)}`
                  : ""}
              </p>
            ) : null}
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
        {rejectedCompetitorCandidateCount > 0 && rejectedCompetitorCandidates.length > 0 ? (
          <div className="stack" data-testid="rejected-competitor-candidates-debug">
            <p className="hint muted">
              <strong>Rejected competitor candidates (debug)</strong>: {rejectedCompetitorCandidateCount}
            </p>
            <div className="table-container table-container-compact">
              <table className="table">
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>Reasons</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {rejectedCompetitorCandidates.map((candidate) => (
                    <tr key={`${candidate.domain}-${candidate.reasons.join("-")}`}>
                      <td>
                        <code>{candidate.domain}</code>
                      </td>
                      <td>
                        <div className="stack-micro">
                          {candidate.reasons.map((reason) => (
                            <span key={`${candidate.domain}-${reason}`} className="badge badge-muted">
                              {formatFailureCategory(reason)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="table-cell-wrap">{candidate.summary || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rejectedCompetitorCandidateCount > rejectedCompetitorCandidates.length ? (
              <p className="hint muted">
                Showing {rejectedCompetitorCandidates.length} of {rejectedCompetitorCandidateCount} rejected
                candidates.
              </p>
            ) : null}
          </div>
        ) : null}
        {tuningRejectedCompetitorCandidateCount > 0 && tuningRejectedCompetitorCandidates.length > 0 ? (
          <div className="stack" data-testid="tuning-rejected-competitor-candidates-debug">
            <p className="hint muted">
              <strong>Removed by tuning (debug)</strong>: {tuningRejectedCompetitorCandidateCount}
            </p>
            {Object.values(tuningRejectionReasonCounts).some((count) => count > 0) ? (
              <p className="hint muted">
                Reason counts:{" "}
                {Object.entries(tuningRejectionReasonCounts)
                  .filter(([, count]) => count > 0)
                  .sort(([left], [right]) => left.localeCompare(right))
                  .map(([reason, count]) => `${formatFailureCategory(reason)}=${count}`)
                  .join(", ")}
              </p>
            ) : null}
            <div className="table-container table-container-compact">
              <table className="table">
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>Reasons</th>
                    <th>Final score</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {tuningRejectedCompetitorCandidates.map((candidate) => (
                    <tr key={`${candidate.domain}-${candidate.reasons.join("-")}`}>
                      <td>
                        <code>{candidate.domain}</code>
                      </td>
                      <td>
                        <div className="stack-micro">
                          {candidate.reasons.map((reason) => (
                            <span key={`${candidate.domain}-${reason}`} className="badge badge-muted">
                              {formatFailureCategory(reason)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>{typeof candidate.final_score === "number" ? candidate.final_score : "-"}</td>
                      <td className="table-cell-wrap">{candidate.summary || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {tuningRejectedCompetitorCandidateCount > tuningRejectedCompetitorCandidates.length ? (
              <p className="hint muted">
                Showing {tuningRejectedCompetitorCandidates.length} of {tuningRejectedCompetitorCandidateCount}{" "}
                removed-by-tuning candidates.
              </p>
            ) : null}
          </div>
        ) : null}
        {competitorCandidatePipelineSummary ? (
          <div className="stack" data-testid="competitor-candidate-pipeline-summary-debug">
            <p className="hint muted">
              <strong>Candidate pipeline (debug)</strong>
            </p>
            <p className="hint muted">Proposed: {competitorCandidatePipelineSummary.proposed_candidate_count}</p>
            <p className="hint muted">
              Rejected by eligibility: {competitorCandidatePipelineSummary.rejected_by_eligibility_count}
            </p>
            <p className="hint muted">
              Eligible after filtering: {competitorCandidatePipelineSummary.eligible_candidate_count}
            </p>
            <p className="hint muted">
              Removed by tuning: {competitorCandidatePipelineSummary.rejected_by_tuning_count}
            </p>
            <p className="hint muted">
              Survived tuning: {competitorCandidatePipelineSummary.survived_tuning_count}
            </p>
            <p className="hint muted">
              Removed by existing-domain match:{" "}
              {competitorCandidatePipelineSummary.removed_by_existing_domain_match_count}
            </p>
            <p className="hint muted">
              Removed by deduplication: {competitorCandidatePipelineSummary.removed_by_deduplication_count}
            </p>
            <p className="hint muted">
              Removed by final limit: {competitorCandidatePipelineSummary.removed_by_final_limit_count}
            </p>
            <p className="hint muted">Final returned: {competitorCandidatePipelineSummary.final_candidate_count}</p>
          </div>
        ) : null}
        {competitorProviderAttemptCount > 0 && competitorProviderAttempts.length > 0 ? (
          <div className="stack" data-testid="competitor-provider-attempts-debug">
            <p className="hint muted">
              <strong>Provider attempts (debug)</strong>: {competitorProviderAttemptCount}
            </p>
            <p className="hint muted">
              Degraded timeout retry used: {competitorProviderDegradedRetryUsed ? "yes" : "no"}
            </p>
            <div className="table-container table-container-compact">
              <table className="table">
                <thead>
                  <tr>
                    <th>Attempt</th>
                    <th>Mode</th>
                    <th>Reduced context</th>
                    <th>Outcome</th>
                    <th>Duration</th>
                    <th>Prompt chars</th>
                    <th>Timeout</th>
                    <th>Endpoint</th>
                    <th>Web search</th>
                  </tr>
                </thead>
                <tbody>
                  {competitorProviderAttempts.map((attempt) => (
                    <tr key={`provider-attempt-${attempt.attempt_number}`}>
                      <td>{attempt.attempt_number}</td>
                      <td>{attempt.degraded_mode ? "degraded_retry" : "standard"}</td>
                      <td>{attempt.reduced_context_mode ? "yes" : "no"}</td>
                      <td>{formatProviderAttemptOutcome(attempt.outcome, attempt.failure_kind)}</td>
                      <td>
                        {typeof attempt.request_duration_ms === "number"
                          ? `${Math.max(0, Math.round(attempt.request_duration_ms))} ms`
                          : "-"}
                      </td>
                      <td>
                        {typeof attempt.prompt_total_chars === "number"
                          ? Math.max(0, Math.round(attempt.prompt_total_chars)).toLocaleString()
                          : "-"}
                      </td>
                      <td>
                        {typeof attempt.timeout_seconds === "number"
                          ? `${Math.max(1, Math.round(attempt.timeout_seconds))} s`
                          : "-"}
                      </td>
                      <td>{attempt.endpoint_path || "-"}</td>
                      <td>
                        {attempt.web_search_enabled === null
                          ? "-"
                          : attempt.web_search_enabled
                            ? "enabled"
                            : "disabled"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {competitorProviderAttemptCount > competitorProviderAttempts.length ? (
              <p className="hint muted">
                Showing {competitorProviderAttempts.length} of {competitorProviderAttemptCount} provider attempts.
              </p>
            ) : null}
          </div>
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
                  const provenanceLabel = formatCompetitorDraftProvenanceLabel(draft.provenance_classification);
                  return (
                    <Fragment key={draft.id}>
                      <tr data-testid="competitor-profile-draft-row">
                        <td className="table-cell-wrap">
                          <strong>{draft.suggested_name}</strong>
                          <br />
                          <code>{draft.suggested_domain}</code>
                          {provenanceLabel ? (
                            <>
                              <br />
                              <span className={competitorDraftProvenanceHintClass(draft.provenance_classification)}>
                                <strong>Source:</strong> {provenanceLabel}
                              </span>
                            </>
                          ) : null}
                        </td>
                        <td>{draft.competitor_type}</td>
                        <td>{draft.confidence_score.toFixed(2)}</td>
                        <td className="table-cell-wrap">
                          {truncateText(draft.summary || "No summary provided.", 140)}
                          <br />
                          <span className="hint muted">
                            <strong>Why this competitor:</strong>{" "}
                            {truncateText(draft.why_competitor || "Reasoning not provided.", 140)}
                          </span>
                          {draft.provenance_explanation ? (
                            <>
                              <br />
                              <span className={competitorDraftProvenanceHintClass(draft.provenance_classification)}>
                                <strong>Selection basis:</strong> {truncateText(draft.provenance_explanation, 160)}
                              </span>
                            </>
                          ) : null}
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
                                className="button button-primary button-inline"
                                onClick={() => void handleAcceptCompetitorProfileDraft(draft.id)}
                                disabled={!editable || actionDisabled}
                              >
                                {draftActionTargetId === draft.id ? "Applying..." : "Accept"}
                              </button>
                              <button
                                type="button"
                                className="button button-danger button-inline"
                                onClick={() => void handleRejectCompetitorProfileDraft(draft.id)}
                                disabled={!editable || actionDisabled}
                              >
                                {draftActionTargetId === draft.id ? "Applying..." : "Reject"}
                              </button>
                              <button
                                type="button"
                                className="button button-tertiary button-inline"
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
                                  className="button button-secondary button-inline"
                                  onClick={() => void handleSaveDraftEdit(draft.id)}
                                  disabled={editActionInFlight || draftActionTargetId === draft.id}
                                >
                                  {editActionInFlight ? "Saving..." : "Save Edits"}
                                </button>
                                <button
                                  type="button"
                                  className="button button-primary button-inline"
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
                                  className="button button-tertiary button-inline"
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
        <div className="stack-tight">
          <div className="form-actions">
            <button
              type="button"
              className="button button-primary"
              onClick={() => void handleGenerateRecommendations()}
              disabled={loadingWorkspace || recommendationGenerationInFlight || !recommendationGenerationPrerequisitesMet}
            >
              {recommendationGenerationInFlight ? "Generating..." : "Generate Recommendations"}
            </button>
          </div>
          <p className="hint muted">
            Creates a recommendation run from the latest completed audit and/or competitor comparison inputs.
          </p>
          {!loadingWorkspace && !recommendationGenerationPrerequisitesMet ? (
            <p className="hint warning">
              Run site audit before generating recommendations.
            </p>
          ) : null}
          {recommendationGenerationError ? <p className="hint error">{recommendationGenerationError}</p> : null}
          {recommendationGenerationMessage ? <p className="hint success">{recommendationGenerationMessage}</p> : null}
        </div>
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
          <p className="hint muted">No recommendations yet — generate recommendations to analyze this site.</p>
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
        <h3>Latest Completed Run</h3>
        {latestCompletedRecommendationsError ? (
          <p className="hint warning">{latestCompletedRecommendationsError}</p>
        ) : null}
        {recommendationWorkspaceSummaryState === "no_runs" && !latestCompletedRecommendationsError ? (
          <p className="hint muted">No recommendation runs have been recorded for this site yet.</p>
        ) : null}
        {recommendationWorkspaceSummaryState === "no_completed_runs" && !latestCompletedRecommendationsError ? (
          <p className="hint muted">
            No completed recommendation run is available yet.
            {latestRecommendationRun ? (
              <>
                {" "}
                Latest run{" "}
                <Link href={buildRecommendationRunHref(latestRecommendationRun.id, selectedSite.id)}>
                  {latestRecommendationRun.id}
                </Link>{" "}
                is currently <strong>{latestRecommendationRun.status}</strong>.
              </>
            ) : null}
            </p>
        ) : null}
        {latestCompletedRecommendationRun ? (
          <div className="stack">
            <p>
              Run:{" "}
              <Link href={buildRecommendationRunHref(latestCompletedRecommendationRun.id, selectedSite.id)}>
                {latestCompletedRecommendationRun.id}
              </Link>{" "}
              ({latestCompletedRecommendationRun.status})
            </p>
            <p className="hint muted">
              Created {formatDateTime(latestCompletedRecommendationRun.created_at)} | Completed{" "}
              {formatDateTime(latestCompletedRecommendationRun.completed_at)} | Total{" "}
              {latestCompletedRecommendationRun.total_recommendations} | Critical{" "}
              {latestCompletedRecommendationRun.critical_recommendations} | Warning{" "}
              {latestCompletedRecommendationRun.warning_recommendations} | Info{" "}
              {latestCompletedRecommendationRun.info_recommendations}
            </p>
            {recommendationOrderingExplanation ? (
              <div className="panel panel-compact stack-tight" data-testid="recommendation-ordering-explanation">
                <span className="hint muted">Why this order</span>
                <span className="hint">{recommendationOrderingExplanation.message}</span>
                {recommendationOrderingExplanation.contextReasons.length > 0 ? (
                  <div className="link-row">
                    {recommendationOrderingExplanation.contextReasons.map((reason) => (
                      <span key={`ordering-reason-${reason}`} className="badge badge-muted">
                        {formatPriorityReason(reason)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            <h4>Deterministic Recommendations</h4>
            {!latestCompletedRecommendationsError && latestCompletedRecommendations.length === 0 ? (
              <p className="hint muted">No recommendations yet — generate recommendations to analyze this site.</p>
            ) : null}
            {latestCompletedRecommendations.length > 0 ? (
              recommendationThemeSections.length <= 1 ? (
                <div className="table-container">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Recommendation</th>
                        <th>Category</th>
                        <th>Severity</th>
                        <th>Priority</th>
                        <th>Status</th>
                        <th>Deterministic Rationale</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(recommendationThemeSections[0]?.items || latestCompletedRecommendations).map((item, index) => {
                        const recommendationRank = recommendationRankById.get(item.id) ?? index;
                        const impactLabel = recommendationImpactLabel(item, recommendationRank);
                        const eeatCategories = normalizeEEATCategories(item.eeat_categories);
                        const priorityReasons = normalizeRecommendationPriorityReasons(item.priority_reasons);
                        const recommendationProgress = normalizeRecommendationProgress(item);
                        const recommendationLifecycle = normalizeRecommendationLifecycle(item);
                        const recommendationEvidenceSummary = normalizeRecommendationEvidenceSummary(item);
                        const recommendationObservedGapSummary = normalizeRecommendationObservedGapSummary(item);
                        const recommendationEvidenceTrace = normalizeRecommendationEvidenceTrace(item);
                        const renderObservedGapSummary = recommendationObservedGapSummary
                          && recommendationObservedGapSummary.toLowerCase() !== recommendationEvidenceSummary?.toLowerCase();
                        const recommendationActionClarity = normalizeRecommendationActionClarity(item);
                        const recommendationExpectedOutcome = normalizeRecommendationExpectedOutcome(item);
                        const recommendationTargetContext = normalizeRecommendationTargetContext(item);
                        const recommendationTargetPageHints = normalizeRecommendationTargetPageHints(item);
                        const rowId = recommendationRowId(item.id);
                        return (
                          <tr
                            key={item.id}
                            id={rowId}
                            className={startHereFocusedTargetId === rowId ? "start-here-target-active" : undefined}
                          >
                            <td className="table-cell-wrap">
                              <Link href={buildRecommendationDetailHref(item.id, selectedSite.id)}>{item.title}</Link>
                              <br />
                              {impactLabel ? (
                                <>
                                  <span className={recommendationImpactBadgeClass(impactLabel)}>{impactLabel}</span>
                                  <br />
                                </>
                              ) : null}
                              {eeatCategories.length > 0 ? (
                                <>
                                  <span className="hint muted">EEAT impact</span>
                                  <div className="link-row" data-testid="recommendation-eeat-badges">
                                    {eeatCategories.map((category) => (
                                      <span key={`${item.id}-${category}`} className="badge badge-muted">
                                        {formatEEATCategory(category)}
                                      </span>
                                    ))}
                                  </div>
                                </>
                              ) : null}
                              {priorityReasons.length > 0 ? (
                                <>
                                  <span className="hint muted">Why surfaced</span>
                                  <div className="link-row" data-testid="recommendation-priority-reasons">
                                    {priorityReasons.map((reason) => (
                                      <span key={`${item.id}-${reason}`} className="badge badge-muted">
                                        {formatPriorityReason(reason)}
                                      </span>
                                    ))}
                                  </div>
                                </>
                              ) : null}
                              <span className="hint muted">Progress</span>
                              <div className="link-row" data-testid="recommendation-progress-status">
                                <span className={recommendationProgress.badgeClass}>{recommendationProgress.label}</span>
                                <span className="hint muted">{recommendationProgress.summary}</span>
                              </div>
                              {recommendationLifecycle ? (
                                <>
                                  <span className="hint muted">Lifecycle</span>
                                  <div className="link-row" data-testid="recommendation-lifecycle-state">
                                    <span className={recommendationLifecycle.badgeClass}>{recommendationLifecycle.label}</span>
                                    <span className="hint muted">{recommendationLifecycle.summary}</span>
                                  </div>
                                </>
                              ) : null}
                              {recommendationEvidenceSummary ? (
                                <span className="hint muted" data-testid="recommendation-evidence-summary">
                                  Why this matters: {recommendationEvidenceSummary}
                                </span>
                              ) : null}
                              {recommendationEvidenceTrace.length > 0 ? (
                                <span className="hint muted" data-testid="recommendation-evidence-trace">
                                  Evidence trace: {recommendationEvidenceTrace.join(" · ")}
                                </span>
                              ) : null}
                              {renderObservedGapSummary ? (
                                <span className="hint muted" data-testid="recommendation-observed-gap-summary">
                                  Observed gap: {recommendationObservedGapSummary}
                                </span>
                              ) : null}
                              {recommendationActionClarity ? (
                                <span className="hint muted" data-testid="recommendation-action-clarity">
                                  Action: {recommendationActionClarity}
                                </span>
                              ) : null}
                              {recommendationExpectedOutcome ? (
                                <span className="hint muted" data-testid="recommendation-expected-outcome">
                                  Expected outcome: {recommendationExpectedOutcome}
                                </span>
                              ) : null}
                              {recommendationTargetContext ? (
                                <span className="hint muted" data-testid="recommendation-target-context">
                                  Where: {formatRecommendationTargetContext(recommendationTargetContext)}
                                </span>
                              ) : null}
                              {recommendationTargetPageHints.length > 0 ? (
                                <span className="hint muted" data-testid="recommendation-target-page-hints">
                                  Likely pages: {recommendationTargetPageHints.join(", ")}
                                </span>
                              ) : null}
                              <span className="hint muted"><code>{item.id}</code></span>
                            </td>
                            <td>{item.category}</td>
                            <td>{item.severity}</td>
                            <td>
                              {item.priority_score} ({item.priority_band})
                            </td>
                            <td>{item.status}</td>
                            <td className="table-cell-wrap">{truncateText(item.rationale, 180)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="stack" data-testid="recommendation-theme-groups">
                  {recommendationThemeSections.map((section) => (
                    <div
                      key={`theme-${section.theme}`}
                      className="stack-tight"
                      data-testid={`recommendation-theme-group-${section.theme}`}
                    >
                      <div className="link-row">
                        <strong>{section.label}</strong>
                        <span className="badge badge-muted">{section.items.length}</span>
                      </div>
                      <span
                        className="hint muted"
                        data-testid={`recommendation-theme-summary-${section.theme}`}
                      >
                        {formatRecommendationThemeSummary(section.theme)}
                      </span>
                      <div className="table-container">
                        <table className="table">
                          <thead>
                            <tr>
                              <th>Recommendation</th>
                              <th>Category</th>
                              <th>Severity</th>
                              <th>Priority</th>
                              <th>Status</th>
                              <th>Deterministic Rationale</th>
                            </tr>
                          </thead>
                          <tbody>
                            {section.items.map((item, index) => {
                              const recommendationRank = recommendationRankById.get(item.id) ?? index;
                              const impactLabel = recommendationImpactLabel(item, recommendationRank);
                              const eeatCategories = normalizeEEATCategories(item.eeat_categories);
                              const priorityReasons = normalizeRecommendationPriorityReasons(item.priority_reasons);
                              const recommendationProgress = normalizeRecommendationProgress(item);
                              const recommendationLifecycle = normalizeRecommendationLifecycle(item);
                              const recommendationEvidenceSummary = normalizeRecommendationEvidenceSummary(item);
                              const recommendationObservedGapSummary = normalizeRecommendationObservedGapSummary(item);
                              const recommendationEvidenceTrace = normalizeRecommendationEvidenceTrace(item);
                              const renderObservedGapSummary = recommendationObservedGapSummary
                                && recommendationObservedGapSummary.toLowerCase() !== recommendationEvidenceSummary?.toLowerCase();
                              const recommendationActionClarity = normalizeRecommendationActionClarity(item);
                              const recommendationExpectedOutcome = normalizeRecommendationExpectedOutcome(item);
                              const recommendationTargetContext = normalizeRecommendationTargetContext(item);
                              const recommendationTargetPageHints = normalizeRecommendationTargetPageHints(item);
                              const rowId = recommendationRowId(item.id);
                              return (
                                <tr
                                  key={item.id}
                                  id={rowId}
                                  className={startHereFocusedTargetId === rowId ? "start-here-target-active" : undefined}
                                >
                                  <td className="table-cell-wrap">
                                    <Link href={buildRecommendationDetailHref(item.id, selectedSite.id)}>{item.title}</Link>
                                    <br />
                                    {impactLabel ? (
                                      <>
                                        <span className={recommendationImpactBadgeClass(impactLabel)}>{impactLabel}</span>
                                        <br />
                                      </>
                                    ) : null}
                                    {eeatCategories.length > 0 ? (
                                      <>
                                        <span className="hint muted">EEAT impact</span>
                                        <div className="link-row" data-testid="recommendation-eeat-badges">
                                          {eeatCategories.map((category) => (
                                            <span key={`${item.id}-${category}`} className="badge badge-muted">
                                              {formatEEATCategory(category)}
                                            </span>
                                          ))}
                                        </div>
                                      </>
                                    ) : null}
                                    {priorityReasons.length > 0 ? (
                                      <>
                                        <span className="hint muted">Why surfaced</span>
                                        <div className="link-row" data-testid="recommendation-priority-reasons">
                                          {priorityReasons.map((reason) => (
                                            <span key={`${item.id}-${reason}`} className="badge badge-muted">
                                              {formatPriorityReason(reason)}
                                            </span>
                                          ))}
                                        </div>
                                      </>
                                    ) : null}
                                    <span className="hint muted">Progress</span>
                                    <div className="link-row" data-testid="recommendation-progress-status">
                                      <span className={recommendationProgress.badgeClass}>{recommendationProgress.label}</span>
                                      <span className="hint muted">{recommendationProgress.summary}</span>
                                    </div>
                                    {recommendationLifecycle ? (
                                      <>
                                        <span className="hint muted">Lifecycle</span>
                                        <div className="link-row" data-testid="recommendation-lifecycle-state">
                                          <span className={recommendationLifecycle.badgeClass}>
                                            {recommendationLifecycle.label}
                                          </span>
                                          <span className="hint muted">{recommendationLifecycle.summary}</span>
                                        </div>
                                      </>
                                    ) : null}
                                    {recommendationEvidenceSummary ? (
                                      <span className="hint muted" data-testid="recommendation-evidence-summary">
                                        Why this matters: {recommendationEvidenceSummary}
                                      </span>
                                    ) : null}
                                    {recommendationEvidenceTrace.length > 0 ? (
                                      <span className="hint muted" data-testid="recommendation-evidence-trace">
                                        Evidence trace: {recommendationEvidenceTrace.join(" · ")}
                                      </span>
                                    ) : null}
                                    {renderObservedGapSummary ? (
                                      <span className="hint muted" data-testid="recommendation-observed-gap-summary">
                                        Observed gap: {recommendationObservedGapSummary}
                                      </span>
                                    ) : null}
                                    {recommendationActionClarity ? (
                                      <span className="hint muted" data-testid="recommendation-action-clarity">
                                        Action: {recommendationActionClarity}
                                      </span>
                                    ) : null}
                                    {recommendationExpectedOutcome ? (
                                      <span className="hint muted" data-testid="recommendation-expected-outcome">
                                        Expected outcome: {recommendationExpectedOutcome}
                                      </span>
                                    ) : null}
                                    {recommendationTargetContext ? (
                                      <span className="hint muted" data-testid="recommendation-target-context">
                                        Where: {formatRecommendationTargetContext(recommendationTargetContext)}
                                      </span>
                                    ) : null}
                                    {recommendationTargetPageHints.length > 0 ? (
                                      <span className="hint muted" data-testid="recommendation-target-page-hints">
                                        Likely pages: {recommendationTargetPageHints.join(", ")}
                                      </span>
                                    ) : null}
                                    <span className="hint muted"><code>{item.id}</code></span>
                                  </td>
                                  <td>{item.category}</td>
                                  <td>{item.severity}</td>
                                  <td>
                                    {item.priority_score} ({item.priority_band})
                                  </td>
                                  <td>{item.status}</td>
                                  <td className="table-cell-wrap">{truncateText(item.rationale, 180)}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              )
            ) : null}
            <h4>AI Narrative Overlay</h4>
            {latestRecommendationPromptPreview ? (
              <PromptPreviewPanel
                preview={latestRecommendationPromptPreview}
                copyFeedback={promptPreviewCopyFeedbackByType.recommendation}
                onCopy={() => void handleCopyPromptPreview("recommendation")}
                onDownload={() => handleDownloadPromptPreview("recommendation")}
                testId="recommendation-prompt-preview"
              />
            ) : null}
            {latestCompletedRecommendationNarrative ? (
              <div className="stack">
                <p className="hint muted">
                  Narrative v{latestCompletedRecommendationNarrative.version} (
                  {latestCompletedRecommendationNarrative.status}) | Provider{" "}
                  {latestCompletedRecommendationNarrative.provider_name} | Model{" "}
                  {latestCompletedRecommendationNarrative.model_name} | Template{" "}
                  {latestCompletedRecommendationNarrative.prompt_version}
                </p>
                <p>
                  <Link
                    href={buildNarrativeDetailHref(
                      latestCompletedRecommendationRun.id,
                      latestCompletedRecommendationNarrative.id,
                      selectedSite.id,
                    )}
                  >
                    Open latest narrative
                  </Link>
                </p>
                {narrativeActionSummary ? (
                  <div className="panel panel-compact stack" data-testid="narrative-action-summary">
                    <span className="hint muted">Next best move</span>
                    <strong>{narrativeActionSummary.primaryAction}</strong>
                    {narrativeActionSummary.whyItMatters ? (
                      <span className="hint">Why this matters: {narrativeActionSummary.whyItMatters}</span>
                    ) : null}
                    {narrativeEEATFocusCategories.length > 0 ? (
                      <span className="hint muted">
                        EEAT focus: {narrativeEEATFocusCategories.map((category) => formatEEATCategory(category)).join(", ")}
                      </span>
                    ) : null}
                    {narrativeActionSummary.firstStep ? (
                      <span className="hint success">Start here: {narrativeActionSummary.firstStep}</span>
                    ) : null}
                    {narrativeActionSummary.evidence.length > 0 ? (
                      <div className="stack-tight">
                        <span className="hint muted">Evidence</span>
                        <div className="link-row">
                          {narrativeActionSummary.evidence.map((evidenceItem) => (
                            <span key={evidenceItem} className="badge badge-muted">
                              {evidenceItem}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {narrativeCompetitorInfluence ? (
                  <div className="panel panel-compact stack-tight" data-testid="narrative-competitor-influence">
                    <span className="hint muted">Competitor-informed</span>
                    {narrativeCompetitorInfluence.summary ? (
                      <span className="hint">{narrativeCompetitorInfluence.summary}</span>
                    ) : null}
                    {narrativeCompetitorInfluence.topOpportunities.length > 0 ? (
                      <span className="hint muted">
                        Top opportunities: {narrativeCompetitorInfluence.topOpportunities.join(", ")}
                      </span>
                    ) : null}
                    {narrativeCompetitorInfluence.competitorNames.length > 0 ? (
                      <span className="hint muted">
                        Nearby competitors: {narrativeCompetitorInfluence.competitorNames.join(", ")}
                      </span>
                    ) : null}
                  </div>
                ) : null}
                {narrativeSignalSummary ? (
                  <div className="panel panel-compact stack-tight" data-testid="narrative-signal-summary">
                    <span className="hint muted">Backed by</span>
                    <span className="hint">
                      Support level: {formatNarrativeSupportLevel(narrativeSignalSummary.supportLevel)}
                    </span>
                    {narrativeSignalSummary.evidenceSources.length > 0 ? (
                      <div className="link-row">
                        {narrativeSignalSummary.evidenceSources.map((source) => (
                          <span key={source} className="badge badge-muted">
                            {source}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    <span className="hint muted">
                      Signal check: site {narrativeSignalSummary.siteSignalUsed ? "yes" : "no"}; competitors{" "}
                      {narrativeSignalSummary.competitorSignalUsed ? "yes" : "no"}; references{" "}
                      {narrativeSignalSummary.referenceSignalUsed ? "yes" : "no"}.
                    </span>
                  </div>
                ) : null}
                {recommendationEEATGapSummary ? (
                  <div className="panel panel-compact stack-tight" data-testid="narrative-eeat-gap-summary">
                    <span className="hint muted">EEAT gap summary</span>
                    <div className="link-row">
                      {recommendationEEATGapSummary.categories.map((category) => (
                        <span key={`eeat-gap-${category}`} className="badge badge-warn">
                          {formatEEATCategory(category)}
                        </span>
                      ))}
                    </div>
                    <span className="hint">{recommendationEEATGapSummary.message}</span>
                    {recommendationEEATGapSummary.supportingSignals.length > 0 ? (
                      <div className="stack-tight">
                        <span className="hint muted">Supporting signals</span>
                        <div className="link-row">
                          {recommendationEEATGapSummary.supportingSignals.map((signal) => (
                            <span key={signal} className="badge badge-muted">
                              {signal}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {recommendationApplyOutcome ? (
                  <div className="panel panel-compact stack-tight" data-testid="narrative-apply-outcome">
                    <span className="hint muted">Latest apply outcome</span>
                    <span className="hint success">Applied</span>
                    {recommendationApplyOutcome.recommendationLabel ? (
                      <span className="hint">Recommendation: {recommendationApplyOutcome.recommendationLabel}</span>
                    ) : null}
                    {recommendationApplyOutcome.expectedChange ? (
                      <span className="hint muted">Expected change: {recommendationApplyOutcome.expectedChange}</span>
                    ) : null}
                    {recommendationApplyOutcome.reflectedOnNextRun ? (
                      <span className="hint muted">
                        Reflects on next run: {recommendationApplyOutcome.reflectedOnNextRun}
                      </span>
                    ) : null}
                    {recommendationApplyOutcome.appliedAt ? (
                      <span className="hint muted">Applied at: {formatDateTime(recommendationApplyOutcome.appliedAt)}</span>
                    ) : null}
                    {recommendationApplyOutcome.source === "recommendation" ? (
                      <span className="hint muted">Source: recommendation-guided tuning action.</span>
                    ) : null}
                  </div>
                ) : null}
                {recommendationAnalysisFreshness ? (
                  <div className="panel panel-compact stack-tight" data-testid="narrative-analysis-freshness">
                    <span className="hint muted">Analysis freshness</span>
                    <span className={analysisFreshnessBadgeClass(recommendationAnalysisFreshness.status)}>
                      {analysisFreshnessLabel(recommendationAnalysisFreshness.status)}
                    </span>
                    <span className="hint">{recommendationAnalysisFreshness.message}</span>
                    {recommendationAnalysisFreshness.analysisGeneratedAt ? (
                      <span className="hint muted">
                        Analysis generated at: {formatDateTime(recommendationAnalysisFreshness.analysisGeneratedAt)}
                      </span>
                    ) : null}
                    {recommendationAnalysisFreshness.lastApplyAt ? (
                      <span className="hint muted">
                        Last apply at: {formatDateTime(recommendationAnalysisFreshness.lastApplyAt)}
                      </span>
                    ) : null}
                    {formatLocationContextSourceLabel(siteLocationContextSource) ? (
                      <span className="hint muted">
                        Location source: {formatLocationContextSourceLabel(siteLocationContextSource)}
                      </span>
                    ) : null}
                  </div>
                ) : null}
                {competitorContextHealth ? (
                  <div className="panel panel-compact stack-tight" data-testid="competitor-context-health">
                    <span className="hint muted">Competitor context health</span>
                    <span className={competitorContextHealthBadgeClass(competitorContextHealth.status)}>
                      {competitorContextHealthLabel(competitorContextHealth.status)}
                    </span>
                    <span className="hint">{competitorContextHealth.message}</span>
                    {competitorContextHealth.checks.length > 0 ? (
                      <div className="stack-tight">
                        {competitorContextHealth.checks.map((check) => (
                          <div key={`competitor-context-health-${check.key}`} className="link-row">
                            <span className={competitorContextHealthCheckBadgeClass(check.status)}>
                              {check.status === "strong" ? "Strong" : "Weak"}
                            </span>
                            <span className="hint">
                              {check.label}: {check.detail}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {latestCompletedRecommendationNarrative.narrative_text ? (
                  <p>{latestCompletedRecommendationNarrative.narrative_text}</p>
                ) : null}
                {!latestCompletedRecommendationNarrative.narrative_text &&
                latestCompletedRecommendationNarrative.status === "completed" ? (
                  <p className="hint muted">Narrative completed without summary text.</p>
                ) : null}
                {latestCompletedRecommendationNarrative.status === "failed" ? (
                  <p className="hint warning">
                    Narrative generation failed.
                    {latestCompletedRecommendationNarrative.error_message
                      ? ` ${latestCompletedRecommendationNarrative.error_message}`
                      : ""}
                  </p>
                ) : null}
                <span className="hint muted">AI-Assisted Tuning Suggestions</span>
                {tuningApplyMessage ? <span className="hint success">{tuningApplyMessage}</span> : null}
                {latestCompletedTuningSuggestions.length > 0 ? (
                  latestCompletedTuningSuggestions.map((suggestion) => {
                    const previewKey = buildTuningPreviewKey(latestCompletedRecommendationRun.id, suggestion);
                    const suggestionCardId = tuningSuggestionCardId(latestCompletedRecommendationRun.id, suggestion);
                    const currentValue = currentSuggestionValue(suggestion);
                    const alreadyApplied = currentValue === suggestion.recommended_value;
                    const preview = tuningPreviewByKey[previewKey];
                    return (
                      <div
                        key={`${latestCompletedRecommendationRun.id}-${suggestion.setting}-${suggestion.recommended_value}`}
                        id={suggestionCardId}
                        className={
                          startHereFocusedTargetId === suggestionCardId ||
                          aiActionFocusedTargetId === suggestionCardId
                            ? "panel panel-compact stack start-here-target-active"
                            : "panel panel-compact stack"
                        }
                        data-testid="tuning-suggestion-card"
                      >
                        <strong>{formatTuningSettingLabel(suggestion.setting)}</strong>
                        <span className="hint">
                          Current -&gt; Suggested: <strong>{currentValue}</strong> -&gt;{" "}
                          <strong>{suggestion.recommended_value}</strong>
                        </span>
                        <span className="hint muted">{suggestion.reason}</span>
                        <span className="hint muted">Confidence: {suggestion.confidence}</span>
                        <button
                          type="button"
                          className="button button-tertiary button-inline"
                          onClick={() =>
                            handlePreviewTuningSuggestion(
                              latestCompletedRecommendationRun.id,
                              latestCompletedRecommendationNarrative.id,
                              suggestion,
                            )
                          }
                          disabled={tuningPreviewLoadingKey === previewKey}
                        >
                          {tuningPreviewLoadingKey === previewKey ? "Previewing..." : "Preview Impact"}
                        </button>
                        <button
                          type="button"
                          className="button button-primary button-inline"
                          onClick={() =>
                            handleApplyTuningSuggestion(
                              latestCompletedRecommendationRun.id,
                              suggestion,
                            )
                          }
                          disabled={alreadyApplied || tuningApplyLoadingKey === previewKey}
                        >
                          {alreadyApplied
                            ? "Applied"
                            : tuningApplyLoadingKey === previewKey
                              ? "Applying..."
                              : "Apply Suggestion"}
                        </button>
                        {tuningPreviewErrorByKey[previewKey] ? (
                          <span className="hint warning">{tuningPreviewErrorByKey[previewKey]}</span>
                        ) : null}
                        {tuningApplyErrorByKey[previewKey] ? (
                          <span className="hint warning">{tuningApplyErrorByKey[previewKey]}</span>
                        ) : null}
                        {preview ? (
                          <>
                            <span className="hint">
                              Impact hint: {formatSignedDelta(preview.estimated_impact.estimated_included_candidate_delta)}{" "}
                              candidates included
                            </span>
                            <span className="hint muted">{preview.estimated_impact.summary}</span>
                            <span className="hint muted">
                              Included delta:{" "}
                              {formatSignedDelta(preview.estimated_impact.estimated_included_candidate_delta)};
                              excluded delta:{" "}
                              {formatSignedDelta(preview.estimated_impact.estimated_excluded_candidate_delta)}
                            </span>
                          </>
                        ) : null}
                      </div>
                    );
                  })
                ) : (
                  <span className="hint muted">No tuning adjustments suggested for current data.</span>
                )}
                {recentTuningChanges.length > 0 ? (
                  <div className="panel panel-compact stack" data-testid="recent-changes-panel">
                    <span className="hint muted">Recent Changes</span>
                    <ul>
                      {recentTuningChanges.map((change) => (
                        <li key={change.id}>
                          <span className="hint">
                            {change.setting_label}: {change.previous_value} -&gt; {change.next_value} (
                            {formatDateTime(change.applied_at)})
                          </span>
                          {change.ai_attribution ? (
                            <>
                              <br />
                              <span className="badge badge-muted">From AI Recommendation</span>
                              <span className="hint muted"> {change.ai_attribution.recommendation_title}</span>
                            </>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="hint muted">
                No narrative has been generated for the latest completed recommendation run yet.
              </p>
            )}
          </div>
        ) : null}
        <h3>Recent Run History</h3>
        {recommendationRuns.length > 0 ? (
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
                            <Link href={buildNarrativeDetailHref(run.id, latestNarrative.id, selectedSite.id)}>
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
        ) : null}
      </SectionCard>
    </PageContainer>
  );
}
