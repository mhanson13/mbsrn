"use client";

import Link from "next/link";
import { Fragment, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ActionControls } from "../../components/action-execution/ActionControls";
import { OutputReview } from "../../components/action-execution/OutputReview";
import { DetailFocusPanel, type DetailFocusFact } from "../../components/layout/DetailFocusPanel";
import { OperationalItemCard } from "../../components/layout/OperationalItemCard";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  ApiRequestError,
  bindActionExecutionItemAutomation,
  fetchAutomationRuns,
  fetchRecommendations,
  runActionExecutionItemAutomation,
  updateRecommendationStatus,
} from "../../lib/api/client";
import { runBoundedBulkActionQueue, type BulkActionQueueProgress } from "../../lib/bulkActionQueue";
import { deriveRecommendationOperatorActionState } from "../../lib/operatorActionState";
import {
  applyActionDecisionLocally,
  deriveActionControls,
  deriveActionStatePresentation,
} from "../../lib/transforms/actionExecution";
import type {
  ActionControl,
  ActionDecision,
  ActionExecutionItem,
  AutomationRun,
  RecommendationFilteredSummary,
  Recommendation,
  RecommendationActionStatus,
  RecommendationListFilters,
  RecommendationListResponse,
} from "../../lib/api/types";

type FilterState = {
  status: "" | NonNullable<RecommendationListFilters["status"]>;
  priorityBand: "" | NonNullable<RecommendationListFilters["priority_band"]>;
  category: "" | NonNullable<RecommendationListFilters["category"]>;
};

type SortState = "priority_desc" | "priority_asc" | "newest" | "oldest";
type QueuePresetKey = "all_recommendations" | "open_high_priority" | "accepted" | "dismissed";
type QueuePresetSelection = QueuePresetKey | "__custom__";
type QueueSummary = {
  total: number;
  open: number;
  accepted: number;
  dismissed: number;
  highPriority: number;
};

type RecommendationDecisiveness = {
  priorityCue: string;
  priorityCueTone: "badge-success" | "badge-warn" | "badge-muted";
  actionabilityCue: string;
  actionabilityTone: "badge-success" | "badge-warn" | "badge-muted";
  choiceCue: string;
  choiceCueTone: "badge-success" | "badge-warn" | "badge-muted";
  effortCue: string;
  effortCueTone: "badge-success" | "badge-warn" | "badge-muted";
  blockerCue: string;
  blockerCueTone: "badge-success" | "badge-warn" | "badge-muted";
  lifecycleCue: string;
  lifecycleCueTone: "badge-success" | "badge-warn" | "badge-muted";
  revisitCue: string;
  revisitCueTone: "badge-success" | "badge-warn" | "badge-muted";
  freshnessCue: string;
  freshnessCueTone: "badge-success" | "badge-warn" | "badge-muted";
  refreshCheck: string;
  whyNow: string;
  blockingState: string;
  afterAction: string;
  evidencePreview: string;
  evidenceTrustCue: string;
  evidenceTrustTone: "badge-success" | "badge-warn" | "badge-muted";
};

type RecommendationAutomationOriginCue = {
  label: string;
  badgeClass: "badge-success" | "badge-muted";
};
type OptimisticBulkQueueState = {
  items: Recommendation[];
  totalRecommendations: number | null;
  queueSummary: QueueSummary;
};

const DEFAULT_FILTERS: FilterState = {
  status: "",
  priorityBand: "",
  category: "",
};

const DEFAULT_SORT: SortState = "priority_desc";
const DEFAULT_PAGE = 1;
const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = PAGE_SIZE_OPTIONS[0];
const BULK_ACTION_CONCURRENCY_LIMIT = 4;
const EMPTY_QUEUE_SUMMARY: QueueSummary = {
  total: 0,
  open: 0,
  accepted: 0,
  dismissed: 0,
  highPriority: 0,
};
const RECOMMENDATION_COLLAPSED_WHY_NOW_MAX_CHARS = 96;

const SORT_OPTIONS: Array<{ label: string; value: SortState }> = [
  { label: "Priority: High to Low", value: "priority_desc" },
  { label: "Priority: Low to High", value: "priority_asc" },
  { label: "Newest First", value: "newest" },
  { label: "Oldest First", value: "oldest" },
];

const STATUS_FILTER_OPTIONS: Array<{ label: string; value: FilterState["status"] }> = [
  { label: "All statuses", value: "" },
  { label: "Open", value: "open" },
  { label: "In Progress", value: "in_progress" },
  { label: "Accepted", value: "accepted" },
  { label: "Dismissed", value: "dismissed" },
  { label: "Snoozed", value: "snoozed" },
  { label: "Resolved", value: "resolved" },
];

const PRIORITY_FILTER_OPTIONS: Array<{ label: string; value: FilterState["priorityBand"] }> = [
  { label: "All priorities", value: "" },
  { label: "Critical", value: "critical" },
  { label: "High", value: "high" },
  { label: "Medium", value: "medium" },
  { label: "Low", value: "low" },
];

const CATEGORY_FILTER_OPTIONS: Array<{ label: string; value: FilterState["category"] }> = [
  { label: "All categories", value: "" },
  { label: "SEO", value: "SEO" },
  { label: "Content", value: "CONTENT" },
  { label: "Structure", value: "STRUCTURE" },
  { label: "Technical", value: "TECHNICAL" },
];

const QUEUE_PRESETS: Array<{
  key: QueuePresetKey;
  label: string;
  filters: FilterState;
  sort: SortState;
}> = [
  {
    key: "all_recommendations",
    label: "All Recommendations",
    filters: DEFAULT_FILTERS,
    sort: DEFAULT_SORT,
  },
  {
    key: "open_high_priority",
    label: "Open High Priority",
    filters: {
      status: "open",
      priorityBand: "high",
      category: "",
    },
    sort: "priority_desc",
  },
  {
    key: "accepted",
    label: "Accepted",
    filters: {
      status: "accepted",
      priorityBand: "",
      category: "",
    },
    sort: "newest",
  },
  {
    key: "dismissed",
    label: "Dismissed",
    filters: {
      status: "dismissed",
      priorityBand: "",
      category: "",
    },
    sort: "newest",
  },
];

function parseStatusFilter(value: string | null): FilterState["status"] {
  if (!value) {
    return "";
  }
  const normalized = value.trim().toLowerCase();
  const allowedValues = new Set(STATUS_FILTER_OPTIONS.map((option) => option.value));
  if (!allowedValues.has(normalized as FilterState["status"])) {
    return "";
  }
  return normalized as FilterState["status"];
}

function parsePriorityFilter(value: string | null): FilterState["priorityBand"] {
  if (!value) {
    return "";
  }
  const normalized = value.trim().toLowerCase();
  const allowedValues = new Set(PRIORITY_FILTER_OPTIONS.map((option) => option.value));
  if (!allowedValues.has(normalized as FilterState["priorityBand"])) {
    return "";
  }
  return normalized as FilterState["priorityBand"];
}

function parseCategoryFilter(value: string | null): FilterState["category"] {
  if (!value) {
    return "";
  }
  const normalized = value.trim().toUpperCase();
  const allowedValues = new Set(CATEGORY_FILTER_OPTIONS.map((option) => option.value));
  if (!allowedValues.has(normalized as FilterState["category"])) {
    return "";
  }
  return normalized as FilterState["category"];
}

