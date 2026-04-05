"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useState } from "react";

import { ActionControls } from "../../../components/action-execution/ActionControls";
import { OutputReview } from "../../../components/action-execution/OutputReview";
import { PageContainer } from "../../../components/layout/PageContainer";
import { SectionHeader } from "../../../components/layout/SectionHeader";
import { SectionCard } from "../../../components/layout/SectionCard";
import { SummaryStatCard } from "../../../components/layout/SummaryStatCard";
import { useOperatorContext } from "../../../components/useOperatorContext";
import {
  acceptCompetitorProfileDraft,
  ApiRequestError,
  bindActionExecutionItemAutomation,
  createCompetitorProfileGenerationRun,
  createRecommendationRun,
  editCompetitorProfileDraft,
  fetchAuditRuns,
  fetchAutomationRuns,
  fetchBusinessSettings,
  fetchGA4SiteOnboardingStatus,
  fetchGoogleBusinessProfileConnection,
  fetchSearchConsoleSiteSummary,
  fetchSiteAnalyticsSummary,
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
  runActionExecutionItemAutomation,
  updateSite,
  updateBusinessSettings,
  updateRecommendationStatus,
} from "../../../lib/api/client";
import {
  deriveAutomationRunOperatorActionState,
  deriveRecommendationOperatorActionState,
} from "../../../lib/operatorActionState";
import {
  applyActionDecisionLocally,
  deriveActionControls,
  deriveActionStatePresentation,
} from "../../../lib/transforms/actionExecution";
import type {
  ActionControl,
  ActionDecision,
  ActionExecutionItem,
  AIPromptPreview,
  AutomationRun,
  AutomationRunOutcomeSummary,
  AutomationRunStep,
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
  GoogleBusinessProfileConnectionStatusResponse,
  GA4SiteOnboardingStatusResponse,
  RecommendationAnalysisFreshness,
  RecommendationApplyOutcome,
  RecommendationEEATCategory,
  RecommendationEEATGapSummary,
  RecommendationOrderingExplanation,
  RecommendationLifecycleState,
  RecommendationProgressStatus,
  RecommendationPriorityReason,
  RecommendationStartHere,
  RecommendationActionPlanStep,
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
  SearchConsoleSiteSummaryResponse,
  SiteAnalyticsSummaryResponse,
  SEOAuditRun,
  WorkspaceSectionFreshness,
  WorkspaceTrustSummary,
} from "../../../lib/api/types";

const MAX_AUDIT_ROWS = 8;
const MAX_COMPETITOR_ROWS = 8;
const MAX_RECOMMENDATION_ROWS = 8;
const MAX_RECOMMENDATION_RUN_ROWS = 8;
const MAX_AUTOMATION_RUN_ROWS = 8;
const NARRATIVE_LOOKUP_LIMIT = 5;
const MAX_TIMELINE_EVENTS = 20;
const TIMELINE_INITIAL_VISIBLE_COUNT = 10;
const AI_OPPORTUNITY_INITIAL_COUNT = 3;
const AI_ACTION_HIGHLIGHT_DURATION_MS = 1800;
const MAX_RECENT_TUNING_CHANGES = 8;
const COMPETITOR_PROFILE_DRAFT_CANDIDATE_COUNT = 10;
const COMPETITOR_PROFILE_POLL_INTERVAL_MS = 3000;
const COMPETITOR_PROFILE_POLL_MAX_ATTEMPTS = 30;
const MAX_REJECTED_CANDIDATE_DEBUG_ROWS = 8;
const MAX_TUNING_REJECTED_CANDIDATE_DEBUG_ROWS = 8;
const MAX_PROVIDER_ATTEMPT_DEBUG_ROWS = 2;
const HIDE_SYNTHETIC_DEFAULT_NON_SYNTHETIC_THRESHOLD = 5;
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
type WorkspaceContentTab = "summary" | "recommendations" | "activity";

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

