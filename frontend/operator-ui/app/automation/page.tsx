"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ActionControls } from "../../components/action-execution/ActionControls";
import { OutputReview } from "../../components/action-execution/OutputReview";
import { useAuth } from "../../components/AuthProvider";
import { OperationalItemCard } from "../../components/layout/OperationalItemCard";
import { PageContainer } from "../../components/layout/PageContainer";
import {
  OperatorPageHero,
  OperatorPageSectionStack,
} from "../../components/layout/OperatorPageSurface";
import { OperatorRouteSupportState } from "../../components/layout/OperatorRouteSupportState";
import { RouteActionCluster } from "../../components/layout/RouteActionCluster";
import { SectionStatusItem, SectionStatusStrip } from "../../components/layout/SectionStatusStrip";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { WorkspaceActionBar } from "../../components/layout/WorkspaceActionBar";
import { WorkspaceEmptyStateCard } from "../../components/layout/WorkspaceEmptyStateCard";
import { WorkspaceMessageStack } from "../../components/layout/WorkspaceMessageStack";
import { WorkspaceMetadataGrid, WorkspaceMetadataItem } from "../../components/layout/WorkspaceMetadataGrid";
import { WorkspaceTableShell } from "../../components/layout/WorkspaceTableShell";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  ApiRequestError,
  createAutomationRun,
  fetchAutomationRuns,
  fetchAutomationStatus,
  patchAutomationConfig,
} from "../../lib/api/client";
import { deriveAutomationRunOperatorActionState } from "../../lib/operatorActionState";
import {
  applyActionDecisionLocally,
  deriveActionControls,
  deriveActionStatePresentation,
} from "../../lib/transforms/actionExecution";
import type {
  ActionControl,
  ActionDecision,
  ActionExecutionItem,
  AutomationConfig,
  AutomationConfigPatchRequest,
  AutomationRun,
  AutomationRunOutcomeSummary,
  AutomationRunStep,
} from "../../lib/api/types";

const AUTOMATION_STEP_LABELS: Record<string, string> = {
  audit_run: "Audit run",
  audit_summary: "Audit summary",
  competitor_snapshot_run: "Competitor snapshot",
  comparison_run: "Competitor comparison",
  competitor_summary: "Competitor summary",
  recommendation_run: "Recommendation run",
  recommendation_narrative: "Recommendation narrative",
};

type AutomationCompletenessSignal = {
  label: "Complete" | "Complete (limited)" | "Partial";
  badgeClass: "badge-success" | "badge-warn";
  hint: string | null;
};

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

type AutomationEditableStepField =
  | "trigger_audit"
  | "trigger_audit_summary"
  | "trigger_competitor_snapshot"
  | "trigger_comparison"
  | "trigger_competitor_summary"
  | "trigger_recommendations"
  | "trigger_recommendation_narrative";

type AutomationConfigStepDefinition = {
  field: AutomationEditableStepField;
  label: string;
  helperText: string;
};

type AutomationConfigStepGroup = {
  id: string;
  label: string;
  description: string;
  dependencyNote: string | null;
  fields: AutomationEditableStepField[];
};

const AUTOMATION_CONFIG_STEP_DEFINITIONS: Record<AutomationEditableStepField, AutomationConfigStepDefinition> = {
  trigger_audit: {
    field: "trigger_audit",
    label: "Audit run",
    helperText:
      "Creates the crawl + issue dataset. Keep enabled for full site health checks; disable for quick output refreshes.",
  },
  trigger_audit_summary: {
    field: "trigger_audit_summary",
    label: "Audit summary",
    helperText:
      "Builds the plain-language audit summary. Keep enabled when operators need concise issue rollups.",
  },
  trigger_competitor_snapshot: {
    field: "trigger_competitor_snapshot",
    label: "Competitor snapshot",
    helperText:
      "Collects competitor baseline inputs. Disable when competitor analysis is intentionally out of scope.",
  },
  trigger_comparison: {
    field: "trigger_comparison",
    label: "Competitor comparison",
    helperText:
      "Compares your site against snapshot output. Most useful when competitor snapshot is enabled.",
  },
  trigger_competitor_summary: {
    field: "trigger_competitor_summary",
    label: "Competitor summary",
    helperText:
      "Summarizes competitor comparison findings for operators. Disable if you only need raw comparison output.",
  },
  trigger_recommendations: {
    field: "trigger_recommendations",
    label: "Recommendation run",
    helperText:
      "Generates structured recommendation outputs. Keep enabled for recommendation-driven workflows.",
  },
  trigger_recommendation_narrative: {
    field: "trigger_recommendation_narrative",
    label: "Recommendation narrative",
    helperText:
      "Generates narrative guidance from recommendation output. Disable when structured recommendation data is enough.",
  },
};

const AUTOMATION_EDITABLE_STEP_FIELDS: Array<{ field: AutomationEditableStepField; label: string }> = [
  { field: "trigger_audit", label: AUTOMATION_CONFIG_STEP_DEFINITIONS.trigger_audit.label },
  { field: "trigger_audit_summary", label: AUTOMATION_CONFIG_STEP_DEFINITIONS.trigger_audit_summary.label },
  {
    field: "trigger_competitor_snapshot",
    label: AUTOMATION_CONFIG_STEP_DEFINITIONS.trigger_competitor_snapshot.label,
  },
  { field: "trigger_comparison", label: AUTOMATION_CONFIG_STEP_DEFINITIONS.trigger_comparison.label },
  {
    field: "trigger_competitor_summary",
    label: AUTOMATION_CONFIG_STEP_DEFINITIONS.trigger_competitor_summary.label,
  },
  { field: "trigger_recommendations", label: AUTOMATION_CONFIG_STEP_DEFINITIONS.trigger_recommendations.label },
  {
    field: "trigger_recommendation_narrative",
    label: AUTOMATION_CONFIG_STEP_DEFINITIONS.trigger_recommendation_narrative.label,
  },
];

const AUTOMATION_CONFIG_STEP_GROUPS: AutomationConfigStepGroup[] = [
  {
    id: "site-audit",
    label: "Site audit",
    description: "Crawl, issue detection, and audit summary outputs.",
    dependencyNote: "Audit summary is most useful when Audit run is enabled.",
    fields: ["trigger_audit", "trigger_audit_summary"],
  },
  {
    id: "competitor-analysis",
    label: "Competitor analysis",
    description: "Competitor snapshot, comparison, and summary outputs.",
    dependencyNote: "Competitor comparison and summary rely on competitor snapshot output.",
    fields: ["trigger_competitor_snapshot", "trigger_comparison", "trigger_competitor_summary"],
  },
  {
    id: "recommendations",
    label: "Recommendations",
    description: "Recommendation outputs and narrative guidance.",
    dependencyNote: "Recommendation narrative is most useful when Recommendation run is enabled.",
    fields: ["trigger_recommendations", "trigger_recommendation_narrative"],
  },
];

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