function extractAutomationLinkedRecommendationRunIds(runs: AutomationRun[]): Set<string> {
  const linkedRecommendationRunIds = new Set<string>();
  for (const run of runs) {
    if (!Array.isArray(run.steps_json)) {
      continue;
    }
    for (const step of run.steps_json) {
      if (!step || typeof step !== "object") {
        continue;
      }
      const stepName = typeof step.step_name === "string" ? step.step_name : "";
      const stepStatus = typeof step.status === "string" ? step.status.toLowerCase() : "";
      const linkedOutputId = typeof step.linked_output_id === "string" ? step.linked_output_id.trim() : "";
      if (stepName === "recommendation_run" && stepStatus === "completed" && linkedOutputId.length > 0) {
        linkedRecommendationRunIds.add(linkedOutputId);
      }
    }
  }
  return linkedRecommendationRunIds;
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

function deriveRecommendationAutomationOriginCue(
  item: Recommendation,
  linkedRecommendationRunIds: Set<string>,
  automationLinkageReady: boolean,
): RecommendationAutomationOriginCue {
  const lineage = item.action_lineage || null;
  if (lineage) {
    if ((lineage.counts?.activated_action_count || 0) > 0) {
      return {
        label: "Activated next step",
        badgeClass: "badge-success",
      };
    }
    if ((lineage.counts?.automation_ready_count || 0) > 0) {
      return {
        label: "Automation-ready next step",
        badgeClass: "badge-muted",
      };
    }
    if ((lineage.counts?.chained_draft_count || 0) > 0) {
      return {
        label: "Next step available",
        badgeClass: "badge-muted",
      };
    }
  }
  if (linkedRecommendationRunIds.has(item.recommendation_run_id)) {
    return {
      label: "Automation-triggered output",
      badgeClass: "badge-success",
    };
  }
  if (!automationLinkageReady) {
    return {
      label: "Automation linkage unavailable",
      badgeClass: "badge-muted",
    };
  }
  return {
    label: "No automation linkage detected",
    badgeClass: "badge-muted",
  };
}

function deriveRecommendationTrustTier(
  item: Recommendation,
): ActionExecutionItem["trustTier"] {
  const tiers = (item.competitor_evidence_links || [])
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

function deriveRecommendationActionExecutionItem(params: {
  item: Recommendation;
  actionStateCode: ActionExecutionItem["actionStateCode"];
  automationLinkedOutput: boolean;
  automationContextAvailable: boolean;
  automationInFlight: boolean;
}): ActionExecutionItem {
  const { item, actionStateCode, automationLinkedOutput, automationContextAvailable, automationInFlight } = params;
  const hasOutputReviewContext =
    automationLinkedOutput
    || (item.recommendation_action_clarity || "").trim().length > 0
    || (item.recommendation_evidence_summary || "").trim().length > 0;

  return {
    id: item.id,
    title: item.title,
    actionStateCode,
    priorityBand: item.priority_band,
    trustTier: deriveRecommendationTrustTier(item),
    actionLineage: item.action_lineage || null,
    linkedOutputId: automationLinkedOutput ? item.recommendation_run_id : null,
    automationAvailable: automationContextAvailable,
    automationInFlight,
    blockedReason:
      actionStateCode === "blocked_unavailable"
        ? "Recommendation state is blocked. Resolve run issues before action."
        : undefined,
    outputReview: hasOutputReviewContext
      ? {
          outputId: automationLinkedOutput ? item.recommendation_run_id : null,
          summary:
            item.recommendation_action_clarity
            || item.recommendation_evidence_summary
            || item.rationale,
          details:
            item.recommendation_expected_outcome
            || item.recommendation_observed_gap_summary
            || null,
          sourceLabel: automationLinkedOutput ? "Automation recommendation output" : "Recommendation context",
        }
      : undefined,
  };
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

function parseSortOption(
  sortValue: string | null,
  sortByValue: string | null,
  sortOrderValue: string | null,
): SortState {
  const allowedSortValues = new Set(SORT_OPTIONS.map((option) => option.value));
  const normalizedSort = (sortValue || "").trim().toLowerCase();
  if (allowedSortValues.has(normalizedSort as SortState)) {
    return normalizedSort as SortState;
  }

  const sortBy = (sortByValue || "").trim().toLowerCase();
  const sortOrder = (sortOrderValue || "").trim().toLowerCase();
  if (sortBy === "created_at") {
    return sortOrder === "asc" ? "oldest" : "newest";
  }
  if (sortBy === "priority_score" && sortOrder === "asc") {
    return "priority_asc";
  }
  return DEFAULT_SORT;
}

function parsePage(value: string | null): number {
  if (!value) {
    return DEFAULT_PAGE;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < DEFAULT_PAGE) {
    return DEFAULT_PAGE;
  }
  return parsed;
}

function parsePageSize(value: string | null): number {
  if (!value) {
    return DEFAULT_PAGE_SIZE;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return DEFAULT_PAGE_SIZE;
  }
  if (!PAGE_SIZE_OPTIONS.includes(parsed as (typeof PAGE_SIZE_OPTIONS)[number])) {
    return DEFAULT_PAGE_SIZE;
  }
  return parsed;
}

function totalPagesFor(totalItems: number, pageSize: number): number {
  if (totalItems <= 0) {
    return 1;
  }
  return Math.ceil(totalItems / pageSize);
}

function mapSortToApi(sort: SortState): Pick<RecommendationListFilters, "sort_by" | "sort_order"> {
  if (sort === "newest") {
    return { sort_by: "created_at", sort_order: "desc" };
  }
  if (sort === "oldest") {
    return { sort_by: "created_at", sort_order: "asc" };
  }
  if (sort === "priority_asc") {
    return { sort_by: "priority_score", sort_order: "asc" };
  }
  return { sort_by: "priority_score", sort_order: "desc" };
}

function matchesPresetState(filters: FilterState, sort: SortState, preset: (typeof QUEUE_PRESETS)[number]): boolean {
  return (
    preset.sort === sort &&
    preset.filters.status === filters.status &&
    preset.filters.priorityBand === filters.priorityBand &&
    preset.filters.category === filters.category
  );
}

function deriveSourceType(item: Recommendation): string {
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

function truncateRecommendationEvidence(text: string, maxChars: number): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
}

function truncateRecommendationWhyNow(text: string): string {
  return truncateRecommendationEvidence(text, RECOMMENDATION_COLLAPSED_WHY_NOW_MAX_CHARS);
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
  return truncateRecommendationEvidence(candidates[0], 118);
}

function deriveRecommendationEvidenceTrust(item: Recommendation): {
  cue: string;
  tone: "badge-success" | "badge-warn" | "badge-muted";
} {
  const trustedCount = (item.competitor_evidence_links || []).filter((link) => {
    const tier = link.trust_tier || link.evidence_trust_tier || null;
    return tier === "trusted_verified";
  }).length;
  const informationalCount = (item.competitor_evidence_links || []).filter((link) => {
    const tier = link.trust_tier || link.evidence_trust_tier || null;
    return tier === "informational_unverified" || tier === "informational_candidate";
  }).length;

  if (trustedCount > 0) {
    return { cue: "Support cue: verified linkage evidence", tone: "badge-success" };
  }
  if (informationalCount > 0) {
    return { cue: "Support cue: informational linkage evidence", tone: "badge-muted" };
  }
  if ((item.recommendation_evidence_trace || []).length > 0 || (item.recommendation_evidence_summary || "").trim().length > 0) {
    return { cue: "Support cue: recommendation-context evidence", tone: "badge-muted" };
  }
  return { cue: "Support cue: operator review required", tone: "badge-warn" };
}

function recommendationIsReadyNow(item: Recommendation): boolean {
  return item.status === "open" || item.status === "in_progress";
}

function deriveRecommendationLifecycleSupport(item: Recommendation): {
  lifecycleCue: string;
  lifecycleCueTone: "badge-success" | "badge-warn" | "badge-muted";
  revisitCue: string;
  revisitCueTone: "badge-success" | "badge-warn" | "badge-muted";
} {
  if (item.status === "accepted") {
    return {
      lifecycleCue: "Applied / completed",
      lifecycleCueTone: "badge-success",
      revisitCue: "Revisit after visibility refresh",
      revisitCueTone: "badge-warn",
    };
  }
  if (item.status === "dismissed" || item.status === "resolved" || item.status === "snoozed") {
    return {
      lifecycleCue: "Background item / revisit later",
      lifecycleCueTone: "badge-muted",
      revisitCue: "Ignore for now unless context changes",
      revisitCueTone: "badge-muted",
    };
  }
  if (recommendationIsReadyNow(item)) {
    return {
      lifecycleCue: "Needs review / pending",
      lifecycleCueTone: "badge-warn",
      revisitCue: "Revisit now",
      revisitCueTone: "badge-success",
    };
  }
  return {
    lifecycleCue: "Needs review / pending",
    lifecycleCueTone: "badge-warn",
    revisitCue: "Revisit now",
    revisitCueTone: "badge-warn",
  };
}

function deriveRecommendationFreshnessSupport(item: Recommendation): {
  freshnessCue: string;
  freshnessCueTone: "badge-success" | "badge-warn" | "badge-muted";
  refreshCheck: string;
} {
  const hasTimestamp = (item.updated_at || item.created_at || "").trim().length > 0;
  if (!hasTimestamp) {
    return {
      freshnessCue: "Possibly outdated",
      freshnessCueTone: "badge-warn",
      refreshCheck: "Refresh likely needed before acting.",
    };
  }
  if (item.status === "accepted") {
    return {
      freshnessCue: "Pending refresh",
      freshnessCueTone: "badge-warn",
      refreshCheck: "Refresh not required before acting. Validate visibility after next refresh.",
    };
  }
  if (item.status === "dismissed" || item.status === "resolved" || item.status === "snoozed") {
    return {
      freshnessCue: "Review soon",
      freshnessCueTone: "badge-muted",
      refreshCheck: "No immediate refresh needed while deferred.",
    };
  }
  if (recommendationIsReadyNow(item)) {
    return {
      freshnessCue: "Fresh enough to act",
      freshnessCueTone: "badge-success",
      refreshCheck: "No refresh required before acting.",
    };
  }
  return {
    freshnessCue: "Possibly outdated",
    freshnessCueTone: "badge-warn",
    refreshCheck: "Refresh likely needed before acting.",
  };
}

function deriveRecommendationEffortCue(item: Recommendation): {
  cue: string;
  tone: "badge-success" | "badge-warn" | "badge-muted";
} {
  const effortHint = item.recommendation_priority?.effort_hint || null;
  if (effortHint === "quick_win") {
    return { cue: "Quick win", tone: "badge-success" };
  }
  if (effortHint === "larger_change") {
    return { cue: "More involved", tone: "badge-warn" };
  }
  if (effortHint === "moderate") {
    return { cue: "Moderate lift", tone: "badge-muted" };
  }

  const effortBucket = (item.effort_bucket || "").trim().toLowerCase();
  if (effortBucket === "small") {
    return { cue: "Quick win", tone: "badge-success" };
  }
  if (effortBucket === "large" || effortBucket === "xlarge") {
    return { cue: "More involved", tone: "badge-warn" };
  }
  if (effortBucket.length > 0) {
    return { cue: "Moderate lift", tone: "badge-muted" };
  }
  return { cue: "Effort not specified", tone: "badge-muted" };
}

function deriveRecommendationChoiceSupport(params: {
  item: Recommendation;
  topReadyRecommendationId: string | null;
  effortCue: string;
}): {
  choiceCue: string;
  choiceCueTone: "badge-success" | "badge-warn" | "badge-muted";
  blockerCue: string;
  blockerCueTone: "badge-success" | "badge-warn" | "badge-muted";
} {
  const { item, topReadyRecommendationId, effortCue } = params;
  if (item.status === "accepted") {
    return {
      choiceCue: "Waiting on visibility",
      choiceCueTone: "badge-warn",
      blockerCue: "Manual follow-up required",
      blockerCueTone: "badge-warn",
    };
  }
  if (item.status === "dismissed" || item.status === "resolved" || item.status === "snoozed") {
    return {
      choiceCue: "Lower-immediacy background item",
      choiceCueTone: "badge-muted",
      blockerCue: "No blocker",
      blockerCueTone: "badge-muted",
    };
  }
  if (recommendationIsReadyNow(item)) {
    if (item.id === topReadyRecommendationId) {
      return {
        choiceCue: "Best immediate move",
        choiceCueTone: "badge-warn",
        blockerCue: "Blocked by operator review",
        blockerCueTone: "badge-warn",
      };
    }
    if (effortCue === "Quick win") {
      return {
        choiceCue: "Quick win alternative",
        choiceCueTone: "badge-success",
        blockerCue: "Blocked by operator review",
        blockerCueTone: "badge-warn",
      };
    }
    return {
      choiceCue: "Ready-now alternative",
      choiceCueTone: "badge-muted",
      blockerCue: "Blocked by operator review",
      blockerCueTone: "badge-warn",
    };
  }
  return {
    choiceCue: "Review before applying",
    choiceCueTone: "badge-warn",
    blockerCue: "Blocked by operator review",
    blockerCueTone: "badge-warn",
  };
}

function deriveRecommendationDecisiveness(
  item: Recommendation,
  topReadyRecommendationId: string | null,
): RecommendationDecisiveness {
  const evidencePreview = deriveRecommendationEvidencePreview(item);
  const evidenceTrust = deriveRecommendationEvidenceTrust(item);
  const effortCue = deriveRecommendationEffortCue(item);
  const lifecycleSupport = deriveRecommendationLifecycleSupport(item);
  const freshnessSupport = deriveRecommendationFreshnessSupport(item);
  const choiceSupport = deriveRecommendationChoiceSupport({
    item,
    topReadyRecommendationId,
    effortCue: effortCue.cue,
  });
  if (recommendationIsReadyNow(item)) {
    if (item.priority_band === "critical" || item.priority_band === "high") {
      return {
        priorityCue: "High-value next step",
        priorityCueTone: "badge-warn",
        actionabilityCue: "Ready now",
        actionabilityTone: "badge-success",
        choiceCue: choiceSupport.choiceCue,
        choiceCueTone: choiceSupport.choiceCueTone,
        effortCue: effortCue.cue,
        effortCueTone: effortCue.tone,
        blockerCue: choiceSupport.blockerCue,
        blockerCueTone: choiceSupport.blockerCueTone,
        lifecycleCue: lifecycleSupport.lifecycleCue,
        lifecycleCueTone: lifecycleSupport.lifecycleCueTone,
        revisitCue: lifecycleSupport.revisitCue,
        revisitCueTone: lifecycleSupport.revisitCueTone,
        freshnessCue: freshnessSupport.freshnessCue,
        freshnessCueTone: freshnessSupport.freshnessCueTone,
        refreshCheck: freshnessSupport.refreshCheck,
        whyNow: "Open high-priority recommendation is ready for operator decision.",
        blockingState: "No blocker detected.",
        afterAction: "Queue status updates now; confirm external visibility on next refresh.",
        evidencePreview,
        evidenceTrustCue: evidenceTrust.cue,
        evidenceTrustTone: evidenceTrust.tone,
      };
    }
    return {
      priorityCue: "Review before applying",
      priorityCueTone: "badge-muted",
      actionabilityCue: "Ready now",
      actionabilityTone: "badge-success",
      choiceCue: choiceSupport.choiceCue,
      choiceCueTone: choiceSupport.choiceCueTone,
      effortCue: effortCue.cue,
      effortCueTone: effortCue.tone,
      blockerCue: choiceSupport.blockerCue,
      blockerCueTone: choiceSupport.blockerCueTone,
      lifecycleCue: lifecycleSupport.lifecycleCue,
      lifecycleCueTone: lifecycleSupport.lifecycleCueTone,
      revisitCue: lifecycleSupport.revisitCue,
      revisitCueTone: lifecycleSupport.revisitCueTone,
      freshnessCue: freshnessSupport.freshnessCue,
      freshnessCueTone: freshnessSupport.freshnessCueTone,
      refreshCheck: freshnessSupport.refreshCheck,
      whyNow: "Recommendation is ready but lower priority than top urgent items.",
      blockingState: "Awaiting operator decision.",
      afterAction: "Queue status updates now; visibility follows after refresh.",
      evidencePreview,
      evidenceTrustCue: evidenceTrust.cue,
      evidenceTrustTone: evidenceTrust.tone,
    };
  }

  if (item.status === "accepted") {
    return {
      priorityCue: "Waiting on visibility",
      priorityCueTone: "badge-warn",
      actionabilityCue: "Manual follow-up required",
      actionabilityTone: "badge-warn",
      choiceCue: choiceSupport.choiceCue,
      choiceCueTone: choiceSupport.choiceCueTone,
      effortCue: effortCue.cue,
      effortCueTone: effortCue.tone,
      blockerCue: choiceSupport.blockerCue,
      blockerCueTone: choiceSupport.blockerCueTone,
      lifecycleCue: lifecycleSupport.lifecycleCue,
      lifecycleCueTone: lifecycleSupport.lifecycleCueTone,
      revisitCue: lifecycleSupport.revisitCue,
      revisitCueTone: lifecycleSupport.revisitCueTone,
      freshnessCue: freshnessSupport.freshnessCue,
      freshnessCueTone: freshnessSupport.freshnessCueTone,
      refreshCheck: freshnessSupport.refreshCheck,
      whyNow: "Apply was recorded and now requires visibility confirmation.",
      blockingState: "Pending next refresh for visibility confirmation.",
      afterAction: "Re-check after next refresh and confirm observed impact.",
      evidencePreview,
      evidenceTrustCue: evidenceTrust.cue,
      evidenceTrustTone: evidenceTrust.tone,
    };
  }

  if (item.status === "dismissed" || item.status === "resolved" || item.status === "snoozed") {
    return {
      priorityCue: "Informational",
      priorityCueTone: "badge-muted",
      actionabilityCue: "No immediate action",
      actionabilityTone: "badge-muted",
      choiceCue: choiceSupport.choiceCue,
      choiceCueTone: choiceSupport.choiceCueTone,
      effortCue: effortCue.cue,
      effortCueTone: effortCue.tone,
      blockerCue: choiceSupport.blockerCue,
      blockerCueTone: choiceSupport.blockerCueTone,
      lifecycleCue: lifecycleSupport.lifecycleCue,
      lifecycleCueTone: lifecycleSupport.lifecycleCueTone,
      revisitCue: lifecycleSupport.revisitCue,
      revisitCueTone: lifecycleSupport.revisitCueTone,
      freshnessCue: freshnessSupport.freshnessCue,
      freshnessCueTone: freshnessSupport.freshnessCueTone,
      refreshCheck: freshnessSupport.refreshCheck,
      whyNow: "Recommendation is retained for history and auditability.",
      blockingState: "No active blocker.",
      afterAction: "No further effect unless recommendation is re-opened.",
      evidencePreview,
      evidenceTrustCue: evidenceTrust.cue,
      evidenceTrustTone: evidenceTrust.tone,
    };
  }

  return {
    priorityCue: "Needs review / pending",
    priorityCueTone: "badge-warn",
    actionabilityCue: "Review required",
    actionabilityTone: "badge-warn",
    choiceCue: choiceSupport.choiceCue,
    choiceCueTone: choiceSupport.choiceCueTone,
    effortCue: effortCue.cue,
    effortCueTone: effortCue.tone,
    blockerCue: choiceSupport.blockerCue,
    blockerCueTone: choiceSupport.blockerCueTone,
    lifecycleCue: lifecycleSupport.lifecycleCue,
    lifecycleCueTone: lifecycleSupport.lifecycleCueTone,
    revisitCue: lifecycleSupport.revisitCue,
    revisitCueTone: lifecycleSupport.revisitCueTone,
    freshnessCue: freshnessSupport.freshnessCue,
    freshnessCueTone: freshnessSupport.freshnessCueTone,
    refreshCheck: freshnessSupport.refreshCheck,
    whyNow: "Current status still requires an operator decision.",
    blockingState: "Current status requires operator review.",
    afterAction: "Once applied, visibility can be confirmed after refresh.",
    evidencePreview,
    evidenceTrustCue: evidenceTrust.cue,
    evidenceTrustTone: evidenceTrust.tone,
  };
}

function isHighPriority(item: Recommendation): boolean {
  return item.priority_band === "high" || item.priority_band === "critical";
}

function summarizeQueueFromItems(items: Recommendation[]): QueueSummary {
  return items.reduce(
    (summary, item) => {
      summary.total += 1;
      if (item.status === "open") {
        summary.open += 1;
      }
      if (item.status === "accepted") {
        summary.accepted += 1;
      }
      if (item.status === "dismissed") {
        summary.dismissed += 1;
      }
      if (isHighPriority(item)) {
        summary.highPriority += 1;
      }
      return summary;
    },
    { ...EMPTY_QUEUE_SUMMARY },
  );
}

function adjustSummaryStatusCount(summary: QueueSummary, status: string, delta: number): void {
  if (status === "open") {
    summary.open = Math.max(0, summary.open + delta);
    return;
  }
  if (status === "accepted") {
    summary.accepted = Math.max(0, summary.accepted + delta);
    return;
  }
  if (status === "dismissed") {
    summary.dismissed = Math.max(0, summary.dismissed + delta);
  }
}

function applyOptimisticBulkStatusToQueueState(params: {
  baselineItems: Recommendation[];
  baselineTotalRecommendations: number | null;
  baselineQueueSummary: QueueSummary;
  selectedItemIds: string[];
  nextStatus: RecommendationActionStatus;
  statusFilter: FilterState["status"];
}): OptimisticBulkQueueState {
  const {
    baselineItems,
    baselineTotalRecommendations,
    baselineQueueSummary,
    selectedItemIds,
    nextStatus,
    statusFilter,
  } = params;

  const selectedIdSet = new Set(selectedItemIds);
  let nextTotalRecommendations = baselineTotalRecommendations;
  const nextQueueSummary: QueueSummary = { ...baselineQueueSummary };
  const nextItems: Recommendation[] = [];

  for (const item of baselineItems) {
    if (!selectedIdSet.has(item.id)) {
      nextItems.push(item);
      continue;
    }

    const updatedItem: Recommendation = {
      ...item,
      status: nextStatus,
    };

    const remainsInFilteredView = !statusFilter || statusFilter === nextStatus;
    if (statusFilter && statusFilter !== nextStatus) {
      if (nextTotalRecommendations !== null) {
        nextTotalRecommendations = Math.max(0, nextTotalRecommendations - 1);
      }
      nextQueueSummary.total = Math.max(0, nextQueueSummary.total - 1);
      adjustSummaryStatusCount(nextQueueSummary, item.status, -1);
      if (isHighPriority(item)) {
        nextQueueSummary.highPriority = Math.max(0, nextQueueSummary.highPriority - 1);
      }
    } else if (item.status !== nextStatus) {
      adjustSummaryStatusCount(nextQueueSummary, item.status, -1);
      adjustSummaryStatusCount(nextQueueSummary, nextStatus, 1);
    }

    if (remainsInFilteredView) {
      nextItems.push(updatedItem);
    }
  }

  return {
    items: nextItems,
    totalRecommendations: nextTotalRecommendations,
    queueSummary: nextQueueSummary,
  };
}

function toQueueSummary(summary: RecommendationFilteredSummary | null | undefined): QueueSummary | null {
  if (!summary) {
    return null;
  }
  return {
    total: summary.total,
    open: summary.open,
    accepted: summary.accepted,
    dismissed: summary.dismissed,
    highPriority: summary.high_priority,
  };
}

function deriveQueueSummary(response: RecommendationListResponse): QueueSummary {
  const providedSummary = toQueueSummary(response.filtered_summary);
  if (providedSummary) {
    return providedSummary;
  }
  return summarizeQueueFromItems(response.items);
}

function safeRecommendationsErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view recommendations.";
    }
    if (error.status === 404) {
      return "Recommendation data for the selected site was not found.";
    }
  }
  return "Unable to load recommendations right now. Please try again.";
}

function safeBulkRecommendationErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to update one or more recommendations.";
    }
    if (error.status === 404) {
      return "One or more recommendations were not found in your tenant scope.";
    }
    if (error.status === 422) {
      return "One or more recommendation updates are not allowed in the current state.";
    }
  }
  return "Unable to update one or more recommendations right now. Please try again.";
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
      return "The activated action or bound automation record was not found.";
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

function RecommendationsPageContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const context = useOperatorContext();
  const [items, setItems] = useState<Recommendation[]>([]);
  const [totalRecommendations, setTotalRecommendations] = useState<number | null>(null);
  const [queueSummary, setQueueSummary] = useState<QueueSummary>(EMPTY_QUEUE_SUMMARY);
  const [automationLinkedRecommendationRunIds, setAutomationLinkedRecommendationRunIds] = useState<Set<string>>(
    () => new Set<string>(),
  );
  const [automationBindingTargetId, setAutomationBindingTargetId] = useState<string | null>(null);
  const [automationLinkageReady, setAutomationLinkageReady] = useState(false);
  const [automationInFlight, setAutomationInFlight] = useState(false);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [selectedRecommendationIds, setSelectedRecommendationIds] = useState<string[]>([]);
  const [bulkActionInFlight, setBulkActionInFlight] = useState<RecommendationActionStatus | null>(null);
  const [bulkActionSuccess, setBulkActionSuccess] = useState<string | null>(null);
  const [bulkActionError, setBulkActionError] = useState<string | null>(null);
  const [bulkActionProgress, setBulkActionProgress] = useState<BulkActionQueueProgress | null>(null);
  const [bulkRefreshNonce, setBulkRefreshNonce] = useState(0);
  const [expandedRecommendationIds, setExpandedRecommendationIds] = useState<Set<string>>(() => new Set());
  const [actionDecisionByItemId, setActionDecisionByItemId] = useState<Record<string, ActionDecision>>({});
  const [actionDecisionSavingByItemId, setActionDecisionSavingByItemId] = useState<Record<string, boolean>>({});
  const [actionDecisionErrorByItemId, setActionDecisionErrorByItemId] = useState<Record<string, string | null>>({});
  const [automationBindingPendingByActionId, setAutomationBindingPendingByActionId] = useState<Record<string, boolean>>({});
  const [automationBindingErrorByActionId, setAutomationBindingErrorByActionId] = useState<Record<string, string | null>>(
    {},
  );
  const [automationRunPendingByActionId, setAutomationRunPendingByActionId] = useState<Record<string, boolean>>({});
  const [automationRunErrorByActionId, setAutomationRunErrorByActionId] = useState<Record<string, string | null>>({});

  const filters = useMemo<FilterState>(() => {
    return {
      status: parseStatusFilter(searchParams.get("status")),
      priorityBand: parsePriorityFilter(searchParams.get("priority") || searchParams.get("priority_band")),
      category: parseCategoryFilter(searchParams.get("category")),
    };
  }, [searchParams]);
  const sort = useMemo<SortState>(() => {
    return parseSortOption(
      searchParams.get("sort"),
      searchParams.get("sort_by"),
      searchParams.get("sort_order"),
    );
  }, [searchParams]);
  const currentPage = useMemo<number>(() => parsePage(searchParams.get("page")), [searchParams]);
  const pageSize = useMemo<number>(() => parsePageSize(searchParams.get("page_size")), [searchParams]);
  const activePreset = useMemo<QueuePresetSelection>(() => {
    const matchedPreset = QUEUE_PRESETS.find((preset) => matchesPresetState(filters, sort, preset));
    return matchedPreset ? matchedPreset.key : "__custom__";
  }, [filters, sort]);
  const selectedSite = useMemo(
    () => context.sites.find((site) => site.id === context.selectedSiteId) || null,
    [context.selectedSiteId, context.sites],
  );

  const resolvedTotalRecommendations = totalRecommendations ?? 0;
  const totalPages = useMemo<number>(() => {
    if (totalRecommendations === null) {
      return currentPage;
    }
    return totalPagesFor(totalRecommendations, pageSize);
  }, [currentPage, pageSize, totalRecommendations]);
  const activePage = useMemo<number>(() => {
    if (totalRecommendations === null) {
      return currentPage;
    }
    return Math.min(currentPage, totalPages);
  }, [currentPage, totalPages, totalRecommendations]);
  const hasVisibleRows = resolvedTotalRecommendations > 0 && items.length > 0;
  const firstVisiblePosition = hasVisibleRows ? (activePage - DEFAULT_PAGE) * pageSize + 1 : 0;
  const lastVisiblePosition = hasVisibleRows ? firstVisiblePosition + items.length - 1 : 0;

  const hasActiveFilters = Boolean(filters.status || filters.priorityBand || filters.category);
  const displayedRecommendationIds = useMemo(() => items.map((item) => item.id), [items]);
  const displayedRecommendationIdSet = useMemo(() => new Set(displayedRecommendationIds), [displayedRecommendationIds]);
  const selectedCount = selectedRecommendationIds.length;
  const allDisplayedSelected =
    displayedRecommendationIds.length > 0 &&
    displayedRecommendationIds.every((id) => selectedRecommendationIds.includes(id));
  const hasInFlightActionExecution = useMemo(
    () => items.some((item) => hasInFlightLineageExecution(item.action_lineage || null)),
    [items],
  );
  const executionPollingActive = Boolean(
    hasInFlightActionExecution
    && !loadingItems
    && !context.loading
    && !context.error
    && context.selectedSiteId,
  );
  const toggleRecommendationDetails = useCallback((recommendationId: string) => {
    setExpandedRecommendationIds((previous) => {
      const next = new Set(previous);
      if (next.has(recommendationId)) {
        next.delete(recommendationId);
      } else {
        next.add(recommendationId);
      }
      return next;
    });
  }, []);
  const buildRecommendationDetailHref = useCallback((item: Recommendation): string => {
    const params = new URLSearchParams();
    params.set("site_id", item.site_id);
    if (filters.status) {
      params.set("status", filters.status);
    }
    if (filters.priorityBand) {
      params.set("priority", filters.priorityBand);
    }
    if (filters.category) {
      params.set("category", filters.category);
    }
    if (sort !== DEFAULT_SORT) {
      params.set("sort", sort);
    }
    if (activePage > DEFAULT_PAGE) {
      params.set("page", String(activePage));
    }
    if (pageSize !== DEFAULT_PAGE_SIZE) {
      params.set("page_size", String(pageSize));
    }
    return `/recommendations/${item.id}?${params.toString()}`;
  }, [activePage, filters.category, filters.priorityBand, filters.status, pageSize, sort]);
  const topReadyRecommendation = useMemo(() => {
    const openItems = items.filter((item) => recommendationIsReadyNow(item));
    if (openItems.length === 0) {
      return null;
    }
    return [...openItems].sort((left, right) => {
      if (right.priority_score !== left.priority_score) {
        return right.priority_score - left.priority_score;
      }
      return right.created_at.localeCompare(left.created_at);
    })[0] || null;
  }, [items]);
  const topAppliedRecommendation = useMemo(() => {
    const acceptedItems = items.filter((item) => item.status === "accepted");
    if (acceptedItems.length === 0) {
      return null;
    }
    return [...acceptedItems].sort((left, right) => {
      return right.updated_at.localeCompare(left.updated_at);
    })[0] || null;
  }, [items]);
  const recommendationQueueWhyNow = useMemo(() => {
    if (loadingItems) {
      return "Queue decisiveness context is still loading.";
    }
    if (topReadyRecommendation) {
      if (isHighPriority(topReadyRecommendation)) {
        return `"${topReadyRecommendation.title}" is a high-value next step and ready now.`;
      }
      return `"${topReadyRecommendation.title}" is ready now and surfaced for review before apply.`;
    }
    if (topAppliedRecommendation) {
      return `"${topAppliedRecommendation.title}" was applied and now needs visibility confirmation.`;
    }
    if (queueSummary.total > 0) {
      return "Queue has recommendations, but no top-priority ready-now action in this filter view.";
    }
    return "No recommendation items are currently available in this queue view.";
  }, [loadingItems, queueSummary.total, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueActionability = useMemo(() => {
    if (loadingItems) {
      return "Actionability is pending while queue data loads.";
    }
    if (topReadyRecommendation) {
      return "Yes. You can act now by reviewing the top ready recommendation.";
    }
    if (topAppliedRecommendation) {
      return "Not yet. Wait for visibility refresh, then validate the applied change.";
    }
    if (queueSummary.total > 0) {
      return "Review current statuses to identify the next actionable item.";
    }
    return "No immediate recommendation action is required.";
  }, [loadingItems, queueSummary.total, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueBlockingState = useMemo(() => {
    if (loadingItems) {
      return "Queue data is still loading.";
    }
    if (topReadyRecommendation) {
      return "No blocking state detected.";
    }
    if (topAppliedRecommendation) {
      return "Blocked by pending visibility timing until next refresh.";
    }
    if (queueSummary.total > 0) {
      return "No ready-now recommendation is available in this filter set.";
    }
    return "No blocking state because there are no queue items.";
  }, [loadingItems, queueSummary.total, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueEvidencePreview = useMemo(() => {
    const candidate = topReadyRecommendation || topAppliedRecommendation || items[0] || null;
    if (!candidate) {
      return "No supporting proof is available in this queue view yet.";
    }
    return deriveRecommendationEvidencePreview(candidate);
  }, [items, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueEvidenceTrust = useMemo(() => {
    const candidate = topReadyRecommendation || topAppliedRecommendation || items[0] || null;
    if (!candidate) {
      return "Support cue: no evidence signal available";
    }
    return deriveRecommendationEvidenceTrust(candidate).cue;
  }, [items, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueChoiceSupport = useMemo(() => {
    if (loadingItems) {
      return "Choice support is pending while queue data loads.";
    }
    if (topReadyRecommendation) {
      return `"${topReadyRecommendation.title}" is the best immediate move in this queue view.`;
    }
    if (topAppliedRecommendation) {
      return `"${topAppliedRecommendation.title}" is waiting on visibility confirmation.`;
    }
    if (queueSummary.total > 0) {
      return "Queue items are available but currently better deferred from immediate action.";
    }
    return "No choice-support signal is available because the queue is empty.";
  }, [loadingItems, queueSummary.total, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueLifecycleStage = useMemo(() => {
    if (loadingItems) {
      return "Lifecycle stage is pending while queue data loads.";
    }
    if (topReadyRecommendation) {
      return "Needs review / pending";
    }
    if (topAppliedRecommendation) {
      return "Applied / completed";
    }
    if (queueSummary.total > 0) {
      return "Background item / revisit later";
    }
    return "No active lifecycle stage in this queue view.";
  }, [loadingItems, queueSummary.total, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueRevisitTiming = useMemo(() => {
    if (loadingItems) {
      return "Revisit timing is pending while queue data loads.";
    }
    if (topReadyRecommendation) {
      return "Revisit now.";
    }
    if (topAppliedRecommendation) {
      return "Revisit after visibility refresh.";
    }
    if (queueSummary.total > 0) {
      return "Revisit later unless context changes.";
    }
    return "No revisit is needed for this queue view.";
  }, [loadingItems, queueSummary.total, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueFreshnessPosture = useMemo(() => {
    if (loadingItems) {
      return "Freshness posture is pending while queue data loads.";
    }
    const candidate = topReadyRecommendation || topAppliedRecommendation || items[0] || null;
    if (!candidate) {
      return "No freshness posture is available for this queue view.";
    }
    return deriveRecommendationFreshnessSupport(candidate).freshnessCue;
  }, [items, loadingItems, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueRefreshCheck = useMemo(() => {
    if (loadingItems) {
      return "Refresh check is pending while queue data loads.";
    }
    const candidate = topReadyRecommendation || topAppliedRecommendation || items[0] || null;
    if (!candidate) {
      return "No refresh check is required for this queue view.";
    }
    return deriveRecommendationFreshnessSupport(candidate).refreshCheck;
  }, [items, loadingItems, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueEffortSignal = useMemo(() => {
    const candidate = topReadyRecommendation || topAppliedRecommendation || items[0] || null;
    if (!candidate) {
      return "Effort signal unavailable.";
    }
    return deriveRecommendationEffortCue(candidate).cue;
  }, [items, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueAfterAction = useMemo(() => {
    if (loadingItems) {
      return "After-action visibility is pending while queue data loads.";
    }
    if (topReadyRecommendation) {
      return "After apply, queue status updates immediately and impact should be verified after the next refresh.";
    }
    if (topAppliedRecommendation) {
      return "After refresh, validate whether the applied change is now visible.";
    }
    if (queueSummary.total > 0) {
      return "After decision updates, queue status reflects changes immediately.";
    }
    return "No after-action step is required for the current view.";
  }, [loadingItems, queueSummary.total, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueTakeaway = useMemo(() => {
    if (loadingItems) {
      return "Recommendation queue status is still loading.";
    }
    if (topReadyRecommendation) {
      return `${queueSummary.open} recommendation${queueSummary.open === 1 ? "" : "s"} are ready for action now.`;
    }
    if (topAppliedRecommendation || queueSummary.accepted > 0) {
      return `No ready-now items in this view; ${queueSummary.accepted} recommendation${queueSummary.accepted === 1 ? "" : "s"} are already applied/completed.`;
    }
    return "No immediate recommendation action is required for the current queue filters.";
  }, [loadingItems, queueSummary.accepted, queueSummary.open, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueNextStep = useMemo(() => {
    if (topReadyRecommendation) {
      return {
        href: buildRecommendationDetailHref(topReadyRecommendation),
        label: "Open top ready recommendation",
        note: "High-value next step. Confirm rationale and decide whether to apply now.",
      };
    }
    if (topAppliedRecommendation || (queueSummary.accepted > 0 && items.length > 0)) {
      const candidateItem = topAppliedRecommendation || items[0];
      if (!candidateItem) {
        return null;
      }
      return {
        href: buildRecommendationDetailHref(candidateItem),
        label: "Review latest applied recommendation",
        note: "Waiting on visibility. Confirm downstream refresh timing and follow-up.",
      };
    }
    return {
      href: "/sites",
      label: "Open site workspace",
      note: "Run or refresh recommendations when new analysis context is available.",
    };
  }, [buildRecommendationDetailHref, items, queueSummary.accepted, topAppliedRecommendation, topReadyRecommendation]);
  const recommendationQueueFacts = useMemo<DetailFocusFact[]>(() => {
    if (loadingItems) {
      return [];
    }
    const manualFollowUpText = queueSummary.open > 0
      ? "Yes. Ready-now recommendations still need an operator decision."
      : queueSummary.accepted > 0
        ? "Yes. Validate accepted recommendation visibility after the next refresh."
        : "No immediate follow-up is required for the current view.";
    const visibilityTimingText = queueSummary.accepted > 0
      ? "Accepted items may need one refresh cycle before downstream visibility fully updates."
      : "Queue status updates immediately for this view.";

    return [
      {
        label: "Why this matters now",
        value: recommendationQueueWhyNow,
        tone: topReadyRecommendation ? "warning" : topAppliedRecommendation ? "neutral" : "neutral",
      },
      {
        label: "Current status",
        value: queueSummary.open > 0 ? "Needs review / pending" : "Applied / completed",
        tone: queueSummary.open > 0 ? "warning" : "success",
      },
      {
        label: "Lifecycle stage",
        value: recommendationQueueLifecycleStage,
        tone: topReadyRecommendation ? "warning" : topAppliedRecommendation ? "success" : "neutral",
      },
      {
        label: "Freshness posture",
        value: recommendationQueueFreshnessPosture,
        tone: topReadyRecommendation ? "success" : topAppliedRecommendation ? "warning" : "neutral",
      },
      {
        label: "Can I act now",
        value: recommendationQueueActionability,
        tone: topReadyRecommendation ? "success" : "neutral",
      },
      {
        label: "Blocking state",
        value: recommendationQueueBlockingState,
        tone: topAppliedRecommendation ? "warning" : "neutral",
      },
      {
        label: "Revisit timing",
        value: recommendationQueueRevisitTiming,
        tone: topReadyRecommendation || topAppliedRecommendation ? "warning" : "neutral",
      },
      {
        label: "Refresh check",
        value: recommendationQueueRefreshCheck,
        tone: topAppliedRecommendation ? "warning" : "neutral",
      },
      {
        label: "Choice support",
        value: recommendationQueueChoiceSupport,
        tone: topReadyRecommendation ? "warning" : "neutral",
      },
      {
        label: "Effort signal",
        value: recommendationQueueEffortSignal,
        tone: "neutral",
      },
      {
        label: "After action",
        value: recommendationQueueAfterAction,
        tone: topReadyRecommendation || topAppliedRecommendation ? "warning" : "neutral",
      },
      {
        label: "Evidence preview",
        value: recommendationQueueEvidencePreview,
        tone: "neutral",
      },
      {
        label: "Evidence trust",
        value: recommendationQueueEvidenceTrust,
        tone: "neutral",
      },
      {
        label: "What changed",
        value: bulkActionSuccess || "No recent queue status change in this session.",
        tone: bulkActionSuccess ? "success" : "neutral",
      },
      {
        label: "Manual follow-up",
        value: manualFollowUpText,
        tone: queueSummary.open > 0 || queueSummary.accepted > 0 ? "warning" : "neutral",
      },
      { label: "Expected visibility", value: visibilityTimingText, tone: queueSummary.accepted > 0 ? "warning" : "neutral" },
    ];
  }, [
    bulkActionSuccess,
    loadingItems,
    queueSummary.accepted,
    queueSummary.open,
    recommendationQueueActionability,
    recommendationQueueAfterAction,
    recommendationQueueBlockingState,
    recommendationQueueChoiceSupport,
    recommendationQueueEvidencePreview,
    recommendationQueueEffortSignal,
    recommendationQueueEvidenceTrust,
    recommendationQueueLifecycleStage,
    recommendationQueueFreshnessPosture,
    recommendationQueueRefreshCheck,
    recommendationQueueRevisitTiming,
    recommendationQueueWhyNow,
    topAppliedRecommendation,
    topReadyRecommendation,
  ]);
  const recommendationQuickScanItems = useMemo(() => items.slice(0, 6), [items]);

  function updateQueueParams(nextFilters: FilterState, nextSort: SortState) {
    const params = new URLSearchParams(searchParams.toString());
    if (nextFilters.status) {
      params.set("status", nextFilters.status);
    } else {
      params.delete("status");
    }
    if (nextFilters.priorityBand) {
      params.set("priority", nextFilters.priorityBand);
    } else {
      params.delete("priority");
    }
    params.delete("priority_band");
    if (nextFilters.category) {
      params.set("category", nextFilters.category);
    } else {
      params.delete("category");
    }
    if (nextSort === DEFAULT_SORT) {
      params.delete("sort");
    } else {
      params.set("sort", nextSort);
    }
    params.delete("preset");
    params.delete("sort_by");
    params.delete("sort_order");
    params.delete("page");
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function updateFilterParams(nextFilters: FilterState) {
    updateQueueParams(nextFilters, sort);
  }

  function updateSortParam(nextSort: SortState) {
    updateQueueParams(filters, nextSort);
  }

  function applyPreset(presetKey: QueuePresetKey) {
    const preset = QUEUE_PRESETS.find((item) => item.key === presetKey);
    if (!preset) {
      return;
    }
    updateQueueParams(preset.filters, preset.sort);
  }

  function updatePaginationParams(nextPage: number, nextPageSize: number) {
    const params = new URLSearchParams(searchParams.toString());
    if (nextPage > DEFAULT_PAGE) {
      params.set("page", String(nextPage));
    } else {
      params.delete("page");
    }
    if (nextPageSize !== DEFAULT_PAGE_SIZE) {
      params.set("page_size", String(nextPageSize));
    } else {
      params.delete("page_size");
    }
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function updatePageSizeParam(nextPageSize: number) {
    updatePaginationParams(DEFAULT_PAGE, nextPageSize);
  }

  function goToPage(nextPage: number) {
    const boundedPage = Math.min(Math.max(nextPage, DEFAULT_PAGE), totalPages);
    updatePaginationParams(boundedPage, pageSize);
  }

  function buildRecommendationRunDetailHref(item: Recommendation): string {
    const params = new URLSearchParams();
    params.set("site_id", item.site_id);
    if (filters.status) {
      params.set("status", filters.status);
    }
    if (filters.priorityBand) {
      params.set("priority", filters.priorityBand);
    }
    if (filters.category) {
      params.set("category", filters.category);
    }
    if (sort !== DEFAULT_SORT) {
      params.set("sort", sort);
    }
    if (activePage > DEFAULT_PAGE) {
      params.set("page", String(activePage));
    }
    if (pageSize !== DEFAULT_PAGE_SIZE) {
      params.set("page_size", String(pageSize));
    }
    return `/recommendations/runs/${item.recommendation_run_id}?${params.toString()}`;
  }

  function resolveRecommendationControlHref(control: ActionControl, item: Recommendation): string | undefined {
    if (control.type === "review_recommendation" || control.type === "mark_completed") {
      return buildRecommendationDetailHref(item);
    }
    if (control.type === "review_output") {
      return buildRecommendationRunDetailHref(item);
    }
    if (control.type === "run_automation" || control.type === "view_automation_status") {
      const params = new URLSearchParams();
      if (item.site_id) {
        params.set("site_id", item.site_id);
      }
      const query = params.toString();
      return query ? `/automation?${query}` : "/automation";
    }
    return undefined;
  }

  function resolveRecommendationOutputReviewHref(
    outputId: string,
    recommendation: Recommendation,
  ): string | undefined {
    if (outputId.length === 0) {
      return undefined;
    }
    return buildRecommendationRunDetailHref(recommendation);
  }

  function applyLocalActionDecision(
    actionExecutionItem: ActionExecutionItem,
  ): ActionExecutionItem {
    const decision = actionDecisionByItemId[actionExecutionItem.id];
    if (!decision) {
      return actionExecutionItem;
    }
    return applyActionDecisionLocally(actionExecutionItem, decision);
  }

  async function handleRecommendationActionDecision(
    recommendation: Recommendation,
    decision: ActionDecision,
  ): Promise<void> {
    const actionId = recommendation.id;
    setActionDecisionByItemId((current) => ({
      ...current,
      [actionId]: decision,
    }));
    setActionDecisionErrorByItemId((current) => ({
      ...current,
      [actionId]: null,
    }));

    if (decision === "deferred") {
      return;
    }

    const nextStatus: RecommendationActionStatus = decision === "accepted" ? "accepted" : "dismissed";
    setActionDecisionSavingByItemId((current) => ({
      ...current,
      [actionId]: true,
    }));
    try {
      await updateRecommendationStatus(
        context.token,
        context.businessId,
        recommendation.site_id,
        recommendation.id,
        { status: nextStatus },
      );
      setItems((currentItems) =>
        currentItems.map((item) =>
          item.id === recommendation.id
            ? {
                ...item,
                status: nextStatus,
                updated_at: new Date().toISOString(),
              }
            : item,
        ),
      );
    } catch (error) {
      setActionDecisionErrorByItemId((current) => ({
        ...current,
        [actionId]: safeBulkRecommendationErrorMessage(error),
      }));
    } finally {
      setActionDecisionSavingByItemId((current) => ({
        ...current,
        [actionId]: false,
      }));
    }
  }

  async function handleRecommendationAutomationBinding(
    recommendation: Recommendation,
    actionExecutionItemId: string,
    automationId: string,
  ): Promise<void> {
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
        recommendation.site_id,
        actionExecutionItemId,
        automationId,
      );
      setBulkRefreshNonce((current) => current + 1);
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

  async function handleRecommendationAutomationRun(
    recommendation: Recommendation,
    actionExecutionItemId: string,
  ): Promise<void> {
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
        recommendation.site_id,
        actionExecutionItemId,
      );
      setBulkRefreshNonce((current) => current + 1);
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

  function toggleRecommendationSelection(recommendationId: string) {
    setSelectedRecommendationIds((current) => {
      if (current.includes(recommendationId)) {
        return current.filter((value) => value !== recommendationId);
      }
      return [...current, recommendationId];
    });
  }

  function toggleSelectAllDisplayed(checked: boolean) {
    if (checked) {
      setSelectedRecommendationIds(displayedRecommendationIds);
      return;
    }
    setSelectedRecommendationIds([]);
  }

  async function handleBulkStatusUpdate(status: RecommendationActionStatus) {
    if (!context.selectedSiteId || selectedRecommendationIds.length === 0 || bulkActionInFlight) {
      return;
    }

    const selectedItems = items.filter((item) => selectedRecommendationIds.includes(item.id));
    if (selectedItems.length === 0) {
      return;
    }
    const selectedItemIds = selectedItems.map((item) => item.id);
    const statusFilter = filters.status;
    const baselineItems = items;
    const baselineQueueSummary = queueSummary;
    const baselineTotalRecommendations = totalRecommendations;
    const optimisticState = applyOptimisticBulkStatusToQueueState({
      baselineItems,
      baselineTotalRecommendations,
      baselineQueueSummary,
      selectedItemIds,
      nextStatus: status,
      statusFilter,
    });

    setBulkActionInFlight(status);
    setBulkActionSuccess(null);
    setBulkActionError(null);
    setBulkActionProgress({
      total: selectedItems.length,
      processed: 0,
      succeeded: 0,
      failed: 0,
    });
    setItems(optimisticState.items);
    setTotalRecommendations(optimisticState.totalRecommendations);
    setQueueSummary(optimisticState.queueSummary);
    setSelectedRecommendationIds([]);

    try {
      const queueResult = await runBoundedBulkActionQueue({
        items: selectedItems,
        concurrency: BULK_ACTION_CONCURRENCY_LIMIT,
        worker: (selectedItem) =>
          updateRecommendationStatus(context.token, context.businessId, selectedItem.site_id, selectedItem.id, {
            status,
          }),
        onProgress: (progress) => {
          setBulkActionProgress(progress);
        },
      });

      const successfulItems = queueResult.successes.map((entry) => entry.value);
      const successfulItemIds = queueResult.successes.map((entry) => entry.item.id);
      const failedItems = queueResult.failures.map((entry) => entry.item);
      const failedErrors = queueResult.failures.map((entry) => entry.error);
      const successfulCount = queueResult.succeeded;
      const failedCount = queueResult.failed;
      const reconciledState = applyOptimisticBulkStatusToQueueState({
        baselineItems,
        baselineTotalRecommendations,
        baselineQueueSummary,
        selectedItemIds: successfulItemIds,
        nextStatus: status,
        statusFilter,
      });
      const successfulItemById = new Map(successfulItems.map((item) => [item.id, item]));
      const reconciledItems = reconciledState.items.map((item) => successfulItemById.get(item.id) || item);

      setItems(reconciledItems);
      setTotalRecommendations(reconciledState.totalRecommendations);
      setQueueSummary(reconciledState.queueSummary);

      setBulkActionSuccess(
        `Bulk ${status} complete: ${successfulCount}/${queueResult.total} succeeded, ${failedCount} failed.`,
      );
      if (successfulCount > 0) {
        setBulkRefreshNonce((current) => current + 1);
      }

      if (failedCount > 0) {
        const firstError = failedErrors[0];
        const baseErrorMessage = safeBulkRecommendationErrorMessage(firstError ?? null);
        setBulkActionError(
          `${baseErrorMessage} ${failedCount} update${failedCount === 1 ? "" : "s"} failed.`,
        );
        const failedIdSet = new Set(failedItems.map((item) => item.id));
        setSelectedRecommendationIds(reconciledItems.filter((item) => failedIdSet.has(item.id)).map((item) => item.id));
      }
    } finally {
      setBulkActionInFlight(null);
      setBulkActionProgress(null);
    }
  }

  useEffect(() => {
    if (totalRecommendations === null || currentPage === activePage) {
      return;
    }
    const params = new URLSearchParams(searchParams.toString());
    if (activePage > DEFAULT_PAGE) {
      params.set("page", String(activePage));
    } else {
      params.delete("page");
    }
    if (pageSize !== DEFAULT_PAGE_SIZE) {
      params.set("page_size", String(pageSize));
    } else {
      params.delete("page_size");
    }
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [activePage, currentPage, pageSize, pathname, router, searchParams, totalRecommendations]);

  useEffect(() => {
    setSelectedRecommendationIds((current) => current.filter((id) => displayedRecommendationIdSet.has(id)));
  }, [displayedRecommendationIdSet]);

  useEffect(() => {
    if (!executionPollingActive) {
      return;
    }
    const intervalId = window.setInterval(() => {
      setBulkRefreshNonce((current) => current + 1);
    }, 4000);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [executionPollingActive]);

  useEffect(() => {
    if (context.loading || context.error || !context.selectedSiteId) {
      setItems([]);
      setTotalRecommendations(null);
      setQueueSummary(EMPTY_QUEUE_SUMMARY);
      setAutomationLinkedRecommendationRunIds(new Set<string>());
      setAutomationBindingTargetId(null);
      setAutomationLinkageReady(false);
      setAutomationInFlight(false);
      setActionDecisionByItemId({});
      setActionDecisionSavingByItemId({});
      setActionDecisionErrorByItemId({});
      setAutomationBindingPendingByActionId({});
      setAutomationBindingErrorByActionId({});
      setAutomationRunPendingByActionId({});
      setAutomationRunErrorByActionId({});
      setItemsError(null);
      setLoadingItems(false);
      setSelectedRecommendationIds([]);
      setBulkActionInFlight(null);
      setBulkActionSuccess(null);
      setBulkActionError(null);
      setBulkActionProgress(null);
      return;
    }
    let cancelled = false;
    const selectedSiteId = context.selectedSiteId;

    async function loadRecommendations() {
      setLoadingItems(true);
      setItemsError(null);
      setAutomationLinkageReady(false);
      setAutomationInFlight(false);
      setAutomationBindingTargetId(null);
      try {
        const activeFilters: RecommendationListFilters = {};
        if (filters.status) {
          activeFilters.status = filters.status;
        }
        if (filters.priorityBand) {
          activeFilters.priority_band = filters.priorityBand;
        }
        if (filters.category) {
          activeFilters.category = filters.category;
        }
        const sortConfig = mapSortToApi(sort);
        activeFilters.sort_by = sortConfig.sort_by;
        activeFilters.sort_order = sortConfig.sort_order;
        activeFilters.page = currentPage;
        activeFilters.page_size = pageSize;
        const [recommendationsResult, automationRunsResult] = await Promise.allSettled([
          fetchRecommendations(context.token, context.businessId, selectedSiteId, activeFilters),
          fetchAutomationRuns(context.token, context.businessId, selectedSiteId),
        ]);
        if (!cancelled) {
          if (recommendationsResult.status === "fulfilled") {
            setItems(recommendationsResult.value.items);
            setTotalRecommendations(recommendationsResult.value.total);
            setQueueSummary(deriveQueueSummary(recommendationsResult.value));
            setActionDecisionByItemId({});
            setActionDecisionSavingByItemId({});
            setActionDecisionErrorByItemId({});
            setAutomationBindingPendingByActionId({});
            setAutomationBindingErrorByActionId({});
            setAutomationRunPendingByActionId({});
            setAutomationRunErrorByActionId({});
          } else {
            throw recommendationsResult.reason;
          }

          if (automationRunsResult.status === "fulfilled") {
            setAutomationLinkedRecommendationRunIds(
              extractAutomationLinkedRecommendationRunIds(automationRunsResult.value.items),
            );
            setAutomationBindingTargetId(deriveAutomationBindingTargetId(automationRunsResult.value.items));
            setAutomationInFlight(
              automationRunsResult.value.items.some((run) => {
                const normalizedStatus = (run.status || "").trim().toLowerCase();
                return normalizedStatus === "queued" || normalizedStatus === "running";
              }),
            );
          } else {
            setAutomationLinkedRecommendationRunIds(new Set<string>());
            setAutomationBindingTargetId(null);
            setAutomationInFlight(false);
          }
          setAutomationLinkageReady(true);
        }
      } catch (err) {
        if (!cancelled) {
          setItemsError(safeRecommendationsErrorMessage(err));
          setQueueSummary(EMPTY_QUEUE_SUMMARY);
          setAutomationLinkedRecommendationRunIds(new Set<string>());
          setAutomationBindingTargetId(null);
          setAutomationLinkageReady(false);
          setAutomationInFlight(false);
          setActionDecisionByItemId({});
          setActionDecisionSavingByItemId({});
          setActionDecisionErrorByItemId({});
          setAutomationBindingPendingByActionId({});
          setAutomationBindingErrorByActionId({});
          setAutomationRunPendingByActionId({});
          setAutomationRunErrorByActionId({});
        }
      } finally {
        if (!cancelled) {
          setLoadingItems(false);
        }
      }
    }
    void loadRecommendations();
    return () => {
      cancelled = true;
    };
  }, [
    context.businessId,
    context.error,
    context.loading,
    context.selectedSiteId,
    context.token,
    filters.status,
    filters.priorityBand,
    filters.category,
    sort,
    currentPage,
    pageSize,
    bulkRefreshNonce,
  ]);

  if (context.loading) {
    return (
      <PageContainer width="full" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Workflow"
            subtitle="Loading recommendation queue state for your selected site."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer width="full" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Workflow"
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
      <PageContainer width="full" density="compact">
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Workflow"
            subtitle="No SEO sites are configured yet. Add a site first to view recommendations."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="full" density="compact">
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Recommendation Workflow"
            subtitle="Review priorities, update recommendation status, and keep action flow moving."
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
              label="Filtered recommendations"
              value={queueSummary.total}
              detail={hasActiveFilters ? "Current filter set" : "All statuses"}
              tone={queueSummary.total > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Ready now"
              value={queueSummary.open}
              detail="Open recommendations awaiting action"
              tone={queueSummary.open > 0 ? "success" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Applied / completed"
              value={queueSummary.accepted}
              detail="Accepted recommendations in current view"
              tone={queueSummary.accepted > 0 ? "success" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="High priority"
              value={queueSummary.highPriority}
              detail="High or critical priorities in current view"
              tone={queueSummary.highPriority > 0 ? "warning" : "neutral"}
              variant="elevated"
            />
          </div>
        </SectionCard>
      </div>

      <DetailFocusPanel
        data-testid="recommendation-queue-outcome-focus"
        title="Recommendation outcome snapshot"
        takeaway={recommendationQueueTakeaway}
        nextStep={recommendationQueueNextStep}
        facts={recommendationQueueFacts}
        detailHint="Queue controls and recommendation details below show action history, rationale, and lineage."
      />

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Recommendation queue"
          subtitle="Filter, sort, batch update, and open recommendation details."
          headingLevel={2}
          variant="support"
        />
        <label htmlFor="site-picker-recommendations">Site</label>
        <select
          id="site-picker-recommendations"
          className="operator-select"
          value={context.selectedSiteId || ""}
          onChange={(event) => context.setSelectedSiteId(event.target.value)}
        >
          {context.sites.map((site) => (
            <option key={site.id} value={site.id}>
              {site.display_name}
            </option>
          ))}
        </select>

        <div className="grid-fit-180">
          <div className="stack-tight">
          <label htmlFor="recommendation-preset">Preset</label>
          <select
            id="recommendation-preset"
            className="operator-select"
            value={activePreset}
            onChange={(event) => {
              const selectedValue = event.target.value as QueuePresetSelection;
              if (selectedValue !== "__custom__") {
                applyPreset(selectedValue);
              }
            }}
          >
            <option value="__custom__">Custom View</option>
            {QUEUE_PRESETS.map((preset) => (
              <option key={preset.key} value={preset.key}>
                {preset.label}
              </option>
            ))}
          </select>
          </div>
          <div className="stack-tight">
          <label htmlFor="recommendation-filter-status">Status</label>
          <select
            id="recommendation-filter-status"
            className="operator-select"
            value={filters.status}
            onChange={(event) =>
              updateFilterParams({
                ...filters,
                status: event.target.value as FilterState["status"],
              })
            }
          >
            {STATUS_FILTER_OPTIONS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          </div>
          <div className="stack-tight">
          <label htmlFor="recommendation-filter-priority">Priority</label>
          <select
            id="recommendation-filter-priority"
            className="operator-select"
            value={filters.priorityBand}
            onChange={(event) =>
              updateFilterParams({
                ...filters,
                priorityBand: event.target.value as FilterState["priorityBand"],
              })
            }
          >
            {PRIORITY_FILTER_OPTIONS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          </div>
          <div className="stack-tight">
          <label htmlFor="recommendation-filter-category">Category</label>
          <select
            id="recommendation-filter-category"
            className="operator-select"
            value={filters.category}
            onChange={(event) =>
              updateFilterParams({
                ...filters,
                category: event.target.value as FilterState["category"],
              })
            }
          >
            {CATEGORY_FILTER_OPTIONS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          </div>
          <div className="stack-tight">
          <label htmlFor="recommendation-sort">Sort</label>
          <select
            id="recommendation-sort"
            className="operator-select"
            value={sort}
            onChange={(event) => updateSortParam(event.target.value as SortState)}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          </div>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => updateFilterParams(DEFAULT_FILTERS)}
            disabled={loadingItems || !hasActiveFilters}
          >
            Clear Filters
          </button>
        </div>

        <div className="grid-fit-120">
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">Total Filtered</span>
          <strong>{queueSummary.total}</strong>
          </div>
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">Open</span>
          <strong>{queueSummary.open}</strong>
          </div>
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">Accepted</span>
          <strong>{queueSummary.accepted}</strong>
          </div>
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">Dismissed</span>
          <strong>{queueSummary.dismissed}</strong>
          </div>
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">High Priority</span>
          <strong>{queueSummary.highPriority}</strong>
          </div>
        </div>
        <p className="hint muted">Summary cards reflect all filtered results across pages.</p>

        <div className="stack" data-testid="recommendation-quick-scan">
          <h3 className="heading-reset">Queue quick scan</h3>
          <p className="hint muted">
            Summary-first cards show what each recommendation is, its current readiness, and the best next action.
          </p>
          {recommendationQuickScanItems.length === 0 && !loadingItems ? (
            <p className="hint muted">No recommendation items available for quick scan.</p>
          ) : null}
          {recommendationQuickScanItems.length > 0 ? (
            <div className="operational-item-list">
              {recommendationQuickScanItems.map((item) => {
                const decisiveness = deriveRecommendationDecisiveness(item, topReadyRecommendation?.id || null);
                const automationOriginCue = deriveRecommendationAutomationOriginCue(
                  item,
                  automationLinkedRecommendationRunIds,
                  automationLinkageReady,
                );
                const actionStateCue = deriveRecommendationOperatorActionState({
                  status: item.status,
                  automationLinkedOutput: automationLinkedRecommendationRunIds.has(item.recommendation_run_id),
                  automationContextAvailable: automationLinkageReady,
                });
                const actionExecutionItem = deriveRecommendationActionExecutionItem({
                  item,
                  actionStateCode: actionStateCue.code,
                  automationLinkedOutput: automationLinkedRecommendationRunIds.has(item.recommendation_run_id),
                  automationContextAvailable: automationLinkageReady,
                  automationInFlight,
                });
                const effectiveActionExecutionItem = applyLocalActionDecision(actionExecutionItem);
                const actionPresentation = deriveActionStatePresentation({
                  item: effectiveActionExecutionItem,
                  fallbackLabel: actionStateCue.label,
                  fallbackBadgeClass: actionStateCue.badgeClass,
                  fallbackOutcome: actionStateCue.outcome,
                  fallbackNextStep: actionStateCue.nextStep,
                });
                const actionControls = deriveActionControls(effectiveActionExecutionItem);
                const showBlockerBadge =
                  decisiveness.blockerCue.trim().length > 0 && decisiveness.blockerCue !== "No blocker";
                return (
                  <OperationalItemCard
                    key={`quick-scan-${item.id}`}
                    data-testid={`recommendation-quick-scan-item-${item.id}`}
                    title={`Queue item: ${item.title}`}
                    identity={<code>{item.id}</code>}
                    chips={(
                      <>
                        <span className={actionPresentation.badgeClass}>{actionPresentation.label}</span>
                        <span className={`badge ${decisiveness.actionabilityTone}`}>
                          {decisiveness.actionabilityCue}
                        </span>
                        <span className={`badge ${decisiveness.effortCueTone}`}>{decisiveness.effortCue}</span>
                        {showBlockerBadge ? (
                          <span className={`badge ${decisiveness.blockerCueTone}`}>{decisiveness.blockerCue}</span>
                        ) : null}
                      </>
                    )}
                    summary={
                      <span>
                        <span className="text-strong">Why now:</span> {truncateRecommendationWhyNow(decisiveness.whyNow)}
                      </span>
                    }
                    primaryAction={
                      <ActionControls
                        controls={actionControls}
                        resolveHref={(control) => resolveRecommendationControlHref(control, item)}
                        data-testid={`recommendation-action-controls-${item.id}`}
                      />
                    }
                    secondaryMeta={
                      <>
                        <span className="badge badge-muted">{item.status}</span>
                        <span className="badge badge-muted">{item.priority_band}</span>
                        <span className="badge badge-muted">{deriveSourceType(item)}</span>
                        <span className={`badge ${automationOriginCue.badgeClass}`}>{automationOriginCue.label}</span>
                      </>
                    }
                    expandedDetail={
                      <>
                        <p className="hint muted">
                          <span className="text-strong">Action state:</span> {actionPresentation.outcome}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Next step:</span> {actionPresentation.nextStep}
                        </p>
                        <OutputReview
                          item={effectiveActionExecutionItem}
                          stateLabel={actionPresentation.label}
                          stateBadgeClass={actionPresentation.badgeClass}
                          outcome={actionPresentation.outcome}
                          nextStep={actionPresentation.nextStep}
                          onDecision={(decision) => {
                            void handleRecommendationActionDecision(item, decision);
                          }}
                          onBindAutomation={(actionExecutionItemId, automationId) =>
                            handleRecommendationAutomationBinding(item, actionExecutionItemId, automationId)
                          }
                          onRunAutomation={(actionExecutionItemId) =>
                            handleRecommendationAutomationRun(item, actionExecutionItemId)
                          }
                          bindAutomationTargetId={automationBindingTargetId}
                          bindAutomationPendingByActionId={automationBindingPendingByActionId}
                          bindAutomationErrorByActionId={automationBindingErrorByActionId}
                          runAutomationPendingByActionId={automationRunPendingByActionId}
                          runAutomationErrorByActionId={automationRunErrorByActionId}
                          decisionPending={Boolean(actionDecisionSavingByItemId[item.id])}
                          decisionError={actionDecisionErrorByItemId[item.id]}
                          resolveOutputHref={(outputId) => resolveRecommendationOutputReviewHref(outputId, item)}
                          data-testid={`recommendation-output-review-${item.id}`}
                        />
                        <p className="hint muted">
                          <span className="text-strong">Blocking:</span> {decisiveness.blockingState}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">After action:</span> {decisiveness.afterAction}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Evidence:</span> {decisiveness.evidencePreview}
                        </p>
                        <p className="hint muted">
                          <span className={`badge ${decisiveness.evidenceTrustTone}`}>
                            {decisiveness.evidenceTrustCue}
                          </span>
                        </p>
                      </>
                    }
                  />
                );
              })}
            </div>
          ) : null}
        </div>

        <div className="row-wrap-end">
          <div className="stack-tight min-width-140">
          <label htmlFor="recommendation-page-size">Results per page</label>
          <select
            id="recommendation-page-size"
            className="operator-select"
            value={pageSize}
            onChange={(event) => updatePageSizeParam(Number.parseInt(event.target.value, 10))}
          >
            {PAGE_SIZE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          </div>
          <div className="row-wrap-tight">
          <button
            type="button"
            className="button button-secondary button-inline"
            onClick={() => goToPage(activePage - 1)}
            disabled={loadingItems || activePage <= DEFAULT_PAGE}
          >
            Previous
          </button>
          <span className="hint muted">
            Page {activePage} of {totalPages}
          </span>
          <button
            type="button"
            className="button button-secondary button-inline"
            onClick={() => goToPage(activePage + 1)}
            disabled={loadingItems || activePage >= totalPages}
          >
            Next
          </button>
          </div>
          <span className="hint muted push-right">
          Showing {firstVisiblePosition}-{lastVisiblePosition} of {resolvedTotalRecommendations}
          </span>
        </div>

        {loadingItems ? <p className="hint muted">Loading recommendations...</p> : null}
        {itemsError ? <p className="hint error">{itemsError}</p> : null}
        {bulkActionSuccess ? <p className="hint">{bulkActionSuccess}</p> : null}
        {bulkActionError ? <p className="hint error">{bulkActionError}</p> : null}
        {bulkActionProgress ? (
          <p className="hint muted" data-testid="bulk-action-progress">
            Processing {bulkActionProgress.processed}/{bulkActionProgress.total} • {bulkActionProgress.succeeded} succeeded •{" "}
            {bulkActionProgress.failed} failed
          </p>
        ) : null}
        {executionPollingActive ? (
          <p className="hint muted" data-testid="recommendation-execution-polling-status">
            Automation execution is in progress. Status refreshes automatically every few seconds.
          </p>
        ) : null}

        <div className="row-wrap-tight">
          <button
            type="button"
            className="button button-primary"
            disabled={selectedCount === 0 || bulkActionInFlight !== null}
            onClick={() => {
              void handleBulkStatusUpdate("accepted");
            }}
          >
            {bulkActionInFlight === "accepted" ? "Applying..." : "Accept Selected"}
          </button>
          <button
            type="button"
            className="button button-secondary"
            disabled={selectedCount === 0 || bulkActionInFlight !== null}
            onClick={() => {
              void handleBulkStatusUpdate("dismissed");
            }}
          >
            {bulkActionInFlight === "dismissed" ? "Applying..." : "Dismiss Selected"}
          </button>
          <span className="hint muted">{selectedCount} selected on this page</span>
        </div>

        <div className="table-container">
          <table className="table table-dense">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label="Select all displayed recommendations"
                    checked={allDisplayedSelected}
                    onChange={(event) => toggleSelectAllDisplayed(event.target.checked)}
                    disabled={items.length === 0 || bulkActionInFlight !== null}
                  />
                </th>
                <th>Title</th>
                <th>Summary</th>
                <th>Status</th>
                <th>Decisiveness</th>
                <th>Category</th>
                <th>Priority</th>
                <th>Source</th>
                <th>Recommendation Run</th>
                <th>Business</th>
                <th>Site</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const decisiveness = deriveRecommendationDecisiveness(item, topReadyRecommendation?.id || null);
                const automationOriginCue = deriveRecommendationAutomationOriginCue(
                  item,
                  automationLinkedRecommendationRunIds,
                  automationLinkageReady,
                );
                const actionStateCue = deriveRecommendationOperatorActionState({
                  status: item.status,
                  automationLinkedOutput: automationLinkedRecommendationRunIds.has(item.recommendation_run_id),
                  automationContextAvailable: automationLinkageReady,
                });
                const actionExecutionItem = deriveRecommendationActionExecutionItem({
                  item,
                  actionStateCode: actionStateCue.code,
                  automationLinkedOutput: automationLinkedRecommendationRunIds.has(item.recommendation_run_id),
                  automationContextAvailable: automationLinkageReady,
                  automationInFlight,
                });
                const effectiveActionExecutionItem = applyLocalActionDecision(actionExecutionItem);
                const actionPresentation = deriveActionStatePresentation({
                  item: effectiveActionExecutionItem,
                  fallbackLabel: actionStateCue.label,
                  fallbackBadgeClass: actionStateCue.badgeClass,
                  fallbackOutcome: actionStateCue.outcome,
                  fallbackNextStep: actionStateCue.nextStep,
                });
                const actionControls = deriveActionControls(effectiveActionExecutionItem);
                const isExpanded = expandedRecommendationIds.has(item.id);
                const detailsId = `recommendation-details-${item.id}`;
                const showBlockerBadge = decisiveness.blockerCue.trim().length > 0 && decisiveness.blockerCue !== "No blocker";
                return (
                  <Fragment key={item.id}>
                    <tr
                      role="link"
                      tabIndex={0}
                      className="clickable-row"
                      onClick={() => router.push(buildRecommendationDetailHref(item))}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          router.push(buildRecommendationDetailHref(item));
                        }
                      }}
                    >
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Select recommendation ${item.id}`}
                          checked={selectedRecommendationIds.includes(item.id)}
                          disabled={bulkActionInFlight !== null}
                          onClick={(event) => event.stopPropagation()}
                          onKeyDown={(event) => event.stopPropagation()}
                          onChange={() => toggleRecommendationSelection(item.id)}
                        />
                      </td>
                      <td>{item.title}</td>
                      <td>{item.rationale}</td>
                      <td>{item.status}</td>
                      <td data-testid={`recommendation-decisiveness-${item.id}`}>
                        <div className="recommendation-decisiveness">
                          <div className="recommendation-decisiveness-badge-row">
                            <div className="recommendation-decisiveness-badges recommendation-decisiveness-badges-primary">
                              <span className={actionPresentation.badgeClass}>{actionPresentation.label}</span>
                              <span className={`badge ${decisiveness.actionabilityTone}`}>{decisiveness.actionabilityCue}</span>
                              <span className={`badge ${decisiveness.effortCueTone}`}>{decisiveness.effortCue}</span>
                            </div>
                            {showBlockerBadge ? (
                              <div className="recommendation-decisiveness-badges recommendation-decisiveness-badges-blocker">
                                <span className={`badge ${decisiveness.blockerCueTone}`}>{decisiveness.blockerCue}</span>
                              </div>
                            ) : null}
                          </div>
                          <p className="hint muted recommendation-decisiveness-why-now">
                            <span className="text-strong">Why now:</span> {truncateRecommendationWhyNow(decisiveness.whyNow)}
                          </p>
                          <button
                            type="button"
                            className="button button-tertiary button-inline recommendation-decisiveness-toggle"
                            aria-expanded={isExpanded}
                            aria-controls={detailsId}
                            onClick={(event) => {
                              event.stopPropagation();
                              toggleRecommendationDetails(item.id);
                            }}
                            onKeyDown={(event) => event.stopPropagation()}
                          >
                            {isExpanded ? "Hide details" : "View details"}
                          </button>
                        </div>
                      </td>
                      <td>{item.category}</td>
                      <td>
                        {item.priority_score} ({item.priority_band})
                      </td>
                      <td>{deriveSourceType(item)}</td>
                      <td>
                        <Link
                          href={buildRecommendationRunDetailHref(item)}
                          onClick={(event) => event.stopPropagation()}
                          onKeyDown={(event) => event.stopPropagation()}
                        >
                          <code>{item.recommendation_run_id}</code>
                        </Link>
                        <p className="hint muted" data-testid={`recommendation-automation-origin-${item.id}`}>
                          {automationOriginCue.label}
                        </p>
                      </td>
                      <td>{item.business_id}</td>
                      <td>{item.site_id}</td>
                    </tr>
                    {isExpanded ? (
                      <tr className="table-expanded-row" data-testid={`recommendation-decisiveness-detail-row-${item.id}`}>
                        <td colSpan={11}>
                          <div
                            id={detailsId}
                            className="table-expanded-panel recommendation-decisiveness-details"
                            data-testid={`recommendation-decisiveness-detail-panel-${item.id}`}
                          >
                            <p className="hint muted">
                              <span className="text-strong">Action state:</span> {actionPresentation.outcome}
                            </p>
                            <p className="hint muted">
                              <span className="text-strong">Next step:</span> {actionPresentation.nextStep}
                            </p>
                            <ActionControls
                              controls={actionControls}
                              resolveHref={(control) => resolveRecommendationControlHref(control, item)}
                              data-testid={`recommendation-expanded-action-controls-${item.id}`}
                            />
                            <OutputReview
                              item={effectiveActionExecutionItem}
                              stateLabel={actionPresentation.label}
                              stateBadgeClass={actionPresentation.badgeClass}
                              outcome={actionPresentation.outcome}
                              nextStep={actionPresentation.nextStep}
                              onDecision={(decision) => {
                                void handleRecommendationActionDecision(item, decision);
                              }}
                              onBindAutomation={(actionExecutionItemId, automationId) =>
                                handleRecommendationAutomationBinding(item, actionExecutionItemId, automationId)
                              }
                              onRunAutomation={(actionExecutionItemId) =>
                                handleRecommendationAutomationRun(item, actionExecutionItemId)
                              }
                              bindAutomationTargetId={automationBindingTargetId}
                              bindAutomationPendingByActionId={automationBindingPendingByActionId}
                              bindAutomationErrorByActionId={automationBindingErrorByActionId}
                              runAutomationPendingByActionId={automationRunPendingByActionId}
                              runAutomationErrorByActionId={automationRunErrorByActionId}
                              decisionPending={Boolean(actionDecisionSavingByItemId[item.id])}
                              decisionError={actionDecisionErrorByItemId[item.id]}
                              resolveOutputHref={(outputId) => resolveRecommendationOutputReviewHref(outputId, item)}
                              data-testid={`recommendation-expanded-output-review-${item.id}`}
                            />
                            <p className="hint muted">
                              <span className="text-strong">Priority:</span>{" "}
                              <span className={`badge ${decisiveness.priorityCueTone}`}>{decisiveness.priorityCue}</span>
                            </p>
                            <p className="hint muted">
                              <span className="text-strong">Choice support:</span>{" "}
                              <span className={`badge ${decisiveness.choiceCueTone}`}>{decisiveness.choiceCue}</span>
                            </p>
                            <p className="hint muted">
                              <span className="text-strong">Lifecycle:</span>{" "}
                              <span className={`badge ${decisiveness.lifecycleCueTone}`}>{decisiveness.lifecycleCue}</span>
                            </p>
                            <p className="hint muted">
                              <span className="text-strong">Freshness:</span>{" "}
                              <span className={`badge ${decisiveness.freshnessCueTone}`}>{decisiveness.freshnessCue}</span>{" "}
                              {decisiveness.refreshCheck}
                            </p>
                            <p className="hint muted">
                              <span className="text-strong">Why now:</span> {decisiveness.whyNow}
                            </p>
                            <p className="hint muted">
                              <span className="text-strong">Blocking:</span> {decisiveness.blockingState}
                            </p>
                            <p className="hint muted">
                              <span className="text-strong">After action:</span> {decisiveness.afterAction}
                            </p>
                            <p className="hint muted">
                              <span className="text-strong">Evidence:</span> {decisiveness.evidencePreview}
                            </p>
                            <p className="hint muted">
                              <span className={`badge ${decisiveness.evidenceTrustTone}`}>{decisiveness.evidenceTrustCue}</span>
                            </p>
                            <p className="hint muted">
                              <span className="text-strong">Revisit:</span>{" "}
                              <span className={`badge ${decisiveness.revisitCueTone}`}>{decisiveness.revisitCue}</span>
                            </p>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
              {items.length === 0 && !loadingItems ? (
                <tr>
                  <td colSpan={11}>
                    {hasActiveFilters
                      ? "No recommendations match the current filters."
                      : "No recommendations found for this site."}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </PageContainer>
  );
}

export default function RecommendationsPage() {
  return (
    <Suspense
      fallback={
        <PageContainer width="full" density="compact">
          <SectionCard as="div" variant="support" className="role-surface-support">
            <SectionHeader
              title="Recommendation Workflow"
              subtitle="Loading recommendation queue state for your selected site."
              headingLevel={1}
              variant="support"
            />
          </SectionCard>
        </PageContainer>
      }
    >
      <RecommendationsPageContent />
    </Suspense>
  );
}
