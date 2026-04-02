"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ActionControls } from "../../components/action-execution/ActionControls";
import { OutputReview } from "../../components/action-execution/OutputReview";
import { OperationalItemCard } from "../../components/layout/OperationalItemCard";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { WorkflowSiteSelector } from "../../components/layout/WorkflowSiteSelector";
import { useOperatorContext } from "../../components/useOperatorContext";
import { fetchAutomationRuns } from "../../lib/api/client";
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

export default function AutomationPage() {
  const context = useOperatorContext();
  const [items, setItems] = useState<AutomationRun[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);
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

  function handleLocalDecision(actionItemId: string, decision: ActionDecision): void {
    setActionDecisions((current) => ({
      ...current,
      [actionItemId]: decision,
    }));
  }

  useEffect(() => {
    if (!context.selectedSiteId || context.loading || context.error) {
      return;
    }
    let cancelled = false;
    async function loadRuns() {
      setLoadingItems(true);
      setItemsError(null);
      try {
        const response = await fetchAutomationRuns(context.token, context.businessId, context.selectedSiteId as string);
        if (!cancelled) {
          setItems(response.items);
        }
      } catch (err) {
        if (!cancelled) {
          setItemsError(err instanceof Error ? err.message : "Failed to load automation runs.");
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

  if (context.loading) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Automation Run History"
            subtitle="Loading automation run status for your selected site."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Automation Run History"
            subtitle={`Error: ${context.error}`}
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.sites.length === 0) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Automation Run History"
            subtitle="No SEO sites are configured yet. Add a site before reviewing automation run history."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="wide" density="compact">
      <SectionCard variant="support" className="role-surface-support">
        <WorkflowSiteSelector
          id="site-picker-automation"
          sites={context.sites}
          selectedSiteId={context.selectedSiteId}
          onChange={context.setSelectedSiteId}
        />
      </SectionCard>
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Automation Run History"
            subtitle="Monitor automated recommendation and workflow run outcomes."
            headingLevel={1}
            variant="hero"
          />
          <div className="workspace-summary-strip role-summary-strip">
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
          </div>
        </SectionCard>
      </div>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Automation runs"
          subtitle="Select a site and review trigger, lifecycle, and error outcome details."
          headingLevel={2}
          variant="support"
        />

        {loadingItems ? <p className="hint muted">Loading automation runs...</p> : null}
        {itemsError ? <p className="hint error">{itemsError}</p> : null}
        <p className="hint muted" data-testid="automation-non-publishing-banner">
          This automation analyzes your site and generates recommendations. It does not make changes to your website.
        </p>
        {automationPollingActive ? (
          <p className="hint muted" data-testid="automation-polling-status">
            Automation execution is in progress. Status refreshes automatically every few seconds.
          </p>
        ) : null}

        <div className="stack" data-testid="automation-quick-scan">
          {latestRun ? (
            <SectionCard variant="summary" className="role-surface-support" data-testid="automation-latest-run-summary">
              <SectionHeader
                title="Latest automation outcome"
                subtitle="Summary-first lifecycle and output visibility for the most recent run."
                headingLevel={3}
                variant="support"
              />
              <div className="stack-tight">
                <div className="link-row">
                  <span className={`badge ${automationStatusBadgeClass(latestRun.status)}`}>
                    {latestRun.status}
                  </span>
                  {latestRunOutcomeSummary ? (
                    <span className={`badge ${automationTerminalOutcomeBadgeClass(latestRunOutcomeSummary.terminal_outcome)}`}>
                      {formatAutomationTerminalOutcomeLabel(latestRunOutcomeSummary.terminal_outcome)}
                    </span>
                  ) : null}
                  {latestRunCompleteness ? (
                    <span className={`badge ${latestRunCompleteness.badgeClass}`}>
                      {latestRunCompleteness.label}
                    </span>
                  ) : null}
                  <span className={latestRunActionPresentation?.badgeClass || latestRunActionState.badgeClass}>
                    {latestRunActionPresentation?.label || latestRunActionState.label}
                  </span>
                  <span className="badge badge-muted">Trigger: {latestRun.trigger_source}</span>
                  <span className="badge badge-muted">Run: {latestRun.id}</span>
                </div>
                {latestRunOutcomeSummary ? (
                  <div className="link-row">
                    <span className="badge badge-muted">
                      {latestRunOutcomeSummary.steps_completed_count} completed
                    </span>
                    <span className="badge badge-muted">
                      {latestRunOutcomeSummary.steps_skipped_count} skipped
                    </span>
                    <span className="badge badge-muted">
                      {latestRunOutcomeSummary.steps_failed_count} failed
                    </span>
                  </div>
                ) : null}
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
                      Review recommendation run output
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
          <h3 className="heading-reset">Run quick scan</h3>
          <p className="hint muted">
            Summary-first cards show automation status, blockers, and follow-up urgency before deep history review.
          </p>
          {items.length === 0 && !loadingItems ? (
            <p className="hint muted">No automation runs available for quick scan.</p>
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
                                return (
                                  <li key={`automation-step-${item.id}-${step.step_name}-${index}`} className="hint muted">
                                    <span className={`badge ${automationStatusBadgeClass(step.status)}`}>{step.status}</span>{" "}
                                    <span className="text-strong">{formatAutomationStepName(step.step_name)}</span>:{" "}
                                    {automationStepOutcomeLabel(step)}
                                    {step.started_at ? ` · started ${formatDateTime(step.started_at)}` : ""}
                                    {step.finished_at ? ` · finished ${formatDateTime(step.finished_at)}` : ""}
                                    {stepReason ? ` · reason: ${stepReason}` : ""}
                                    {step.pages_analyzed_count !== null && step.pages_analyzed_count !== undefined
                                      ? ` · pages analyzed: ${step.pages_analyzed_count}`
                                      : ""}
                                    {step.issues_found_count !== null && step.issues_found_count !== undefined
                                      ? ` · issues found: ${step.issues_found_count}`
                                      : ""}
                                    {step.recommendations_generated_count !== null
                                      && step.recommendations_generated_count !== undefined
                                      ? ` · recommendations generated: ${step.recommendations_generated_count}`
                                      : ""}
                                    {stepRecommendationRunOutputId ? (
                                      <>
                                        {" "}
                                        ·{" "}
                                        <Link
                                          href={buildAutomationRecommendationRunHref(stepRecommendationRunOutputId, item.site_id)}
                                        >
                                          Recommendation run output
                                        </Link>
                                      </>
                                    ) : null}
                                    {recommendationRunOutputId && stepRecommendationNarrativeOutputId ? (
                                      <>
                                        {" "}
                                        ·{" "}
                                        <Link
                                          href={buildAutomationRecommendationNarrativeHref(
                                            recommendationRunOutputId,
                                            stepRecommendationNarrativeOutputId,
                                            item.site_id,
                                          )}
                                        >
                                          Narrative output
                                        </Link>
                                      </>
                                    ) : null}
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

        <div className="table-container">
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
        </div>
      </SectionCard>
    </PageContainer>
  );
}