interface CompetitorPipelineStageRow {
  stage: string;
  count: number;
  description: string;
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

function normalizeAutomationRunStatus(status: string | null | undefined): string {
  return (status || "").trim().toLowerCase();
}

const COMPETITOR_DEPENDENCY_TERMS = [
  "competitor snapshot",
  "snapshot output",
  "comparison step",
  "comparison output",
  "prerequisite",
  "dependency",
  "not completed",
  "not ready",
];

type AutomationCompletenessSignal = {
  label: "Complete" | "Complete (limited)" | "Partial";
  badgeClass: "badge-success" | "badge-warn";
  hint: string | null;
};

function normalizeAutomationRunSteps(run: AutomationRun | null): AutomationRunStep[] {
  if (!run || !Array.isArray(run.steps_json)) {
    return [];
  }
  return run.steps_json
    .filter((step): step is AutomationRunStep => Boolean(step && typeof step === "object"))
    .map((step) => ({
      step_name: typeof step.step_name === "string" ? step.step_name : "unknown",
      status: typeof step.status === "string" ? step.status : "queued",
      started_at: typeof step.started_at === "string" ? step.started_at : null,
      finished_at: typeof step.finished_at === "string" ? step.finished_at : null,
      linked_output_id: typeof step.linked_output_id === "string" ? step.linked_output_id : null,
      error_message: typeof step.error_message === "string" ? step.error_message : null,
      reason_summary: typeof step.reason_summary === "string" ? step.reason_summary : null,
      pages_analyzed_count:
        typeof step.pages_analyzed_count === "number" ? step.pages_analyzed_count : null,
      issues_found_count: typeof step.issues_found_count === "number" ? step.issues_found_count : null,
      recommendations_generated_count:
        typeof step.recommendations_generated_count === "number"
          ? step.recommendations_generated_count
          : null,
    }));
}

function hasCompetitorDependencyReason(reason: string | null | undefined): boolean {
  const normalizedReason = (reason || "").trim().toLowerCase();
  if (!normalizedReason) {
    return false;
  }
  return COMPETITOR_DEPENDENCY_TERMS.some((term) => normalizedReason.includes(term));
}

function deriveAutomationCompletenessSignal(
  run: AutomationRun | null,
  steps: AutomationRunStep[],
  summary: AutomationRunOutcomeSummary | null,
): AutomationCompletenessSignal | null {
  const normalizedStatus = normalizeAutomationRunStatus(run?.status);
  if (normalizedStatus !== "completed" && normalizedStatus !== "failed") {
    return null;
  }

  const hasCompetitorDependencyGap = steps.some((step) => {
    const status = normalizeAutomationRunStatus(step.status);
    if (status !== "skipped" && status !== "failed") {
      return false;
    }
    if (step.step_name === "comparison_run" || step.step_name === "competitor_summary") {
      return true;
    }
    return hasCompetitorDependencyReason(step.reason_summary || step.error_message || null);
  });

  const hasMissingCompetitorMetrics = steps.some((step) => {
    if (step.step_name !== "comparison_run" && step.step_name !== "competitor_summary") {
      return false;
    }
    if (normalizeAutomationRunStatus(step.status) !== "completed") {
      return false;
    }
    return (
      step.pages_analyzed_count === null
      && step.issues_found_count === null
      && step.recommendations_generated_count === null
      && !step.linked_output_id
    );
  });

  if (hasCompetitorDependencyGap || summary?.terminal_outcome === "completed_with_skips" || summary?.terminal_outcome === "partial") {
    return {
      label: "Partial",
      badgeClass: "badge-warn",
      hint: "Competitor data not available at run time; insights may be limited.",
    };
  }

  if (hasMissingCompetitorMetrics) {
    return {
      label: "Complete (limited)",
      badgeClass: "badge-warn",
      hint: "Competitor data not available at run time; insights may be limited.",
    };
  }

  if (normalizedStatus === "completed") {
    return {
      label: "Complete",
      badgeClass: "badge-success",
      hint: null,
    };
  }

  return {
    label: "Partial",
    badgeClass: "badge-warn",
    hint: null,
  };
}

function automationRunStatusBadgeClass(status: string | null | undefined): string {
  const normalized = normalizeAutomationRunStatus(status);
  if (normalized === "completed") {
    return "badge-success";
  }
  if (normalized === "failed") {
    return "badge-error";
  }
  if (normalized === "running" || normalized === "queued") {
    return "badge-warn";
  }
  return "badge-muted";
}

function normalizeAutomationRunOutcomeSummary(run: AutomationRun | null): AutomationRunOutcomeSummary | null {
  const summary = run?.outcome_summary;
  if (!summary || typeof summary !== "object") {
    return null;
  }
  if (
    typeof summary.summary_title !== "string"
    || typeof summary.summary_text !== "string"
    || typeof summary.steps_completed_count !== "number"
    || typeof summary.steps_skipped_count !== "number"
    || typeof summary.steps_failed_count !== "number"
  ) {
    return null;
  }
  return {
    summary_title: summary.summary_title,
    summary_text: summary.summary_text,
    pages_analyzed_count:
      typeof summary.pages_analyzed_count === "number" ? summary.pages_analyzed_count : null,
    issues_found_count:
      typeof summary.issues_found_count === "number" ? summary.issues_found_count : null,
    recommendations_generated_count:
      typeof summary.recommendations_generated_count === "number"
        ? summary.recommendations_generated_count
        : null,
    steps_completed_count: summary.steps_completed_count,
    steps_skipped_count: summary.steps_skipped_count,
    steps_failed_count: summary.steps_failed_count,
    terminal_outcome:
      summary.terminal_outcome === "completed"
      || summary.terminal_outcome === "completed_with_skips"
      || summary.terminal_outcome === "failed"
      || summary.terminal_outcome === "partial"
        ? summary.terminal_outcome
        : "partial",
  };
}

function formatAutomationTerminalOutcomeLabel(
  terminalOutcome: AutomationRunOutcomeSummary["terminal_outcome"] | null,
): string | null {
  if (!terminalOutcome) {
    return null;
  }
  if (terminalOutcome === "completed") {
    return "Completed";
  }
  if (terminalOutcome === "completed_with_skips") {
    return "Completed with skips";
  }
  if (terminalOutcome === "failed") {
    return "Failed";
  }
  return "Partial";
}

function automationTerminalOutcomeBadgeClass(
  terminalOutcome: AutomationRunOutcomeSummary["terminal_outcome"] | null,
): string {
  if (terminalOutcome === "completed") {
    return "badge-success";
  }
  if (terminalOutcome === "completed_with_skips" || terminalOutcome === "partial") {
    return "badge-warn";
  }
  if (terminalOutcome === "failed") {
    return "badge-error";
  }
  return "badge-muted";
}

function deriveAutomationRunNextStep(run: AutomationRun | null): string {
  const summary = normalizeAutomationRunOutcomeSummary(run);
  if (summary?.terminal_outcome === "completed") {
    return summary.recommendations_generated_count && summary.recommendations_generated_count > 0
      ? "Review newly generated recommendations."
      : "Review completed SEO artifacts and proceed with the next operator action.";
  }
  if (summary?.terminal_outcome === "completed_with_skips") {
    return "Review skipped steps and rerun after prerequisites are available.";
  }
  if (summary?.terminal_outcome === "failed") {
    return "Review failed step details before rerunning SEO automation.";
  }
  if (summary?.terminal_outcome === "partial") {
    return "Review partial outputs and rerun remaining steps once prerequisites are ready.";
  }
  const normalizedStatus = normalizeAutomationRunStatus(run?.status);
  if (normalizedStatus === "running" || normalizedStatus === "queued") {
    return "Wait for completion before taking downstream recommendation actions.";
  }
  return "Review automation run detail to confirm lifecycle and output state.";
}

function extractAutomationRecommendationRunOutputId(run: AutomationRun | null): string | null {
  if (!run || !Array.isArray(run.steps_json)) {
    return null;
  }
  for (const step of run.steps_json) {
    if (!step || typeof step !== "object") {
      continue;
    }
    const stepName = typeof step.step_name === "string" ? step.step_name : "";
    const stepStatus = typeof step.status === "string" ? step.status.toLowerCase() : "";
    const linkedOutputId = typeof step.linked_output_id === "string" ? step.linked_output_id.trim() : "";
    if (stepName === "recommendation_run" && stepStatus === "completed" && linkedOutputId.length > 0) {
      return linkedOutputId;
    }
  }
  return null;
}

function extractAutomationRecommendationNarrativeOutputId(run: AutomationRun | null): string | null {
  if (!run || !Array.isArray(run.steps_json)) {
    return null;
  }
  for (const step of run.steps_json) {
    if (!step || typeof step !== "object") {
      continue;
    }
    const stepName = typeof step.step_name === "string" ? step.step_name : "";
    const stepStatus = typeof step.status === "string" ? step.status.toLowerCase() : "";
    const linkedOutputId = typeof step.linked_output_id === "string" ? step.linked_output_id.trim() : "";
    if (stepName === "recommendation_narrative" && stepStatus === "completed" && linkedOutputId.length > 0) {
      return linkedOutputId;
    }
  }
  return null;
}

function deriveAutomationBindingTargetId(runs: AutomationRun[]): string | null {
  for (const run of runs) {
    const automationConfigId = typeof run.automation_config_id === "string" ? run.automation_config_id.trim() : "";
    if (automationConfigId.length > 0) {
      return automationConfigId;
    }
  }
  return null;
}

function hasInFlightLineageExecution(lineage: Recommendation["action_lineage"] | null | undefined): boolean {
  if (!lineage) {
    return false;
  }
  return lineage.activated_actions.some((activatedAction) => {
    const runStatus = (activatedAction.automation_run_status || "").trim().toLowerCase();
    const executionState = (activatedAction.automation_execution_state || "").trim().toLowerCase();
    return (
      runStatus === "queued"
      || runStatus === "running"
      || executionState === "requested"
      || executionState === "running"
    );
  });
}

function sortAutomationRunsNewestFirst(runs: AutomationRun[]): AutomationRun[] {
  return [...runs].sort((left, right) => {
    const leftTime = Date.parse(left.created_at || left.started_at || "");
    const rightTime = Date.parse(right.created_at || right.started_at || "");
    if (Number.isNaN(leftTime) || Number.isNaN(rightTime)) {
      return right.id.localeCompare(left.id);
    }
    return rightTime - leftTime;
  });
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

function formatCompetitorDraftConfidenceLevelLabel(
  confidenceLevel: CompetitorProfileDraft["confidence_level"],
): string | null {
  switch (confidenceLevel) {
    case "high":
      return "High confidence";
    case "medium":
      return "Medium confidence";
    case "low":
      return "Low confidence";
    default:
      return null;
  }
}

function competitorDraftConfidenceLevelBadgeClass(
  confidenceLevel: CompetitorProfileDraft["confidence_level"],
): string {
  if (confidenceLevel === "high") {
    return "badge badge-success";
  }
  if (confidenceLevel === "medium") {
    return "badge badge-warn";
  }
  if (confidenceLevel === "low") {
    return "badge badge-muted";
  }
  return "badge badge-muted";
}

function formatCompetitorDraftSourceTypeLabel(
  sourceType: CompetitorProfileDraft["source_type"],
): string | null {
  switch (sourceType) {
    case "places":
      return "Nearby seed";
    case "search":
      return "AI search";
    case "fallback":
      return "Fallback fill";
    case "synthetic":
      return "Synthetic";
    default:
      return null;
  }
}

function competitorDraftSourceTypeBadgeClass(sourceType: CompetitorProfileDraft["source_type"]): string {
  if (sourceType === "synthetic" || sourceType === "fallback") {
    return "badge badge-warn";
  }
  if (sourceType === "places") {
    return "badge badge-success";
  }
  return "badge badge-muted";
}

function isSyntheticScaffoldDomain(domain: string | null | undefined): boolean {
  const normalized = (domain || "").trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  return (
    (normalized.startsWith("review-scaffold-") && normalized.endsWith(".invalid"))
    || normalized.startsWith("unknown-domain-")
    || normalized.endsWith(".mbsrn-fallback.local")
  );
}

function isSyntheticCompetitorDraft(draft: CompetitorProfileDraft): boolean {
  return draft.provenance_classification === "synthetic_fallback" || draft.source_type === "synthetic";
}

function formatCompetitorDraftDomainDisplay(draft: CompetitorProfileDraft): { value: string; asPlaceholder: boolean } {
  const normalized = (draft.suggested_domain || "").trim();
  const isSynthetic = isSyntheticCompetitorDraft(draft);
  if (isSynthetic && isSyntheticScaffoldDomain(normalized)) {
    return { value: "No verified website (review scaffold)", asPlaceholder: true };
  }
  if (!normalized) {
    return { value: "No verified website", asPlaceholder: true };
  }
  return { value: normalized, asPlaceholder: false };
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

function normalizeGa4PropertyInput(value: string): string {
  const compacted = (value || "").trim();
  if (!compacted) {
    return "";
  }
  return compacted.replace(/^properties\//i, "");
}

function looksLikeGa4PropertyId(value: string): boolean {
  return /^\d{4,20}$/.test(value);
}

function ga4DiagnosticReasonMessage(
  reason: SiteAnalyticsSummaryResponse["ga4_error_reason"] | null | undefined,
): string | null {
  if (!reason) {
    return null;
  }
  if (reason === "not_configured") {
    return "GA4 is not configured yet. Add the site property ID and confirm workspace credentials are available.";
  }
  if (reason === "access_denied") {
    return "This property is not accessible. Ensure the service account has Viewer access.";
  }
  if (reason === "property_not_found") {
    return "This GA4 property ID was not found.";
  }
  if (reason === "invalid_property_format") {
    return "GA4 property ID format is invalid. Use only the numeric property ID (for example, 123456789).";
  }
  if (reason === "no_data") {
    return "Property is connected but has limited or no recent data.";
  }
  return "GA4 connection failed for an unknown reason. Verify the site property ID and workspace GA4 access.";
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

function formatSignedPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "No prior baseline";
  }
  const rounded = Math.round(value * 10) / 10;
  const prefix = rounded > 0 ? "+" : "";
  const formatted = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `${prefix}${formatted}%`;
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
  appliedRecommendationId: string | null;
  appliedRecommendationTitle: string | null;
  appliedChangeSummary: string | null;
  appliedPreviewSummary: string | null;
  nextRefreshExpectation: string | null;
  source: "recommendation" | "manual" | null;
}

interface RecommendationApplyOutcomePresentationView {
  statusBucket: "applied_completed" | "needs_review_pending";
  statusLabel: "Applied / completed" | "Needs review / pending";
  statusBadgeClass: string;
  timingGuidance: string;
  sourceGuidance: string | null;
}

interface OperatorPrimaryActionView {
  priorityCode:
    | "gbp_not_connected"
    | "gbp_action_needed"
    | "recommendation_ready_now"
    | "applied_pending_visibility"
    | "review_required"
    | "no_immediate_action";
  urgencyLabel: string;
  urgencyBadgeClass: string;
  title: string;
  reason: string;
  actionLabel: string;
  actionHref: string;
  actionKind: "navigate" | "focus";
  actionTargetId: string | null;
  contextHint: string | null;
}

interface WorkspaceTrustSummaryView {
  latestCompetitorStatus: CompetitorRunOutcomeSummary["status_level"] | null;
  usedGooglePlacesSeeds: boolean | null;
  usedSyntheticFallback: boolean | null;
  latestRecommendationApplyTitle: string | null;
  latestRecommendationApplyChangeSummary: string | null;
  nextRefreshExpectation: string | null;
  freshnessNote: string | null;
}

interface WorkspaceSectionFreshnessView {
  state: "fresh" | "pending_refresh" | "running" | "stale";
  message: string;
  stateCode: "fresh" | "pending_refresh" | "running" | "stale" | "possibly_outdated";
  stateLabel: string;
  stateReason: string;
  evaluatedAt: string | null;
  refreshExpected: boolean;
}

function normalizeRecommendationApplyOutcome(
  applyOutcome: RecommendationApplyOutcome | null | undefined,
): RecommendationApplyOutcomeView | null {
  if (!applyOutcome || !applyOutcome.applied) {
    return null;
  }
  const appliedRecommendationId = truncateOptionalText(applyOutcome.applied_recommendation_id, 48);
  const appliedRecommendationTitle = truncateOptionalText(
    applyOutcome.applied_recommendation_title ?? applyOutcome.recommendation_label,
    180,
  );
  const appliedChangeSummary = truncateOptionalText(
    applyOutcome.applied_change_summary ?? applyOutcome.expected_change,
    240,
  );
  const appliedPreviewSummary = truncateOptionalText(applyOutcome.applied_preview_summary, 240);
  const nextRefreshExpectation = truncateOptionalText(
    applyOutcome.next_refresh_expectation ?? applyOutcome.reflected_on_next_run,
    220,
  );
  const appliedAt = truncateOptionalText(applyOutcome.applied_at, 64);
  const source =
    applyOutcome.source === "recommendation" || applyOutcome.source === "manual"
      ? applyOutcome.source
      : null;
  if (
    !appliedRecommendationTitle &&
    !appliedChangeSummary &&
    !appliedPreviewSummary &&
    !nextRefreshExpectation &&
    !appliedAt
  ) {
    return null;
  }
  return {
    applied: true,
    appliedAt,
    appliedRecommendationId,
    appliedRecommendationTitle,
    appliedChangeSummary,
    appliedPreviewSummary,
    nextRefreshExpectation,
    source,
  };
}

function normalizeRecommendationApplyOutcomePresentation(
  applyOutcome: RecommendationApplyOutcomeView | null,
  recommendationFreshness: WorkspaceSectionFreshnessView | null,
): RecommendationApplyOutcomePresentationView | null {
  if (!applyOutcome) {
    return null;
  }
  const pendingVisibility =
    recommendationFreshness?.stateCode === "pending_refresh"
    || recommendationFreshness?.stateCode === "running";
  const statusBucket: RecommendationApplyOutcomePresentationView["statusBucket"] = pendingVisibility
    ? "needs_review_pending"
    : "applied_completed";
  const statusLabel: RecommendationApplyOutcomePresentationView["statusLabel"] = pendingVisibility
    ? "Needs review / pending"
    : "Applied / completed";
  const statusBadgeClass = recommendationPresentationBucketBadgeClass(statusBucket);
  const timingGuidance = applyOutcome.nextRefreshExpectation
    ? `Expected visibility: ${applyOutcome.nextRefreshExpectation}`
    : pendingVisibility
      ? "Expected visibility: Visible after next refresh."
      : "Expected visibility: Reflected in the latest workspace analysis.";
  const sourceGuidance =
    applyOutcome.source === "manual"
      ? "Next step: Review in Business Profile."
      : applyOutcome.source === "recommendation"
        ? "Source: Recommendation-guided update."
        : null;
  return {
    statusBucket,
    statusLabel,
    statusBadgeClass,
    timingGuidance,
    sourceGuidance,
  };
}

function buildOperatorPrimaryAction(params: {
  googleBusinessProfileStatus: GoogleBusinessProfileWorkspaceStatusView;
  recommendations: Recommendation[];
  recommendationApplyOutcome: RecommendationApplyOutcomeView | null;
  recommendationApplyOutcomePresentation: RecommendationApplyOutcomePresentationView | null;
  recommendationFreshness: WorkspaceSectionFreshnessView | null;
  competitorFreshness: WorkspaceSectionFreshnessView | null;
  workspaceReadinessMessage: string;
}): OperatorPrimaryActionView {
  const {
    googleBusinessProfileStatus,
    recommendations,
    recommendationApplyOutcome,
    recommendationApplyOutcomePresentation,
    recommendationFreshness,
    competitorFreshness,
    workspaceReadinessMessage,
  } = params;

  if (googleBusinessProfileStatus.stateCode === "not_connected") {
    return {
      priorityCode: "gbp_not_connected",
      urgencyLabel: "Action needed",
      urgencyBadgeClass: "badge badge-critical",
      title: "Connect Google Business Profile",
      reason: "Business Profile data is not connected for this business yet.",
      actionLabel: "Connect Google Business Profile",
      actionHref: "/business-profile",
      actionKind: "navigate",
      actionTargetId: null,
      contextHint: "Until this is connected, profile and location-backed workflows stay limited.",
    };
  }
  if (googleBusinessProfileStatus.stateCode === "connected_action_needed") {
    return {
      priorityCode: "gbp_action_needed",
      urgencyLabel: "Action needed",
      urgencyBadgeClass: "badge badge-critical",
      title: "Reconnect Google Business Profile",
      reason: "The connection exists but needs reauthorization before it is fully usable.",
      actionLabel: "Reconnect Google Business Profile",
      actionHref: "/business-profile",
      actionKind: "navigate",
      actionTargetId: null,
      contextHint: "Reconnect first so location and profile data can be used reliably.",
    };
  }

  const topReadyNowRecommendation = firstReadyNowRecommendation(recommendations);
  if (topReadyNowRecommendation) {
    const targetId = recommendationRowId(topReadyNowRecommendation.id);
    return {
      priorityCode: "recommendation_ready_now",
      urgencyLabel: "Ready now",
      urgencyBadgeClass: "badge badge-critical",
      title: topReadyNowRecommendation.title,
      reason: "This is the highest-value recommendation currently ready for action.",
      actionLabel: "Review top ready recommendation",
      actionHref: `#${targetId}`,
      actionKind: "focus",
      actionTargetId: targetId,
      contextHint: "Apply this first to move the strongest current gap.",
    };
  }

  const pendingVisibility =
    Boolean(recommendationApplyOutcome)
    && recommendationApplyOutcomePresentation?.statusBucket === "needs_review_pending";
  if (pendingVisibility) {
    return {
      priorityCode: "applied_pending_visibility",
      urgencyLabel: "Pending visibility",
      urgencyBadgeClass: "badge badge-warn",
      title: "Recently applied change needs refresh",
      reason:
        recommendationApplyOutcomePresentation?.timingGuidance
        || "A recent apply event is waiting for refreshed analysis visibility.",
      actionLabel: "Review recommendation outcomes",
      actionHref: "#recommendation-runs-section",
      actionKind: "focus",
      actionTargetId: "recommendation-runs-section",
      contextHint: recommendationApplyOutcome?.appliedRecommendationTitle
        ? `Latest applied: ${recommendationApplyOutcome.appliedRecommendationTitle}.`
        : null,
    };
  }

  const recommendationNeedsReview =
    recommendationFreshness?.stateCode === "stale"
    || recommendationFreshness?.stateCode === "possibly_outdated";
  const competitorNeedsReview =
    competitorFreshness?.stateCode === "stale"
    || competitorFreshness?.stateCode === "possibly_outdated";
  const gbpStatusUnavailable = googleBusinessProfileStatus.stateCode === "status_unavailable";
  if (recommendationNeedsReview || competitorNeedsReview || gbpStatusUnavailable) {
    if (recommendationNeedsReview) {
      return {
        priorityCode: "review_required",
        urgencyLabel: "Review",
        urgencyBadgeClass: "badge badge-warn",
        title: "Refresh recommendation insights",
        reason: recommendationFreshness?.stateReason || "Recommendation freshness needs review.",
        actionLabel: "Open recommendation queue",
        actionHref: "#recommendation-queue-section",
        actionKind: "focus",
        actionTargetId: "recommendation-queue-section",
        contextHint: "Run or review recommendation analysis to confirm current action priorities.",
      };
    }
    if (competitorNeedsReview) {
      return {
        priorityCode: "review_required",
        urgencyLabel: "Review",
        urgencyBadgeClass: "badge badge-warn",
        title: "Review competitor profile freshness",
        reason: competitorFreshness?.stateReason || "Competitor data may be outdated.",
        actionLabel: "Open competitor profiles",
        actionHref: "#competitor-profiles-section",
        actionKind: "focus",
        actionTargetId: "competitor-profiles-section",
        contextHint: "Refresh competitor profiles before relying on downstream comparisons.",
      };
    }
    return {
      priorityCode: "review_required",
      urgencyLabel: "Review",
      urgencyBadgeClass: "badge badge-warn",
      title: "Review Business Profile connection status",
      reason: googleBusinessProfileStatus.detail,
      actionLabel: "Open Business Profile",
      actionHref: "/business-profile",
      actionKind: "navigate",
      actionTargetId: null,
      contextHint: "Status data was unavailable, so verify integration health directly.",
    };
  }

  return {
    priorityCode: "no_immediate_action",
    urgencyLabel: "No immediate action needed",
    urgencyBadgeClass: "badge badge-success",
    title: "No urgent workspace action",
    reason: workspaceReadinessMessage,
    actionLabel: "Review latest recommendations",
    actionHref: "#recommendation-runs-section",
    actionKind: "focus",
    actionTargetId: "recommendation-runs-section",
    contextHint: "Use this time to review outcomes and plan the next optimization pass.",
  };
}

function firstReadyNowRecommendation(recommendations: Recommendation[]): Recommendation | null {
  const readyNow = recommendations.filter((item) => classifyRecommendationPresentationBucket(item) === "ready_to_act");
  if (readyNow.length === 0) {
    return null;
  }
  const ranked = [...readyNow].sort((left, right) => {
    if (right.priority_score !== left.priority_score) {
      return right.priority_score - left.priority_score;
    }
    return right.updated_at.localeCompare(left.updated_at);
  });
  return ranked[0];
}

function normalizeWorkspaceTrustSummary(
  summary: WorkspaceTrustSummary | null | undefined,
): WorkspaceTrustSummaryView | null {
  if (!summary) {
    return null;
  }
  const latestCompetitorStatus =
    summary.latest_competitor_status === "normal" ||
    summary.latest_competitor_status === "recovered" ||
    summary.latest_competitor_status === "degraded" ||
    summary.latest_competitor_status === "failed"
      ? summary.latest_competitor_status
      : null;
  const usedGooglePlacesSeeds =
    typeof summary.used_google_places_seeds === "boolean" ? summary.used_google_places_seeds : null;
  const usedSyntheticFallback =
    typeof summary.used_synthetic_fallback === "boolean" ? summary.used_synthetic_fallback : null;
  const latestRecommendationApplyTitle = truncateOptionalText(summary.latest_recommendation_apply_title, 180);
  const latestRecommendationApplyChangeSummary = truncateOptionalText(
    summary.latest_recommendation_apply_change_summary,
    240,
  );
  const nextRefreshExpectation = truncateOptionalText(summary.next_refresh_expectation, 220);
  const freshnessNote = truncateOptionalText(summary.freshness_note, 220);
  if (
    !latestCompetitorStatus &&
    usedGooglePlacesSeeds === null &&
    usedSyntheticFallback === null &&
    !latestRecommendationApplyTitle &&
    !latestRecommendationApplyChangeSummary &&
    !nextRefreshExpectation &&
    !freshnessNote
  ) {
    return null;
  }
  return {
    latestCompetitorStatus,
    usedGooglePlacesSeeds,
    usedSyntheticFallback,
    latestRecommendationApplyTitle,
    latestRecommendationApplyChangeSummary,
    nextRefreshExpectation,
    freshnessNote,
  };
}

function normalizeWorkspaceSectionFreshness(
  freshness: WorkspaceSectionFreshness | null | undefined,
): WorkspaceSectionFreshnessView | null {
  if (!freshness) {
    return null;
  }
  const state =
    freshness.state === "fresh" ||
    freshness.state === "pending_refresh" ||
    freshness.state === "running" ||
    freshness.state === "stale"
      ? freshness.state
      : null;
  const message = truncateOptionalText(freshness.message, 220);
  if (!state || !message) {
    return null;
  }
  const stateCode =
    freshness.state_code === "fresh" ||
    freshness.state_code === "pending_refresh" ||
    freshness.state_code === "running" ||
    freshness.state_code === "stale" ||
    freshness.state_code === "possibly_outdated"
      ? freshness.state_code
      : state;
  const stateLabel = truncateOptionalText(freshness.state_label, 80) || workspaceSectionFreshnessLabel(stateCode);
  const stateReason = truncateOptionalText(freshness.state_reason, 220) || message;
  const evaluatedAt = truncateOptionalText(freshness.evaluated_at, 64);
  const refreshExpected = typeof freshness.refresh_expected === "boolean"
    ? freshness.refresh_expected
    : stateCode === "pending_refresh" || stateCode === "running" || stateCode === "possibly_outdated";
  return { state, message, stateCode, stateLabel, stateReason, evaluatedAt, refreshExpected };
}

function workspaceSectionFreshnessLabel(
  state: WorkspaceSectionFreshnessView["stateCode"] | WorkspaceSectionFreshnessView["state"],
): string {
  switch (state) {
    case "fresh":
      return "Fresh";
    case "pending_refresh":
      return "Refresh pending";
    case "running":
      return "Run in progress";
    case "possibly_outdated":
      return "Possibly outdated";
    case "stale":
    default:
      return "Stale";
  }
}

function workspaceSectionFreshnessBadgeClass(
  state: WorkspaceSectionFreshnessView["stateCode"] | WorkspaceSectionFreshnessView["state"],
): string {
  switch (state) {
    case "fresh":
      return "badge badge-success";
    case "pending_refresh":
      return "badge badge-warn";
    case "running":
      return "badge badge-muted";
    case "possibly_outdated":
      return "badge badge-warn";
    case "stale":
    default:
      return "badge badge-warn";
  }
}

function workspaceSectionFreshnessCardTone(
  state: WorkspaceSectionFreshnessView["stateCode"] | WorkspaceSectionFreshnessView["state"] | null,
): "neutral" | "success" | "warning" | "danger" {
  if (state === "fresh") {
    return "success";
  }
  if (state === "running") {
    return "neutral";
  }
  if (state === "pending_refresh" || state === "stale" || state === "possibly_outdated") {
    return "warning";
  }
  return "neutral";
}

interface GoogleBusinessProfileWorkspaceStatusView {
  stateCode: "connected_usable" | "connected_action_needed" | "not_connected" | "status_unavailable";
  stateLabel: string;
  detail: string;
  nextActionLabel: string;
  tone: "neutral" | "success" | "warning" | "danger";
  badgeClass: string;
}

function normalizeGoogleBusinessProfileWorkspaceStatus(
  connection: GoogleBusinessProfileConnectionStatusResponse | null,
  connectionError: string | null,
): GoogleBusinessProfileWorkspaceStatusView {
  if (connectionError) {
    return {
      stateCode: "status_unavailable",
      stateLabel: "Status unavailable",
      detail: "We could not load Google Business Profile integration status right now.",
      nextActionLabel: "Review integration status",
      tone: "warning",
      badgeClass: "badge badge-warn",
    };
  }
  if (!connection || !connection.connected) {
    return {
      stateCode: "not_connected",
      stateLabel: "Not connected",
      detail: "Connect Google Business Profile to load account and location access.",
      nextActionLabel: "Connect Google Business Profile",
      tone: "neutral",
      badgeClass: "badge badge-muted",
    };
  }

  const requiresAction = connection.reconnect_required
    || connection.token_status === "reconnect_required"
    || connection.token_status === "insufficient_scope"
    || !connection.required_scopes_satisfied
    || !connection.refresh_token_present;

  if (requiresAction) {
    return {
      stateCode: "connected_action_needed",
      stateLabel: "Action needed",
      detail: "Connection exists, but reauthorization or scope review is required before data access is reliable.",
      nextActionLabel: "Reconnect Google Business Profile",
      tone: "warning",
      badgeClass: "badge badge-warn",
    };
  }

  return {
    stateCode: "connected_usable",
    stateLabel: "Connected and usable",
    detail: "Google Business Profile access is healthy for this business.",
    nextActionLabel: "Review integration status",
    tone: "success",
    badgeClass: "badge badge-success",
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

function normalizeRecommendationTargetContentLabels(item: Recommendation): string[] {
  if (!Array.isArray(item.recommendation_target_content_types)) {
    return [];
  }
  const labels: string[] = [];
  const seen = new Set<string>();
  for (const target of item.recommendation_target_content_types) {
    const label = truncateOptionalText(target?.label, 80);
    if (!label) {
      continue;
    }
    const key = label.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    labels.push(label);
    if (labels.length >= 4) {
      break;
    }
  }
  return labels;
}

function normalizeRecommendationTargetContentSummary(item: Recommendation): string | null {
  const summary = truncateOptionalText(item.recommendation_target_content_summary, 220);
  if (summary) {
    return summary;
  }
  const labels = normalizeRecommendationTargetContentLabels(item);
  if (labels.length === 0) {
    return null;
  }
  if (labels.length === 1) {
    return labels[0];
  }
  if (labels.length === 2) {
    return `${labels[0]} and ${labels[1]}`;
  }
  return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
}

function normalizeRecommendationActionPlanSteps(item: Recommendation): RecommendationActionPlanStep[] {
  const rawSteps = item.action_plan?.action_steps;
  if (!Array.isArray(rawSteps)) {
    return [];
  }
  const normalized: RecommendationActionPlanStep[] = [];
  const seenStepNumbers = new Set<number>();
  for (const rawStep of rawSteps) {
    if (!rawStep || typeof rawStep !== "object") {
      continue;
    }
    const stepNumber = Number.isFinite(rawStep.step_number) ? Math.max(1, Math.trunc(rawStep.step_number)) : null;
    const title = truncateOptionalText(rawStep.title, 120);
    const instruction = truncateOptionalText(rawStep.instruction, 280);
    const targetType = rawStep.target_type === "page" || rawStep.target_type === "content" ? rawStep.target_type : null;
    const targetIdentifier = truncateOptionalText(rawStep.target_identifier, 140);
    if (
      stepNumber === null
      || seenStepNumbers.has(stepNumber)
      || !title
      || !instruction
      || !targetType
      || !targetIdentifier
    ) {
      continue;
    }
    seenStepNumbers.add(stepNumber);
    normalized.push({
      step_number: stepNumber,
      title,
      instruction,
      target_type: targetType,
      target_identifier: targetIdentifier,
      field: truncateOptionalText(rawStep.field, 80),
      before_example: truncateOptionalText(rawStep.before_example, 220),
      after_example: truncateOptionalText(rawStep.after_example, 220),
      confidence: Number.isFinite(rawStep.confidence)
        ? Math.max(0, Math.min(1, Number(rawStep.confidence)))
        : 0.7,
    });
    if (normalized.length >= 4) {
      break;
    }
  }
  normalized.sort((left, right) => left.step_number - right.step_number);
  return normalized;
}

function normalizeRecommendationCompetitorLinkageSummary(item: Recommendation): string | null {
  return truncateOptionalText(item.competitor_linkage_summary, 240);
}

function normalizeRecommendationCompetitorEvidenceLinks(
  item: Recommendation,
): Array<{
  competitorDraftId: string;
  competitorName: string;
  competitorDomain: string | null;
  confidenceLevel: "high" | "medium" | "low" | null;
  sourceType: "search" | "places" | "fallback" | "synthetic" | null;
  verificationStatus: "verified" | "unverified" | null;
  trustTier: "trusted_verified" | "informational_unverified" | "informational_candidate";
  evidenceSummary: string | null;
}> {
  if (!Array.isArray(item.competitor_evidence_links)) {
    return [];
  }
  const normalized: Array<{
    competitorDraftId: string;
    competitorName: string;
    competitorDomain: string | null;
    confidenceLevel: "high" | "medium" | "low" | null;
    sourceType: "search" | "places" | "fallback" | "synthetic" | null;
    verificationStatus: "verified" | "unverified" | null;
    trustTier: "trusted_verified" | "informational_unverified" | "informational_candidate";
    evidenceSummary: string | null;
  }> = [];
  const seenDraftIds = new Set<string>();
  for (const rawLink of item.competitor_evidence_links) {
    const competitorDraftId = truncateOptionalText(rawLink?.competitor_draft_id, 36);
    const competitorName = truncateOptionalText(rawLink?.competitor_name, 180);
    if (!competitorDraftId || !competitorName || seenDraftIds.has(competitorDraftId)) {
      continue;
    }
    seenDraftIds.add(competitorDraftId);
    const confidenceLevel =
      rawLink?.confidence_level === "high" || rawLink?.confidence_level === "medium" || rawLink?.confidence_level === "low"
        ? rawLink.confidence_level
        : null;
    const sourceType =
      rawLink?.source_type === "search"
      || rawLink?.source_type === "places"
      || rawLink?.source_type === "fallback"
      || rawLink?.source_type === "synthetic"
        ? rawLink.source_type
        : null;
    const verificationStatus =
      rawLink?.verification_status === "verified" || rawLink?.verification_status === "unverified"
        ? rawLink.verification_status
        : null;
    const trustTier =
      rawLink?.trust_tier === "trusted_verified"
      || rawLink?.trust_tier === "informational_unverified"
      || rawLink?.trust_tier === "informational_candidate"
        ? rawLink.trust_tier
        : rawLink?.evidence_trust_tier === "trusted_verified"
          || rawLink?.evidence_trust_tier === "informational_unverified"
          || rawLink?.evidence_trust_tier === "informational_candidate"
            ? rawLink.evidence_trust_tier
            : "informational_candidate";
    normalized.push({
      competitorDraftId,
      competitorName,
      competitorDomain: truncateOptionalText(rawLink?.competitor_domain, 255),
      confidenceLevel,
      sourceType,
      verificationStatus,
      trustTier,
      evidenceSummary: truncateOptionalText(rawLink?.evidence_summary, 220),
    });
    if (normalized.length >= 3) {
      break;
    }
  }
  return normalized;
}

function formatRecommendationActionDeltaEvidenceStrength(
  value: "high" | "medium" | "low",
): string {
  if (value === "high") {
    return "High";
  }
  if (value === "medium") {
    return "Medium";
  }
  return "Low";
}

function formatRecommendationEvidenceTrustTierLabel(
  value: "trusted_verified" | "informational_unverified" | "informational_candidate",
): string | null {
  if (value === "trusted_verified") {
    return "Verified competitor";
  }
  if (value === "informational_unverified") {
    return "Unverified competitor";
  }
  if (value === "informational_candidate") {
    return "Candidate competitor";
  }
  return null;
}

function recommendationEvidenceTrustTierBadgeClass(
  value: "trusted_verified" | "informational_unverified" | "informational_candidate",
): string {
  if (value === "trusted_verified") {
    return "badge badge-success";
  }
  if (value === "informational_unverified") {
    return "badge badge-warn";
  }
  return "badge badge-muted";
}

function normalizeRecommendationActionDelta(
  item: Recommendation,
): {
  observedCompetitorPattern: string;
  observedSiteGap: string;
  recommendedOperatorAction: string;
  evidenceStrength: "high" | "medium" | "low";
} | null {
  const raw = item.recommendation_action_delta;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const observedCompetitorPattern = truncateOptionalText(raw.observed_competitor_pattern, 220);
  const observedSiteGap = truncateOptionalText(raw.observed_site_gap, 220);
  const recommendedOperatorAction = truncateOptionalText(raw.recommended_operator_action, 220);
  const evidenceStrength =
    raw.evidence_strength === "high" || raw.evidence_strength === "medium" || raw.evidence_strength === "low"
      ? raw.evidence_strength
      : null;
  if (!observedCompetitorPattern || !observedSiteGap || !recommendedOperatorAction || !evidenceStrength) {
    return null;
  }
  return {
    observedCompetitorPattern,
    observedSiteGap,
    recommendedOperatorAction,
    evidenceStrength,
  };
}

function formatRecommendationPriorityLevelLabel(level: "high" | "medium" | "low"): string {
  if (level === "high") {
    return "Take first";
  }
  if (level === "medium") {
    return "Next up";
  }
  return "Later";
}

function recommendationPriorityLevelBadgeClass(level: "high" | "medium" | "low"): string {
  if (level === "high") {
    return "badge badge-critical";
  }
  if (level === "medium") {
    return "badge badge-warn";
  }
  return "badge badge-muted";
}

function formatRecommendationEffortHintLabel(
  value: "quick_win" | "moderate" | "larger_change",
): string {
  if (value === "quick_win") {
    return "Quick win";
  }
  if (value === "moderate") {
    return "Moderate effort";
  }
  return "Larger change";
}

function normalizeRecommendationPriority(
  item: Recommendation,
): {
  priorityLevel: "high" | "medium" | "low";
  priorityReason: string;
  effortHint: "quick_win" | "moderate" | "larger_change" | null;
} | null {
  const raw = item.recommendation_priority;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const priorityLevel =
    raw.priority_level === "high" || raw.priority_level === "medium" || raw.priority_level === "low"
      ? raw.priority_level
      : null;
  const priorityReason = truncateOptionalText(raw.priority_reason, 220);
  const effortHint =
    raw.effort_hint === "quick_win" || raw.effort_hint === "moderate" || raw.effort_hint === "larger_change"
      ? raw.effort_hint
      : null;
  if (!priorityLevel || !priorityReason) {
    return null;
  }
  return {
    priorityLevel,
    priorityReason,
    effortHint,
  };
}

function normalizeRecommendationPriorityRationale(item: Recommendation): string | null {
  return truncateOptionalText(item.priority_rationale, 260);
}

function normalizeRecommendationWhyNow(item: Recommendation): string | null {
  return truncateOptionalText(item.why_now, 240);
}

function normalizeRecommendationNextAction(item: Recommendation): string | null {
  return truncateOptionalText(item.next_action, 220);
}

function normalizeRecommendationCompetitorInsight(item: Recommendation): string | null {
  return truncateOptionalText(item.competitor_insight, 220);
}

function normalizeRecommendationMeasurementContext(
  item: Recommendation,
): {
  measurementStatus: "available" | "no_match" | "unavailable" | "not_configured";
  matchedPagePath: string | null;
  comparisonScope: "page" | "site" | null;
  sessions: {
    current: number;
    previous: number;
    deltaAbsolute: number;
    deltaPercent: number | null;
  } | null;
  pageviews: {
    current: number;
    previous: number;
    deltaAbsolute: number;
    deltaPercent: number | null;
  } | null;
  beforeWindowSummary: {
    startDate: string;
    endDate: string;
    users: number;
    sessions: number;
    pageviews: number;
  } | null;
  afterWindowSummary: {
    startDate: string;
    endDate: string;
    users: number;
    sessions: number;
    pageviews: number;
  } | null;
  deltaSummary: {
    usersDeltaAbsolute: number;
    usersDeltaPercent: number | null;
    sessionsDeltaAbsolute: number;
    sessionsDeltaPercent: number | null;
    pageviewsDeltaAbsolute: number;
    pageviewsDeltaPercent: number | null;
  } | null;
} | null {
  const raw = item.recommendation_measurement_context;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const measurementStatus = (raw.measurement_status || "").trim().toLowerCase();
  if (
    measurementStatus !== "available"
    && measurementStatus !== "no_match"
    && measurementStatus !== "unavailable"
    && measurementStatus !== "not_configured"
  ) {
    return null;
  }

  const sessions = raw.sessions;
  const pageviews = raw.pageviews;
  const beforeWindowSummaryRaw = raw.before_window_summary;
  const afterWindowSummaryRaw = raw.after_window_summary;
  const deltaSummaryRaw = raw.delta_summary;

  const normalizeWindowSummary = (
    value: Recommendation["recommendation_measurement_context"] extends infer Context
      ? Context extends { before_window_summary?: infer WindowSummary }
        ? WindowSummary
        : never
      : never,
  ) => {
    if (!value || typeof value !== "object") {
      return null;
    }
    const startDate = typeof (value as { start_date?: string }).start_date === "string"
      ? (value as { start_date: string }).start_date.trim()
      : "";
    const endDate = typeof (value as { end_date?: string }).end_date === "string"
      ? (value as { end_date: string }).end_date.trim()
      : "";
    if (!startDate || !endDate) {
      return null;
    }
    return {
      startDate,
      endDate,
      users: Math.max(0, Number((value as { users?: number }).users) || 0),
      sessions: Math.max(0, Number((value as { sessions?: number }).sessions) || 0),
      pageviews: Math.max(0, Number((value as { pageviews?: number }).pageviews) || 0),
    };
  };

  const normalizeDeltaSummary = (
    value: Recommendation["recommendation_measurement_context"] extends infer Context
      ? Context extends { delta_summary?: infer DeltaSummary }
        ? DeltaSummary
        : never
      : never,
  ) => {
    if (!value || typeof value !== "object") {
      return null;
    }
    const usersDeltaPercent = (value as { users_delta_percent?: number | null }).users_delta_percent;
    const sessionsDeltaPercent = (value as { sessions_delta_percent?: number | null }).sessions_delta_percent;
    const pageviewsDeltaPercent = (value as { pageviews_delta_percent?: number | null }).pageviews_delta_percent;
    return {
      usersDeltaAbsolute: Number((value as { users_delta_absolute?: number }).users_delta_absolute) || 0,
      usersDeltaPercent: typeof usersDeltaPercent === "number" && Number.isFinite(usersDeltaPercent)
        ? usersDeltaPercent
        : null,
      sessionsDeltaAbsolute:
        Number((value as { sessions_delta_absolute?: number }).sessions_delta_absolute) || 0,
      sessionsDeltaPercent: typeof sessionsDeltaPercent === "number" && Number.isFinite(sessionsDeltaPercent)
        ? sessionsDeltaPercent
        : null,
      pageviewsDeltaAbsolute:
        Number((value as { pageviews_delta_absolute?: number }).pageviews_delta_absolute) || 0,
      pageviewsDeltaPercent: typeof pageviewsDeltaPercent === "number" && Number.isFinite(pageviewsDeltaPercent)
        ? pageviewsDeltaPercent
        : null,
    };
  };

  return {
    measurementStatus,
    matchedPagePath: truncateOptionalText(raw.matched_page_path, 220),
    comparisonScope:
      raw.comparison_scope === "page" || raw.comparison_scope === "site" ? raw.comparison_scope : null,
    sessions: sessions
      ? {
        current: Math.max(0, Number(sessions.current) || 0),
        previous: Math.max(0, Number(sessions.previous) || 0),
        deltaAbsolute: Number(sessions.delta_absolute) || 0,
        deltaPercent:
            typeof sessions.delta_percent === "number" && Number.isFinite(sessions.delta_percent)
              ? sessions.delta_percent
              : null,
      }
      : null,
    pageviews: pageviews
      ? {
        current: Math.max(0, Number(pageviews.current) || 0),
        previous: Math.max(0, Number(pageviews.previous) || 0),
        deltaAbsolute: Number(pageviews.delta_absolute) || 0,
        deltaPercent:
            typeof pageviews.delta_percent === "number" && Number.isFinite(pageviews.delta_percent)
            ? pageviews.delta_percent
            : null,
      }
      : null,
    beforeWindowSummary: normalizeWindowSummary(beforeWindowSummaryRaw ?? null),
    afterWindowSummary: normalizeWindowSummary(afterWindowSummaryRaw ?? null),
    deltaSummary: normalizeDeltaSummary(deltaSummaryRaw ?? null),
  };
}

function buildRecommendationMeasurementContextLine(
  measurementContext: {
    measurementStatus: "available" | "no_match" | "unavailable" | "not_configured";
    matchedPagePath: string | null;
    comparisonScope: "page" | "site" | null;
    sessions: {
      current: number;
      previous: number;
      deltaAbsolute: number;
      deltaPercent: number | null;
    } | null;
    pageviews: {
      current: number;
      previous: number;
      deltaAbsolute: number;
      deltaPercent: number | null;
    } | null;
    beforeWindowSummary: {
      startDate: string;
      endDate: string;
      users: number;
      sessions: number;
      pageviews: number;
    } | null;
    afterWindowSummary: {
      startDate: string;
      endDate: string;
      users: number;
      sessions: number;
      pageviews: number;
    } | null;
    deltaSummary: {
      usersDeltaAbsolute: number;
      usersDeltaPercent: number | null;
      sessionsDeltaAbsolute: number;
      sessionsDeltaPercent: number | null;
      pageviewsDeltaAbsolute: number;
      pageviewsDeltaPercent: number | null;
    } | null;
  } | null,
): string | null {
  if (
    !measurementContext
    || measurementContext.measurementStatus !== "available"
    || !measurementContext.sessions
    || !measurementContext.pageviews
  ) {
    return null;
  }
  const pathLabel = measurementContext.matchedPagePath ? `${measurementContext.matchedPagePath} — ` : "";
  return (
    `${pathLabel}${measurementContext.sessions.current.toLocaleString()} sessions `
    + `(${formatSignedPercent(measurementContext.sessions.deltaPercent)} vs prior period), `
    + `${measurementContext.pageviews.current.toLocaleString()} pageviews `
    + `(${formatSignedPercent(measurementContext.pageviews.deltaPercent)} vs prior period)`
  );
}

function formatDirectionalPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "no prior baseline";
  }
  const rounded = Math.round(Math.abs(value) * 10) / 10;
  if (value > 0) {
    return `↑ ${rounded}%`;
  }
  if (value < 0) {
    return `↓ ${rounded}%`;
  }
  return "→ 0%";
}

function buildRecommendationMeasurementSinceLine(
  measurementContext: {
    measurementStatus: "available" | "no_match" | "unavailable" | "not_configured";
    matchedPagePath: string | null;
    comparisonScope: "page" | "site" | null;
    sessions: {
      current: number;
      previous: number;
      deltaAbsolute: number;
      deltaPercent: number | null;
    } | null;
    pageviews: {
      current: number;
      previous: number;
      deltaAbsolute: number;
      deltaPercent: number | null;
    } | null;
    beforeWindowSummary: {
      startDate: string;
      endDate: string;
      users: number;
      sessions: number;
      pageviews: number;
    } | null;
    afterWindowSummary: {
      startDate: string;
      endDate: string;
      users: number;
      sessions: number;
      pageviews: number;
    } | null;
    deltaSummary: {
      usersDeltaAbsolute: number;
      usersDeltaPercent: number | null;
      sessionsDeltaAbsolute: number;
      sessionsDeltaPercent: number | null;
      pageviewsDeltaAbsolute: number;
      pageviewsDeltaPercent: number | null;
    } | null;
  } | null,
): string | null {
  if (
    !measurementContext
    || measurementContext.measurementStatus !== "available"
    || !measurementContext.deltaSummary
  ) {
    return null;
  }
  const scopeLabel = measurementContext.comparisonScope === "site" ? "site trend" : "page trend";
  return (
    `${scopeLabel}: sessions ${formatDirectionalPercent(measurementContext.deltaSummary.sessionsDeltaPercent)}, `
    + `pageviews ${formatDirectionalPercent(measurementContext.deltaSummary.pageviewsDeltaPercent)}.`
  );
}

function normalizeRecommendationSearchConsoleContext(
  item: Recommendation,
): {
  searchConsoleStatus: "available" | "no_match" | "unavailable" | "not_configured";
  matchedPagePath: string | null;
  comparisonScope: "page" | "site" | null;
  currentWindowSummary: {
    startDate: string;
    endDate: string;
    clicks: number;
    impressions: number;
    ctr: number;
    averagePosition: number;
  } | null;
  previousWindowSummary: {
    startDate: string;
    endDate: string;
    clicks: number;
    impressions: number;
    ctr: number;
    averagePosition: number;
  } | null;
  deltaSummary: {
    clicksDeltaAbsolute: number;
    clicksDeltaPercent: number | null;
    impressionsDeltaAbsolute: number;
    impressionsDeltaPercent: number | null;
    ctrDeltaAbsolute: number;
    averagePositionDeltaAbsolute: number;
  } | null;
  topQueriesSummary: {
    query: string;
    clicks: number;
    impressions: number;
    ctr: number;
    averagePosition: number;
  }[];
} | null {
  const raw = item.recommendation_search_console_context;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const searchConsoleStatus = (raw.search_console_status || "").trim().toLowerCase();
  if (
    searchConsoleStatus !== "available"
    && searchConsoleStatus !== "no_match"
    && searchConsoleStatus !== "unavailable"
    && searchConsoleStatus !== "not_configured"
  ) {
    return null;
  }

  const normalizeWindowSummary = (value: unknown) => {
    if (!value || typeof value !== "object") {
      return null;
    }
    const startDate = typeof (value as { start_date?: string }).start_date === "string"
      ? (value as { start_date: string }).start_date.trim()
      : "";
    const endDate = typeof (value as { end_date?: string }).end_date === "string"
      ? (value as { end_date: string }).end_date.trim()
      : "";
    if (!startDate || !endDate) {
      return null;
    }
    return {
      startDate,
      endDate,
      clicks: Math.max(0, Number((value as { clicks?: number }).clicks) || 0),
      impressions: Math.max(0, Number((value as { impressions?: number }).impressions) || 0),
      ctr: Number((value as { ctr?: number }).ctr) || 0,
      averagePosition: Number((value as { average_position?: number }).average_position) || 0,
    };
  };

  const normalizeDeltaSummary = (value: unknown) => {
    if (!value || typeof value !== "object") {
      return null;
    }
    const clicksDeltaPercent = (value as { clicks_delta_percent?: number | null }).clicks_delta_percent;
    const impressionsDeltaPercent = (value as { impressions_delta_percent?: number | null }).impressions_delta_percent;
    return {
      clicksDeltaAbsolute: Number((value as { clicks_delta_absolute?: number }).clicks_delta_absolute) || 0,
      clicksDeltaPercent: typeof clicksDeltaPercent === "number" && Number.isFinite(clicksDeltaPercent)
        ? clicksDeltaPercent
        : null,
      impressionsDeltaAbsolute:
        Number((value as { impressions_delta_absolute?: number }).impressions_delta_absolute) || 0,
      impressionsDeltaPercent: typeof impressionsDeltaPercent === "number" && Number.isFinite(impressionsDeltaPercent)
        ? impressionsDeltaPercent
        : null,
      ctrDeltaAbsolute: Number((value as { ctr_delta_absolute?: number }).ctr_delta_absolute) || 0,
      averagePositionDeltaAbsolute:
        Number((value as { average_position_delta_absolute?: number }).average_position_delta_absolute) || 0,
    };
  };

  const topQueriesSummary = Array.isArray(raw.top_queries_summary)
    ? raw.top_queries_summary
      .map((value) => {
        if (!value || typeof value !== "object") {
          return null;
        }
        const query = truncateOptionalText((value as { query?: string }).query, 120);
        if (!query) {
          return null;
        }
        return {
          query,
          clicks: Math.max(0, Number((value as { clicks?: number }).clicks) || 0),
          impressions: Math.max(0, Number((value as { impressions?: number }).impressions) || 0),
          ctr: Number((value as { ctr?: number }).ctr) || 0,
          averagePosition: Number((value as { average_position?: number }).average_position) || 0,
        };
      })
      .filter((value): value is NonNullable<typeof value> => value !== null)
      .slice(0, 3)
    : [];

  return {
    searchConsoleStatus,
    matchedPagePath: truncateOptionalText(raw.matched_page_path, 220),
    comparisonScope:
      raw.comparison_scope === "page" || raw.comparison_scope === "site" ? raw.comparison_scope : null,
    currentWindowSummary: normalizeWindowSummary(raw.current_window_summary ?? null),
    previousWindowSummary: normalizeWindowSummary(raw.previous_window_summary ?? null),
    deltaSummary: normalizeDeltaSummary(raw.delta_summary ?? null),
    topQueriesSummary,
  };
}

function buildRecommendationSearchVisibilityContextLine(
  searchContext: {
    searchConsoleStatus: "available" | "no_match" | "unavailable" | "not_configured";
    matchedPagePath: string | null;
    comparisonScope: "page" | "site" | null;
    currentWindowSummary: {
      startDate: string;
      endDate: string;
      clicks: number;
      impressions: number;
      ctr: number;
      averagePosition: number;
    } | null;
    previousWindowSummary: {
      startDate: string;
      endDate: string;
      clicks: number;
      impressions: number;
      ctr: number;
      averagePosition: number;
    } | null;
    deltaSummary: {
      clicksDeltaAbsolute: number;
      clicksDeltaPercent: number | null;
      impressionsDeltaAbsolute: number;
      impressionsDeltaPercent: number | null;
      ctrDeltaAbsolute: number;
      averagePositionDeltaAbsolute: number;
    } | null;
    topQueriesSummary: {
      query: string;
      clicks: number;
      impressions: number;
      ctr: number;
      averagePosition: number;
    }[];
  } | null,
): string | null {
  if (!searchContext || searchContext.searchConsoleStatus !== "available" || !searchContext.currentWindowSummary) {
    return null;
  }
  const summary = searchContext.currentWindowSummary;
  const delta = searchContext.deltaSummary;
  const pathLabel = searchContext.matchedPagePath ? `${searchContext.matchedPagePath} — ` : "";
  return (
    `${pathLabel}${summary.clicks.toLocaleString()} clicks `
    + `(${formatSignedPercent(delta?.clicksDeltaPercent ?? null)} vs prior period), `
    + `${summary.impressions.toLocaleString()} impressions `
    + `(${formatSignedPercent(delta?.impressionsDeltaPercent ?? null)} vs prior period), `
    + `avg position ${summary.averagePosition.toFixed(1)}`
  );
}

function buildRecommendationSearchVisibilitySinceLine(
  searchContext: {
    searchConsoleStatus: "available" | "no_match" | "unavailable" | "not_configured";
    matchedPagePath: string | null;
    comparisonScope: "page" | "site" | null;
    currentWindowSummary: {
      startDate: string;
      endDate: string;
      clicks: number;
      impressions: number;
      ctr: number;
      averagePosition: number;
    } | null;
    previousWindowSummary: {
      startDate: string;
      endDate: string;
      clicks: number;
      impressions: number;
      ctr: number;
      averagePosition: number;
    } | null;
    deltaSummary: {
      clicksDeltaAbsolute: number;
      clicksDeltaPercent: number | null;
      impressionsDeltaAbsolute: number;
      impressionsDeltaPercent: number | null;
      ctrDeltaAbsolute: number;
      averagePositionDeltaAbsolute: number;
    } | null;
    topQueriesSummary: {
      query: string;
      clicks: number;
      impressions: number;
      ctr: number;
      averagePosition: number;
    }[];
  } | null,
): string | null {
  if (!searchContext || searchContext.searchConsoleStatus !== "available" || !searchContext.deltaSummary) {
    return null;
  }
  const scopeLabel = searchContext.comparisonScope === "site" ? "site visibility trend" : "page visibility trend";
  const positionDelta = searchContext.deltaSummary.averagePositionDeltaAbsolute;
  const roundedPositionDelta = Math.round(Math.abs(positionDelta) * 10) / 10;
  const positionDirection = positionDelta < 0 ? "improved" : positionDelta > 0 ? "declined" : "held steady";
  return (
    `${scopeLabel}: clicks ${formatDirectionalPercent(searchContext.deltaSummary.clicksDeltaPercent)}, `
    + `impressions ${formatDirectionalPercent(searchContext.deltaSummary.impressionsDeltaPercent)}, `
    + `position ${positionDirection}${roundedPositionDelta > 0 ? ` by ${roundedPositionDelta}` : ""}.`
  );
}

function normalizeRecommendationEffectivenessSummary(item: Recommendation): string | null {
  const raw = item.recommendation_effectiveness_context;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const status = (raw.effectiveness_status || "").trim().toLowerCase();
  if (status !== "available" && status !== "partial") {
    return null;
  }
  return truncateOptionalText(raw.summary, 220);
}

function normalizeRecommendationExecutionType(
  item: Recommendation,
):
  | "content_update"
  | "page_update"
  | "metadata_update"
  | "internal_linking"
  | "local_seo"
  | "technical_fix"
  | "mixed"
  | null {
  const normalized = (item.execution_type || "").trim().toLowerCase();
  if (
    normalized === "content_update"
    || normalized === "page_update"
    || normalized === "metadata_update"
    || normalized === "internal_linking"
    || normalized === "local_seo"
    || normalized === "technical_fix"
    || normalized === "mixed"
  ) {
    return normalized;
  }
  return null;
}

function formatRecommendationExecutionTypeLabel(
  value:
    | "content_update"
    | "page_update"
    | "metadata_update"
    | "internal_linking"
    | "local_seo"
    | "technical_fix"
    | "mixed",
): string {
  if (value === "content_update") {
    return "Content update";
  }
  if (value === "page_update") {
    return "Page update";
  }
  if (value === "metadata_update") {
    return "Metadata update";
  }
  if (value === "internal_linking") {
    return "Internal linking";
  }
  if (value === "local_seo") {
    return "Local SEO";
  }
  if (value === "technical_fix") {
    return "Technical fix";
  }
  return "Mixed work";
}

function normalizeRecommendationExecutionScope(item: Recommendation): string | null {
  return truncateOptionalText(item.execution_scope, 220);
}

function normalizeRecommendationExecutionInputs(item: Recommendation): string[] {
  if (!Array.isArray(item.execution_inputs)) {
    return [];
  }
  const normalized: string[] = [];
  for (const rawInput of item.execution_inputs) {
    if (typeof rawInput !== "string") {
      continue;
    }
    const cleaned = truncateOptionalText(rawInput, 140);
    if (!cleaned) {
      continue;
    }
    if (normalized.some((existing) => existing.toLowerCase() === cleaned.toLowerCase())) {
      continue;
    }
    normalized.push(cleaned);
    if (normalized.length >= 4) {
      break;
    }
  }
  return normalized;
}

function normalizeRecommendationExecutionReadiness(
  item: Recommendation,
): "ready" | "needs_review" | "needs_more_input" | null {
  const normalized = (item.execution_readiness || "").trim().toLowerCase();
  if (normalized === "ready" || normalized === "needs_review" || normalized === "needs_more_input") {
    return normalized;
  }
  return null;
}

function formatRecommendationExecutionReadinessLabel(
  value: "ready" | "needs_review" | "needs_more_input",
): string {
  if (value === "ready") {
    return "Ready to act";
  }
  if (value === "needs_review") {
    return "Needs review";
  }
  return "Needs more input";
}

function recommendationExecutionReadinessBadgeClass(
  value: "ready" | "needs_review" | "needs_more_input",
): string {
  if (value === "ready") {
    return "badge badge-success";
  }
  if (value === "needs_review") {
    return "badge badge-warn";
  }
  return "badge badge-muted";
}

function normalizeRecommendationBlockingReason(item: Recommendation): string | null {
  return truncateOptionalText(item.blocking_reason, 220);
}

function normalizeRecommendationEvidenceStrength(
  item: Recommendation,
): "strong" | "moderate" | "limited" | null {
  const normalized = (item.evidence_strength || "").trim().toLowerCase();
  if (normalized === "strong" || normalized === "moderate" || normalized === "limited") {
    return normalized;
  }
  return null;
}

function normalizeRecommendationCompetitorInfluenceLevel(
  item: Recommendation,
): "none" | "supporting" | "meaningful" | null {
  const normalized = (item.competitor_influence_level || "").trim().toLowerCase();
  if (normalized === "none" || normalized === "supporting" || normalized === "meaningful") {
    return normalized;
  }
  return null;
}

function formatRecommendationEvidenceStrengthLabel(
  value: "strong" | "moderate" | "limited",
): string {
  if (value === "strong") {
    return "Strong evidence";
  }
  if (value === "moderate") {
    return "Moderate evidence";
  }
  return "Limited evidence";
}

function recommendationEvidenceStrengthBadgeClass(
  value: "strong" | "moderate" | "limited",
): string {
  if (value === "strong") {
    return "badge badge-success";
  }
  if (value === "moderate") {
    return "badge badge-warn";
  }
  return "badge badge-muted";
}

function formatRecommendationCompetitorInfluenceLabel(
  value: "none" | "supporting" | "meaningful",
): string {
  if (value === "meaningful") {
    return "Meaningful influence";
  }
  if (value === "supporting") {
    return "Supporting influence";
  }
  return "No material influence";
}

function recommendationCompetitorInfluenceBadgeClass(
  value: "none" | "supporting" | "meaningful",
): string {
  if (value === "meaningful") {
    return "badge badge-success";
  }
  if (value === "supporting") {
    return "badge badge-warn";
  }
  return "badge badge-muted";
}

function sortRecommendationsByDeterministicPriority(recommendations: Recommendation[]): Recommendation[] {
  if (recommendations.length <= 1) {
    return recommendations;
  }
  const rank = (item: Recommendation): number => {
    const level = item.recommendation_priority?.priority_level;
    if (level === "high") {
      return 0;
    }
    if (level === "medium") {
      return 1;
    }
    if (level === "low") {
      return 2;
    }
    return 3;
  };
  const indexed = recommendations.map((item, index) => ({ item, index }));
  indexed.sort((left, right) => {
    const rankDiff = rank(left.item) - rank(right.item);
    if (rankDiff !== 0) {
      return rankDiff;
    }
    return left.index - right.index;
  });
  return indexed.map((entry) => entry.item);
}

type RecommendationPresentationBucketKey =
  | "ready_to_act"
  | "applied_completed"
  | "needs_review_pending"
  | "informational";

interface RecommendationPresentationBucket {
  key: RecommendationPresentationBucketKey;
  label: string;
  subtitle: string;
  badgeClass: string;
  items: Recommendation[];
}

interface RecommendationDetailClarityView {
  observedPattern: string | null;
  observedGap: string | null;
  recommendedAction: string | null;
  evidenceContextLines: string[];
}

function recommendationPresentationBucketBadgeClass(
  key: RecommendationPresentationBucketKey,
): string {
  if (key === "ready_to_act") {
    return "badge badge-critical";
  }
  if (key === "applied_completed") {
    return "badge badge-success";
  }
  if (key === "needs_review_pending") {
    return "badge badge-warn";
  }
  return "badge badge-muted";
}

function recommendationPresentationStateLabel(
  key: RecommendationPresentationBucketKey,
): string {
  if (key === "ready_to_act") {
    return "Do next";
  }
  if (key === "applied_completed") {
    return "Applied";
  }
  if (key === "needs_review_pending") {
    return "Review needed";
  }
  return "Context only";
}

function recommendationPresentationStateBadgeClass(
  key: RecommendationPresentationBucketKey,
): string {
  if (key === "ready_to_act") {
    return "badge badge-critical";
  }
  if (key === "applied_completed") {
    return "badge badge-success";
  }
  if (key === "needs_review_pending") {
    return "badge badge-warn";
  }
  return "badge badge-muted";
}

function normalizeRecommendationStatusForPresentation(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase();
}

function classifyRecommendationPresentationBucket(
  item: Recommendation,
): RecommendationPresentationBucketKey {
  const normalizedStatus = normalizeRecommendationStatusForPresentation(item.status);
  const progress = normalizeRecommendationProgress(item);
  const lifecycle = normalizeRecommendationLifecycle(item);
  const recommendationPriority = normalizeRecommendationPriority(item);
  const hasActionDelta = Boolean(normalizeRecommendationActionDelta(item));

  const appliedOrCompleted =
    progress.status === "applied_pending_refresh"
    || progress.status === "reflected_in_latest_analysis"
    || normalizedStatus === "accepted"
    || normalizedStatus === "resolved"
    || lifecycle?.state === "applied_waiting_validation"
    || lifecycle?.state === "reflected_still_relevant"
    || lifecycle?.state === "likely_resolved";
  if (appliedOrCompleted) {
    return "applied_completed";
  }

  if (normalizedStatus === "dismissed" || normalizedStatus === "snoozed") {
    return "informational";
  }

  const isPriorityAction =
    recommendationPriority?.priorityLevel === "high"
    || item.priority_band === "critical"
    || item.priority_band === "high"
    || hasActionDelta;
  if (normalizedStatus === "open" && isPriorityAction) {
    return "ready_to_act";
  }

  if (normalizedStatus === "open" || normalizedStatus === "in_progress") {
    return "needs_review_pending";
  }

  return "informational";
}

function buildRecommendationPresentationBuckets(
  recommendations: Recommendation[],
): RecommendationPresentationBucket[] {
  const grouped: Record<RecommendationPresentationBucketKey, Recommendation[]> = {
    ready_to_act: [],
    applied_completed: [],
    needs_review_pending: [],
    informational: [],
  };
  for (const recommendation of recommendations) {
    const key = classifyRecommendationPresentationBucket(recommendation);
    grouped[key].push(recommendation);
  }
  const orderedKeys: RecommendationPresentationBucketKey[] = [
    "ready_to_act",
    "applied_completed",
    "needs_review_pending",
    "informational",
  ];
  const labels: Record<
    RecommendationPresentationBucketKey,
    { label: string; subtitle: string }
  > = {
    ready_to_act: {
      label: "Ready now",
      subtitle: "Highest-impact recommendations you can act on immediately.",
    },
    applied_completed: {
      label: "Applied / completed",
      subtitle: "Already applied, or now reflected in the latest analysis.",
    },
    needs_review_pending: {
      label: "Needs review / pending",
      subtitle: "Still needs review, a decision, or follow-through.",
    },
    informational: {
      label: "Informational",
      subtitle: "Useful context with lower urgency.",
    },
  };
  return orderedKeys
    .map((key) => {
      const items = grouped[key];
      if (items.length === 0) {
        return null;
      }
      return {
        key,
        label: labels[key].label,
        subtitle: labels[key].subtitle,
        badgeClass: recommendationPresentationBucketBadgeClass(key),
        items,
      };
    })
    .filter((bucket): bucket is RecommendationPresentationBucket => bucket !== null);
}

function buildRecommendationDetailClarityView(params: {
  actionDelta: {
    observedCompetitorPattern: string;
    observedSiteGap: string;
    recommendedOperatorAction: string;
    evidenceStrength: "high" | "medium" | "low";
  } | null;
  evidenceSummary: string | null;
  observedGapSummary: string | null;
  actionClarity: string | null;
  expectedOutcome: string | null;
  competitorLinkageSummary: string | null;
  evidenceTrace: string[];
  targetContext: RecommendationTargetContext | null;
  targetPageHints: string[];
  targetContentSummary: string | null;
}): RecommendationDetailClarityView {
  const observedPattern =
    params.actionDelta?.observedCompetitorPattern
    || params.evidenceSummary
    || null;
  const observedGap =
    params.actionDelta?.observedSiteGap
    || params.observedGapSummary
    || params.competitorLinkageSummary
    || null;
  const recommendedAction =
    params.actionDelta?.recommendedOperatorAction
    || params.actionClarity
    || params.expectedOutcome
    || null;
  const evidenceContextLines: string[] = [];
  if (params.actionDelta) {
    evidenceContextLines.push(
      `Evidence strength: ${formatRecommendationActionDeltaEvidenceStrength(params.actionDelta.evidenceStrength)}.`,
    );
  }
  if (params.evidenceTrace.length > 0) {
    evidenceContextLines.push(`Evidence trace: ${params.evidenceTrace.join(" · ")}`);
  }
  if (params.targetContext) {
    evidenceContextLines.push(`Target context: ${formatRecommendationTargetContext(params.targetContext)}`);
  }
  if (params.targetPageHints.length > 0) {
    evidenceContextLines.push(`Likely pages: ${params.targetPageHints.join(", ")}`);
  }
  if (params.targetContentSummary) {
    evidenceContextLines.push(`Content to update: ${params.targetContentSummary}`);
  }
  if (params.expectedOutcome && params.expectedOutcome !== recommendedAction) {
    evidenceContextLines.push(`Expected outcome: ${params.expectedOutcome}`);
  }
  return {
    observedPattern,
    observedGap,
    recommendedAction,
    evidenceContextLines,
  };
}

function hasRecommendationDetailClarityContent(clarity: RecommendationDetailClarityView): boolean {
  return Boolean(
    clarity.observedPattern
    || clarity.observedGap
    || clarity.recommendedAction
    || clarity.evidenceContextLines.length > 0,
  );
}

function buildRecommendationDetailClarityFromItem(item: Recommendation): RecommendationDetailClarityView {
  return buildRecommendationDetailClarityView({
    actionDelta: normalizeRecommendationActionDelta(item),
    evidenceSummary: normalizeRecommendationEvidenceSummary(item),
    observedGapSummary: normalizeRecommendationObservedGapSummary(item),
    actionClarity: normalizeRecommendationActionClarity(item),
    expectedOutcome: normalizeRecommendationExpectedOutcome(item),
    competitorLinkageSummary: normalizeRecommendationCompetitorLinkageSummary(item),
    evidenceTrace: normalizeRecommendationEvidenceTrace(item),
    targetContext: normalizeRecommendationTargetContext(item),
    targetPageHints: normalizeRecommendationTargetPageHints(item),
    targetContentSummary: normalizeRecommendationTargetContentSummary(item),
  });
}

function RecommendationDetailClarity({
  clarity,
  bucketKey,
  testId = "recommendation-detail-clarity",
}: {
  clarity: RecommendationDetailClarityView;
  bucketKey: RecommendationPresentationBucketKey;
  testId?: string;
}): JSX.Element | null {
  if (!hasRecommendationDetailClarityContent(clarity)) {
    return null;
  }
  return (
    <div className={`recommendation-detail-clarity recommendation-detail-clarity-${bucketKey}`} data-testid={testId}>
      {clarity.observedPattern ? (
        <div className="recommendation-detail-clarity-row" data-testid="recommendation-clarity-observed-pattern">
          <span className="recommendation-detail-clarity-label">What we observed</span>
          <span className="hint muted">{clarity.observedPattern}</span>
        </div>
      ) : null}
      {clarity.observedGap ? (
        <div className="recommendation-detail-clarity-row" data-testid="recommendation-clarity-gap">
          <span className="recommendation-detail-clarity-label">What needs improvement</span>
          <span className="hint muted">{clarity.observedGap}</span>
        </div>
      ) : null}
      {clarity.recommendedAction ? (
        <div className="recommendation-detail-clarity-row recommendation-detail-clarity-row-action" data-testid="recommendation-clarity-action">
          <span className="recommendation-detail-clarity-label">What to do next</span>
          <strong>{clarity.recommendedAction}</strong>
        </div>
      ) : null}
      {clarity.evidenceContextLines.length > 0 ? (
        <div className="recommendation-detail-clarity-row recommendation-detail-clarity-row-evidence" data-testid="recommendation-clarity-evidence">
          <span className="recommendation-detail-clarity-label">Why this is recommended</span>
          <div className="stack-micro">
            {clarity.evidenceContextLines.map((line, index) => (
              <span key={`recommendation-clarity-evidence-${index}`} className="hint muted">
                {line}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
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
  const [promptExpanded, setPromptExpanded] = useState(false);
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

  useEffect(() => {
    setPromptExpanded(false);
  }, [
    preview.promptType,
    preview.source,
    preview.model,
    preview.promptVersion,
    preview.promptLabel,
    preview.systemPrompt,
    preview.userPrompt,
  ]);

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
      <details
        open={promptExpanded}
        onToggle={(event) => {
          setPromptExpanded(event.currentTarget.open);
        }}
      >
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

function safeAutomationBindingErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired while binding automation.";
    }
    if (error.status === 404) {
      return "Automation binding target was not found.";
    }
    if (error.status === 409) {
      return "This action is already bound to a different automation.";
    }
    if (error.status === 422) {
      return "Automation binding is not allowed for this action state.";
    }
  }
  return "Unable to bind this action to automation right now.";
}

function safeAutomationExecutionErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 404) {
      return "Activated action or bound automation was not found.";
    }
    if (error.status === 409) {
      return "An automation run is already in progress for this site.";
    }
    if (error.status === 422) {
      return "Automation execution is not available for this action state.";
    }
    if (error.status === 401) {
      return "Session expired while requesting automation execution.";
    }
  }
  return "Unable to request automation execution right now.";
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

function buildAutomationPageHref(siteId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  return `/automation?${params.toString()}`;
}

function deriveRecommendationTrustTier(
  recommendation: Recommendation,
): ActionExecutionItem["trustTier"] {
  const tiers = (recommendation.competitor_evidence_links || [])
    .map((link) => link.trust_tier || link.evidence_trust_tier || null)
    .filter((value): value is NonNullable<typeof value> => Boolean(value));
  if (tiers.includes("trusted_verified")) {
    return "trusted_verified";
  }
  if (tiers.includes("informational_unverified")) {
    return "informational_unverified";
  }
  if (tiers.includes("informational_candidate")) {
    return "informational_candidate";
  }
  return null;
}

function deriveWorkspaceRecommendationActionExecutionItem(params: {
  recommendation: Recommendation;
  actionStateCode: ActionExecutionItem["actionStateCode"];
  automationContextAvailable: boolean;
  automationInFlight: boolean;
  linkedRecommendationRunOutputId: string | null;
  linkedRecommendationNarrativeOutputId: string | null;
}): ActionExecutionItem {
  const {
    recommendation,
    actionStateCode,
    automationContextAvailable,
    automationInFlight,
    linkedRecommendationRunOutputId,
    linkedRecommendationNarrativeOutputId,
  } = params;
  const linkedRecommendationRunId =
    linkedRecommendationRunOutputId === recommendation.recommendation_run_id
      ? recommendation.recommendation_run_id
      : null;
  return {
    id: recommendation.id,
    title: recommendation.title,
    actionStateCode,
    priorityBand: recommendation.priority_band,
    trustTier: deriveRecommendationTrustTier(recommendation),
    actionLineage: recommendation.action_lineage || null,
    linkedOutputId: linkedRecommendationRunId,
    linkedNarrativeId: linkedRecommendationRunId ? linkedRecommendationNarrativeOutputId : null,
    automationAvailable: automationContextAvailable,
    automationInFlight,
    blockedReason:
      actionStateCode === "blocked_unavailable"
        ? "Recommendation is blocked until required automation or run dependencies are available."
        : undefined,
    triggerSource: recommendationSourceType(recommendation),
    outputReview: linkedRecommendationRunId
      ? {
          outputId: linkedRecommendationRunId,
          summary:
            recommendation.recommendation_action_clarity
            || recommendation.recommendation_evidence_summary
            || recommendation.rationale,
          details:
            recommendation.recommendation_expected_outcome
            || recommendation.recommendation_observed_gap_summary
            || null,
          sourceLabel: "Automation recommendation output",
        }
      : undefined,
  };
}

function deriveWorkspaceAutomationActionExecutionItem(params: {
  run: AutomationRun;
  actionStateCode: ActionExecutionItem["actionStateCode"];
  linkedRecommendationRunOutputId: string | null;
  linkedRecommendationNarrativeOutputId: string | null;
}): ActionExecutionItem {
  const { run, actionStateCode, linkedRecommendationRunOutputId, linkedRecommendationNarrativeOutputId } = params;
  const normalizedStatus = normalizeAutomationRunStatus(run.status);
  const steps = normalizeAutomationRunSteps(run);
  return {
    id: run.id,
    title: `Automation run ${run.id}`,
    actionStateCode,
    linkedOutputId: linkedRecommendationRunOutputId,
    linkedNarrativeId: linkedRecommendationNarrativeOutputId,
    automationAvailable: true,
    automationInFlight: normalizedStatus === "queued" || normalizedStatus === "running",
    blockedReason:
      normalizedStatus === "failed"
        ? "Automation failed before linked recommendation output completed."
        : undefined,
    triggerSource: run.trigger_source,
    outputReview: linkedRecommendationRunOutputId || linkedRecommendationNarrativeOutputId
      ? {
          outputId: linkedRecommendationRunOutputId || linkedRecommendationNarrativeOutputId,
          summary:
            normalizedStatus === "completed"
              ? "Automation output is ready for operator review."
              : "Automation output context is available for review.",
          details:
            normalizedStatus === "failed"
              ? "Automation failed before all outputs were completed."
              : "Use linked recommendation outputs to confirm next operator steps.",
          sourceLabel: "Automation output",
          stepDetails: steps.map((step) => ({
            stepName: step.step_name.replace(/_/g, " "),
            status: step.status,
            reasonSummary: (step.reason_summary || step.error_message || null),
            pagesAnalyzedCount: step.pages_analyzed_count ?? null,
            issuesFoundCount: step.issues_found_count ?? null,
            recommendationsGeneratedCount: step.recommendations_generated_count ?? null,
          })),
        }
      : undefined,
  };
}

function resolveWorkspaceRecommendationControlHref(params: {
  control: ActionControl;
  recommendation: Recommendation;
  siteId: string;
  linkedRecommendationRunOutputId: string | null;
}): string | undefined {
  const { control, recommendation, siteId, linkedRecommendationRunOutputId } = params;
  if (control.type === "review_recommendation" || control.type === "mark_completed") {
    return buildRecommendationDetailHref(recommendation.id, siteId);
  }
  if (control.type === "review_output") {
    const recommendationRunId = linkedRecommendationRunOutputId || recommendation.recommendation_run_id;
    return buildRecommendationRunHref(recommendationRunId, siteId);
  }
  if (control.type === "run_automation" || control.type === "view_automation_status") {
    return buildAutomationPageHref(siteId);
  }
  return undefined;
}

function resolveWorkspaceAutomationControlHref(params: {
  control: ActionControl;
  siteId: string;
  linkedRecommendationRunOutputId: string | null;
}): string | undefined {
  const { control, siteId, linkedRecommendationRunOutputId } = params;
  if (control.type === "run_automation" || control.type === "view_automation_status") {
    return buildAutomationPageHref(siteId);
  }
  if (
    control.type === "review_output"
    || control.type === "review_recommendation"
    || control.type === "mark_completed"
  ) {
    if (linkedRecommendationRunOutputId) {
      return buildRecommendationRunHref(linkedRecommendationRunOutputId, siteId);
    }
    return "/recommendations";
  }
  return undefined;
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
  const [googleBusinessProfileConnection, setGoogleBusinessProfileConnection] =
    useState<GoogleBusinessProfileConnectionStatusResponse | null>(null);
  const [googleBusinessProfileConnectionError, setGoogleBusinessProfileConnectionError] = useState<string | null>(null);

  const [queueResponse, setQueueResponse] = useState<RecommendationListResponse | null>(null);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [recommendationActionDecisionByItemId, setRecommendationActionDecisionByItemId] =
    useState<Record<string, ActionDecision>>({});
  const [recommendationActionDecisionSavingByItemId, setRecommendationActionDecisionSavingByItemId] =
    useState<Record<string, boolean>>({});
  const [recommendationActionDecisionErrorByItemId, setRecommendationActionDecisionErrorByItemId] =
    useState<Record<string, string | null>>({});
  const [automationBindingPendingByActionId, setAutomationBindingPendingByActionId] =
    useState<Record<string, boolean>>({});
  const [automationBindingErrorByActionId, setAutomationBindingErrorByActionId] =
    useState<Record<string, string | null>>({});
  const [automationRunPendingByActionId, setAutomationRunPendingByActionId] =
    useState<Record<string, boolean>>({});
  const [automationRunErrorByActionId, setAutomationRunErrorByActionId] =
    useState<Record<string, string | null>>({});
  const [automationActionDecisionByItemId, setAutomationActionDecisionByItemId] =
    useState<Record<string, ActionDecision>>({});

  const [recommendationRuns, setRecommendationRuns] = useState<RecommendationRun[]>([]);
  const [recommendationRunError, setRecommendationRunError] = useState<string | null>(null);
  const [automationRuns, setAutomationRuns] = useState<AutomationRun[]>([]);
  const [automationRunError, setAutomationRunError] = useState<string | null>(null);
  const [siteAnalyticsSummary, setSiteAnalyticsSummary] = useState<SiteAnalyticsSummaryResponse | null>(null);
  const [siteAnalyticsError, setSiteAnalyticsError] = useState<string | null>(null);
  const [ga4OnboardingStatus, setGa4OnboardingStatus] = useState<GA4SiteOnboardingStatusResponse | null>(null);
  const [ga4OnboardingError, setGa4OnboardingError] = useState<string | null>(null);
  const [ga4PropertyInput, setGa4PropertyInput] = useState("");
  const [ga4PropertySavePending, setGa4PropertySavePending] = useState(false);
  const [ga4PropertySaveError, setGa4PropertySaveError] = useState<string | null>(null);
  const [ga4PropertySaveMessage, setGa4PropertySaveMessage] = useState<string | null>(null);
  const [searchConsoleSiteSummary, setSearchConsoleSiteSummary] = useState<SearchConsoleSiteSummaryResponse | null>(null);
  const [searchConsoleSiteSummaryError, setSearchConsoleSiteSummaryError] = useState<string | null>(null);
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
  const [latestWorkspaceTrustSummary, setLatestWorkspaceTrustSummary] = useState<WorkspaceTrustSummary | null>(null);
  const [latestCompetitorSectionFreshness, setLatestCompetitorSectionFreshness] =
    useState<WorkspaceSectionFreshness | null>(null);
  const [latestRecommendationSectionFreshness, setLatestRecommendationSectionFreshness] =
    useState<WorkspaceSectionFreshness | null>(null);
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
  const [confirmSyntheticAcceptByDraftId, setConfirmSyntheticAcceptByDraftId] = useState<Record<string, boolean>>({});
  const [hideSyntheticScaffoldOverride, setHideSyntheticScaffoldOverride] = useState<boolean | null>(null);

  const [activeEventTypes, setActiveEventTypes] = useState<Set<SiteTimelineEventType>>(
    () => new Set(TIMELINE_EVENT_TYPE_OPTIONS.map((option) => option.value)),
  );
  const [activeStatuses, setActiveStatuses] = useState<Set<string>>(() => new Set());
  const [expandedTimeline, setExpandedTimeline] = useState(false);
  const [activeWorkspaceContentTab, setActiveWorkspaceContentTab] = useState<WorkspaceContentTab>("summary");

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
  const syntheticCompetitorDraftCount = useMemo(
    () => competitorProfileDrafts.filter((draft) => isSyntheticCompetitorDraft(draft)).length,
    [competitorProfileDrafts],
  );
  const nonSyntheticCompetitorDraftCount = Math.max(0, competitorProfileDrafts.length - syntheticCompetitorDraftCount);
  const defaultHideSyntheticScaffolds =
    nonSyntheticCompetitorDraftCount >= HIDE_SYNTHETIC_DEFAULT_NON_SYNTHETIC_THRESHOLD;
  const hideSyntheticScaffolds = hideSyntheticScaffoldOverride ?? defaultHideSyntheticScaffolds;
  const visibleCompetitorProfileDrafts = useMemo(
    () =>
      hideSyntheticScaffolds
        ? competitorProfileDrafts.filter((draft) => !isSyntheticCompetitorDraft(draft))
        : competitorProfileDrafts,
    [competitorProfileDrafts, hideSyntheticScaffolds],
  );
  const hiddenSyntheticDraftCount = hideSyntheticScaffolds ? syntheticCompetitorDraftCount : 0;

  useEffect(() => {
    setHideSyntheticScaffoldOverride(null);
  }, [latestCompetitorProfileRun?.id]);

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

  const competitorSummaryStripMetrics = useMemo(() => {
    const proposedFromPipeline = competitorCandidatePipelineSummary?.proposed_candidate_count;
    const finalFromPipeline = competitorCandidatePipelineSummary?.final_candidate_count;
    const rejectedEligibilityFromPipeline =
      competitorCandidatePipelineSummary?.rejected_by_eligibility_count || 0;
    const fallbackProposedCount =
      competitorProfileDrafts.length + Math.max(rejectedCompetitorCandidateCount, rejectedEligibilityFromPipeline);
    const totalCandidates = Math.max(
      0,
      proposedFromPipeline
        ?? latestCompetitorProfileRun?.requested_candidate_count
        ?? fallbackProposedCount,
    );
    const eligibleCandidates = Math.max(
      0,
      competitorCandidatePipelineSummary?.eligible_candidate_count
        ?? totalCandidates - Math.max(0, rejectedCompetitorCandidateCount),
    );
    const finalReturned = Math.max(0, finalFromPipeline ?? competitorProfileDrafts.length);
    const excludedCandidates = Math.max(0, totalCandidates - finalReturned);
    const failureCountFromAttempts = competitorProviderAttempts.reduce((count, attempt) => {
      const outcome = (attempt.outcome || "").trim().toLowerCase();
      return outcome === "success" ? count : count + 1;
    }, 0);
    const failureCount = failureCountFromAttempts > 0
      ? failureCountFromAttempts
      : latestCompetitorProfileRun?.status === "failed"
        ? 1
        : 0;
    const retryCountBase = Math.max(
      0,
      (competitorProviderAttemptCount || competitorProviderAttempts.length || 0) - 1,
    );
    const retryCount = retryCountBase > 0
      ? retryCountBase
      : latestCompetitorProfileRun?.parent_run_id
        ? 1
        : 0;
    return {
      totalCandidates,
      eligibleCandidates,
      finalReturned,
      excludedCandidates,
      failureCount,
      retryCount,
    };
  }, [
    competitorCandidatePipelineSummary,
    competitorProfileDrafts.length,
    competitorProviderAttemptCount,
    competitorProviderAttempts,
    latestCompetitorProfileRun,
    rejectedCompetitorCandidateCount,
  ]);

  const competitorPipelineStageRows = useMemo<CompetitorPipelineStageRow[]>(() => {
    if (!competitorCandidatePipelineSummary) {
      return [];
    }
    return [
      {
        stage: "Proposed",
        count: competitorCandidatePipelineSummary.proposed_candidate_count,
        description: "Candidates parsed from provider output before deterministic filtering.",
      },
      {
        stage: "Rejected by eligibility",
        count: competitorCandidatePipelineSummary.rejected_by_eligibility_count,
        description: "Removed by strict eligibility rules.",
      },
      {
        stage: "Eligible",
        count: competitorCandidatePipelineSummary.eligible_candidate_count,
        description: "Candidates that passed eligibility checks.",
      },
      {
        stage: "Removed by tuning",
        count: competitorCandidatePipelineSummary.rejected_by_tuning_count,
        description: "Filtered out by deterministic tuning thresholds.",
      },
      {
        stage: "Survived tuning",
        count: competitorCandidatePipelineSummary.survived_tuning_count,
        description: "Candidates still in the pool after tuning.",
      },
      {
        stage: "Removed by existing-domain match",
        count: competitorCandidatePipelineSummary.removed_by_existing_domain_match_count,
        description: "Dropped because domain already exists in known competitors.",
      },
      {
        stage: "Removed by deduplication",
        count: competitorCandidatePipelineSummary.removed_by_deduplication_count,
        description: "Removed as duplicates.",
      },
      {
        stage: "Removed by final limit",
        count: competitorCandidatePipelineSummary.removed_by_final_limit_count,
        description: "Trimmed by final output cap.",
      },
      {
        stage: "Final returned",
        count: competitorCandidatePipelineSummary.final_candidate_count,
        description: "Reviewable drafts returned to operators.",
      },
    ];
  }, [competitorCandidatePipelineSummary]);

  const competitorFailureCategoryChips = useMemo(
    () =>
      competitorProfileSummary
        ? Object.entries(competitorProfileSummary.failure_category_counts)
            .filter(([, value]) => value > 0)
            .sort(([left], [right]) => left.localeCompare(right))
        : [],
    [competitorProfileSummary],
  );

  const competitorExclusionReasonChips = useMemo(
    () =>
      competitorProfileSummary
        ? Object.entries(competitorProfileSummary.exclusion_counts_by_reason)
            .filter(([, value]) => value > 0)
            .sort(([left], [right]) => left.localeCompare(right))
        : [],
    [competitorProfileSummary],
  );

  const hasCompetitorDebugDetails = Boolean(
    latestCompetitorPromptPreview
    || competitorProfileSummary
    || (rejectedCompetitorCandidateCount > 0 && rejectedCompetitorCandidates.length > 0)
    || (tuningRejectedCompetitorCandidateCount > 0 && tuningRejectedCompetitorCandidates.length > 0)
    || (competitorProviderAttemptCount > 0 && competitorProviderAttempts.length > 0)
    || latestCompetitorProfileRun?.parent_run_id
    || latestCompetitorProfileRun?.failure_category
    || latestCompetitorProfileRun?.error_summary,
  );

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
  const workspaceTrustSummary = useMemo(
    () => normalizeWorkspaceTrustSummary(latestWorkspaceTrustSummary),
    [latestWorkspaceTrustSummary],
  );
  const competitorSectionFreshness = useMemo(
    () => normalizeWorkspaceSectionFreshness(latestCompetitorSectionFreshness),
    [latestCompetitorSectionFreshness],
  );
  const recommendationSectionFreshness = useMemo(
    () => normalizeWorkspaceSectionFreshness(latestRecommendationSectionFreshness),
    [latestRecommendationSectionFreshness],
  );
  const recommendationApplyOutcomePresentation = useMemo(
    () => normalizeRecommendationApplyOutcomePresentation(recommendationApplyOutcome, recommendationSectionFreshness),
    [recommendationApplyOutcome, recommendationSectionFreshness],
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
  const recommendationPresentationBuckets = useMemo(
    () => buildRecommendationPresentationBuckets(latestCompletedRecommendations),
    [latestCompletedRecommendations],
  );
  const recommendationReadyNowBucket = useMemo(
    () => recommendationPresentationBuckets.find((bucket) => bucket.key === "ready_to_act") || null,
    [recommendationPresentationBuckets],
  );
  const topReadyNowRecommendation = useMemo(
    () => (recommendationReadyNowBucket?.items[0] ? recommendationReadyNowBucket.items[0] : null),
    [recommendationReadyNowBucket],
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
    setLatestCompletedRecommendations(sortRecommendationsByDeterministicPriority(summary.recommendations.items));
    setLatestCompletedRecommendationNarrative(summary.latest_narrative);
    setLatestCompletedTuningSuggestions(summary.tuning_suggestions);
    setLatestRecommendationApplyOutcome(summary.apply_outcome || null);
    setLatestWorkspaceTrustSummary(summary.workspace_trust_summary || null);
    setLatestCompetitorSectionFreshness(summary.competitor_section_freshness || null);
    setLatestRecommendationSectionFreshness(summary.recommendation_section_freshness || null);
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
      setGa4PropertyInput("");
      setGa4PropertySaveError(null);
      setGa4PropertySaveMessage(null);
      return;
    }
    setGa4PropertyInput(normalizeGa4PropertyInput(selectedSite.ga4_property_id || ""));
    setGa4PropertySaveError(null);
    setGa4PropertySaveMessage(null);
  }, [selectedSite?.id, selectedSite?.ga4_property_id]);

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

  async function handleSaveGa4Property(): Promise<void> {
    if (!selectedSite) {
      return;
    }
    const normalizedProperty = normalizeGa4PropertyInput(ga4PropertyInput);
    if (normalizedProperty && !looksLikeGa4PropertyId(normalizedProperty)) {
      setGa4PropertySaveError("Use only the numeric GA4 property ID (for example, 123456789).");
      return;
    }

    setGa4PropertySavePending(true);
    setGa4PropertySaveError(null);
    setGa4PropertySaveMessage(null);
    try {
      await updateSite(context.token, context.businessId, selectedSite.id, {
        ga4_property_id: normalizedProperty || null,
      });
      await context.refreshSites();
      setWorkspaceRefreshNonce((current) => current + 1);
      if (normalizedProperty) {
        setGa4PropertySaveMessage("GA4 property saved. Connection status will refresh shortly.");
      } else {
        setGa4PropertySaveMessage("GA4 property cleared for this site.");
      }
    } catch (error) {
      if (error instanceof ApiRequestError) {
        if (error.status === 403) {
          setGa4PropertySaveError("Only admin users can update GA4 property settings.");
        } else if (error.status === 422) {
          setGa4PropertySaveError("Invalid GA4 property value. Use only the numeric GA4 property ID.");
        } else {
          setGa4PropertySaveError("Unable to save GA4 property right now. Try again.");
        }
      } else {
        setGa4PropertySaveError("Unable to save GA4 property right now. Try again.");
      }
    } finally {
      setGa4PropertySavePending(false);
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

  const latestApplyTitle = recommendationApplyOutcome?.appliedRecommendationTitle || null;
  const latestApplyExpectation = recommendationApplyOutcome?.nextRefreshExpectation || null;
  const competitorSummaryTone = workspaceSectionFreshnessCardTone(competitorSectionFreshness?.stateCode || null);
  const recommendationSummaryTone = workspaceSectionFreshnessCardTone(
    recommendationSectionFreshness?.stateCode || null,
  );
  const trustSummaryTone: "neutral" | "success" | "warning" | "danger" =
    workspaceTrustSummary?.latestCompetitorStatus === "failed"
      ? "danger"
      : workspaceTrustSummary?.usedSyntheticFallback
        ? "warning"
        : "neutral";
  const googleBusinessProfileWorkspaceStatus = useMemo(
    () =>
      normalizeGoogleBusinessProfileWorkspaceStatus(
        googleBusinessProfileConnection,
        googleBusinessProfileConnectionError,
      ),
    [googleBusinessProfileConnection, googleBusinessProfileConnectionError],
  );
  const latestWorkflowChangeNote = recommendationApplyOutcome?.appliedAt
    ? `Applied ${formatDateTime(recommendationApplyOutcome.appliedAt)}.`
    : latestCompletedRecommendationRun?.completed_at
      ? `Latest recommendation run completed ${formatDateTime(latestCompletedRecommendationRun.completed_at)}.`
      : latestCompetitorProfileRun?.completed_at
        ? `Latest competitor run completed ${formatDateTime(latestCompetitorProfileRun.completed_at)}.`
        : null;
  const operatorActionRecommendations = useMemo(
    () =>
      latestCompletedRecommendations.length > 0
        ? latestCompletedRecommendations
        : (queueResponse?.items || []),
    [latestCompletedRecommendations, queueResponse?.items],
  );
  const operatorPrimaryAction = useMemo(
    () =>
      buildOperatorPrimaryAction({
        googleBusinessProfileStatus: googleBusinessProfileWorkspaceStatus,
        recommendations: operatorActionRecommendations,
        recommendationApplyOutcome,
        recommendationApplyOutcomePresentation,
        recommendationFreshness: recommendationSectionFreshness,
        competitorFreshness: competitorSectionFreshness,
        workspaceReadinessMessage,
      }),
    [
      competitorSectionFreshness,
      googleBusinessProfileWorkspaceStatus,
      operatorActionRecommendations,
      recommendationApplyOutcome,
      recommendationApplyOutcomePresentation,
      recommendationSectionFreshness,
      workspaceReadinessMessage,
    ],
  );

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
      setConfirmSyntheticAcceptByDraftId({});
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
      setConfirmSyntheticAcceptByDraftId({});
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
      setConfirmSyntheticAcceptByDraftId((current) => {
        const next = { ...current };
        delete next[draftId];
        return next;
      });
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
    draft: CompetitorProfileDraft,
    overrides?: ReturnType<typeof buildDraftEditPayloadFromFormState>,
    options?: { acceptAsUnverified?: boolean },
  ): Promise<void> {
    const draftId = draft.id;
    if (!context.token || !context.businessId || !siteId || !latestCompetitorProfileRunId) {
      return;
    }
    const syntheticDraft = isSyntheticCompetitorDraft(draft);
    const acceptAsUnverified = Boolean(options?.acceptAsUnverified);
    const syntheticConfirmed = Boolean(confirmSyntheticAcceptByDraftId[draftId]);
    const candidateDomain = (overrides?.suggested_domain ?? draft.suggested_domain ?? "").trim();
    const hasVerifiedSyntheticDomain = !isSyntheticScaffoldDomain(candidateDomain);
    if (acceptAsUnverified && !syntheticDraft) {
      setCompetitorProfileActionError(
        "Accept as unverified is only available for synthetic review scaffolds.",
      );
      setCompetitorProfileActionMessage(null);
      return;
    }
    if (syntheticDraft && !syntheticConfirmed) {
      setCompetitorProfileActionError(
        "Synthetic review scaffold drafts require explicit confirmation before acceptance.",
      );
      setCompetitorProfileActionMessage(null);
      return;
    }
    if (syntheticDraft && !hasVerifiedSyntheticDomain && !acceptAsUnverified) {
      setCompetitorProfileActionError(
        "Synthetic review scaffold drafts require a verified website/domain before acceptance.",
      );
      setCompetitorProfileActionMessage(null);
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
          ...(syntheticDraft ? { confirm_synthetic_scaffold: syntheticConfirmed } : {}),
          ...(acceptAsUnverified ? { accept_as_unverified: true } : {}),
        },
      );
      upsertDraft(updated);
      setConfirmSyntheticAcceptByDraftId((current) => {
        const next = { ...current };
        delete next[draftId];
        return next;
      });
      setCompetitorProfileActionMessage(
        acceptAsUnverified
          ? "Draft accepted as unverified competitor scaffold."
          : "Draft accepted and added to competitors.",
      );
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
      setGoogleBusinessProfileConnection(null);
      setGoogleBusinessProfileConnectionError(null);
      setQueueResponse(null);
      setQueueError(null);
      setRecommendationActionDecisionByItemId({});
      setRecommendationActionDecisionSavingByItemId({});
      setRecommendationActionDecisionErrorByItemId({});
      setAutomationBindingPendingByActionId({});
      setAutomationBindingErrorByActionId({});
      setAutomationRunPendingByActionId({});
      setAutomationRunErrorByActionId({});
      setAutomationActionDecisionByItemId({});
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
      setLatestWorkspaceTrustSummary(null);
      setLatestCompetitorSectionFreshness(null);
      setLatestRecommendationSectionFreshness(null);
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
      setConfirmSyntheticAcceptByDraftId({});
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
      setConfirmSyntheticAcceptByDraftId({});
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
      setLatestWorkspaceTrustSummary(null);
      setLatestCompetitorSectionFreshness(null);
      setLatestRecommendationSectionFreshness(null);
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
      setConfirmSyntheticAcceptByDraftId({});
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
      setAutomationRuns([]);
      setAutomationRunError(null);
      return;
    }

    let cancelled = false;

    async function loadWorkspace() {
      setLoadingWorkspace(true);
      setNotFound(false);
      setAuditError(null);
      setCompetitorError(null);
      setGoogleBusinessProfileConnection(null);
      setGoogleBusinessProfileConnectionError(null);
      setQueueError(null);
      setRecommendationRunError(null);
      setAutomationRuns([]);
      setAutomationRunError(null);
      setNarrativeLookupError(null);
      setLatestCompletedRecommendationRun(null);
      setLatestCompletedRecommendations([]);
      setLatestCompletedRecommendationNarrative(null);
      setLatestCompletedTuningSuggestions([]);
      setLatestRecommendationApplyOutcome(null);
      setLatestWorkspaceTrustSummary(null);
      setLatestCompetitorSectionFreshness(null);
      setLatestRecommendationSectionFreshness(null);
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
      setSiteAnalyticsSummary(null);
      setSiteAnalyticsError(null);
      setGa4OnboardingStatus(null);
      setGa4OnboardingError(null);
      setSearchConsoleSiteSummary(null);
      setSearchConsoleSiteSummaryError(null);
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
        automationRunsResult,
        recommendationWorkspaceSummaryResult,
        googleBusinessProfileConnectionResult,
        businessSettingsResult,
        siteAnalyticsSummaryResult,
        ga4OnboardingStatusResult,
        searchConsoleSiteSummaryResult,
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
          fetchAutomationRuns(context.token, context.businessId, siteId),
          fetchRecommendationWorkspaceSummary(context.token, context.businessId, siteId),
          fetchGoogleBusinessProfileConnection(context.token),
          fetchBusinessSettings(context.token, context.businessId),
          fetchSiteAnalyticsSummary(context.token, context.businessId, siteId),
          fetchGA4SiteOnboardingStatus(context.token, context.businessId, siteId),
          fetchSearchConsoleSiteSummary(context.token, context.businessId, siteId),
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

      if (googleBusinessProfileConnectionResult.status === "fulfilled") {
        setGoogleBusinessProfileConnection(googleBusinessProfileConnectionResult.value);
        setGoogleBusinessProfileConnectionError(null);
      } else {
        setGoogleBusinessProfileConnection(null);
        setGoogleBusinessProfileConnectionError(
          safeSectionErrorMessage(
            "Google Business Profile integration status",
            googleBusinessProfileConnectionResult.reason,
          ),
        );
      }

      if (queueResult.status === "fulfilled") {
        setQueueResponse(queueResult.value);
        setRecommendationActionDecisionByItemId({});
        setRecommendationActionDecisionSavingByItemId({});
        setRecommendationActionDecisionErrorByItemId({});
        setAutomationBindingPendingByActionId({});
        setAutomationBindingErrorByActionId({});
        setAutomationRunPendingByActionId({});
        setAutomationRunErrorByActionId({});
      } else {
        setQueueResponse(null);
        setRecommendationActionDecisionByItemId({});
        setRecommendationActionDecisionSavingByItemId({});
        setRecommendationActionDecisionErrorByItemId({});
        setAutomationBindingPendingByActionId({});
        setAutomationBindingErrorByActionId({});
        setAutomationRunPendingByActionId({});
        setAutomationRunErrorByActionId({});
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

      if (automationRunsResult.status === "fulfilled") {
        setAutomationRuns(sortAutomationRunsNewestFirst(automationRunsResult.value.items).slice(0, MAX_AUTOMATION_RUN_ROWS));
        setAutomationRunError(null);
      } else {
        setAutomationRuns([]);
        setAutomationRunError(safeSectionErrorMessage("automation runs", automationRunsResult.reason));
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
        setLatestWorkspaceTrustSummary(null);
        setLatestCompetitorSectionFreshness(null);
        setLatestRecommendationSectionFreshness(null);
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

      if (siteAnalyticsSummaryResult.status === "fulfilled") {
        setSiteAnalyticsSummary(siteAnalyticsSummaryResult.value);
        setSiteAnalyticsError(null);
      } else {
        setSiteAnalyticsSummary(null);
        setSiteAnalyticsError(safeSectionErrorMessage("traffic trend", siteAnalyticsSummaryResult.reason));
      }

      if (ga4OnboardingStatusResult.status === "fulfilled") {
        setGa4OnboardingStatus(ga4OnboardingStatusResult.value);
        setGa4OnboardingError(null);
      } else {
        setGa4OnboardingStatus(null);
        setGa4OnboardingError(safeSectionErrorMessage("GA4 onboarding status", ga4OnboardingStatusResult.reason));
      }

      if (searchConsoleSiteSummaryResult.status === "fulfilled") {
        setSearchConsoleSiteSummary(searchConsoleSiteSummaryResult.value);
        setSearchConsoleSiteSummaryError(null);
      } else {
        setSearchConsoleSiteSummary(null);
        setSearchConsoleSiteSummaryError(
          safeSectionErrorMessage("search visibility trend", searchConsoleSiteSummaryResult.reason),
        );
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
            setConfirmSyntheticAcceptByDraftId({});
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
            setConfirmSyntheticAcceptByDraftId({});
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
          setConfirmSyntheticAcceptByDraftId({});
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
        setConfirmSyntheticAcceptByDraftId({});
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
        setConfirmSyntheticAcceptByDraftId({});
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

  useEffect(() => {
    const hasInFlightLineage = (queueResponse?.items || []).some((item) =>
      hasInFlightLineageExecution(item.action_lineage || null),
    );
    const hasInFlightAutomationRun = automationRuns.some((run) => {
      const normalizedStatus = normalizeAutomationRunStatus(run.status);
      return normalizedStatus === "queued" || normalizedStatus === "running";
    });
    if (
      (!hasInFlightLineage && !hasInFlightAutomationRun)
      || loadingWorkspace
      || context.loading
      || context.error
      || !siteId
    ) {
      return;
    }

    const intervalId = window.setInterval(() => {
      setWorkspaceRefreshNonce((current) => current + 1);
    }, 4000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [automationRuns, context.error, context.loading, loadingWorkspace, queueResponse, siteId]);

  if (context.loading) {
    return (
      <PageContainer width="full" density="compact">
        <SectionCard as="div">Loading site workspace...</SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer width="full" density="compact">
        <SectionCard as="div">Unable to load tenant context. Refresh and sign in again.</SectionCard>
      </PageContainer>
    );
  }
  if (!siteId) {
    return (
      <PageContainer width="full" density="compact">
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
      <PageContainer width="full" density="compact">
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

  const showSummaryTab = activeWorkspaceContentTab === "summary";
  const showRecommendationsTab = activeWorkspaceContentTab === "recommendations";
  const showRecommendationSections = showSummaryTab || showRecommendationsTab;
  const showActivityTab = activeWorkspaceContentTab === "activity";
  const latestAuditRun = auditRuns[0] || null;
  const compactAuditStatus = latestAuditRun?.status || selectedSite.last_audit_status || "No audit run yet";
  const compactAuditCompletedAt = latestAuditRun?.completed_at || selectedSite.last_audit_completed_at;
  const compactAuditPagesCrawled = latestAuditRun?.pages_crawled;
  const compactAuditErrors = latestAuditRun?.errors_encountered;
  const latestAutomationRun = automationRuns[0] || null;
  const latestAutomationSteps = normalizeAutomationRunSteps(latestAutomationRun);
  const latestAutomationOutcomeSummary = normalizeAutomationRunOutcomeSummary(latestAutomationRun);
  const latestAutomationCompleteness = deriveAutomationCompletenessSignal(
    latestAutomationRun,
    latestAutomationSteps,
    latestAutomationOutcomeSummary,
  );
  const workspaceAutomationBindingTargetId = deriveAutomationBindingTargetId(automationRuns);
  const latestAutomationRecommendationRunOutputId = extractAutomationRecommendationRunOutputId(latestAutomationRun);
  const latestAutomationRecommendationNarrativeOutputId =
    extractAutomationRecommendationNarrativeOutputId(latestAutomationRun);
  const latestAutomationStatus = latestAutomationRun?.status || "No automation run yet";
  const latestAutomationTriggerSource = latestAutomationRun?.trigger_source || "none";
  const latestAutomationStatusBadgeClass = automationRunStatusBadgeClass(latestAutomationStatus);
  const latestAutomationOutcomeCue = latestAutomationRun
    ? latestAutomationOutcomeSummary?.summary_text
      || (() => {
        const normalizedStatus = normalizeAutomationRunStatus(latestAutomationRun.status);
        if (normalizedStatus === "completed") {
          return latestAutomationRecommendationNarrativeOutputId
            ? "Completed with recommendation narrative output."
            : latestAutomationRecommendationRunOutputId
              ? "Completed with recommendation output."
              : "Completed without linked recommendation output.";
        }
        if (normalizedStatus === "failed") {
          return "Failed before linked recommendation output completed.";
        }
        if (normalizedStatus === "running") {
          return "Automation is running; output may still change.";
        }
        if (normalizedStatus === "queued") {
          return "Automation is queued and waiting to run.";
        }
        return `Automation status is ${latestAutomationRun.status}.`;
      })()
    : "No automation lifecycle signal is available for this site yet.";
  const latestAutomationActionState = deriveAutomationRunOperatorActionState({
    runStatus: latestAutomationRun?.status || null,
    hasRecommendationOutput: Boolean(latestAutomationRecommendationRunOutputId),
    hasNarrativeOutput: Boolean(latestAutomationRecommendationNarrativeOutputId),
  });
  const automationContextAvailable = automationRuns.length > 0 && !automationRunError;
  const automationInFlight = automationRuns.some((run) => {
    const normalizedStatus = normalizeAutomationRunStatus(run.status);
    return normalizedStatus === "queued" || normalizedStatus === "running";
  });
  const siteTrafficMetricsSummary = siteAnalyticsSummary?.site_metrics_summary || null;
  const trafficTrendValue = siteTrafficMetricsSummary
    ? `${siteTrafficMetricsSummary.users.current.toLocaleString()} users`
    : "Unavailable";
  const trafficTrendDetail = siteTrafficMetricsSummary
    ? `${siteTrafficMetricsSummary.sessions.current.toLocaleString()} sessions (${formatSignedPercent(
      siteTrafficMetricsSummary.sessions.delta_percent,
    )} vs prior period)`
    : siteAnalyticsSummary?.message || siteAnalyticsError || "Google Analytics data is not available for this site yet.";
  const trafficTrendTone = siteTrafficMetricsSummary
    ? siteTrafficMetricsSummary.sessions.delta_percent !== null
      ? siteTrafficMetricsSummary.sessions.delta_percent >= 0
        ? "success"
        : "warning"
      : "neutral"
    : "neutral";
  const ga4ConnectivityStatus = siteAnalyticsSummary?.ga4_status
    || ((selectedSite?.ga4_property_id || "").trim() ? "configured" : "not_configured");
  const ga4ConnectivityReason = siteAnalyticsSummary?.ga4_error_reason
    || (ga4ConnectivityStatus === "not_configured" ? "not_configured" : null);
  const ga4ConnectivityLabel = (() => {
    if (ga4ConnectivityStatus === "connected") {
      return "Connected";
    }
    if (ga4ConnectivityStatus === "configured") {
      return "Configured";
    }
    if (ga4ConnectivityStatus === "error") {
      return "Error";
    }
    return "Not configured";
  })();
  const ga4ConnectivityBadgeClass = (() => {
    if (ga4ConnectivityStatus === "connected") {
      return "badge badge-success";
    }
    if (ga4ConnectivityStatus === "configured") {
      return "badge badge-muted";
    }
    if (ga4ConnectivityStatus === "error") {
      return "badge badge-warn";
    }
    return "badge badge-muted";
  })();
  const ga4ConnectivityDetail = ga4DiagnosticReasonMessage(ga4ConnectivityReason)
    || (ga4ConnectivityStatus === "connected"
      ? "GA4 measurements are being read successfully for this site."
      : "GA4 connection diagnostics are unavailable.");
  const normalizedGa4PropertyInput = normalizeGa4PropertyInput(ga4PropertyInput);
  const normalizedSavedGa4PropertyInput = normalizeGa4PropertyInput(selectedSite?.ga4_property_id || "");
  const ga4PropertyChanged = normalizedGa4PropertyInput !== normalizedSavedGa4PropertyInput;
  const ga4PropertyInputFormatWarning = normalizedGa4PropertyInput && !looksLikeGa4PropertyId(normalizedGa4PropertyInput)
    ? "Use only the numeric GA4 property ID (for example, 123456789)."
    : null;
  const ga4PropertySaveDisabled = ga4PropertySavePending || Boolean(ga4PropertyInputFormatWarning) || !ga4PropertyChanged;
  const ga4OnboardingStatusCode = ga4OnboardingStatus?.ga4_onboarding_status || "unavailable";
  const ga4OnboardingValue = (() => {
    if (ga4OnboardingStatusCode === "stream_configured" || ga4OnboardingStatusCode === "property_configured") {
      return "Property configured";
    }
    if (ga4OnboardingStatusCode === "account_available" || ga4OnboardingStatusCode === "incomplete") {
      return "Property needed";
    }
    if (ga4OnboardingStatusCode === "not_connected") {
      return "Not connected";
    }
    return "Unavailable";
  })();
  const ga4OnboardingDetail = ga4OnboardingStatus
    ? (
      ga4OnboardingStatus.account_discovery_available
        ? (ga4OnboardingStatus.message || "GA4 onboarding status available.")
        : "Account discovery is not enabled. Enter your GA4 property ID directly."
    )
    : ga4OnboardingError || "Account discovery is not enabled. Enter your GA4 property ID directly.";
  const ga4OnboardingTone = (() => {
    if (ga4OnboardingStatusCode === "stream_configured" || ga4OnboardingStatusCode === "property_configured") {
      return "success";
    }
    if (ga4OnboardingStatusCode === "account_available" || ga4OnboardingStatusCode === "incomplete") {
      return "warning";
    }
    if (ga4OnboardingStatusCode === "unavailable") {
      return "danger";
    }
    return "neutral";
  })();
  const searchVisibilityMetricsSummary = searchConsoleSiteSummary?.site_metrics_summary || null;
  const searchVisibilityTrendValue = searchVisibilityMetricsSummary
    ? `${searchVisibilityMetricsSummary.clicks.current.toLocaleString()} clicks`
    : "Unavailable";
  const searchVisibilityTrendDetail = searchVisibilityMetricsSummary
    ? `${searchVisibilityMetricsSummary.impressions.current.toLocaleString()} impressions `
      + `(${formatSignedPercent(searchVisibilityMetricsSummary.impressions.delta_percent)} vs prior period), `
      + `avg position ${searchVisibilityMetricsSummary.average_position_current.toFixed(1)}`
    : searchConsoleSiteSummary?.message
      || searchConsoleSiteSummaryError
      || "Search Console data is not available for this site yet.";
  const searchVisibilityTrendTone = searchVisibilityMetricsSummary
    ? searchVisibilityMetricsSummary.impressions.delta_percent !== null
      ? searchVisibilityMetricsSummary.impressions.delta_percent >= 0
        ? "success"
        : "warning"
      : "neutral"
    : "neutral";
  const topQueueRecommendation = queueResponse?.items?.[0] || null;
  const topQueueRecommendationActionState = topQueueRecommendation
    ? deriveRecommendationOperatorActionState({
      status: topQueueRecommendation.status,
      automationLinkedOutput:
        latestAutomationRecommendationRunOutputId === topQueueRecommendation.recommendation_run_id,
      automationContextAvailable,
    })
    : null;
  const topQueueRecommendationActionExecutionItem =
    topQueueRecommendation && topQueueRecommendationActionState
      ? deriveWorkspaceRecommendationActionExecutionItem({
        recommendation: topQueueRecommendation,
        actionStateCode: topQueueRecommendationActionState.code,
        automationContextAvailable,
        automationInFlight,
        linkedRecommendationRunOutputId: latestAutomationRecommendationRunOutputId,
        linkedRecommendationNarrativeOutputId: latestAutomationRecommendationNarrativeOutputId,
      })
      : null;
  const effectiveTopQueueRecommendationActionExecutionItem =
    topQueueRecommendationActionExecutionItem && recommendationActionDecisionByItemId[topQueueRecommendationActionExecutionItem.id]
      ? applyActionDecisionLocally(
        topQueueRecommendationActionExecutionItem,
        recommendationActionDecisionByItemId[topQueueRecommendationActionExecutionItem.id],
      )
      : topQueueRecommendationActionExecutionItem;
  const topQueueRecommendationActionPresentation = effectiveTopQueueRecommendationActionExecutionItem
    ? deriveActionStatePresentation({
      item: effectiveTopQueueRecommendationActionExecutionItem,
      fallbackLabel: topQueueRecommendationActionState?.label,
      fallbackBadgeClass: topQueueRecommendationActionState?.badgeClass,
      fallbackOutcome: topQueueRecommendationActionState?.outcome,
      fallbackNextStep: topQueueRecommendationActionState?.nextStep,
    })
    : null;
  const topQueueRecommendationActionControls = effectiveTopQueueRecommendationActionExecutionItem
    ? deriveActionControls(effectiveTopQueueRecommendationActionExecutionItem)
    : [];
  const latestAutomationActionExecutionItem = latestAutomationRun
    ? deriveWorkspaceAutomationActionExecutionItem({
      run: latestAutomationRun,
      actionStateCode: latestAutomationActionState.code,
      linkedRecommendationRunOutputId: latestAutomationRecommendationRunOutputId,
      linkedRecommendationNarrativeOutputId: latestAutomationRecommendationNarrativeOutputId,
    })
    : null;
  const effectiveLatestAutomationActionExecutionItem =
    latestAutomationActionExecutionItem && automationActionDecisionByItemId[latestAutomationActionExecutionItem.id]
      ? applyActionDecisionLocally(
        latestAutomationActionExecutionItem,
        automationActionDecisionByItemId[latestAutomationActionExecutionItem.id],
      )
      : latestAutomationActionExecutionItem;
  const latestAutomationActionPresentation = effectiveLatestAutomationActionExecutionItem
    ? deriveActionStatePresentation({
      item: effectiveLatestAutomationActionExecutionItem,
      fallbackLabel: latestAutomationActionState.label,
      fallbackBadgeClass: latestAutomationActionState.badgeClass,
      fallbackOutcome: latestAutomationActionState.outcome,
      fallbackNextStep: latestAutomationActionState.nextStep,
    })
    : null;
  const latestAutomationActionControls = effectiveLatestAutomationActionExecutionItem
    ? deriveActionControls(effectiveLatestAutomationActionExecutionItem)
    : [];
  const workspaceHasInFlightActionExecution = (() => {
    if (effectiveTopQueueRecommendationActionExecutionItem?.actionLineage
      && hasInFlightLineageExecution(effectiveTopQueueRecommendationActionExecutionItem.actionLineage)) {
      return true;
    }
    if (effectiveLatestAutomationActionExecutionItem?.actionLineage
      && hasInFlightLineageExecution(effectiveLatestAutomationActionExecutionItem.actionLineage)) {
      return true;
    }
    return (queueResponse?.items || []).some((item) => hasInFlightLineageExecution(item.action_lineage || null));
  })();
  const workspaceExecutionPollingActive = Boolean(
    workspaceHasInFlightActionExecution
    && !loadingWorkspace
    && !context.loading
    && !context.error
    && siteId,
  );

  async function handleWorkspaceRecommendationDecision(
    recommendation: Recommendation,
    decision: ActionDecision,
  ): Promise<void> {
    setRecommendationActionDecisionByItemId((current) => ({
      ...current,
      [recommendation.id]: decision,
    }));
    setRecommendationActionDecisionErrorByItemId((current) => ({
      ...current,
      [recommendation.id]: null,
    }));

    if (decision === "deferred") {
      return;
    }

    const nextStatus = decision === "accepted" ? "accepted" : "dismissed";
    setRecommendationActionDecisionSavingByItemId((current) => ({
      ...current,
      [recommendation.id]: true,
    }));
    try {
      await updateRecommendationStatus(
        context.token,
        context.businessId,
        recommendation.site_id,
        recommendation.id,
        { status: nextStatus },
      );
      setQueueResponse((current) => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          items: current.items.map((item) =>
            item.id === recommendation.id
              ? {
                  ...item,
                  status: nextStatus,
                  updated_at: new Date().toISOString(),
                }
              : item,
          ),
        };
      });
    } catch (error) {
      setRecommendationActionDecisionErrorByItemId((current) => ({
        ...current,
        [recommendation.id]: safeSectionErrorMessage("recommendation action decision", error),
      }));
    } finally {
      setRecommendationActionDecisionSavingByItemId((current) => ({
        ...current,
        [recommendation.id]: false,
      }));
    }
  }

  function handleWorkspaceAutomationDecision(actionId: string, decision: ActionDecision): void {
    setAutomationActionDecisionByItemId((current) => ({
      ...current,
      [actionId]: decision,
    }));
  }

  async function handleWorkspaceRecommendationAutomationBinding(
    actionExecutionItemId: string,
    automationId: string,
  ): Promise<void> {
    if (!selectedSite) {
      setAutomationBindingErrorByActionId((current) => ({
        ...current,
        [actionExecutionItemId]: "Site context is unavailable for automation binding.",
      }));
      return;
    }

    setAutomationBindingPendingByActionId((current) => ({
      ...current,
      [actionExecutionItemId]: true,
    }));
    setAutomationBindingErrorByActionId((current) => ({
      ...current,
      [actionExecutionItemId]: null,
    }));
    try {
      await bindActionExecutionItemAutomation(
        context.token,
        context.businessId,
        selectedSite.id,
        actionExecutionItemId,
        automationId,
      );
      setWorkspaceRefreshNonce((current) => current + 1);
    } catch (error) {
      setAutomationBindingErrorByActionId((current) => ({
        ...current,
        [actionExecutionItemId]: safeAutomationBindingErrorMessage(error),
      }));
    } finally {
      setAutomationBindingPendingByActionId((current) => ({
        ...current,
        [actionExecutionItemId]: false,
      }));
    }
  }

  async function handleWorkspaceRecommendationAutomationExecution(
    actionExecutionItemId: string,
  ): Promise<void> {
    if (!selectedSite) {
      setAutomationRunErrorByActionId((current) => ({
        ...current,
        [actionExecutionItemId]: "Site context is unavailable for automation execution.",
      }));
      return;
    }

    setAutomationRunPendingByActionId((current) => ({
      ...current,
      [actionExecutionItemId]: true,
    }));
    setAutomationRunErrorByActionId((current) => ({
      ...current,
      [actionExecutionItemId]: null,
    }));
    try {
      await runActionExecutionItemAutomation(
        context.token,
        context.businessId,
        selectedSite.id,
        actionExecutionItemId,
      );
      setWorkspaceRefreshNonce((current) => current + 1);
    } catch (error) {
      setAutomationRunErrorByActionId((current) => ({
        ...current,
        [actionExecutionItemId]: safeAutomationExecutionErrorMessage(error),
      }));
    } finally {
      setAutomationRunPendingByActionId((current) => ({
        ...current,
        [actionExecutionItemId]: false,
      }));
    }
  }

  return (
    <PageContainer width="full" density="compact">
      <div className="workspace-dashboard-landing">
        <SectionCard className="workspace-shell-overview workspace-shell-overview-hero" variant="support">
          <div className="workspace-section-header workspace-section-header-compact">
            <div className="workspace-section-header-main">
              <p>
                <Link href="/sites">Back to Sites</Link>
              </p>
              <h1>Site SEO Workspace</h1>
              <p className="hint muted workspace-section-subtitle">
                Site: <strong>{selectedSite.display_name}</strong>
              </p>
              <div className="workspace-section-meta">
                <span className="hint muted">Business ID: <code>{selectedSite.business_id}</code></span>
                <span className="hint muted">Site ID: <code>{selectedSite.id}</code></span>
                <span className="hint muted">Domain: {selectedSite.normalized_domain}</span>
                <span className="hint muted">Base URL: {selectedSite.base_url}</span>
                <span className="hint muted">Active: {selectedSite.is_active ? "yes" : "no"}</span>
                <span className="hint muted">Primary: {selectedSite.is_primary ? "yes" : "no"}</span>
                <span className="hint muted">
                  Last audit: {selectedSite.last_audit_status || "-"} ({formatDateTime(selectedSite.last_audit_completed_at)})
                </span>
                <span className="hint muted">
                  Operator context:{" "}
                  {context.selectedSiteId === selectedSite.id
                    ? "currently selected"
                    : "page-scoped to this site"}
                </span>
              </div>
            </div>
            <div className="workspace-section-actions">
              <div className="toolbar-row toolbar-row-links">
                <Link href="/audits">Audit Runs</Link>
                <Link href={`/competitors?site_id=${encodeURIComponent(selectedSite.id)}`}>Competitor Workspace</Link>
                <Link href="/recommendations">Recommendation Queue</Link>
              </div>
            </div>
          </div>
          {loadingWorkspace ? <p className="hint muted">Loading workspace data...</p> : null}
        </SectionCard>

      <SectionCard className="operator-shell-summary-panel" variant="summary">
        <SectionHeader
          title="Workspace Snapshot"
          subtitle="At-a-glance trust, freshness, and action visibility for this site."
          headingLevel={2}
          variant="support"
          data-testid="workspace-snapshot-header"
        />
        <div className="workspace-summary-strip" data-testid="workspace-summary-strip">
          <SummaryStatCard
            label="Competitor section"
            value={competitorSectionFreshness?.stateLabel || "No run state yet"}
            detail={
              latestCompetitorProfileRun
                ? `${visibleCompetitorProfileDrafts.length} visible draft${visibleCompetitorProfileDrafts.length === 1 ? "" : "s"}`
                : "No competitor profile run yet"
            }
            tone={competitorSummaryTone}
            variant="elevated"
            data-testid="workspace-summary-competitors"
          />
          <SummaryStatCard
            label="Recommendation section"
            value={recommendationSectionFreshness?.stateLabel || "No queue state yet"}
            detail={`${recommendationQueueSummary.open} open of ${recommendationQueueSummary.total} total`}
            tone={recommendationSummaryTone}
            variant="elevated"
            data-testid="workspace-summary-recommendations"
          />
          <SummaryStatCard
            label="Actionable recommendations"
            value={actionableRecommendationCount}
            detail={
              latestApplyTitle
                ? `Latest applied: ${latestApplyTitle}`
                : latestApplyExpectation || "No recent apply outcome"
            }
            tone={actionableRecommendationCount > 0 ? "success" : "neutral"}
            variant="elevated"
            data-testid="workspace-summary-actionable"
          />
          <SummaryStatCard
            label="Automation lifecycle"
            value={latestAutomationStatus}
            detail={
              latestAutomationRun
                ? `Trigger: ${latestAutomationTriggerSource} · ${latestAutomationOutcomeCue}`
                : automationRunError || latestAutomationOutcomeCue
            }
            tone={latestAutomationStatus === "failed" ? "danger" : latestAutomationStatus === "completed" ? "success" : "neutral"}
            variant="elevated"
            data-testid="workspace-summary-automation"
          />
          <SummaryStatCard
            label="Traffic trend"
            value={trafficTrendValue}
            detail={trafficTrendDetail}
            tone={trafficTrendTone}
            variant="elevated"
            data-testid="workspace-summary-traffic"
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
            label="Competitor readiness"
            value={workspaceReadinessMessage}
            detail={
              typeof workspaceTrustSummary?.usedGooglePlacesSeeds === "boolean"
                ? `Nearby seed discovery used: ${workspaceTrustSummary.usedGooglePlacesSeeds ? "yes" : "no"}`
                : "Nearby seed discovery telemetry not available"
            }
            tone={trustSummaryTone}
            variant="elevated"
            data-testid="workspace-summary-readiness"
          />
          <SummaryStatCard
            label="Google Business Profile"
            value={googleBusinessProfileWorkspaceStatus.stateLabel}
            detail={(
              <>
                {googleBusinessProfileWorkspaceStatus.detail}{" "}
                <Link href="/business-profile">{googleBusinessProfileWorkspaceStatus.nextActionLabel}</Link>
              </>
            )}
            tone={googleBusinessProfileWorkspaceStatus.tone}
            variant="elevated"
            data-testid="workspace-summary-gbp"
          />
        </div>
        <div className="panel panel-compact stack-tight" data-testid="workspace-ga4-connect-panel">
          <div className="link-row">
            <strong>Connect GA4</strong>
            <span className={ga4ConnectivityBadgeClass} data-testid="workspace-ga4-connection-status">
              {ga4ConnectivityLabel}
            </span>
          </div>
          <span className="hint">
            Configure this site&rsquo;s GA4 property to power traffic measurement in this workspace.
          </span>
          <label className="stack-tight">
            <span className="hint muted">GA4 property ID</span>
            <input
              type="text"
              inputMode="numeric"
              value={ga4PropertyInput}
              onChange={(event) => {
                setGa4PropertyInput(normalizeGa4PropertyInput(event.target.value));
                setGa4PropertySaveError(null);
                setGa4PropertySaveMessage(null);
              }}
              placeholder="123456789"
              aria-label="GA4 property ID"
              data-testid="workspace-ga4-property-input"
            />
          </label>
          <span className="hint muted">
            Enter your GA4 Property ID (numeric, for example 123456789). You do not need a measurement ID (G-XXXX).
          </span>
          {ga4PropertyInputFormatWarning ? <span className="hint warning">{ga4PropertyInputFormatWarning}</span> : null}
          <span
            className={ga4ConnectivityStatus === "error" ? "hint warning" : "hint muted"}
            data-testid="workspace-ga4-diagnostic"
          >
            {ga4ConnectivityDetail}
          </span>
          {ga4PropertySaveError ? (
            <span className="hint warning" data-testid="workspace-ga4-save-error">{ga4PropertySaveError}</span>
          ) : null}
          {ga4PropertySaveMessage ? (
            <span className="hint muted" data-testid="workspace-ga4-save-message">{ga4PropertySaveMessage}</span>
          ) : null}
          <div className="form-actions">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void handleSaveGa4Property()}
              disabled={ga4PropertySaveDisabled}
              data-testid="workspace-ga4-save-button"
            >
              {ga4PropertySavePending ? "Saving..." : "Save GA4 property"}
            </button>
          </div>
        </div>
      </SectionCard>

        <SectionCard
          className="operator-shell-insights operator-shell-primary-zone"
          variant="primary"
          data-testid="operator-focus-zone"
        >
        <SectionHeader
          title="Operator Focus"
          subtitle="What changed, what needs attention, and what to do next."
          headingLevel={2}
          variant="focus"
          data-testid="top-insights-header"
        />
        <div className="operator-focus-grid">
          <div className="operator-focus-main stack">
            <div className="panel panel-compact stack-tight operator-focus-callout" data-testid="operator-focus-callout">
              <span className="operator-focus-kicker">What to do now</span>
              <div className="link-row operator-focus-status-row">
                <span
                  className={operatorPrimaryAction.urgencyBadgeClass}
                  data-testid="operator-focus-urgency-badge"
                >
                  {operatorPrimaryAction.urgencyLabel}
                </span>
                {recommendationSectionFreshness?.refreshExpected || competitorSectionFreshness?.refreshExpected ? (
                  <span className="badge badge-warn">Refresh expected</span>
                ) : null}
              </div>
              <strong>{operatorPrimaryAction.title}</strong>
              <span className="hint">{operatorPrimaryAction.reason}</span>
              {operatorPrimaryAction.contextHint ? (
                <span className="hint muted">{operatorPrimaryAction.contextHint}</span>
              ) : null}
              <div className="form-actions">
                {operatorPrimaryAction.actionKind === "navigate" ? (
                  <Link
                    href={operatorPrimaryAction.actionHref}
                    className="button button-primary"
                    data-testid="operator-focus-primary-action-link"
                  >
                    {operatorPrimaryAction.actionLabel}
                  </Link>
                ) : (
                  <button
                    type="button"
                    className="button button-primary"
                    data-testid="operator-focus-primary-action-button"
                    onClick={() => {
                      if (operatorPrimaryAction.actionTargetId) {
                        focusActionTarget(operatorPrimaryAction.actionTargetId);
                      }
                    }}
                  >
                    {operatorPrimaryAction.actionLabel}
                  </button>
                )}
              </div>
              {latestWorkflowChangeNote ? <span className="hint muted">{latestWorkflowChangeNote}</span> : null}
            </div>

            <div className="panel panel-compact stack operator-focus-next-step" data-testid="start-here-section">
              <span className="hint muted">Next best step</span>
              <strong>{startHereAction.title}</strong>
              <span className="hint">{startHereAction.detail}</span>
              <span className="hint muted">Why this first: {startHereAction.whyThisFirst}</span>
              {startHereAction.kind !== "none" ? (
                <button type="button" className="button button-primary" onClick={() => void handleStartHereAction()}>
                  {startHereAction.buttonLabel}
                </button>
              ) : null}
            </div>
          </div>

          <div className="operator-focus-support stack">
            <div className="metrics-grid operator-focus-metrics">
              <div className="panel panel-compact">
                <strong>{actionableRecommendationCount} recommendations are ready to act on</strong>
              </div>
              <div className="panel panel-compact">
                <strong>{latestCompletedTuningSuggestions.length} tuning suggestions are available</strong>
              </div>
              <div className="panel panel-compact">
                <strong>
                  {latestPreviewInsight || "Preview a tuning suggestion to see expected impact"}
                </strong>
              </div>
            </div>

            <div
              className="panel panel-compact stack-tight operator-summary-callout"
              data-testid="workspace-gbp-integration-status"
            >
              <span className="hint muted">Google Business Profile integration</span>
              <div className="link-row">
                <span className={googleBusinessProfileWorkspaceStatus.badgeClass}>
                  {googleBusinessProfileWorkspaceStatus.stateLabel}
                </span>
              </div>
              <span className="hint">{googleBusinessProfileWorkspaceStatus.detail}</span>
              <Link href="/business-profile">{googleBusinessProfileWorkspaceStatus.nextActionLabel}</Link>
            </div>

            {recommendationApplyOutcome ? (
              <div className="panel panel-compact stack-tight operator-summary-callout" data-testid="operator-focus-latest-change">
                <span className="hint muted">Latest change</span>
                {recommendationApplyOutcome.appliedRecommendationTitle ? (
                  <span className="hint">
                    Applied recommendation: {recommendationApplyOutcome.appliedRecommendationTitle}
                  </span>
                ) : null}
                {recommendationApplyOutcome.appliedChangeSummary ? (
                  <span className="hint muted">What changed: {recommendationApplyOutcome.appliedChangeSummary}</span>
                ) : null}
                {recommendationApplyOutcome.nextRefreshExpectation ? (
                  <span className="hint muted">Next refresh: {recommendationApplyOutcome.nextRefreshExpectation}</span>
                ) : null}
              </div>
            ) : null}

            {workspaceTrustSummary ? (
              <div className="panel panel-compact stack-tight operator-summary-callout" data-testid="workspace-trust-summary">
                <span className="hint muted">Trust signals</span>
                {workspaceTrustSummary.latestCompetitorStatus ? (
                  <span className="hint">
                    Latest competitor status:{" "}
                    {formatCompetitorOutcomeStatusLevel(workspaceTrustSummary.latestCompetitorStatus)}
                  </span>
                ) : null}
                {workspaceTrustSummary.usedGooglePlacesSeeds !== null ? (
                  <span className="hint muted">
                    Nearby seed discovery used: {workspaceTrustSummary.usedGooglePlacesSeeds ? "yes" : "no"}.
                  </span>
                ) : null}
                {workspaceTrustSummary.usedSyntheticFallback !== null ? (
                  <span className={workspaceTrustSummary.usedSyntheticFallback ? "hint warning" : "hint muted"}>
                    Synthetic fallback used: {workspaceTrustSummary.usedSyntheticFallback ? "yes" : "no"}.
                  </span>
                ) : null}
                {workspaceTrustSummary.latestRecommendationApplyTitle ? (
                  <span className="hint">
                    Latest applied recommendation: {workspaceTrustSummary.latestRecommendationApplyTitle}.
                  </span>
                ) : null}
                {workspaceTrustSummary.latestRecommendationApplyChangeSummary ? (
                  <span className="hint muted">
                    Latest applied change: {workspaceTrustSummary.latestRecommendationApplyChangeSummary}
                  </span>
                ) : null}
                {workspaceTrustSummary.nextRefreshExpectation ? (
                  <span className="hint muted">Next refresh: {workspaceTrustSummary.nextRefreshExpectation}</span>
                ) : null}
                {workspaceTrustSummary.freshnessNote ? (
                  <span className="hint muted">Freshness: {workspaceTrustSummary.freshnessNote}</span>
                ) : null}
              </div>
            ) : null}

            {recommendationThemeStartHere ? (
              <div
                className="panel panel-compact stack-tight operator-summary-callout"
                data-testid="start-here-theme-helper"
              >
                <span className="hint muted">Suggested focus area</span>
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
          </div>
        </div>
        </SectionCard>
      </div>

      <SectionCard className="operator-shell-section operator-shell-secondary-zone workspace-content-tab-shell">
        <div className="workspace-subtabs" role="tablist" aria-label="Workspace content views">
          <button
            type="button"
            id="workspace-content-tab-summary"
            role="tab"
            className={`button button-secondary workspace-subtab-button ${
              activeWorkspaceContentTab === "summary" ? "workspace-subtab-button-active" : ""
            }`}
            aria-selected={activeWorkspaceContentTab === "summary"}
            aria-controls="workspace-content-summary-panel"
            onClick={() => setActiveWorkspaceContentTab("summary")}
          >
            Summary
          </button>
          <button
            type="button"
            id="workspace-content-tab-recommendations"
            role="tab"
            className={`button button-secondary workspace-subtab-button ${
              activeWorkspaceContentTab === "recommendations" ? "workspace-subtab-button-active" : ""
            }`}
            aria-selected={activeWorkspaceContentTab === "recommendations"}
            aria-controls="workspace-content-recommendations-panel"
            onClick={() => setActiveWorkspaceContentTab("recommendations")}
          >
            Recommendations
          </button>
          <button
            type="button"
            id="workspace-content-tab-activity"
            role="tab"
            className={`button button-secondary workspace-subtab-button ${
              activeWorkspaceContentTab === "activity" ? "workspace-subtab-button-active" : ""
            }`}
            aria-selected={activeWorkspaceContentTab === "activity"}
            aria-controls="workspace-content-activity-panel"
            onClick={() => setActiveWorkspaceContentTab("activity")}
          >
            Activity
          </button>
        </div>
        <p className="hint muted">
          {activeWorkspaceContentTab === "activity"
            ? "Activity keeps full timeline and run-history tables separated from decision surfaces."
            : activeWorkspaceContentTab === "recommendations"
              ? "Recommendations keeps recommendation queue and run narratives front and center."
              : "Summary keeps top operator actions and compact status signals in front."}
        </p>
      </SectionCard>

      {showSummaryTab ? (
        <SectionCard
          className="operator-shell-section operator-shell-secondary-zone"
          role="tabpanel"
          id="workspace-content-summary-panel"
          aria-labelledby="workspace-content-tab-summary"
          data-testid="workspace-summary-tab-panel"
        >
          <SectionHeader
            title="Summary Signals"
            subtitle="Compact audit and competitor readiness context while you work recommendations."
            headingLevel={2}
          />
          <div className="workspace-summary-strip" data-testid="workspace-operational-summary">
            <SummaryStatCard
              label="Last audit"
              value={compactAuditStatus}
              detail={compactAuditCompletedAt ? formatDateTime(compactAuditCompletedAt) : "No completed audit yet"}
              tone={compactAuditStatus === "completed" ? "success" : compactAuditStatus === "failed" ? "warning" : "neutral"}
              variant="elevated"
              data-testid="summary-audit-status"
            />
            <SummaryStatCard
              label="Pages crawled"
              value={compactAuditPagesCrawled ?? "-"}
              detail={compactAuditErrors !== undefined && compactAuditErrors !== null ? `Errors: ${compactAuditErrors}` : "No audit metrics yet"}
              tone={compactAuditErrors && compactAuditErrors > 0 ? "warning" : "neutral"}
              variant="elevated"
              data-testid="summary-audit-metrics"
            />
            <SummaryStatCard
              label="Competitor readiness"
              value={workspaceReadinessMessage}
              detail={`${activeCompetitorSetCount} active sets · ${activeCompetitorDomainCount} active domains`}
              tone={activeCompetitorSetCount > 0 ? "success" : "neutral"}
              variant="elevated"
              data-testid="summary-competitor-readiness"
            />
            <SummaryStatCard
              label="Latest comparison activity"
              value={latestComparisonRun ? latestComparisonRun.status : "No comparison run yet"}
              detail={
                latestComparisonRun
                  ? formatDateTime(latestComparisonRun.completed_at || latestComparisonRun.updated_at)
                  : "Run competitor comparison to populate"
              }
              tone={latestComparisonRun?.status === "completed" ? "neutral" : "warning"}
              variant="elevated"
              data-testid="summary-comparison-activity"
            />
          </div>
          <div className="panel panel-compact stack-tight operator-summary-callout" data-testid="workspace-automation-status-summary">
            <span className="hint muted">Automation status and outcomes</span>
            <span className="hint muted" data-testid="workspace-automation-non-publishing-banner">
              This automation analyzes your site and generates recommendations. It does not make changes to your website.
            </span>
            <div className="link-row">
              <span className={`badge ${latestAutomationStatusBadgeClass}`}>{latestAutomationStatus}</span>
              {latestAutomationCompleteness ? (
                <span className={`badge ${latestAutomationCompleteness.badgeClass}`}>{latestAutomationCompleteness.label}</span>
              ) : null}
              <span className={latestAutomationActionPresentation?.badgeClass || latestAutomationActionState.badgeClass}>
                {latestAutomationActionPresentation?.label || latestAutomationActionState.label}
              </span>
              <span className="badge badge-muted">Trigger: {latestAutomationTriggerSource}</span>
              {latestAutomationRun ? <span className="badge badge-muted">Run: {latestAutomationRun.id}</span> : null}
            </div>
            <span className="hint">{latestAutomationOutcomeCue}</span>
            {latestAutomationCompleteness?.hint ? (
              <span className="hint muted">{latestAutomationCompleteness.hint}</span>
            ) : null}
            <span className="hint muted">{latestAutomationActionPresentation?.outcome || latestAutomationActionState.outcome}</span>
            <span className="hint muted">
              Next step: {latestAutomationOutcomeSummary ? deriveAutomationRunNextStep(latestAutomationRun) : latestAutomationActionPresentation?.nextStep || latestAutomationActionState.nextStep}
            </span>
            {latestAutomationOutcomeSummary ? (
              <div className="link-row">
                <span className={`badge ${automationTerminalOutcomeBadgeClass(latestAutomationOutcomeSummary.terminal_outcome)}`}>
                  {formatAutomationTerminalOutcomeLabel(latestAutomationOutcomeSummary.terminal_outcome)}
                </span>
                <span className="badge badge-muted">
                  {latestAutomationOutcomeSummary.steps_completed_count} completed
                </span>
                <span className="badge badge-muted">
                  {latestAutomationOutcomeSummary.steps_skipped_count} skipped
                </span>
                <span className="badge badge-muted">
                  {latestAutomationOutcomeSummary.steps_failed_count} failed
                </span>
              </div>
            ) : null}
            {latestAutomationActionControls.length > 0 ? (
              <ActionControls
                controls={latestAutomationActionControls}
                resolveHref={(control) =>
                  resolveWorkspaceAutomationControlHref({
                    control,
                    siteId: selectedSite.id,
                    linkedRecommendationRunOutputId: latestAutomationRecommendationRunOutputId,
                  })}
                data-testid="workspace-automation-action-controls"
              />
            ) : null}
            {effectiveLatestAutomationActionExecutionItem ? (
              <OutputReview
                item={effectiveLatestAutomationActionExecutionItem}
                stateLabel={latestAutomationActionPresentation?.label || latestAutomationActionState.label}
                stateBadgeClass={latestAutomationActionPresentation?.badgeClass || latestAutomationActionState.badgeClass}
                outcome={latestAutomationActionPresentation?.outcome || latestAutomationActionState.outcome}
                nextStep={latestAutomationActionPresentation?.nextStep || latestAutomationActionState.nextStep}
                onDecision={(decision) => handleWorkspaceAutomationDecision(effectiveLatestAutomationActionExecutionItem.id, decision)}
                resolveOutputHref={(outputId) => buildRecommendationRunHref(outputId, selectedSite.id)}
                data-testid="workspace-automation-output-review"
              />
            ) : null}
            {workspaceExecutionPollingActive ? (
              <span className="hint muted" data-testid="workspace-automation-execution-polling-status">
                Automation execution is in progress. Status refreshes automatically every few seconds.
              </span>
            ) : null}
            {latestAutomationRun ? (
              <span className="hint muted">
                Started: {formatDateTime(latestAutomationRun.started_at)} · Finished: {formatDateTime(latestAutomationRun.finished_at)}
              </span>
            ) : null}
            {automationRunError ? <span className="hint warning">{automationRunError}</span> : null}
            <div className="toolbar-row toolbar-row-links">
              <Link href={`/automation?site_id=${encodeURIComponent(selectedSite.id)}`}>Review automation runs</Link>
              {latestAutomationRecommendationRunOutputId ? (
                <Link href={buildRecommendationRunHref(latestAutomationRecommendationRunOutputId, selectedSite.id)}>
                  Review recommendation run output
                </Link>
              ) : null}
              {latestAutomationRecommendationRunOutputId && latestAutomationRecommendationNarrativeOutputId ? (
                <Link
                  href={buildNarrativeDetailHref(
                    latestAutomationRecommendationRunOutputId,
                    latestAutomationRecommendationNarrativeOutputId,
                    selectedSite.id,
                  )}
                >
                  Review recommendation narrative output
                </Link>
              ) : null}
            </div>
          </div>
        </SectionCard>
      ) : null}

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
        <SectionCard className="operator-shell-section">
          <SectionHeader
            title="AI Opportunities"
            subtitle="AI suggestions are advisory and should be reviewed."
            headingLevel={2}
          />
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

      {showActivityTab ? (
      <SectionCard
        className="operator-shell-section operator-shell-secondary-zone"
        role="tabpanel"
        id="workspace-content-activity-panel"
        aria-labelledby="workspace-content-tab-activity"
        data-testid="workspace-timeline-panel"
      >
        <SectionHeader
          title="Site Activity Timeline"
          subtitle="Recent audit, competitor, and recommendation activity for this site."
          headingLevel={2}
        />
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
                  <table className="table table-dense">
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
      ) : null}

      {showActivityTab ? (
      <>
      <SectionCard className="operator-shell-section operator-shell-secondary-zone">
        <SectionHeader
          title="Recent Audit Runs"
          subtitle="Latest crawl outcomes and deterministic audit status history."
          headingLevel={2}
        />
        {auditError ? <p className="hint error">{auditError}</p> : null}
        {auditRuns.length === 0 && !auditError ? (
          <p className="hint muted">No audit runs have been recorded for this site yet.</p>
        ) : (
          <div className="table-container">
            <table className="table table-dense">
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

      <SectionCard className="operator-shell-section operator-shell-secondary-zone">
        <SectionHeader
          title="Competitor Readiness"
          subtitle="Configured competitor sets, active domains, and recent snapshot/comparison activity."
          headingLevel={2}
        />
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
              <table className="table table-dense">
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
      </>
      ) : null}

      <SectionCard className="operator-shell-section operator-shell-work-zone">
        <SectionHeader
          title="AI Competitor Profiles"
          subtitle="Generate AI-produced competitor profile drafts, then review and explicitly accept or reject each candidate."
          headingLevel={2}
          data-testid="competitor-section-header"
          actions={(
            <div className="toolbar-row">
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
          )}
        />
        {competitorSectionFreshness ? (
          <p className="hint muted" data-testid="competitor-section-freshness">
            <span className={workspaceSectionFreshnessBadgeClass(competitorSectionFreshness.stateCode)}>
              {competitorSectionFreshness.stateLabel}
            </span>{" "}
            {competitorSectionFreshness.stateReason}
            {competitorSectionFreshness.refreshExpected ? " Refresh expected." : ""}
            {competitorSectionFreshness.evaluatedAt ? ` Evaluated ${formatDateTime(competitorSectionFreshness.evaluatedAt)}.` : ""}
          </p>
        ) : null}
        {competitorProfileError ? <p className="hint error">{competitorProfileError}</p> : null}
        {competitorProfileSummaryError ? <p className="hint warning">{competitorProfileSummaryError}</p> : null}
        {competitorProfileActionError ? <p className="hint error">{competitorProfileActionError}</p> : null}
        {competitorProfileActionMessage ? <p className="hint success">{competitorProfileActionMessage}</p> : null}
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
          <div className="stack operator-summary-callout" data-testid="competitor-run-outcome-summary">
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
        <div className="stack-tight" data-testid="competitor-summary-strip">
          <div className="workspace-section-meta">
            <span className="badge badge-muted">
              Total candidates {competitorSummaryStripMetrics.totalCandidates}
            </span>
            <span className="badge badge-success">
              Eligible {competitorSummaryStripMetrics.eligibleCandidates}
            </span>
            <span className="badge badge-success">
              Final returned {competitorSummaryStripMetrics.finalReturned}
            </span>
            <span className="badge badge-warn">
              Excluded {competitorSummaryStripMetrics.excludedCandidates}
            </span>
            <span className="badge badge-error">
              Failure count {competitorSummaryStripMetrics.failureCount}
            </span>
            <span className="badge badge-muted">
              Retry count {competitorSummaryStripMetrics.retryCount}
            </span>
          </div>
          {competitorFailureCategoryChips.length > 0 ? (
            <div className="workspace-section-meta" data-testid="competitor-failure-category-chips">
              {competitorFailureCategoryChips.map(([category, count]) => (
                <span key={`failure-${category}`} className="badge badge-muted">
                  {formatFailureCategory(category)} {count}
                </span>
              ))}
            </div>
          ) : null}
          {competitorExclusionReasonChips.length > 0 ? (
            <div className="workspace-section-meta" data-testid="competitor-exclusion-reason-chips">
              {competitorExclusionReasonChips.map(([reason, count]) => (
                <span key={`exclusion-${reason}`} className="badge badge-muted">
                  {formatFailureCategory(reason)} {count}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        {competitorPipelineStageRows.length > 0 ? (
          <div className="stack-tight" data-testid="competitor-candidate-pipeline-summary-debug">
            <p className="hint muted">
              <strong>Candidate pipeline</strong>
            </p>
            <div className="table-container table-container-compact">
              <table className="table table-dense" data-testid="competitor-candidate-pipeline-table">
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>Count</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {competitorPipelineStageRows.map((row) => (
                    <tr key={`competitor-pipeline-${row.stage}`}>
                      <td>{row.stage}</td>
                      <td>{row.count}</td>
                      <td className="table-cell-wrap">{row.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
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
          <div className="stack-tight workspace-filter-toolbar">
            <label className="hint muted toolbar-toggle" data-testid="toggle-hide-synthetic-scaffolds">
              <input
                type="checkbox"
                checked={hideSyntheticScaffolds}
                onChange={(event) => setHideSyntheticScaffoldOverride(event.target.checked)}
              />{" "}
              Hide synthetic scaffolds
            </label>
            {hiddenSyntheticDraftCount > 0 ? (
              <p className="hint muted" data-testid="hidden-synthetic-scaffolds-count">
                {hiddenSyntheticDraftCount} synthetic scaffold
                {hiddenSyntheticDraftCount === 1 ? " row hidden" : " rows hidden"}.
              </p>
            ) : null}
            {hideSyntheticScaffolds && visibleCompetitorProfileDrafts.length === 0 ? (
              <p className="hint muted">
                All drafts in this run are synthetic scaffolds. Turn off the filter to review them.
              </p>
            ) : null}
          </div>
        ) : null}
        {!competitorProfileLoading && visibleCompetitorProfileDrafts.length > 0 ? (
          <div className="table-container">
            <table className="table table-dense">
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
                {visibleCompetitorProfileDrafts.map((draft) => {
                  const isEditing = editingDraftId === draft.id && editFormState !== null;
                  const actionDisabled =
                    draftActionTargetId === draft.id || editActionInFlight || generationInFlight || retryInFlight;
                  const editable = draft.review_status === "pending" || draft.review_status === "edited";
                  const syntheticDraft = isSyntheticCompetitorDraft(draft);
                  const syntheticConfirmed = Boolean(confirmSyntheticAcceptByDraftId[draft.id]);
                  const editDomainValue =
                    isEditing && editFormState ? editFormState.suggested_domain : draft.suggested_domain;
                  const syntheticHasVerifiedDomain = !isSyntheticScaffoldDomain(editDomainValue);
                  const syntheticVerifiedAcceptBlocked =
                    syntheticDraft && (!syntheticConfirmed || !syntheticHasVerifiedDomain);
                  const syntheticUnverifiedAcceptBlocked = syntheticDraft && !syntheticConfirmed;
                  const acceptedAsUnverified =
                    draft.review_status === "accepted"
                    && (draft.review_notes || "").toLowerCase().includes("accepted as unverified competitor");
                  const provenanceLabel = formatCompetitorDraftProvenanceLabel(draft.provenance_classification);
                  const confidenceLevelLabel = formatCompetitorDraftConfidenceLevelLabel(draft.confidence_level);
                  const sourceTypeLabel = formatCompetitorDraftSourceTypeLabel(draft.source_type);
                  const domainDisplay = formatCompetitorDraftDomainDisplay(draft);
                  return (
                    <Fragment key={draft.id}>
                      <tr data-testid="competitor-profile-draft-row">
                        <td className="table-cell-wrap">
                          <strong>{draft.suggested_name}</strong>
                          <br />
                          {domainDisplay.asPlaceholder ? (
                            <span className="hint warning">{domainDisplay.value}</span>
                          ) : (
                            <code>{domainDisplay.value}</code>
                          )}
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
                        <td>
                          {draft.confidence_score.toFixed(2)}
                          {confidenceLevelLabel || sourceTypeLabel ? (
                            <div className="link-row" data-testid="competitor-confidence-source-chips">
                              {confidenceLevelLabel ? (
                                <span className={competitorDraftConfidenceLevelBadgeClass(draft.confidence_level)}>
                                  {confidenceLevelLabel}
                                </span>
                              ) : null}
                              {sourceTypeLabel ? (
                                <span className={competitorDraftSourceTypeBadgeClass(draft.source_type)}>
                                  {sourceTypeLabel}
                                </span>
                              ) : null}
                            </div>
                          ) : null}
                        </td>
                        <td className="table-cell-wrap">
                          {truncateText(draft.summary || "No summary provided.", 140)}
                          <br />
                          <span className="hint muted">
                            <strong>Why this competitor:</strong>{" "}
                            {truncateText(draft.why_competitor || "Reasoning not provided.", 140)}
                          </span>
                          {draft.operator_evidence_summary ? (
                            <>
                              <br />
                              <span className="hint muted" data-testid="competitor-operator-evidence-summary">
                                <strong>Evidence signal:</strong> {truncateText(draft.operator_evidence_summary, 180)}
                              </span>
                            </>
                          ) : null}
                          {draft.provenance_explanation ? (
                            <>
                              <br />
                              <span className={competitorDraftProvenanceHintClass(draft.provenance_classification)}>
                                <strong>Selection basis:</strong> {truncateText(draft.provenance_explanation, 160)}
                              </span>
                            </>
                          ) : null}
                        </td>
                        <td className="table-cell-wrap">
                          {draft.review_status}
                          {acceptedAsUnverified ? (
                            <>
                              <br />
                              <span className="hint warning">Accepted as unverified competitor</span>
                            </>
                          ) : null}
                        </td>
                        <td>
                          <div className="stack">
                            <label className="stack">
                              <span className="hint muted">Target Set</span>
                              <select
                                className="operator-select"
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
                            {syntheticDraft ? (
                              <div className="stack">
                                <label className="hint warning">
                                  <input
                                    type="checkbox"
                                    checked={syntheticConfirmed}
                                    onChange={(event) =>
                                      setConfirmSyntheticAcceptByDraftId((current) => ({
                                        ...current,
                                        [draft.id]: event.target.checked,
                                      }))
                                    }
                                    disabled={!editable || actionDisabled}
                                  />{" "}
                                  Confirm synthetic scaffold review
                                </label>
                                {!syntheticHasVerifiedDomain ? (
                                  <span className="hint warning">
                                    Edit this scaffold with a verified website/domain before accepting.
                                  </span>
                                ) : null}
                              </div>
                            ) : null}
                            <div className="form-actions">
                              <button
                                type="button"
                                className="button button-primary button-inline"
                                onClick={() => void handleAcceptCompetitorProfileDraft(draft)}
                                disabled={!editable || actionDisabled || syntheticVerifiedAcceptBlocked}
                              >
                                {draftActionTargetId === draft.id ? "Applying..." : "Accept"}
                              </button>
                              {syntheticDraft ? (
                                <button
                                  type="button"
                                  className="button button-secondary button-inline"
                                  onClick={() =>
                                    void handleAcceptCompetitorProfileDraft(
                                      draft,
                                      undefined,
                                      { acceptAsUnverified: true },
                                    )
                                  }
                                  disabled={!editable || actionDisabled || syntheticUnverifiedAcceptBlocked}
                                >
                                  {draftActionTargetId === draft.id ? "Applying..." : "Accept as Unverified"}
                                </button>
                              ) : null}
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
                                  className="operator-select"
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
                                      draft,
                                      buildDraftEditPayloadFromFormState(editFormState),
                                    )
                                  }
                                  disabled={
                                    editActionInFlight
                                    || draftActionTargetId === draft.id
                                    || syntheticVerifiedAcceptBlocked
                                  }
                                >
                                  {draftActionTargetId === draft.id ? "Applying..." : "Accept Edited"}
                                </button>
                                {syntheticDraft ? (
                                  <button
                                    type="button"
                                    className="button button-secondary button-inline"
                                    onClick={() =>
                                      void handleAcceptCompetitorProfileDraft(
                                        draft,
                                        buildDraftEditPayloadFromFormState(editFormState),
                                        { acceptAsUnverified: true },
                                      )
                                    }
                                    disabled={
                                      editActionInFlight
                                      || draftActionTargetId === draft.id
                                      || syntheticUnverifiedAcceptBlocked
                                    }
                                  >
                                    {draftActionTargetId === draft.id ? "Applying..." : "Accept Edited as Unverified"}
                                  </button>
                                ) : null}
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
        {hasCompetitorDebugDetails ? (
          <div className="panel panel-compact stack-tight operator-shell-secondary-zone" data-testid="competitor-debug-secondary-section">
            <SectionHeader
              title="Debug details"
              subtitle="Secondary prompt and provider telemetry details for run inspection."
              headingLevel={3}
              variant="support"
            />
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
              </Fragment>
            ) : null}
            {rejectedCompetitorCandidateCount > 0 && rejectedCompetitorCandidates.length > 0 ? (
              <div className="stack" data-testid="rejected-competitor-candidates-debug">
                <p className="hint muted">
                  <strong>Rejected competitor candidates (debug)</strong>: {rejectedCompetitorCandidateCount}
                </p>
                <div className="table-container table-container-compact">
                  <table className="table table-dense">
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
                  <div className="workspace-section-meta">
                    {Object.entries(tuningRejectionReasonCounts)
                      .filter(([, count]) => count > 0)
                      .sort(([left], [right]) => left.localeCompare(right))
                      .map(([reason, count]) => (
                        <span key={`tuning-${reason}`} className="badge badge-muted">
                          {formatFailureCategory(reason)} {count}
                        </span>
                      ))}
                  </div>
                ) : null}
                <div className="table-container table-container-compact">
                  <table className="table table-dense">
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
            {competitorProviderAttemptCount > 0 && competitorProviderAttempts.length > 0 ? (
              <div className="stack" data-testid="competitor-provider-attempts-debug">
                <p className="hint muted">
                  <strong>Provider attempts (debug)</strong>: {competitorProviderAttemptCount}
                </p>
                <p className="hint muted">
                  Degraded timeout retry used: {competitorProviderDegradedRetryUsed ? "yes" : "no"}
                </p>
                <div className="table-container table-container-compact">
                  <table className="table table-dense">
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
          </div>
        ) : null}
      </SectionCard>

      {showRecommendationSections ? (
      <>
      <SectionCard
        className="operator-shell-section operator-shell-work-zone"
        role="tabpanel"
        id="workspace-content-recommendations-panel"
        aria-labelledby="workspace-content-tab-recommendations"
      >
        <SectionHeader
          title="Recommendation Queue"
          subtitle="Run deterministic recommendation analysis from the latest audit and competitor comparison context."
          headingLevel={2}
          data-testid="recommendation-queue-header"
          actions={(
            <div className="toolbar-row">
              <button
                type="button"
                className="button button-primary"
                onClick={() => void handleGenerateRecommendations()}
                disabled={loadingWorkspace || recommendationGenerationInFlight || !recommendationGenerationPrerequisitesMet}
              >
                {recommendationGenerationInFlight ? "Generating..." : "Generate Recommendations"}
              </button>
            </div>
          )}
        />
        {recommendationSectionFreshness ? (
          <p className="hint muted" data-testid="recommendation-section-freshness">
            <span className={workspaceSectionFreshnessBadgeClass(recommendationSectionFreshness.stateCode)}>
              {recommendationSectionFreshness.stateLabel}
            </span>{" "}
            {recommendationSectionFreshness.stateReason}
            {recommendationSectionFreshness.refreshExpected ? " Refresh expected." : ""}
            {recommendationSectionFreshness.evaluatedAt
              ? ` Evaluated ${formatDateTime(recommendationSectionFreshness.evaluatedAt)}.`
              : ""}
          </p>
        ) : null}
        <div className="stack-tight">
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
        <div className="workspace-section-meta">
          <span className="badge badge-muted">Total {recommendationQueueSummary.total}</span>
          <span className="badge badge-warn">Open {recommendationQueueSummary.open}</span>
          <span className="badge badge-success">Accepted {recommendationQueueSummary.accepted}</span>
          <span className="badge badge-muted">Dismissed {recommendationQueueSummary.dismissed}</span>
          <span className="badge badge-critical">High priority {recommendationQueueSummary.highPriority}</span>
        </div>
        {topQueueRecommendation && topQueueRecommendationActionState ? (
          <div
            className="panel panel-compact stack-tight operator-summary-callout"
            data-testid="workspace-recommendation-action-state"
          >
            <span className="hint muted">Top recommendation action state</span>
            <div className="link-row">
              <span className={topQueueRecommendationActionPresentation?.badgeClass || topQueueRecommendationActionState.badgeClass}>
                {topQueueRecommendationActionPresentation?.label || topQueueRecommendationActionState.label}
              </span>
              <span className="badge badge-muted">{topQueueRecommendation.status}</span>
              <span className="badge badge-muted">{topQueueRecommendation.priority_band}</span>
            </div>
            <span className="hint">
              <Link href={buildRecommendationDetailHref(topQueueRecommendation.id, selectedSite.id)}>
                {topQueueRecommendation.title}
              </Link>
            </span>
            <span className="hint muted">{topQueueRecommendationActionPresentation?.outcome || topQueueRecommendationActionState.outcome}</span>
            <span className="hint muted">Next step: {topQueueRecommendationActionPresentation?.nextStep || topQueueRecommendationActionState.nextStep}</span>
            {topQueueRecommendationActionControls.length > 0 ? (
              <ActionControls
                controls={topQueueRecommendationActionControls}
                resolveHref={(control) =>
                  resolveWorkspaceRecommendationControlHref({
                    control,
                    recommendation: topQueueRecommendation,
                    siteId: selectedSite.id,
                    linkedRecommendationRunOutputId: latestAutomationRecommendationRunOutputId,
                  })}
                data-testid="workspace-recommendation-action-controls"
              />
            ) : null}
            {effectiveTopQueueRecommendationActionExecutionItem ? (
              <OutputReview
                item={effectiveTopQueueRecommendationActionExecutionItem}
                stateLabel={topQueueRecommendationActionPresentation?.label || topQueueRecommendationActionState.label}
                stateBadgeClass={topQueueRecommendationActionPresentation?.badgeClass || topQueueRecommendationActionState.badgeClass}
                outcome={topQueueRecommendationActionPresentation?.outcome || topQueueRecommendationActionState.outcome}
                nextStep={topQueueRecommendationActionPresentation?.nextStep || topQueueRecommendationActionState.nextStep}
                onDecision={(decision) => {
                  void handleWorkspaceRecommendationDecision(topQueueRecommendation, decision);
                }}
                onBindAutomation={handleWorkspaceRecommendationAutomationBinding}
                onRunAutomation={handleWorkspaceRecommendationAutomationExecution}
                decisionPending={Boolean(recommendationActionDecisionSavingByItemId[topQueueRecommendation.id])}
                decisionError={recommendationActionDecisionErrorByItemId[topQueueRecommendation.id]}
                bindAutomationTargetId={workspaceAutomationBindingTargetId}
                bindAutomationPendingByActionId={automationBindingPendingByActionId}
                bindAutomationErrorByActionId={automationBindingErrorByActionId}
                runAutomationPendingByActionId={automationRunPendingByActionId}
                runAutomationErrorByActionId={automationRunErrorByActionId}
                resolveOutputHref={(outputId) => buildRecommendationRunHref(outputId, selectedSite.id)}
                data-testid="workspace-recommendation-output-review"
              />
            ) : null}
            {workspaceExecutionPollingActive ? (
              <span className="hint muted" data-testid="workspace-recommendation-execution-polling-status">
                Automation execution is in progress. Status refreshes automatically every few seconds.
              </span>
            ) : null}
          </div>
        ) : null}
        <p>
          <Link href="/recommendations">Open Recommendation Queue</Link>
        </p>
        {!queueError && (!queueResponse || queueResponse.items.length === 0) ? (
          <p className="hint muted">No recommendations yet. Generate recommendations to see next best actions for this site.</p>
        ) : null}
        {queueResponse && queueResponse.items.length > 0 ? (
          <div className="stack-tight recommendation-workspace-list" data-testid="workspace-recommendation-queue-list">
            {queueResponse.items.map((item) => (
              <article key={item.id} className="workspace-recommendation-row-card">
                <div className="workspace-recommendation-row-main workspace-recommendation-row-main-bounded">
                  <Link href={buildRecommendationDetailHref(item.id, selectedSite.id)}>{item.title}</Link>
                  <span className="hint muted"><code>{item.id}</code></span>
                </div>
                <div className="link-row">
                  <span className="badge badge-muted">
                    {item.priority_score} ({item.priority_band})
                  </span>
                  <span className="badge badge-muted">{item.status}</span>
                  <span className="badge badge-muted">{item.category}</span>
                  <span className="badge badge-muted">{recommendationSourceType(item)}</span>
                  <span className="badge badge-muted">Updated {formatDateTime(item.updated_at)}</span>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </SectionCard>

      <SectionCard className="operator-shell-section operator-shell-work-zone">
        <SectionHeader
          title="Recommendation Runs and Narratives"
          subtitle="Review deterministic recommendations, AI narrative overlays, and recent tuning outcomes."
          headingLevel={2}
          data-testid="recommendation-runs-header"
          meta={latestCompletedRecommendationRun ? (
            <span className="hint muted">
              Latest completed run: <code>{latestCompletedRecommendationRun.id}</code> (
              {latestCompletedRecommendationRun.status})
            </span>
          ) : null}
        />
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
                <span className="hint muted">Why this priority order</span>
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
            <h4>Recommendations</h4>
            {recommendationApplyOutcome && recommendationApplyOutcomePresentation ? (
              <div
                className="panel panel-compact stack-tight operator-summary-callout recommendation-outcome-surface"
                data-testid="recommendation-apply-outcome-summary"
              >
                <div className="workspace-section-header workspace-section-header-compact">
                  <div className="workspace-section-header-main">
                    <h5 className="workspace-section-title">Recently applied recommendation</h5>
                    <p className="hint muted workspace-section-subtitle">
                      Latest applied change and when to expect visibility updates.
                    </p>
                  </div>
                  <div className="workspace-section-actions">
                    <span className={recommendationApplyOutcomePresentation.statusBadgeClass}>
                      {recommendationApplyOutcomePresentation.statusLabel}
                    </span>
                  </div>
                </div>
                {recommendationApplyOutcome.appliedRecommendationTitle ? (
                  <strong>
                    {recommendationApplyOutcome.appliedRecommendationTitle}
                    {recommendationApplyOutcome.appliedRecommendationId
                      ? ` (${recommendationApplyOutcome.appliedRecommendationId})`
                      : ""}
                  </strong>
                ) : null}
                {recommendationApplyOutcome.appliedChangeSummary ? (
                  <span className="hint">What changed: {recommendationApplyOutcome.appliedChangeSummary}</span>
                ) : null}
                {recommendationApplyOutcome.appliedPreviewSummary ? (
                  <span className="hint muted">
                    Applied from preview: {recommendationApplyOutcome.appliedPreviewSummary}
                  </span>
                ) : null}
                <span className="hint muted">{recommendationApplyOutcomePresentation.timingGuidance}</span>
                {recommendationApplyOutcomePresentation.sourceGuidance ? (
                  <span className="hint muted">{recommendationApplyOutcomePresentation.sourceGuidance}</span>
                ) : null}
                {recommendationApplyOutcome.source === "manual" ? (
                  <Link href="/business-profile">Review in Business Profile</Link>
                ) : null}
                {recommendationApplyOutcome.appliedAt ? (
                  <span className="hint muted">Applied at: {formatDateTime(recommendationApplyOutcome.appliedAt)}</span>
                ) : null}
              </div>
            ) : null}
            {!latestCompletedRecommendationsError && latestCompletedRecommendations.length === 0 ? (
              <p className="hint muted">No recommendations yet. Generate recommendations to see next best actions for this site.</p>
            ) : null}
            {latestCompletedRecommendations.length > 0 ? (
              <div
                className="panel panel-compact stack-tight operator-summary-callout recommendation-emphasis-surface"
                data-testid="recommendation-ready-now-emphasis"
              >
                <div className="workspace-section-header workspace-section-header-compact">
                  <div className="workspace-section-header-main">
                    <h5 className="workspace-section-title">Ready now recommendations</h5>
                    <p className="hint muted workspace-section-subtitle">
                      Highest-value items to review and apply first.
                    </p>
                  </div>
                  <div className="workspace-section-actions">
                    <span className="badge badge-critical">
                      {recommendationReadyNowBucket?.items.length || 0}
                    </span>
                  </div>
                </div>
                {topReadyNowRecommendation ? (
                  <>
                    <strong>{topReadyNowRecommendation.title}</strong>
                    <span className="hint">
                      This recommendation is currently the clearest action to move first.
                    </span>
                    <div className="form-actions">
                      <button
                        type="button"
                        className="button button-primary button-inline"
                        data-testid="recommendation-ready-now-focus-button"
                        onClick={() => focusActionTarget(recommendationRowId(topReadyNowRecommendation.id))}
                      >
                        Focus ready recommendation
                      </button>
                    </div>
                  </>
                ) : (
                  <span className="hint muted">
                    No recommendations are currently marked ready now. Review pending and informational items next.
                  </span>
                )}
              </div>
            ) : null}
            {latestCompletedRecommendations.length > 0 ? (
              <div className="recommendation-bucket-grid" data-testid="recommendation-buckets">
                {recommendationPresentationBuckets.map((bucket) => (
                  <div
                    key={`recommendation-bucket-${bucket.key}`}
                    className={`panel panel-compact stack recommendation-bucket recommendation-bucket-${bucket.key}`}
                    data-testid={`recommendation-bucket-${bucket.key}`}
                  >
                    <div className="workspace-section-header workspace-section-header-compact">
                      <div className="workspace-section-header-main">
                        <h5 className="workspace-section-title">{bucket.label}</h5>
                        <p className="hint muted workspace-section-subtitle">{bucket.subtitle}</p>
                      </div>
                      <div className="workspace-section-actions">
                        <span className={bucket.badgeClass}>{bucket.items.length}</span>
                      </div>
                    </div>
                    <div className="recommendation-bucket-list">
                      {bucket.items.slice(0, 4).map((item) => {
                        const recommendationProgress = normalizeRecommendationProgress(item);
                        const recommendationLifecycle = normalizeRecommendationLifecycle(item);
                        const recommendationPriority = normalizeRecommendationPriority(item);
                        const recommendationDetailClarity = buildRecommendationDetailClarityFromItem(item);
                        const hasRecommendationDetailClarity =
                          hasRecommendationDetailClarityContent(recommendationDetailClarity);
                        const recommendationActionSummary = recommendationDetailClarity.recommendedAction
                          || normalizeRecommendationActionClarity(item)
                          || normalizeRecommendationEvidenceSummary(item)
                          || normalizeRecommendationExpectedOutcome(item)
                          || truncateText(item.rationale, 130);
                        return (
                          <article
                            key={`recommendation-bucket-item-${bucket.key}-${item.id}`}
                            className="recommendation-bucket-item"
                            data-testid={`recommendation-bucket-item-${bucket.key}`}
                          >
                            <div className="recommendation-bucket-item-header">
                              <Link href={buildRecommendationDetailHref(item.id, selectedSite.id)}>{item.title}</Link>
                              <span className={recommendationPresentationStateBadgeClass(bucket.key)}>
                                {recommendationPresentationStateLabel(bucket.key)}
                              </span>
                            </div>
                            <div className="link-row recommendation-bucket-item-meta">
                              <span className={recommendationProgress.badgeClass}>{recommendationProgress.label}</span>
                              {recommendationLifecycle ? (
                                <span className={recommendationLifecycle.badgeClass}>{recommendationLifecycle.label}</span>
                              ) : null}
                              {recommendationPriority ? (
                                <span className={recommendationPriorityLevelBadgeClass(recommendationPriority.priorityLevel)}>
                                  {formatRecommendationPriorityLevelLabel(recommendationPriority.priorityLevel)}
                                </span>
                              ) : null}
                              <span className="badge badge-muted">{item.category}</span>
                              <span className="badge badge-muted">{item.severity}</span>
                            </div>
                            <RecommendationDetailClarity
                              clarity={recommendationDetailClarity}
                              bucketKey={bucket.key}
                              testId={`recommendation-detail-clarity-${bucket.key}-${item.id}`}
                            />
                            {!hasRecommendationDetailClarity && recommendationActionSummary ? (
                              <span className="hint muted">{recommendationActionSummary}</span>
                            ) : null}
                          </article>
                        );
                      })}
                    </div>
                    {bucket.items.length > 4 ? (
                      <span className="hint muted">
                        +{bucket.items.length - 4} more recommendation(s) shown in the detailed list below.
                      </span>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
            {latestCompletedRecommendations.length > 0 ? (
              recommendationThemeSections.length <= 1 ? (
                <div className="stack-tight recommendation-workspace-list">
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
                        const recommendationTargetContentSummary =
                          normalizeRecommendationTargetContentSummary(item);
                        const recommendationActionPlanSteps = normalizeRecommendationActionPlanSteps(item);
                        const recommendationCompetitorLinkageSummary =
                          normalizeRecommendationCompetitorLinkageSummary(item);
                        const recommendationCompetitorEvidenceLinks =
                          normalizeRecommendationCompetitorEvidenceLinks(item);
                        const recommendationActionDelta = normalizeRecommendationActionDelta(item);
                        const recommendationPriority = normalizeRecommendationPriority(item);
                        const recommendationPriorityRationale = normalizeRecommendationPriorityRationale(item);
                        const recommendationEvidenceStrength = normalizeRecommendationEvidenceStrength(item);
                        const recommendationCompetitorInfluence = normalizeRecommendationCompetitorInfluenceLevel(item);
                        const recommendationWhyNow = normalizeRecommendationWhyNow(item);
                        const recommendationNextAction = normalizeRecommendationNextAction(item);
                        const recommendationCompetitorInsight = normalizeRecommendationCompetitorInsight(item);
                        const recommendationMeasurementContext = normalizeRecommendationMeasurementContext(item);
                        const recommendationMeasurementContextLine = buildRecommendationMeasurementContextLine(
                          recommendationMeasurementContext,
                        );
                        const recommendationMeasurementSinceLine = buildRecommendationMeasurementSinceLine(
                          recommendationMeasurementContext,
                        );
                        const recommendationSearchConsoleContext = normalizeRecommendationSearchConsoleContext(item);
                        const recommendationSearchVisibilityContextLine = buildRecommendationSearchVisibilityContextLine(
                          recommendationSearchConsoleContext,
                        );
                        const recommendationSearchVisibilitySinceLine = buildRecommendationSearchVisibilitySinceLine(
                          recommendationSearchConsoleContext,
                        );
                        const recommendationSearchQueriesLine = recommendationSearchConsoleContext
                          && recommendationSearchConsoleContext.searchConsoleStatus === "available"
                          && recommendationSearchConsoleContext.topQueriesSummary.length > 0
                          ? recommendationSearchConsoleContext.topQueriesSummary
                            .map((query) => query.query)
                            .slice(0, 3)
                            .join(" · ")
                          : null;
                        const recommendationEffectivenessSummary = normalizeRecommendationEffectivenessSummary(item);
                        const recommendationExecutionType = normalizeRecommendationExecutionType(item);
                        const recommendationExecutionScope = normalizeRecommendationExecutionScope(item);
                        const recommendationExecutionInputs = normalizeRecommendationExecutionInputs(item);
                        const recommendationExecutionReadiness = normalizeRecommendationExecutionReadiness(item);
                        const recommendationBlockingReason = normalizeRecommendationBlockingReason(item);
                        const recommendationPresentationBucketKey = classifyRecommendationPresentationBucket(item);
                        const recommendationDetailClarity = buildRecommendationDetailClarityView({
                          actionDelta: recommendationActionDelta,
                          evidenceSummary: recommendationEvidenceSummary,
                          observedGapSummary: recommendationObservedGapSummary,
                          actionClarity: recommendationActionClarity,
                          expectedOutcome: recommendationExpectedOutcome,
                          competitorLinkageSummary: recommendationCompetitorLinkageSummary,
                          evidenceTrace: recommendationEvidenceTrace,
                          targetContext: recommendationTargetContext,
                          targetPageHints: recommendationTargetPageHints,
                          targetContentSummary: recommendationTargetContentSummary,
                        });
                        const rowId = recommendationRowId(item.id);
                        return (
                          <article
                            key={item.id}
                            id={rowId}
                            data-testid={`recommendation-workspace-item-${item.id}`}
                            className={[
                              "workspace-recommendation-row-card",
                              startHereFocusedTargetId === rowId ? "start-here-target-active" : "",
                            ].filter(Boolean).join(" ")}
                          >
                            <div className="workspace-recommendation-row-layout">
                                <div
                                  className="workspace-recommendation-row-main workspace-recommendation-row-main-bounded"
                                  data-testid={`recommendation-row-main-${item.id}`}
                                >
                                  <Link href={buildRecommendationDetailHref(item.id, selectedSite.id)}>{item.title}</Link>
                                  <RecommendationDetailClarity
                                    clarity={recommendationDetailClarity}
                                    bucketKey={recommendationPresentationBucketKey}
                                    testId={`recommendation-detail-clarity-row-${item.id}`}
                                  />
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
                                  {recommendationWhyNow ? (
                                    <span className="hint muted" data-testid="recommendation-why-now">
                                      Why now: {recommendationWhyNow}
                                    </span>
                                  ) : null}
                                  {recommendationCompetitorInsight ? (
                                    <span className="hint muted" data-testid="recommendation-competitor-insight">
                                      Competitor insight: {recommendationCompetitorInsight}
                                    </span>
                                  ) : null}
                                  {recommendationCompetitorInfluence && recommendationCompetitorInfluence !== "none" ? (
                                    <span className="hint muted" data-testid="recommendation-competitor-influence">
                                      Competitor influence:{" "}
                                      <span className={recommendationCompetitorInfluenceBadgeClass(recommendationCompetitorInfluence)}>
                                        {formatRecommendationCompetitorInfluenceLabel(recommendationCompetitorInfluence)}
                                      </span>
                                    </span>
                                  ) : null}
                                  {recommendationNextAction ? (
                                    <span className="hint muted" data-testid="recommendation-next-action">
                                      Next action: {recommendationNextAction}
                                    </span>
                                  ) : null}
                                  {recommendationExecutionReadiness ? (
                                    <span className="hint muted" data-testid="recommendation-execution-readiness">
                                      Execution readiness:{" "}
                                      <span className={recommendationExecutionReadinessBadgeClass(recommendationExecutionReadiness)}>
                                        {formatRecommendationExecutionReadinessLabel(recommendationExecutionReadiness)}
                                      </span>
                                    </span>
                                  ) : null}
                                  {recommendationExecutionType ? (
                                    <span className="hint muted" data-testid="recommendation-execution-type">
                                      Execution type: {formatRecommendationExecutionTypeLabel(recommendationExecutionType)}
                                    </span>
                                  ) : null}
                                  {recommendationExecutionScope ? (
                                    <span className="hint muted" data-testid="recommendation-execution-scope">
                                      Execution scope: {recommendationExecutionScope}
                                    </span>
                                  ) : null}
                                  {recommendationExecutionInputs.length > 0 ? (
                                    <span className="hint muted" data-testid="recommendation-execution-inputs">
                                      Execution inputs: {recommendationExecutionInputs.join(" · ")}
                                    </span>
                                  ) : null}
                                  {recommendationExecutionReadiness !== "ready" && recommendationBlockingReason ? (
                                    <span className="hint muted" data-testid="recommendation-execution-blocking">
                                      Execution blocker: {recommendationBlockingReason}
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
                                  {recommendationTargetContentSummary ? (
                                    <span className="hint muted" data-testid="recommendation-target-content-summary">
                                      Content to update: {recommendationTargetContentSummary}
                                    </span>
                                  ) : null}
                                  {recommendationMeasurementContextLine ? (
                                    <span className="hint muted" data-testid="recommendation-measurement-context">
                                      Recent traffic for this page/topic: {recommendationMeasurementContextLine}
                                    </span>
                                  ) : null}
                                  {recommendationMeasurementSinceLine ? (
                                    <span className="hint muted" data-testid="recommendation-measurement-since">
                                      Since this recommendation: {recommendationMeasurementSinceLine}
                                    </span>
                                  ) : null}
                                  {recommendationMeasurementContext?.measurementStatus === "no_match" ? (
                                    <span className="hint muted" data-testid="recommendation-measurement-no-match">
                                      No page-level measurement match available.
                                    </span>
                                  ) : null}
                                  {recommendationSearchVisibilityContextLine ? (
                                    <span className="hint muted" data-testid="recommendation-search-context">
                                      Recent search visibility for this page/topic: {recommendationSearchVisibilityContextLine}
                                    </span>
                                  ) : null}
                                  {recommendationSearchVisibilitySinceLine ? (
                                    <span className="hint muted" data-testid="recommendation-search-since">
                                      Since this recommendation (search): {recommendationSearchVisibilitySinceLine}
                                    </span>
                                  ) : null}
                                  {recommendationSearchQueriesLine ? (
                                    <span className="hint muted" data-testid="recommendation-search-queries">
                                      Top queries: {recommendationSearchQueriesLine}
                                    </span>
                                  ) : null}
                                  {recommendationSearchConsoleContext?.searchConsoleStatus === "no_match" ? (
                                    <span className="hint muted" data-testid="recommendation-search-no-match">
                                      No page-level search visibility match available.
                                    </span>
                                  ) : null}
                                  {recommendationEffectivenessSummary ? (
                                    <span className="hint muted" data-testid="recommendation-effectiveness-summary">
                                      Directional outcome: {recommendationEffectivenessSummary}
                                    </span>
                                  ) : null}
                                  {recommendationActionPlanSteps.length > 0 ? (
                                    <div className="stack-tight" data-testid={`recommendation-action-plan-${item.id}`}>
                                      <span className="hint muted">
                                        <span className="text-strong">How to implement:</span>
                                      </span>
                                      <ol className="compact-list">
                                        {recommendationActionPlanSteps.map((step) => (
                                          <li key={`${item.id}-workspace-plan-${step.step_number}`}>
                                            <span className="hint muted">
                                              <span className="text-strong">Step {step.step_number}:</span> {step.title}
                                            </span>
                                            <br />
                                            <span className="hint muted">{step.instruction}</span>
                                            {step.before_example ? (
                                              <>
                                                <br />
                                                <span className="hint muted">Before: {step.before_example}</span>
                                              </>
                                            ) : null}
                                            {step.after_example ? (
                                              <>
                                                <br />
                                                <span className="hint muted">After: {step.after_example}</span>
                                              </>
                                            ) : null}
                                          </li>
                                        ))}
                                      </ol>
                                    </div>
                                  ) : null}
                                  {recommendationCompetitorLinkageSummary ? (
                                    <span className="hint muted" data-testid="recommendation-competitor-linkage-summary">
                                      Competitor linkage: {recommendationCompetitorLinkageSummary}
                                    </span>
                                  ) : null}
                                  {recommendationCompetitorEvidenceLinks.length > 0 ? (
                                    <span className="hint muted" data-testid="recommendation-competitor-linkage">
                                      Linked competitor evidence:{" "}
                                      {recommendationCompetitorEvidenceLinks.map((link, index) => {
                                        const confidenceLabel = formatCompetitorDraftConfidenceLevelLabel(link.confidenceLevel);
                                        const sourceLabel = formatCompetitorDraftSourceTypeLabel(link.sourceType);
                                        const trustTierLabel = formatRecommendationEvidenceTrustTierLabel(link.trustTier);
                                        const trustTierBadgeClass = recommendationEvidenceTrustTierBadgeClass(link.trustTier);
                                        const suffixParts = [confidenceLabel, sourceLabel].filter(Boolean);
                                        const competitorText = suffixParts.length > 0
                                          ? `${link.competitorName} (${suffixParts.join(", ")})`
                                          : link.competitorName;
                                        return (
                                          <span key={`${item.id}-${link.competitorDraftId}`} className="recommendation-linkage-entry">
                                            {index > 0 ? "; " : null}
                                            {competitorText}{" "}
                                            {trustTierLabel ? <span className={trustTierBadgeClass}>{trustTierLabel}</span> : null}
                                          </span>
                                        );
                                      })}
                                    </span>
                                  ) : null}
                                  {recommendationActionDelta ? (
                                    <span className="hint muted" data-testid="recommendation-action-delta">
                                      Action delta: {recommendationActionDelta.observedCompetitorPattern} Site gap:{" "}
                                      {recommendationActionDelta.observedSiteGap} Next action:{" "}
                                      {recommendationActionDelta.recommendedOperatorAction} Evidence strength:{" "}
                                      {formatRecommendationActionDeltaEvidenceStrength(
                                        recommendationActionDelta.evidenceStrength,
                                      )}
                                      .
                                    </span>
                                  ) : null}
                                </div>
                                <aside className="workspace-recommendation-row-support" data-testid="recommendation-row-support">
                                  {impactLabel ? (
                                    <span className={recommendationImpactBadgeClass(impactLabel)}>{impactLabel}</span>
                                  ) : null}
                                  {eeatCategories.length > 0 ? (
                                    <div className="workspace-recommendation-row-support-group">
                                      <span className="workspace-recommendation-row-support-label">EEAT impact</span>
                                      <div className="link-row" data-testid="recommendation-eeat-badges">
                                        {eeatCategories.map((category) => (
                                          <span key={`${item.id}-${category}`} className="badge badge-muted">
                                            {formatEEATCategory(category)}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  ) : null}
                                  {priorityReasons.length > 0 ? (
                                    <div className="workspace-recommendation-row-support-group">
                                      <span className="workspace-recommendation-row-support-label">Why surfaced</span>
                                      <div className="link-row" data-testid="recommendation-priority-reasons">
                                        {priorityReasons.map((reason) => (
                                          <span key={`${item.id}-${reason}`} className="badge badge-muted">
                                            {formatPriorityReason(reason)}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  ) : null}
                                  <div className="workspace-recommendation-row-support-group">
                                    <span className="workspace-recommendation-row-support-label">Progress</span>
                                    <div className="link-row" data-testid="recommendation-progress-status">
                                      <span className={recommendationProgress.badgeClass}>{recommendationProgress.label}</span>
                                    </div>
                                  </div>
                                  {recommendationLifecycle ? (
                                    <div className="workspace-recommendation-row-support-group">
                                      <span className="workspace-recommendation-row-support-label">Lifecycle</span>
                                      <div className="link-row" data-testid="recommendation-lifecycle-state">
                                        <span className={recommendationLifecycle.badgeClass}>{recommendationLifecycle.label}</span>
                                      </div>
                                    </div>
                                  ) : null}
                                  {recommendationPriority ? (
                                    <div className="workspace-recommendation-row-support-group" data-testid="recommendation-priority">
                                      <span className="workspace-recommendation-row-support-label">Priority</span>
                                      <div className="link-row">
                                        <span className={recommendationPriorityLevelBadgeClass(recommendationPriority.priorityLevel)}>
                                          {formatRecommendationPriorityLevelLabel(recommendationPriority.priorityLevel)}
                                        </span>
                                        {recommendationPriority.effortHint ? (
                                          <span className="badge badge-muted">
                                            Effort: {formatRecommendationEffortHintLabel(recommendationPriority.effortHint)}
                                          </span>
                                        ) : null}
                                      </div>
                                    </div>
                                  ) : null}
                                  {recommendationPriorityRationale ? (
                                    <div className="workspace-recommendation-row-support-group">
                                      <span className="workspace-recommendation-row-support-label">Priority rationale</span>
                                      <span className="hint muted" data-testid="recommendation-priority-rationale">
                                        {recommendationPriorityRationale}
                                      </span>
                                    </div>
                                  ) : null}
                                  {recommendationEvidenceStrength ? (
                                    <div className="workspace-recommendation-row-support-group">
                                      <span className="workspace-recommendation-row-support-label">Evidence strength</span>
                                      <div className="link-row" data-testid="recommendation-evidence-strength">
                                        <span className={recommendationEvidenceStrengthBadgeClass(recommendationEvidenceStrength)}>
                                          {formatRecommendationEvidenceStrengthLabel(recommendationEvidenceStrength)}
                                        </span>
                                      </div>
                                    </div>
                                  ) : null}
                                  <div className="workspace-recommendation-row-support-group">
                                    <span className="workspace-recommendation-row-support-label">Details</span>
                                    <div className="link-row">
                                      <span className="badge badge-muted">{item.category}</span>
                                      <span className="badge badge-muted">{item.severity}</span>
                                      <span className="badge badge-muted">
                                        {item.priority_score} ({item.priority_band})
                                      </span>
                                    </div>
                                  </div>
                                </aside>
                              </div>
                          </article>
                        );
                      })}
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
                      <div className="stack-tight recommendation-workspace-list">
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
                              const recommendationTargetContentSummary =
                                normalizeRecommendationTargetContentSummary(item);
                              const recommendationActionPlanSteps = normalizeRecommendationActionPlanSteps(item);
                              const recommendationCompetitorLinkageSummary =
                                normalizeRecommendationCompetitorLinkageSummary(item);
                              const recommendationCompetitorEvidenceLinks =
                                normalizeRecommendationCompetitorEvidenceLinks(item);
                              const recommendationActionDelta = normalizeRecommendationActionDelta(item);
                              const recommendationPriority = normalizeRecommendationPriority(item);
                              const recommendationPriorityRationale = normalizeRecommendationPriorityRationale(item);
                              const recommendationEvidenceStrength = normalizeRecommendationEvidenceStrength(item);
                              const recommendationCompetitorInfluence = normalizeRecommendationCompetitorInfluenceLevel(item);
                              const recommendationWhyNow = normalizeRecommendationWhyNow(item);
                              const recommendationNextAction = normalizeRecommendationNextAction(item);
                              const recommendationCompetitorInsight = normalizeRecommendationCompetitorInsight(item);
                              const recommendationMeasurementContext = normalizeRecommendationMeasurementContext(item);
                              const recommendationMeasurementContextLine = buildRecommendationMeasurementContextLine(
                                recommendationMeasurementContext,
                              );
                              const recommendationMeasurementSinceLine = buildRecommendationMeasurementSinceLine(
                                recommendationMeasurementContext,
                              );
                              const recommendationSearchConsoleContext = normalizeRecommendationSearchConsoleContext(item);
                              const recommendationSearchVisibilityContextLine = buildRecommendationSearchVisibilityContextLine(
                                recommendationSearchConsoleContext,
                              );
                              const recommendationSearchVisibilitySinceLine = buildRecommendationSearchVisibilitySinceLine(
                                recommendationSearchConsoleContext,
                              );
                              const recommendationSearchQueriesLine = recommendationSearchConsoleContext
                                && recommendationSearchConsoleContext.searchConsoleStatus === "available"
                                && recommendationSearchConsoleContext.topQueriesSummary.length > 0
                                ? recommendationSearchConsoleContext.topQueriesSummary
                                  .map((query) => query.query)
                                  .slice(0, 3)
                                  .join(" · ")
                                : null;
                              const recommendationEffectivenessSummary = normalizeRecommendationEffectivenessSummary(item);
                              const recommendationExecutionType = normalizeRecommendationExecutionType(item);
                              const recommendationExecutionScope = normalizeRecommendationExecutionScope(item);
                              const recommendationExecutionInputs = normalizeRecommendationExecutionInputs(item);
                              const recommendationExecutionReadiness = normalizeRecommendationExecutionReadiness(item);
                              const recommendationBlockingReason = normalizeRecommendationBlockingReason(item);
                              const recommendationPresentationBucketKey = classifyRecommendationPresentationBucket(item);
                              const recommendationDetailClarity = buildRecommendationDetailClarityView({
                                actionDelta: recommendationActionDelta,
                                evidenceSummary: recommendationEvidenceSummary,
                                observedGapSummary: recommendationObservedGapSummary,
                                actionClarity: recommendationActionClarity,
                                expectedOutcome: recommendationExpectedOutcome,
                                competitorLinkageSummary: recommendationCompetitorLinkageSummary,
                                evidenceTrace: recommendationEvidenceTrace,
                                targetContext: recommendationTargetContext,
                                targetPageHints: recommendationTargetPageHints,
                                targetContentSummary: recommendationTargetContentSummary,
                              });
                              const rowId = recommendationRowId(item.id);
                              return (
                                <article
                                  key={item.id}
                                  id={rowId}
                                  data-testid={`recommendation-workspace-item-${item.id}`}
                                  className={[
                                    "workspace-recommendation-row-card",
                                    startHereFocusedTargetId === rowId ? "start-here-target-active" : "",
                                  ].filter(Boolean).join(" ")}
                                >
                                  <div className="workspace-recommendation-row-layout">
                                      <div
                                        className="workspace-recommendation-row-main workspace-recommendation-row-main-bounded"
                                        data-testid={`recommendation-row-main-${item.id}`}
                                      >
                                        <Link href={buildRecommendationDetailHref(item.id, selectedSite.id)}>{item.title}</Link>
                                        <RecommendationDetailClarity
                                          clarity={recommendationDetailClarity}
                                          bucketKey={recommendationPresentationBucketKey}
                                          testId={`recommendation-detail-clarity-row-${section.theme}-${item.id}`}
                                        />
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
                                        {recommendationWhyNow ? (
                                          <span className="hint muted" data-testid="recommendation-why-now">
                                            Why now: {recommendationWhyNow}
                                          </span>
                                        ) : null}
                                        {recommendationCompetitorInsight ? (
                                          <span className="hint muted" data-testid="recommendation-competitor-insight">
                                            Competitor insight: {recommendationCompetitorInsight}
                                          </span>
                                        ) : null}
                                        {recommendationCompetitorInfluence && recommendationCompetitorInfluence !== "none" ? (
                                          <span className="hint muted" data-testid="recommendation-competitor-influence">
                                            Competitor influence:{" "}
                                            <span className={recommendationCompetitorInfluenceBadgeClass(recommendationCompetitorInfluence)}>
                                              {formatRecommendationCompetitorInfluenceLabel(recommendationCompetitorInfluence)}
                                            </span>
                                          </span>
                                        ) : null}
                                        {recommendationNextAction ? (
                                          <span className="hint muted" data-testid="recommendation-next-action">
                                            Next action: {recommendationNextAction}
                                          </span>
                                        ) : null}
                                        {recommendationExecutionReadiness ? (
                                          <span className="hint muted" data-testid="recommendation-execution-readiness">
                                            Execution readiness:{" "}
                                            <span className={recommendationExecutionReadinessBadgeClass(recommendationExecutionReadiness)}>
                                              {formatRecommendationExecutionReadinessLabel(recommendationExecutionReadiness)}
                                            </span>
                                          </span>
                                        ) : null}
                                        {recommendationExecutionType ? (
                                          <span className="hint muted" data-testid="recommendation-execution-type">
                                            Execution type: {formatRecommendationExecutionTypeLabel(recommendationExecutionType)}
                                          </span>
                                        ) : null}
                                        {recommendationExecutionScope ? (
                                          <span className="hint muted" data-testid="recommendation-execution-scope">
                                            Execution scope: {recommendationExecutionScope}
                                          </span>
                                        ) : null}
                                        {recommendationExecutionInputs.length > 0 ? (
                                          <span className="hint muted" data-testid="recommendation-execution-inputs">
                                            Execution inputs: {recommendationExecutionInputs.join(" · ")}
                                          </span>
                                        ) : null}
                                        {recommendationExecutionReadiness !== "ready" && recommendationBlockingReason ? (
                                          <span className="hint muted" data-testid="recommendation-execution-blocking">
                                            Execution blocker: {recommendationBlockingReason}
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
                                        {recommendationTargetContentSummary ? (
                                          <span className="hint muted" data-testid="recommendation-target-content-summary">
                                            Content to update: {recommendationTargetContentSummary}
                                          </span>
                                        ) : null}
                                        {recommendationMeasurementContextLine ? (
                                          <span className="hint muted" data-testid="recommendation-measurement-context">
                                            Recent traffic for this page/topic: {recommendationMeasurementContextLine}
                                          </span>
                                        ) : null}
                                        {recommendationMeasurementSinceLine ? (
                                          <span className="hint muted" data-testid="recommendation-measurement-since">
                                            Since this recommendation: {recommendationMeasurementSinceLine}
                                          </span>
                                        ) : null}
                                        {recommendationMeasurementContext?.measurementStatus === "no_match" ? (
                                          <span className="hint muted" data-testid="recommendation-measurement-no-match">
                                            No page-level measurement match available.
                                          </span>
                                        ) : null}
                                        {recommendationSearchVisibilityContextLine ? (
                                          <span className="hint muted" data-testid="recommendation-search-context">
                                            Recent search visibility for this page/topic: {recommendationSearchVisibilityContextLine}
                                          </span>
                                        ) : null}
                                        {recommendationSearchVisibilitySinceLine ? (
                                          <span className="hint muted" data-testid="recommendation-search-since">
                                            Since this recommendation (search): {recommendationSearchVisibilitySinceLine}
                                          </span>
                                        ) : null}
                                        {recommendationSearchQueriesLine ? (
                                          <span className="hint muted" data-testid="recommendation-search-queries">
                                            Top queries: {recommendationSearchQueriesLine}
                                          </span>
                                        ) : null}
                                        {recommendationSearchConsoleContext?.searchConsoleStatus === "no_match" ? (
                                          <span className="hint muted" data-testid="recommendation-search-no-match">
                                            No page-level search visibility match available.
                                          </span>
                                        ) : null}
                                        {recommendationEffectivenessSummary ? (
                                          <span className="hint muted" data-testid="recommendation-effectiveness-summary">
                                            Directional outcome: {recommendationEffectivenessSummary}
                                          </span>
                                        ) : null}
                                        {recommendationActionPlanSteps.length > 0 ? (
                                          <div className="stack-tight" data-testid={`recommendation-action-plan-${item.id}`}>
                                            <span className="hint muted">
                                              <span className="text-strong">How to implement:</span>
                                            </span>
                                            <ol className="compact-list">
                                              {recommendationActionPlanSteps.map((step) => (
                                                <li key={`${section.theme}-${item.id}-workspace-plan-${step.step_number}`}>
                                                  <span className="hint muted">
                                                    <span className="text-strong">Step {step.step_number}:</span> {step.title}
                                                  </span>
                                                  <br />
                                                  <span className="hint muted">{step.instruction}</span>
                                                  {step.before_example ? (
                                                    <>
                                                      <br />
                                                      <span className="hint muted">Before: {step.before_example}</span>
                                                    </>
                                                  ) : null}
                                                  {step.after_example ? (
                                                    <>
                                                      <br />
                                                      <span className="hint muted">After: {step.after_example}</span>
                                                    </>
                                                  ) : null}
                                                </li>
                                              ))}
                                            </ol>
                                          </div>
                                        ) : null}
                                        {recommendationCompetitorLinkageSummary ? (
                                          <span className="hint muted" data-testid="recommendation-competitor-linkage-summary">
                                            Competitor linkage: {recommendationCompetitorLinkageSummary}
                                          </span>
                                        ) : null}
                                        {recommendationCompetitorEvidenceLinks.length > 0 ? (
                                          <span className="hint muted" data-testid="recommendation-competitor-linkage">
                                            Linked competitor evidence:{" "}
                                            {recommendationCompetitorEvidenceLinks.map((link, index) => {
                                              const confidenceLabel = formatCompetitorDraftConfidenceLevelLabel(
                                                link.confidenceLevel,
                                              );
                                              const sourceLabel = formatCompetitorDraftSourceTypeLabel(link.sourceType);
                                              const trustTierLabel = formatRecommendationEvidenceTrustTierLabel(link.trustTier);
                                              const trustTierBadgeClass = recommendationEvidenceTrustTierBadgeClass(link.trustTier);
                                              const suffixParts = [confidenceLabel, sourceLabel].filter(Boolean);
                                              const competitorText = suffixParts.length > 0
                                                ? `${link.competitorName} (${suffixParts.join(", ")})`
                                                : link.competitorName;
                                              return (
                                                <span
                                                  key={`${section.theme}-${item.id}-${link.competitorDraftId}`}
                                                  className="recommendation-linkage-entry"
                                                >
                                                  {index > 0 ? "; " : null}
                                                  {competitorText}{" "}
                                                  {trustTierLabel ? <span className={trustTierBadgeClass}>{trustTierLabel}</span> : null}
                                                </span>
                                              );
                                            })}
                                          </span>
                                        ) : null}
                                        {recommendationActionDelta ? (
                                          <span className="hint muted" data-testid="recommendation-action-delta">
                                            Action delta: {recommendationActionDelta.observedCompetitorPattern} Site gap:{" "}
                                            {recommendationActionDelta.observedSiteGap} Next action:{" "}
                                            {recommendationActionDelta.recommendedOperatorAction} Evidence strength:{" "}
                                            {formatRecommendationActionDeltaEvidenceStrength(
                                              recommendationActionDelta.evidenceStrength,
                                            )}
                                            .
                                          </span>
                                        ) : null}
                                      </div>
                                      <aside className="workspace-recommendation-row-support" data-testid="recommendation-row-support">
                                        {impactLabel ? (
                                          <span className={recommendationImpactBadgeClass(impactLabel)}>{impactLabel}</span>
                                        ) : null}
                                        {eeatCategories.length > 0 ? (
                                          <div className="workspace-recommendation-row-support-group">
                                            <span className="workspace-recommendation-row-support-label">EEAT impact</span>
                                            <div className="link-row" data-testid="recommendation-eeat-badges">
                                              {eeatCategories.map((category) => (
                                                <span key={`${item.id}-${category}`} className="badge badge-muted">
                                                  {formatEEATCategory(category)}
                                                </span>
                                              ))}
                                            </div>
                                          </div>
                                        ) : null}
                                        {priorityReasons.length > 0 ? (
                                          <div className="workspace-recommendation-row-support-group">
                                            <span className="workspace-recommendation-row-support-label">Why surfaced</span>
                                            <div className="link-row" data-testid="recommendation-priority-reasons">
                                              {priorityReasons.map((reason) => (
                                                <span key={`${item.id}-${reason}`} className="badge badge-muted">
                                                  {formatPriorityReason(reason)}
                                                </span>
                                              ))}
                                            </div>
                                          </div>
                                        ) : null}
                                        <div className="workspace-recommendation-row-support-group">
                                          <span className="workspace-recommendation-row-support-label">Progress</span>
                                          <div className="link-row" data-testid="recommendation-progress-status">
                                            <span className={recommendationProgress.badgeClass}>{recommendationProgress.label}</span>
                                          </div>
                                        </div>
                                        {recommendationLifecycle ? (
                                          <div className="workspace-recommendation-row-support-group">
                                            <span className="workspace-recommendation-row-support-label">Lifecycle</span>
                                            <div className="link-row" data-testid="recommendation-lifecycle-state">
                                              <span className={recommendationLifecycle.badgeClass}>
                                                {recommendationLifecycle.label}
                                              </span>
                                            </div>
                                          </div>
                                        ) : null}
                                        {recommendationPriority ? (
                                          <div className="workspace-recommendation-row-support-group" data-testid="recommendation-priority">
                                            <span className="workspace-recommendation-row-support-label">Priority</span>
                                            <div className="link-row">
                                              <span className={recommendationPriorityLevelBadgeClass(recommendationPriority.priorityLevel)}>
                                                {formatRecommendationPriorityLevelLabel(recommendationPriority.priorityLevel)}
                                              </span>
                                              {recommendationPriority.effortHint ? (
                                                <span className="badge badge-muted">
                                                  Effort: {formatRecommendationEffortHintLabel(recommendationPriority.effortHint)}
                                                </span>
                                              ) : null}
                                            </div>
                                          </div>
                                        ) : null}
                                        {recommendationPriorityRationale ? (
                                          <div className="workspace-recommendation-row-support-group">
                                            <span className="workspace-recommendation-row-support-label">Priority rationale</span>
                                            <span className="hint muted" data-testid="recommendation-priority-rationale">
                                              {recommendationPriorityRationale}
                                            </span>
                                          </div>
                                        ) : null}
                                        {recommendationEvidenceStrength ? (
                                          <div className="workspace-recommendation-row-support-group">
                                            <span className="workspace-recommendation-row-support-label">Evidence strength</span>
                                            <div className="link-row" data-testid="recommendation-evidence-strength">
                                              <span className={recommendationEvidenceStrengthBadgeClass(recommendationEvidenceStrength)}>
                                                {formatRecommendationEvidenceStrengthLabel(recommendationEvidenceStrength)}
                                              </span>
                                            </div>
                                          </div>
                                        ) : null}
                                        <div className="workspace-recommendation-row-support-group">
                                          <span className="workspace-recommendation-row-support-label">Details</span>
                                          <div className="link-row">
                                            <span className="badge badge-muted">{item.category}</span>
                                            <span className="badge badge-muted">{item.severity}</span>
                                            <span className="badge badge-muted">
                                              {item.priority_score} ({item.priority_band})
                                            </span>
                                          </div>
                                        </div>
                                      </aside>
                                    </div>
                                </article>
                              );
                            })}
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
                  <div className="panel panel-compact stack-tight operator-summary-callout" data-testid="narrative-apply-outcome">
                    <span className="hint muted">Latest apply outcome</span>
                    <span className="hint success">Applied</span>
                    {recommendationApplyOutcome.appliedRecommendationTitle ? (
                      <span className="hint">
                        Recommendation: {recommendationApplyOutcome.appliedRecommendationTitle}
                        {recommendationApplyOutcome.appliedRecommendationId
                          ? ` (${recommendationApplyOutcome.appliedRecommendationId})`
                          : ""}
                      </span>
                    ) : null}
                    {recommendationApplyOutcome.appliedChangeSummary ? (
                      <span className="hint muted">What changed: {recommendationApplyOutcome.appliedChangeSummary}</span>
                    ) : null}
                    {recommendationApplyOutcome.appliedPreviewSummary ? (
                      <span className="hint muted">Preview used: {recommendationApplyOutcome.appliedPreviewSummary}</span>
                    ) : null}
                    {recommendationApplyOutcome.nextRefreshExpectation ? (
                      <span className="hint muted">
                        You should see this after: {recommendationApplyOutcome.nextRefreshExpectation}
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
            <table className="table table-dense">
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
      </>
      ) : null}
    </PageContainer>
  );
}