function normalizeAutomationRunSteps(run: AutomationRun): AutomationRunStep[] {
  if (!Array.isArray(run.steps_json)) {
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

function normalizeStatusValue(status: string | null | undefined): string {
  return (status || "").trim().toLowerCase();
}

function hasCompetitorDependencyReason(reason: string | null | undefined): boolean {
  const normalizedReason = (reason || "").trim().toLowerCase();
  if (!normalizedReason) {
    return false;
  }
  return COMPETITOR_DEPENDENCY_TERMS.some((term) => normalizedReason.includes(term));
}

function deriveAutomationConfigSourceLabel(config: AutomationConfig | null): string {
  if (!config) {
    return "Unknown configuration source";
  }
  if (config.config_source === "default") {
    return "Default system configuration";
  }
  if (config.config_source === "site") {
    return "Site-specific configuration";
  }
  return "Unknown configuration source";
}

function isStepDisabledByAutomationConfig(step: AutomationRunStep): boolean {
  const reason = (step.reason_summary || step.error_message || "").trim().toLowerCase();
  if (!reason) {
    return false;
  }
  return reason.includes("disabled in automation configuration") || reason.includes("disabled by config");
}

type AutomationConfigStepDraft = Record<AutomationEditableStepField, boolean>;

function extractAutomationConfigStepDraft(config: AutomationConfig | null): AutomationConfigStepDraft | null {
  if (!config) {
    return null;
  }
  return {
    trigger_audit: config.trigger_audit,
    trigger_audit_summary: config.trigger_audit_summary,
    trigger_competitor_snapshot: config.trigger_competitor_snapshot,
    trigger_comparison: config.trigger_comparison,
    trigger_competitor_summary: config.trigger_competitor_summary,
    trigger_recommendations: config.trigger_recommendations,
    trigger_recommendation_narrative: config.trigger_recommendation_narrative,
  };
}

function buildAutomationConfigPatchPayload(
  current: AutomationConfig | null,
  draft: AutomationConfigStepDraft | null,
): AutomationConfigPatchRequest {
  if (!current || !draft) {
    return {};
  }
  const payload: AutomationConfigPatchRequest = {};
  for (const definition of AUTOMATION_EDITABLE_STEP_FIELDS) {
    const field = definition.field;
    if (current[field] !== draft[field]) {
      payload[field] = draft[field];
    }
  }
  return payload;
}

function mapAutomationConfigSaveError(error: ApiRequestError): string {
  if (error.status === 404) {
    return "Automation configuration is unavailable for this site right now.";
  }
  if (error.status === 422) {
    return "Unable to save settings. Keep at least one automation step enabled.";
  }
  return "Unable to save automation settings right now.";
}

function describeAutomationConfigStepState(enabled: boolean | null): string {
  if (enabled === null) {
    return "unknown";
  }
  return enabled ? "enabled" : "disabled";
}

function deriveAutomationCompletenessSignal(
  run: AutomationRun,
  steps: AutomationRunStep[],
  summary: AutomationRunOutcomeSummary | null,
): AutomationCompletenessSignal | null {
  const normalizedStatus = normalizeStatusValue(run.status);
  if (normalizedStatus !== "completed" && normalizedStatus !== "failed") {
    return null;
  }

  const hasCompetitorDependencyGap = steps.some((step) => {
    const status = normalizeStatusValue(step.status);
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
    if (normalizeStatusValue(step.status) !== "completed") {
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

function automationStatusBadgeClass(status: string | null | undefined): string {
  const normalized = normalizeStatusValue(status);
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

function formatAutomationStepName(stepName: string): string {
  return AUTOMATION_STEP_LABELS[stepName] || stepName.replace(/_/g, " ");
}

function findAutomationRecommendationRunOutputId(steps: AutomationRunStep[]): string | null {
  const recommendationRunStep = steps.find(
    (step) => normalizeStatusValue(step.status) === "completed" && step.step_name === "recommendation_run" && step.linked_output_id,
  );
  return recommendationRunStep?.linked_output_id || null;
}

function findAutomationRecommendationNarrativeOutputId(steps: AutomationRunStep[]): string | null {
  const recommendationNarrativeStep = steps.find(
    (step) =>
      normalizeStatusValue(step.status) === "completed"
      && step.step_name === "recommendation_narrative"
      && step.linked_output_id,
  );
  return recommendationNarrativeStep?.linked_output_id || null;
}

function buildAutomationRecommendationRunHref(recommendationRunId: string, siteId: string): string {
  const params = new URLSearchParams();
  if (siteId.trim().length > 0) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query ? `/recommendations/runs/${recommendationRunId}?${query}` : `/recommendations/runs/${recommendationRunId}`;
}

function buildAutomationRecommendationNarrativeHref(
  recommendationRunId: string,
  recommendationNarrativeId: string,
  siteId: string,
): string {
  const params = new URLSearchParams();
  if (siteId.trim().length > 0) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query
    ? `/recommendations/runs/${recommendationRunId}/narratives/${recommendationNarrativeId}?${query}`
    : `/recommendations/runs/${recommendationRunId}/narratives/${recommendationNarrativeId}`;
}

function buildAutomationStatusHref(siteId: string): string {
  const params = new URLSearchParams();
  if (siteId.trim().length > 0) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query ? `/automation?${query}` : "/automation";
}

function buildRecommendationsHref(siteId: string): string {
  const params = new URLSearchParams();
  if (siteId.trim().length > 0) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query ? `/recommendations?${query}` : "/recommendations";
}

function buildCompetitorsHref(siteId: string): string {
  const params = new URLSearchParams();
  if (siteId.trim().length > 0) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query ? `/competitors?${query}` : "/competitors";
}

type AutomationTriggerContext = {
  siteId: string | null;
  recommendationId: string | null;
  recommendationTitle: string | null;
};

function readAutomationTriggerContextFromLocation(): AutomationTriggerContext {
  if (typeof window === "undefined") {
    return {
      siteId: null,
      recommendationId: null,
      recommendationTitle: null,
    };
  }
  const params = new URLSearchParams(window.location.search);
  const siteId = (params.get("site_id") || "").trim();
  const recommendationId = (params.get("recommendation_id") || "").trim();
  const recommendationTitle = (params.get("recommendation_title") || "").trim();
  return {
    siteId: siteId.length > 0 ? siteId : null,
    recommendationId: recommendationId.length > 0 ? recommendationId : null,
    recommendationTitle: recommendationTitle.length > 0 ? recommendationTitle : null,
  };
}

function sortAutomationRunsNewestFirst(items: AutomationRun[]): AutomationRun[] {
  return [...items].sort((left, right) => {
    const leftTime = Date.parse(left.created_at || left.started_at || "");
    const rightTime = Date.parse(right.created_at || right.started_at || "");
    if (Number.isNaN(leftTime) || Number.isNaN(rightTime)) {
      return right.id.localeCompare(left.id);
    }
    return rightTime - leftTime;
  });
}

function deriveAutomationActionExecutionItem(params: {
  run: AutomationRun;
  recommendationRunOutputId: string | null;
  recommendationNarrativeOutputId: string | null;
}): ActionExecutionItem {
  const { run, recommendationRunOutputId, recommendationNarrativeOutputId } = params;
  const normalizedStatus = normalizeStatusValue(run.status);
  const steps = normalizeAutomationRunSteps(run);
  return {
    id: run.id,
    title: `Automation run ${run.id}`,
    actionStateCode: deriveAutomationRunOperatorActionState({
      runStatus: run.status,
      hasRecommendationOutput: Boolean(recommendationRunOutputId),
      hasNarrativeOutput: Boolean(recommendationNarrativeOutputId),
    }).code,
    linkedOutputId: recommendationRunOutputId,
    linkedNarrativeId: recommendationNarrativeOutputId,
    automationAvailable: true,
    automationInFlight: normalizedStatus === "queued" || normalizedStatus === "running",
    blockedReason:
      normalizedStatus === "failed"
        ? "Automation failed before linked outputs completed."
        : undefined,
    triggerSource: run.trigger_source,
    outputReview: recommendationRunOutputId || recommendationNarrativeOutputId
      ? {
          outputId: recommendationRunOutputId || recommendationNarrativeOutputId,
          summary: summarizeAutomationRunOutcome(run),
          details: summarizeAutomationRunNextStep(run),
          sourceLabel: "Automation output",
          stepDetails: steps.map((step) => ({
            stepName: formatAutomationStepName(step.step_name),
            status: step.status,
            reasonSummary: summarizeAutomationStepReason(step),
            pagesAnalyzedCount: step.pages_analyzed_count ?? null,
            issuesFoundCount: step.issues_found_count ?? null,
            recommendationsGeneratedCount: step.recommendations_generated_count ?? null,
          })),
        }
      : undefined,
  };
}

function resolveAutomationControlHref(
  control: ActionControl,
  run: AutomationRun,
  recommendationRunOutputId: string | null,
  recommendationNarrativeOutputId: string | null,
): string | undefined {
  if (control.type === "review_output" || control.type === "review_recommendation" || control.type === "mark_completed") {
    if (recommendationRunOutputId) {
      return buildAutomationRecommendationRunHref(recommendationRunOutputId, run.site_id);
    }
    return "/recommendations";
  }
  if (control.type === "run_automation" || control.type === "view_automation_status") {
    return buildAutomationStatusHref(run.site_id);
  }
  if (control.type === "blocked" && recommendationNarrativeOutputId && recommendationRunOutputId) {
    return buildAutomationRecommendationNarrativeHref(
      recommendationRunOutputId,
      recommendationNarrativeOutputId,
      run.site_id,
    );
  }
  return undefined;
}

function automationStepOutcomeLabel(step: AutomationRunStep): string {
  const normalizedStatus = normalizeStatusValue(step.status);
  if (normalizedStatus === "completed") {
    return step.linked_output_id ? "Completed with linked output" : "Completed";
  }
  if (normalizedStatus === "skipped") {
    return "Skipped";
  }
  if (normalizedStatus === "failed") {
    return "Failed before output";
  }
  if (normalizedStatus === "running") {
    return "Running";
  }
  if (normalizedStatus === "queued") {
    return "Queued";
  }
  return step.status;
}

function normalizeAutomationRunOutcomeSummary(run: AutomationRun): AutomationRunOutcomeSummary | null {
  const raw = run.outcome_summary;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  if (typeof raw.summary_text !== "string" || typeof raw.summary_title !== "string") {
    return null;
  }
  if (
    typeof raw.steps_completed_count !== "number"
    || typeof raw.steps_skipped_count !== "number"
    || typeof raw.steps_failed_count !== "number"
  ) {
    return null;
  }
  return {
    summary_title: raw.summary_title,
    summary_text: raw.summary_text,
    pages_analyzed_count: typeof raw.pages_analyzed_count === "number" ? raw.pages_analyzed_count : null,
    issues_found_count: typeof raw.issues_found_count === "number" ? raw.issues_found_count : null,
    recommendations_generated_count:
      typeof raw.recommendations_generated_count === "number"
        ? raw.recommendations_generated_count
        : null,
    steps_completed_count: raw.steps_completed_count,
    steps_skipped_count: raw.steps_skipped_count,
    steps_failed_count: raw.steps_failed_count,
    terminal_outcome:
      raw.terminal_outcome === "completed"
      || raw.terminal_outcome === "completed_with_skips"
      || raw.terminal_outcome === "failed"
      || raw.terminal_outcome === "partial"
        ? raw.terminal_outcome
        : "partial",
  };
}

function formatAutomationTerminalOutcomeLabel(
  outcome: AutomationRunOutcomeSummary["terminal_outcome"] | null,
): string | null {
  if (!outcome) {
    return null;
  }
  if (outcome === "completed") {
    return "Completed";
  }
  if (outcome === "completed_with_skips") {
    return "Completed with skips";
  }
  if (outcome === "failed") {
    return "Failed";
  }
  return "Partial";
}

function automationTerminalOutcomeBadgeClass(
  outcome: AutomationRunOutcomeSummary["terminal_outcome"] | null,
): string {
  if (outcome === "completed") {
    return "badge-success";
  }
  if (outcome === "completed_with_skips" || outcome === "partial") {
    return "badge-warn";
  }
  if (outcome === "failed") {
    return "badge-error";
  }
  return "badge-muted";
}

function summarizeAutomationStepReason(step: AutomationRunStep): string | null {
  if (step.reason_summary && step.reason_summary.trim().length > 0) {
    return step.reason_summary.trim();
  }
  if (step.error_message && step.error_message.trim().length > 0) {
    return step.error_message.trim();
  }
  return null;
}

function summarizeAutomationRunOutcome(run: AutomationRun): string {
  const canonicalSummary = normalizeAutomationRunOutcomeSummary(run);
  if (canonicalSummary?.summary_text) {
    return canonicalSummary.summary_text;
  }

  const steps = normalizeAutomationRunSteps(run);
  const completedStepCount = steps.filter((step) => normalizeStatusValue(step.status) === "completed").length;
  const failedStepCount = steps.filter((step) => normalizeStatusValue(step.status) === "failed").length;
  const totalSteps = steps.length;
  const recommendationRunOutputId = findAutomationRecommendationRunOutputId(steps);
  const recommendationNarrativeOutputId = findAutomationRecommendationNarrativeOutputId(steps);
  const runStatus = normalizeStatusValue(run.status);

  const stepSummary =
    totalSteps > 0 ? `${completedStepCount}/${totalSteps} steps completed` : "No step detail recorded";
  const outputSummary = recommendationNarrativeOutputId
    ? "narrative output produced"
    : recommendationRunOutputId
      ? "recommendation output produced"
      : failedStepCount > 0
        ? "no linked output due to failed steps"
        : "no linked output recorded";

  if (runStatus === "completed") {
    return `Completed. ${stepSummary}; ${outputSummary}.`;
  }
  if (runStatus === "running") {
    return `Running. ${stepSummary}; output may still change.`;
  }
  if (runStatus === "queued") {
    return `Queued. ${stepSummary}; waiting for execution.`;
  }
  if (runStatus === "failed") {
    return `Failed. ${stepSummary}; ${outputSummary}.`;
  }
  return `Status ${run.status}. ${stepSummary}; ${outputSummary}.`;
}

function summarizeAutomationRunNextStep(run: AutomationRun): string {
  const canonicalSummary = normalizeAutomationRunOutcomeSummary(run);
  if (canonicalSummary?.terminal_outcome === "completed") {
    return canonicalSummary.recommendations_generated_count && canonicalSummary.recommendations_generated_count > 0
      ? "Review newly generated recommendations."
      : "Review completed SEO artifacts and proceed with the next operator action.";
  }
  if (canonicalSummary?.terminal_outcome === "completed_with_skips") {
    return "Review skipped steps and rerun after prerequisites are available.";
  }
  if (canonicalSummary?.terminal_outcome === "failed") {
    return "Review failed step details before rerunning SEO automation.";
  }
  if (canonicalSummary?.terminal_outcome === "partial") {
    return "Review partial outputs and rerun remaining steps once prerequisites are ready.";
  }

  const status = normalizeStatusValue(run.status);
  if (status === "completed") {
    return "Review linked recommendation artifacts and decide next operator action.";
  }
  if (status === "failed") {
    return "Review failed step details and rerun automation after addressing blockers.";
  }
  if (status === "running" || status === "queued") {
    return "Wait for completion before taking downstream recommendation actions.";
  }
  return "Review run detail to confirm lifecycle and output state.";
}

function deriveLatestAutomationRun(items: AutomationRun[]): AutomationRun | null {
  if (items.length === 0) {
    return null;
  }
  const sorted = [...items].sort((left, right) => {
    const leftTime = Date.parse(left.created_at || left.started_at || "");
    const rightTime = Date.parse(right.created_at || right.started_at || "");
    if (Number.isNaN(leftTime) || Number.isNaN(rightTime)) {
      return right.id.localeCompare(left.id);
    }
    return rightTime - leftTime;
  });
  return sorted[0] || null;
}

function mapAutomationRunCreateError(error: ApiRequestError): string {
  const normalizedMessage = (error.message || "").trim().toLowerCase();
  if (error.status === 409) {
    return "An automation run is already in progress for this site.";
  }
  if (error.status === 404) {
    if (normalizedMessage.includes("automation config not found")) {
      return "Automation configuration was missing and could not be prepared for this site. Retry in a moment.";
    }
    if (normalizedMessage.includes("seo site not found")) {
      return "This site context could not be resolved. Re-select the site and try again.";
    }
    return "Automation run creation is unavailable for this site right now.";
  }
  if (error.status === 422) {
    return "This site is missing required automation inputs. Review site setup and retry.";
  }
  return "Unable to start an automation run right now.";
}

export default function AutomationPage() {
  const { principal } = useAuth();
  const context = useOperatorContext();
  const contextLoading = context.loading;
  const contextError = context.error;
  const selectedSiteId = context.selectedSiteId;
  const availableSites = context.sites;
  const setContextSelectedSiteId = context.setSelectedSiteId;
  const [triggerContext, setTriggerContext] = useState<AutomationTriggerContext>({
    siteId: null,
    recommendationId: null,
    recommendationTitle: null,
  });
  const [items, setItems] = useState<AutomationRun[]>([]);
  const [automationConfig, setAutomationConfig] = useState<AutomationConfig | null>(null);
  const [automationConfigDraft, setAutomationConfigDraft] = useState<AutomationConfigStepDraft | null>(null);
  const [automationConfigEditing, setAutomationConfigEditing] = useState(false);
  const [automationConfigSaving, setAutomationConfigSaving] = useState(false);
  const [automationConfigSaveSuccess, setAutomationConfigSaveSuccess] = useState<string | null>(null);
  const [automationConfigSaveError, setAutomationConfigSaveError] = useState<string | null>(null);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [triggerRunPending, setTriggerRunPending] = useState(false);
  const [triggerRunError, setTriggerRunError] = useState<string | null>(null);
  const [actionDecisions, setActionDecisions] = useState<Record<string, ActionDecision>>({});
  const [refreshNonce, setRefreshNonce] = useState(0);

  const completedRuns = items.filter((run) => run.status.toLowerCase() === "completed").length;
  const runningRuns = items.filter((run) => run.status.toLowerCase() === "running").length;
  const failedRuns = items.filter((run) => run.status.toLowerCase() === "failed").length;
  const latestRun = deriveLatestAutomationRun(items);
  const latestRunOutcomeSummary = latestRun ? normalizeAutomationRunOutcomeSummary(latestRun) : null;
  const latestRunSteps = latestRun ? normalizeAutomationRunSteps(latestRun) : [];
  const latestRunCompleteness = latestRun
    ? deriveAutomationCompletenessSignal(latestRun, latestRunSteps, latestRunOutcomeSummary)
    : null;
  const latestRecommendationRunOutputId = latestRun ? findAutomationRecommendationRunOutputId(latestRunSteps) : null;
  const latestRecommendationNarrativeOutputId = latestRun
    ? findAutomationRecommendationNarrativeOutputId(latestRunSteps)
    : null;
  const latestRunActionState = deriveAutomationRunOperatorActionState({
    runStatus: latestRun?.status || null,
    hasRecommendationOutput: Boolean(latestRecommendationRunOutputId),
    hasNarrativeOutput: Boolean(latestRecommendationNarrativeOutputId),
  });
  const latestRunBaseActionExecutionItem = latestRun
    ? deriveAutomationActionExecutionItem({
        run: latestRun,
        recommendationRunOutputId: latestRecommendationRunOutputId,
        recommendationNarrativeOutputId: latestRecommendationNarrativeOutputId,
      })
    : null;
  const latestRunEffectiveActionExecutionItem = latestRunBaseActionExecutionItem
    ? (actionDecisions[latestRunBaseActionExecutionItem.id]
      ? applyActionDecisionLocally(latestRunBaseActionExecutionItem, actionDecisions[latestRunBaseActionExecutionItem.id])
      : latestRunBaseActionExecutionItem)
    : null;
  const latestRunActionPresentation = latestRunEffectiveActionExecutionItem
    ? deriveActionStatePresentation({
        item: latestRunEffectiveActionExecutionItem,
        fallbackLabel: latestRunActionState.label,
        fallbackBadgeClass: latestRunActionState.badgeClass,
        fallbackOutcome: latestRunActionState.outcome,
        fallbackNextStep: latestRunActionState.nextStep,
      })
    : null;
  const latestRunActionControls = latestRunEffectiveActionExecutionItem
    ? deriveActionControls(latestRunEffectiveActionExecutionItem)
    : [];
  const hasInFlightAutomationRun = items.some((run) => {
    const normalized = normalizeStatusValue(run.status);
    return normalized === "queued" || normalized === "running";
  });
  const automationPollingActive = Boolean(
    hasInFlightAutomationRun
    && !context.loading
    && !context.error
    && !loadingItems
    && context.selectedSiteId,
  );
  const automationConfigSourceLabel = deriveAutomationConfigSourceLabel(automationConfig);
  const canEditAutomationConfig = principal?.role === "admin";
  const automationConfigPatchPayload = buildAutomationConfigPatchPayload(automationConfig, automationConfigDraft);
  const automationConfigHasChanges = Object.keys(automationConfigPatchPayload).length > 0;
  const automationConfigHasEnabledStep = automationConfigDraft
    ? AUTOMATION_EDITABLE_STEP_FIELDS.some(({ field }) => automationConfigDraft[field])
    : false;
  const automationConfigurationGroups = AUTOMATION_CONFIG_STEP_GROUPS.map((group) => ({
    id: group.id,
    label: group.label,
    description: group.description,
    dependencyNote: group.dependencyNote,
    steps: group.fields.map((field) => ({
      field,
      label: AUTOMATION_CONFIG_STEP_DEFINITIONS[field].label,
      helperText: AUTOMATION_CONFIG_STEP_DEFINITIONS[field].helperText,
      enabled: automationConfig ? automationConfig[field] : null,
    })),
  }));
  const automationControlStatusLabel = latestRunActionPresentation?.label || latestRunActionState.label;
  const automationControlOutcome = latestRunActionPresentation?.outcome || latestRunActionState.outcome;
  const automationControlNextStep = latestRunActionPresentation?.nextStep || latestRunActionState.nextStep;
  const automationControlFocus = latestRun
    ? summarizeAutomationRunOutcome(latestRun)
    : "No automation runs recorded yet for this site.";
  const latestRunActivityAt = latestRun
    ? formatDateTime(latestRun.finished_at || latestRun.started_at || latestRun.created_at || null)
    : "-";

  function handleLocalDecision(actionItemId: string, decision: ActionDecision): void {
    setActionDecisions((current) => ({
      ...current,
      [actionItemId]: decision,
    }));
  }

  async function handleRunAutomationNow(): Promise<void> {
    if (!context.selectedSiteId || context.loading || context.error) {
      setTriggerRunError("Select a site before starting automation.");
      return;
    }
    setTriggerRunPending(true);
    setTriggerRunError(null);
    try {
      const createdRun = await createAutomationRun(context.token, context.businessId, context.selectedSiteId);
      setItems((current) =>
        sortAutomationRunsNewestFirst([
          createdRun,
          ...current.filter((run) => run.id !== createdRun.id),
        ]),
      );
      setRefreshNonce((current) => current + 1);
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setTriggerRunError(mapAutomationRunCreateError(error));
      } else {
        setTriggerRunError("Unable to start an automation run right now.");
      }
    } finally {
      setTriggerRunPending(false);
    }
  }

  function handleAutomationConfigEditStart(): void {
    setAutomationConfigDraft(extractAutomationConfigStepDraft(automationConfig));
    setAutomationConfigEditing(true);
    setAutomationConfigSaveError(null);
    setAutomationConfigSaveSuccess(null);
  }

  function handleAutomationConfigEditCancel(): void {
    setAutomationConfigDraft(extractAutomationConfigStepDraft(automationConfig));
    setAutomationConfigEditing(false);
    setAutomationConfigSaveError(null);
  }

  function handleAutomationConfigToggleChange(field: AutomationEditableStepField, enabled: boolean): void {
    setAutomationConfigDraft((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        [field]: enabled,
      };
    });
    setAutomationConfigSaveError(null);
    setAutomationConfigSaveSuccess(null);
  }

  async function handleAutomationConfigSave(): Promise<void> {
    if (!context.selectedSiteId || !automationConfig || !automationConfigDraft) {
      return;
    }
    if (!automationConfigHasEnabledStep) {
      setAutomationConfigSaveError("Keep at least one automation step enabled.");
      return;
    }
    if (!automationConfigHasChanges) {
      setAutomationConfigEditing(false);
      setAutomationConfigSaveSuccess("No automation configuration changes to save.");
      return;
    }
    setAutomationConfigSaving(true);
    setAutomationConfigSaveError(null);
    setAutomationConfigSaveSuccess(null);
    try {
      const updatedConfig = await patchAutomationConfig(
        context.token,
        context.businessId,
        context.selectedSiteId,
        automationConfigPatchPayload,
      );
      setAutomationConfig(updatedConfig);
      setAutomationConfigDraft(extractAutomationConfigStepDraft(updatedConfig));
      setAutomationConfigEditing(false);
      setAutomationConfigSaveSuccess("Automation configuration updated.");
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setAutomationConfigSaveError(mapAutomationConfigSaveError(error));
      } else {
        setAutomationConfigSaveError("Unable to save automation settings right now.");
      }
    } finally {
      setAutomationConfigSaving(false);
    }
  }

  useEffect(() => {
    setTriggerContext(readAutomationTriggerContextFromLocation());
  }, []);

  useEffect(() => {
    if (!triggerContext.siteId || contextLoading || contextError) {
      return;
    }
    if (selectedSiteId === triggerContext.siteId) {
      return;
    }
    const hasMatchingSite = availableSites.some((site) => site.id === triggerContext.siteId);
    if (!hasMatchingSite) {
      return;
    }
    setContextSelectedSiteId(triggerContext.siteId);
  }, [
    availableSites,
    contextError,
    contextLoading,
    selectedSiteId,
    setContextSelectedSiteId,
    triggerContext.siteId,
  ]);

  useEffect(() => {
    if (!context.selectedSiteId || context.loading || context.error) {
      return;
    }
    let cancelled = false;
    async function loadRuns() {
      setLoadingItems(true);
      setItemsError(null);
      try {
        const [runsResult, statusResult] = await Promise.allSettled([
          fetchAutomationRuns(context.token, context.businessId, context.selectedSiteId as string),
          fetchAutomationStatus(context.token, context.businessId, context.selectedSiteId as string),
        ]);
        if (cancelled) {
          return;
        }
        if (runsResult.status === "fulfilled") {
          setItems(sortAutomationRunsNewestFirst(runsResult.value.items));
        } else {
          setItemsError(
            runsResult.reason instanceof Error ? runsResult.reason.message : "Failed to load automation runs.",
          );
        }
        if (statusResult.status === "fulfilled") {
          setAutomationConfig(statusResult.value.config);
        } else {
          setAutomationConfig(null);
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
  }, [context.businessId, context.error, context.loading, context.selectedSiteId, context.token, refreshNonce]);

  useEffect(() => {
    if (!automationPollingActive) {
      return;
    }
    const intervalId = window.setInterval(() => {
      setRefreshNonce((current) => current + 1);
    }, 4000);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [automationPollingActive]);

  useEffect(() => {
    if (automationConfigEditing) {
      return;
    }
    setAutomationConfigDraft(extractAutomationConfigStepDraft(automationConfig));
  }, [automationConfig, automationConfigEditing]);

  if (context.loading) {
    return (
      <OperatorRouteSupportState
        title="Automation Run History"
        subtitle="Loading automation run status for your selected site."
      />
    );
  }
  if (context.error) {
    return (
      <OperatorRouteSupportState
        title="Automation Run History"
        subtitle={`Error: ${context.error}`}
      />
    );
  }
  if (context.sites.length === 0) {
    return (
      <OperatorRouteSupportState
        title="Automation Run History"
        subtitle="No SEO sites are configured yet. Add a site before reviewing automation run history."
      />
    );
  }

  return (
    <PageContainer width="wide" density="compact">
      <OperatorPageHero
        title="Automation Run History"
        subtitle="Monitor repeatable workflow runs that orchestrate audits, competitor analysis, and recommendation generation."
        headingLevel={1}
        data-testid="automation-page-hero"
        summary={(
          <>
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
          </>
        )}
      >
        <WorkspaceMetadataGrid data-testid="automation-control-grid">
          <WorkspaceMetadataItem label="Automation status">
            <p className="hint muted">
              <span className={latestRunActionPresentation?.badgeClass || latestRunActionState.badgeClass}>
                {automationControlStatusLabel}
              </span>
            </p>
            <p className="hint muted">{automationControlOutcome}</p>
          </WorkspaceMetadataItem>
          <WorkspaceMetadataItem label="What matters now">
            <p className="hint muted">{automationControlFocus}</p>
          </WorkspaceMetadataItem>
          <WorkspaceMetadataItem label="Do this next">
            <p className="hint muted">
              <span className="text-strong">{automationControlNextStep}</span>
            </p>
          </WorkspaceMetadataItem>
          <WorkspaceMetadataItem label="Latest activity">
            <p className="hint muted">
              {latestRun ? `${latestRun.id} · ${latestRunActivityAt}` : "No run activity recorded yet."}
            </p>
          </WorkspaceMetadataItem>
        </WorkspaceMetadataGrid>

        <RouteActionCluster
          data-testid="automation-primary-actions"
          primaryActions={(
            <button
              type="button"
              className="button button-primary"
              onClick={() => {
                void handleRunAutomationNow();
              }}
              disabled={triggerRunPending}
            >
              {triggerRunPending ? "Starting run..." : "Run SEO automation"}
            </button>
          )}
          secondaryActions={(
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setRefreshNonce((current) => current + 1)}
              disabled={loadingItems}
            >
              Refresh status
            </button>
          )}
          shortcutActions={(
            <>
              {latestRecommendationRunOutputId && latestRun ? (
                <Link
                  className="button button-tertiary"
                  href={buildAutomationRecommendationRunHref(latestRecommendationRunOutputId, latestRun.site_id)}
                >
                  Open recommendation output
                </Link>
              ) : null}
              {context.selectedSiteId ? (
                <Link className="button button-tertiary" href={`/sites/${context.selectedSiteId}`}>
                  Open site workspace
                </Link>
              ) : null}
            </>
          )}
        />
      </OperatorPageHero>

      <OperatorPageSectionStack>
        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="Automation operations"
            subtitle="Automation orchestrates workflow runs. Recommendation decisions and queue review stay on Recommendations."
            headingLevel={2}
            variant="support"
          />

          <WorkspaceMessageStack>
            {loadingItems ? <p className="hint muted">Loading automation runs...</p> : null}
            {itemsError ? <p className="hint error">{itemsError}</p> : null}
            <p className="hint muted" data-testid="automation-non-publishing-banner">
              This automation analyzes your site and generates recommendations. It does not make changes to your website.
            </p>
            <p className="hint muted" data-testid="automation-boundary-note">
              Use Audit Runs for findings and history, Recommendations for decisioning, and Competitors for profile generation/review.
            </p>
            {triggerContext.recommendationTitle ? (
              <p className="hint muted" data-testid="automation-trigger-context">
                Triggered from recommendation: {triggerContext.recommendationTitle}
                {triggerContext.recommendationId ? ` (${triggerContext.recommendationId})` : ""}
              </p>
            ) : null}
            {automationPollingActive ? (
              <p className="hint muted" data-testid="automation-polling-status">
                Automation execution is in progress. Status refreshes automatically every few seconds.
              </p>
            ) : null}
          </WorkspaceMessageStack>
          <div className="panel panel-compact stack-tight workspace-section-block" data-testid="automation-boundary-links">
            <span className="text-strong">Open dedicated workflow pages</span>
            <span className="hint muted">
              Automation run history stays here. Full findings and execution review live on dedicated pages.
            </span>
            <div className="link-row">
              <Link href="/audits">Open Audit Runs</Link>
              <Link href={buildRecommendationsHref(context.selectedSiteId || "")}>Open Recommendations</Link>
              <Link href={buildCompetitorsHref(context.selectedSiteId || "")}>Open Competitors</Link>
            </div>
          </div>
          <div className="panel panel-compact stack-tight workspace-section-block" data-testid="automation-config-summary">
          <span className="text-strong">Automation configuration</span>
          <span className="hint muted">
            Configure which automation outputs are generated for this site. Changes apply to future runs only.
          </span>
          {automationConfigEditing && automationConfigDraft ? (
            <div className="stack-tight" data-testid="automation-config-editor">
              {automationConfigurationGroups.map((group) => (
                <div
                  key={`automation-config-group-editor-${group.id}`}
                  className="panel panel-compact stack-tight"
                  data-testid={`automation-config-group-${group.id}`}
                >
                  <span className="text-strong">{group.label}</span>
                  <span className="hint muted">{group.description}</span>
                  {group.dependencyNote ? <span className="hint muted">{group.dependencyNote}</span> : null}
                  {group.steps.map((step) => (
                    <div key={`automation-config-editor-${step.field}`} className="stack-tight">
                      <label className="checkbox-chip">
                        <input
                          type="checkbox"
                          checked={Boolean(automationConfigDraft[step.field])}
                          onChange={(event) => handleAutomationConfigToggleChange(step.field, event.target.checked)}
                          disabled={automationConfigSaving}
                        />
                        <span>{step.label}</span>
                      </label>
                      <span className="hint muted">{step.helperText}</span>
                    </div>
                  ))}
                </div>
              ))}
              {!automationConfigHasEnabledStep ? (
                <span className="hint muted">Keep at least one step enabled before saving.</span>
              ) : null}
              <WorkspaceActionBar variant="primary">
                <button
                  type="button"
                  className="button button-primary button-inline"
                  onClick={() => {
                    void handleAutomationConfigSave();
                  }}
                  disabled={automationConfigSaving || !automationConfigHasEnabledStep}
                  data-testid="automation-config-save-button"
                >
                  {automationConfigSaving ? "Saving..." : "Save step settings"}
                </button>
                <button
                  type="button"
                  className="button button-secondary button-inline"
                  onClick={handleAutomationConfigEditCancel}
                  disabled={automationConfigSaving}
                  data-testid="automation-config-cancel-button"
                >
                  Cancel
                </button>
              </WorkspaceActionBar>
            </div>
          ) : (
            <div className="stack-tight">
              {automationConfigurationGroups.map((group) => (
                <div
                  key={`automation-config-group-read-${group.id}`}
                  className="panel panel-compact stack-tight"
                  data-testid={`automation-config-group-${group.id}`}
                >
                  <span className="text-strong">{group.label}</span>
                  <span className="hint muted">{group.description}</span>
                  {group.dependencyNote ? <span className="hint muted">{group.dependencyNote}</span> : null}
                  <ul className="list-compact-reset">
                    {group.steps.map((step) => (
                      <li key={`automation-config-${group.id}-${step.field}`} className="hint muted">
                        <span className="text-strong">{step.label}:</span> {describeAutomationConfigStepState(step.enabled)}
                        <div className="hint muted">{step.helperText}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
          <span className="hint muted">Config source: {automationConfigSourceLabel}</span>
          {automationConfigSaveSuccess ? (
            <span className="hint">{automationConfigSaveSuccess}</span>
          ) : null}
          {automationConfigSaveError ? (
            <span className="hint error" data-testid="automation-config-save-error">
              {automationConfigSaveError}
            </span>
          ) : null}
          {canEditAutomationConfig ? (
            automationConfigEditing ? null : (
              <WorkspaceActionBar variant="secondary">
                <button
                  type="button"
                  className="button button-secondary button-inline"
                  onClick={handleAutomationConfigEditStart}
                  disabled={!automationConfig}
                  data-testid="automation-config-edit-button"
                >
                  Edit step settings
                </button>
              </WorkspaceActionBar>
            )
          ) : (
            <span className="hint muted">Read-only view. Contact admin to change automation settings.</span>
          )}
        </div>
          {!loadingItems && items.length === 0 ? (
            <WorkspaceEmptyStateCard data-testid="automation-empty-state">
              <strong>No automation runs yet</strong>
              <span className="hint muted">
                Generate a new automation run to analyze this site and produce updated recommendations.
              </span>
              <WorkspaceActionBar variant="primary">
                <button
                  type="button"
                  className="button button-primary button-inline"
                  onClick={() => {
                    void handleRunAutomationNow();
                  }}
                  disabled={triggerRunPending}
                  data-testid="automation-empty-state-run-button"
                >
                  {triggerRunPending ? "Starting run..." : "Run SEO automation"}
                </button>
              </WorkspaceActionBar>
              {triggerRunError ? (
                <span className="hint error" data-testid="automation-empty-state-run-error">
                  {triggerRunError}
                </span>
              ) : null}
            </WorkspaceEmptyStateCard>
          ) : null}

        </SectionCard>

        {latestRun ? (
          <SectionCard variant="summary" className="role-surface-support" data-testid="automation-latest-run-summary">
            <SectionHeader
              title="Latest automation outcome"
              subtitle="Summary-first lifecycle and workflow-step visibility for the most recent run."
              headingLevel={2}
              variant="support"
            />
            <div className="stack-tight">
                <SectionStatusStrip
                  compact={true}
                  data-testid="automation-latest-run-status-strip"
                >
                  <SectionStatusItem
                    label="Run status"
                    value={latestRun.status}
                    tone={
                      latestRun.status === "completed"
                        ? "success"
                        : latestRun.status === "failed"
                          ? "danger"
                          : "warning"
                    }
                  />
                  <SectionStatusItem
                    label="Terminal outcome"
                    value={
                      latestRunOutcomeSummary
                        ? formatAutomationTerminalOutcomeLabel(latestRunOutcomeSummary.terminal_outcome)
                        : "Unavailable"
                    }
                    tone={
                      latestRunOutcomeSummary?.terminal_outcome === "failed"
                        ? "danger"
                        : latestRunOutcomeSummary?.terminal_outcome === "completed_with_skips"
                          || latestRunOutcomeSummary?.terminal_outcome === "partial"
                          ? "warning"
                          : latestRunOutcomeSummary
                            ? "success"
                            : "neutral"
                    }
                  />
                  <SectionStatusItem
                    label="Completeness"
                    value={latestRunCompleteness?.label || "Unknown"}
                    detail={latestRunCompleteness?.hint || "No completeness hint available."}
                    tone={
                      latestRunCompleteness?.label === "Complete"
                        ? "success"
                        : latestRunCompleteness
                          ? "warning"
                          : "neutral"
                    }
                  />
                  <SectionStatusItem
                    label="Action state"
                    value={latestRunActionPresentation?.label || latestRunActionState.label}
                    detail={latestRunActionPresentation?.nextStep || latestRunActionState.nextStep}
                    tone={latestRunActionState.summaryTone}
                  />
                  <SectionStatusItem
                    label="Trigger source"
                    value={latestRun.trigger_source}
                    tone="neutral"
                  />
                  <SectionStatusItem
                    label="Step outcomes"
                    value={
                      latestRunOutcomeSummary
                        ? `${latestRunOutcomeSummary.steps_completed_count} completed`
                        : "Pending"
                    }
                    detail={
                      latestRunOutcomeSummary
                        ? `${latestRunOutcomeSummary.steps_skipped_count} skipped · ${latestRunOutcomeSummary.steps_failed_count} failed`
                        : "Step counts are not available yet."
                    }
                    tone={
                      latestRunOutcomeSummary?.steps_failed_count
                        ? "danger"
                        : latestRunOutcomeSummary?.steps_skipped_count
                          ? "warning"
                          : latestRunOutcomeSummary
                            ? "success"
                            : "neutral"
                    }
                  />
                </SectionStatusStrip>
                <span className="hint">{summarizeAutomationRunOutcome(latestRun)}</span>
                {latestRunCompleteness?.hint ? (
                  <span className="hint muted">{latestRunCompleteness.hint}</span>
                ) : null}
                <span className="hint muted">{latestRunActionPresentation?.outcome || latestRunActionState.outcome}</span>
                <span className="hint muted">Next step: {latestRunActionPresentation?.nextStep || latestRunActionState.nextStep}</span>
                <span className="hint muted">{summarizeAutomationRunNextStep(latestRun)}</span>
                <ActionControls
                  controls={latestRunActionControls}
                  resolveHref={(control) =>
                    resolveAutomationControlHref(
                      control,
                      latestRun,
                      latestRecommendationRunOutputId,
                      latestRecommendationNarrativeOutputId,
                    )}
                  data-testid="automation-latest-run-controls"
                  />
                {latestRunEffectiveActionExecutionItem ? (
                  <OutputReview
                    item={latestRunEffectiveActionExecutionItem}
                    stateLabel={latestRunActionPresentation?.label || latestRunActionState.label}
                    stateBadgeClass={latestRunActionPresentation?.badgeClass || latestRunActionState.badgeClass}
                    outcome={latestRunActionPresentation?.outcome || latestRunActionState.outcome}
                    nextStep={latestRunActionPresentation?.nextStep || latestRunActionState.nextStep}
                    onDecision={(decision) => handleLocalDecision(latestRunEffectiveActionExecutionItem.id, decision)}
                    resolveOutputHref={(outputId) => buildAutomationRecommendationRunHref(outputId, latestRun.site_id)}
                    data-testid="automation-latest-run-output-review"
                  />
                ) : null}
                <span className="hint muted">
                  Started: {formatDateTime(latestRun.started_at)} · Finished: {formatDateTime(latestRun.finished_at)}
                </span>
                <div className="link-row">
                  {latestRecommendationRunOutputId ? (
                    <Link
                      href={buildAutomationRecommendationRunHref(latestRecommendationRunOutputId, latestRun.site_id)}
                    >
                      Open recommendation run output
                    </Link>
                  ) : null}
                  {latestRecommendationRunOutputId && latestRecommendationNarrativeOutputId ? (
                    <Link
                      href={buildAutomationRecommendationNarrativeHref(
                        latestRecommendationRunOutputId,
                        latestRecommendationNarrativeOutputId,
                        latestRun.site_id,
                      )}
                    >
                      Review latest narrative output
                    </Link>
                  ) : null}
                  {!latestRecommendationRunOutputId ? (
                    <span className="hint muted">No linked recommendation output recorded yet.</span>
                  ) : null}
                </div>
            </div>
          </SectionCard>
        ) : null}

        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="Run quick scan"
            subtitle="Summary-first cards show workflow status, blockers, and cross-page follow-up before deep history review."
            headingLevel={2}
            variant="support"
          />
          <div className="stack" data-testid="automation-quick-scan">
            {items.length === 0 && !loadingItems ? (
              <WorkspaceEmptyStateCard compact={true}>
                <p className="hint muted">No automation runs available for quick scan. Start a run to populate history.</p>
              </WorkspaceEmptyStateCard>
            ) : null}
            {items.length > 0 ? (
              <div className="operational-item-list">
              {items.slice(0, 6).map((item) => {
                const normalizedStatus = item.status.toLowerCase();
                const steps = normalizeAutomationRunSteps(item);
                const completedStepCount = steps.filter((step) => normalizeStatusValue(step.status) === "completed").length;
                const failedStepCount = steps.filter((step) => normalizeStatusValue(step.status) === "failed").length;
                const runOutcomeSummary = normalizeAutomationRunOutcomeSummary(item);
                const completenessSignal = deriveAutomationCompletenessSignal(item, steps, runOutcomeSummary);
                const recommendationRunOutputId = findAutomationRecommendationRunOutputId(steps);
                const recommendationNarrativeOutputId = findAutomationRecommendationNarrativeOutputId(steps);
                const actionStateCue = deriveAutomationRunOperatorActionState({
                  runStatus: item.status,
                  hasRecommendationOutput: Boolean(recommendationRunOutputId),
                  hasNarrativeOutput: Boolean(recommendationNarrativeOutputId),
                });
                const baseActionExecutionItem = deriveAutomationActionExecutionItem({
                  run: item,
                  recommendationRunOutputId,
                  recommendationNarrativeOutputId,
                });
                const effectiveActionExecutionItem = actionDecisions[baseActionExecutionItem.id]
                  ? applyActionDecisionLocally(baseActionExecutionItem, actionDecisions[baseActionExecutionItem.id])
                  : baseActionExecutionItem;
                const actionPresentation = deriveActionStatePresentation({
                  item: effectiveActionExecutionItem,
                  fallbackLabel: actionStateCue.label,
                  fallbackBadgeClass: actionStateCue.badgeClass,
                  fallbackOutcome: actionStateCue.outcome,
                  fallbackNextStep: actionStateCue.nextStep,
                });
                const actionControls = deriveActionControls(effectiveActionExecutionItem);
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
                        <span className={actionPresentation.badgeClass}>{actionPresentation.label}</span>
                        <span className={`badge ${statusBadgeClass}`}>{item.status}</span>
                        <span className="badge badge-muted">{item.trigger_source}</span>
                        {steps.length > 0 ? (
                          <span className="badge badge-muted">{completedStepCount}/{steps.length} steps completed</span>
                        ) : null}
                        {failedStepCount > 0 ? <span className="badge badge-warn">{failedStepCount} failed</span> : null}
                        {completenessSignal ? (
                          <span className={`badge ${completenessSignal.badgeClass}`}>{completenessSignal.label}</span>
                        ) : null}
                        <span className={`badge ${blockerClass}`}>{blockerLabel}</span>
                      </>
                    )}
                    summary={
                      summarizeAutomationRunOutcome(item)
                    }
                    primaryAction={
                      <ActionControls
                        controls={actionControls}
                        resolveHref={(control) =>
                          resolveAutomationControlHref(
                            control,
                            item,
                            recommendationRunOutputId,
                            recommendationNarrativeOutputId,
                          )}
                        data-testid={`automation-action-controls-${item.id}`}
                      />
                    }
                    secondaryMeta={
                      <>
                        {completenessSignal?.hint ? (
                          <span className="hint muted">{completenessSignal.hint}</span>
                        ) : null}
                        <span className="hint muted">Next step: {actionPresentation.nextStep}</span>
                        <span className="hint muted">
                          Started: {formatDateTime(item.started_at)} | Finished: {formatDateTime(item.finished_at)}
                        </span>
                      </>
                    }
                    expandedDetail={
                      <>
                        <p className="hint muted">
                          <span className="text-strong">Action state:</span> {actionPresentation.outcome}
                        </p>
                        <OutputReview
                          item={effectiveActionExecutionItem}
                          stateLabel={actionPresentation.label}
                          stateBadgeClass={actionPresentation.badgeClass}
                          outcome={actionPresentation.outcome}
                          nextStep={actionPresentation.nextStep}
                          onDecision={(decision) => handleLocalDecision(effectiveActionExecutionItem.id, decision)}
                          resolveOutputHref={(outputId) => buildAutomationRecommendationRunHref(outputId, item.site_id)}
                          data-testid={`automation-output-review-${item.id}`}
                        />
                        <p className="hint muted">
                          <span className="text-strong">Business:</span> {item.business_id}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Site:</span> {item.site_id}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Error:</span> {item.error_message || "None"}
                        </p>
                        {steps.length > 0 ? (
                          <div className="stack-tight">
                            <span className="hint muted text-strong">Step outcomes</span>
                            <ul className="list-compact-reset">
                              {steps.map((step, index) => {
                                const stepRecommendationRunOutputId = step.step_name === "recommendation_run"
                                  ? step.linked_output_id
                                  : null;
                                const stepRecommendationNarrativeOutputId = step.step_name === "recommendation_narrative"
                                  ? step.linked_output_id
                                  : null;
                                const stepReason = summarizeAutomationStepReason(step);
                                const disabledByAutomationConfig = isStepDisabledByAutomationConfig(step);
                                const structuredReason = disabledByAutomationConfig
                                  ? "Disabled in automation configuration"
                                  : stepReason || "No explicit reason provided";
                                return (
                                  <li
                                    key={`automation-step-${item.id}-${step.step_name}-${index}`}
                                    className="panel panel-compact stack-tight"
                                  >
                                    <span className="hint muted">
                                      <span className="text-strong">Step:</span> {formatAutomationStepName(step.step_name)}
                                    </span>
                                    <span className="hint muted">
                                      <span className="text-strong">Status:</span>{" "}
                                      <span className={`badge ${automationStatusBadgeClass(step.status)}`}>{step.status}</span>
                                    </span>
                                    <span className="hint muted">
                                      <span className="text-strong">Outcome:</span> {automationStepOutcomeLabel(step)}
                                    </span>
                                    <span className="hint muted">
                                      <span className="text-strong">Reason:</span> {structuredReason}
                                    </span>
                                    {disabledByAutomationConfig ? (
                                      <span className="hint muted">
                                        <span className="text-strong">Config source:</span> {automationConfigSourceLabel}
                                      </span>
                                    ) : null}
                                    {step.started_at ? (
                                      <span className="hint muted">
                                        <span className="text-strong">Started:</span> {formatDateTime(step.started_at)}
                                      </span>
                                    ) : null}
                                    {step.finished_at ? (
                                      <span className="hint muted">
                                        <span className="text-strong">Finished:</span> {formatDateTime(step.finished_at)}
                                      </span>
                                    ) : null}
                                    {step.pages_analyzed_count !== null && step.pages_analyzed_count !== undefined ? (
                                      <span className="hint muted">
                                        <span className="text-strong">Pages analyzed:</span> {step.pages_analyzed_count}
                                      </span>
                                    ) : null}
                                    {step.issues_found_count !== null && step.issues_found_count !== undefined ? (
                                      <span className="hint muted">
                                        <span className="text-strong">Issues found:</span> {step.issues_found_count}
                                      </span>
                                    ) : null}
                                    {step.recommendations_generated_count !== null
                                      && step.recommendations_generated_count !== undefined ? (
                                      <span className="hint muted">
                                        <span className="text-strong">Recommendations generated:</span>{" "}
                                        {step.recommendations_generated_count}
                                      </span>
                                      ) : null}
                                    <div className="link-row">
                                      {stepRecommendationRunOutputId ? (
                                        <Link
                                          href={buildAutomationRecommendationRunHref(stepRecommendationRunOutputId, item.site_id)}
                                        >
                                          Recommendation run output
                                        </Link>
                                      ) : null}
                                      {recommendationRunOutputId && stepRecommendationNarrativeOutputId ? (
                                        <Link
                                          href={buildAutomationRecommendationNarrativeHref(
                                            recommendationRunOutputId,
                                            stepRecommendationNarrativeOutputId,
                                            item.site_id,
                                          )}
                                        >
                                          Narrative output
                                        </Link>
                                      ) : null}
                                    </div>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        ) : (
                          <p className="hint muted">No step-level lifecycle detail is available for this run.</p>
                        )}
                        {recommendationRunOutputId ? (
                          <p className="hint muted">
                            <Link href={buildAutomationRecommendationRunHref(recommendationRunOutputId, item.site_id)}>
                              Open linked recommendation run
                            </Link>
                          </p>
                        ) : null}
                        {recommendationRunOutputId && recommendationNarrativeOutputId ? (
                          <p className="hint muted">
                            <Link
                              href={buildAutomationRecommendationNarrativeHref(
                                recommendationRunOutputId,
                                recommendationNarrativeOutputId,
                                item.site_id,
                              )}
                            >
                              Open linked recommendation narrative
                            </Link>
                          </p>
                        ) : null}
                      </>
                    }
                  />
                );
              })}
            </div>
          ) : null}
          </div>
        </SectionCard>

        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="Run history"
            subtitle="Recent run lifecycle records for auditability and follow-up."
            headingLevel={2}
            variant="support"
          />
          <WorkspaceTableShell>
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
          </WorkspaceTableShell>
        </SectionCard>
      </OperatorPageSectionStack>
    </PageContainer>
  );
}
