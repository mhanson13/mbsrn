"use client";

import { Suspense, useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { PageContainer } from "../../components/layout/PageContainer";
import {
  OperatorPageHero,
  OperatorPageSectionStack,
} from "../../components/layout/OperatorPageSurface";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { WorkspaceEmptyStateCard } from "../../components/layout/WorkspaceEmptyStateCard";
import { WorkspaceMessageStack } from "../../components/layout/WorkspaceMessageStack";
import { WorkspaceTableShell } from "../../components/layout/WorkspaceTableShell";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  ApiRequestError,
  createCompetitorDomainManualSeed,
  createCompetitorProfileGenerationRun,
  fetchReviewedCompetitorList,
  upsertCompetitorDomainFeedback,
} from "../../lib/api/client";
import type {
  CompetitorDomainFeedbackStatus,
  CompetitorGenerationQualitySummary,
  ReviewedCompetitorListResponse,
  ReviewedCompetitorRow,
  ReviewedCompetitorState,
} from "../../lib/api/types";

const COMPETITOR_GENERATION_POLL_INTERVAL_MS = 5000;

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

function safeCompetitorErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view competitor data.";
    }
    if (error.status === 404) {
      return "Competitor data for the selected site was not found.";
    }
  }
  return "Unable to load competitors right now. Please try again.";
}

function safeGenerationErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to suggest competitors.";
    }
    if (error.status === 404) {
      return "Selected site was not found for competitor suggestions.";
    }
    if (error.status === 422) {
      return "Competitor suggestions cannot start until site context is ready.";
    }
    if (error.status === 429) {
      return "Competitor suggestions are temporarily rate-limited. Try again shortly.";
    }
    if (error.status >= 500) {
      return "Competitor suggestions are temporarily unavailable. Try again shortly.";
    }
  }
  return "Unable to start competitor suggestions right now. Try again.";
}

function safeFeedbackErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to update competitor feedback.";
    }
    if (error.status === 404) {
      return "Selected site was not found for competitor feedback.";
    }
    if (error.status === 422) {
      return "Feedback update was rejected. Check domain format and site relevance.";
    }
  }
  return "Unable to update competitor feedback right now. Try again.";
}

function normalizeDomainForFeedback(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase();
}

function formatFeedbackStatusLabel(status: CompetitorDomainFeedbackStatus | null): string {
  if (status === "useful") {
    return "Useful";
  }
  if (status === "not_useful") {
    return "Not useful";
  }
  if (status === "excluded") {
    return "Excluded";
  }
  if (status === "manually_seeded") {
    return "Manual seed";
  }
  return "Not reviewed";
}

function classifyGenerationStartResponse(
  response: unknown,
): { classification: "success" | "unexpected_response"; message: string } {
  if (!response || typeof response !== "object") {
    return {
      classification: "unexpected_response",
      message:
        "Competitor suggestion request returned an unexpected response. Refresh to confirm run status.",
    };
  }
  const responseRecord = response as { run?: unknown };
  const runRecord =
    responseRecord.run && typeof responseRecord.run === "object"
      ? (responseRecord.run as { id?: unknown; status?: unknown })
      : null;
  const runId =
    runRecord && typeof runRecord.id === "string" ? runRecord.id.trim() : "";
  const runStatus =
    runRecord && typeof runRecord.status === "string" ? runRecord.status.trim() : "";
  if (!runId || !runStatus) {
    return {
      classification: "unexpected_response",
      message:
        "Competitor suggestion request was accepted, but run details were incomplete. Refresh to confirm status.",
    };
  }
  return {
    classification: "success",
    message: `Competitor suggestion started (run ${runId}, ${runStatus}).`,
  };
}

function formatReviewStateLabel(state: ReviewedCompetitorState): string {
  switch (state) {
    case "accepted":
      return "Accepted";
    case "useful":
      return "Useful";
    case "not_useful":
      return "Not useful";
    case "excluded":
      return "Excluded";
    case "needs_review":
      return "Needs review";
    case "manual_seed":
      return "Manual seed";
    case "generated_suggestion":
      return "Generated suggestion";
    case "legacy_synthetic":
      return "Legacy/synthetic";
    default:
      return state;
  }
}

function reviewStateBadgeClass(state: ReviewedCompetitorState): string {
  if (state === "accepted" || state === "useful") {
    return "badge-success";
  }
  if (state === "generated_suggestion" || state === "needs_review") {
    return "badge-warn";
  }
  if (state === "excluded" || state === "legacy_synthetic") {
    return "badge-warn";
  }
  return "badge-muted";
}

function formatProvenanceLabel(value: ReviewedCompetitorRow["provenance"]): string {
  if (value === "ai_suggested") {
    return "AI suggested";
  }
  if (value === "manual_seed") {
    return "Manual seed";
  }
  if (value === "legacy") {
    return "Legacy";
  }
  return "Existing";
}

function formatGenerationQualityStatus(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (normalized === "ready") {
    return "Ready";
  }
  if (normalized === "partial") {
    return "Partial";
  }
  if (normalized === "blocked") {
    return "Blocked";
  }
  return "Unknown";
}

function formatGenerationQualityReason(reason: CompetitorGenerationQualitySummary["top_reason"]): string {
  if (!reason) {
    return "unknown";
  }
  const labels: Record<NonNullable<CompetitorGenerationQualitySummary["top_reason"]>, string> = {
    valid: "Valid candidates retained",
    duplicate_domain: "Duplicate domains removed",
    self_domain: "Self-domain candidates removed",
    malformed_domain: "Malformed domains removed",
    low_relevance: "Low-relevance candidates removed",
    missing_required_fields: "Candidates missing required fields",
    insufficient_candidates: "Insufficient usable candidates",
    provider_unparseable: "Provider output unparseable",
    provider_returned_empty: "Provider returned no candidates",
    provider_schema_invalid: "Provider schema configuration invalid",
    prompt_override_contract_invalid: "Admin competitor prompt override is incompatible",
  };
  return labels[reason];
}

function buildSnapshotRunHref(siteId: string | null, setId: string, runId: string): string {
  const params = new URLSearchParams();
  params.set("set_id", setId);
  if (siteId) {
    params.set("site_id", siteId);
  }
  return `/competitors/snapshot-runs/${runId}?${params.toString()}`;
}

function buildComparisonRunHref(siteId: string | null, setId: string, runId: string): string {
  const params = new URLSearchParams();
  params.set("set_id", setId);
  if (siteId) {
    params.set("site_id", siteId);
  }
  return `/competitors/comparison-runs/${runId}?${params.toString()}`;
}

function CompetitorsPageContent() {
  const searchParams = useSearchParams();
  const context = useOperatorContext();
  const {
    loading: contextLoading,
    error: contextError,
    token,
    businessId,
    sites,
    selectedSiteId,
    setSelectedSiteId,
  } = context;

  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const [loadingCompetitors, setLoadingCompetitors] = useState(false);
  const [competitorsError, setCompetitorsError] = useState<string | null>(null);
  const [reviewedList, setReviewedList] = useState<ReviewedCompetitorListResponse | null>(null);
  const [generationInFlight, setGenerationInFlight] = useState(false);
  const [generationMessage, setGenerationMessage] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [generationWarning, setGenerationWarning] = useState<string | null>(null);
  const [feedbackInFlightDomain, setFeedbackInFlightDomain] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [manualSeedDomain, setManualSeedDomain] = useState("");
  const [manualSeedDisplayName, setManualSeedDisplayName] = useState("");
  const [manualSeedNote, setManualSeedNote] = useState("");
  const [manualSeedInFlight, setManualSeedInFlight] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const reviewedRows = useMemo(() => reviewedList?.items ?? [], [reviewedList]);
  const reviewedSummary = reviewedList?.summary;
  const latestSuggestion = reviewedList?.latest_suggestion;
  const generationQualitySummary = reviewedList?.quality_summary;
  const diagnostics = reviewedList?.diagnostics;
  const manualSeedRows = useMemo(
    () => reviewedRows.filter((item) => item.review_state === "manual_seed"),
    [reviewedRows],
  );

  const generationButtonLabel = (reviewedSummary?.total ?? 0) > 0
    ? "Refresh competitor suggestions"
    : "Suggest competitors";
  const generationButtonDisabled = !selectedSiteId || generationInFlight;
  const generationRunStatus = (latestSuggestion?.run_status || "").trim().toLowerCase();
  const generationAlreadyRunning = generationRunStatus === "queued" || generationRunStatus === "running";

  useEffect(() => {
    if (contextLoading || contextError || !requestedSiteId) {
      return;
    }
    const requestedSiteExists = sites.some((site) => site.id === requestedSiteId);
    if (!requestedSiteExists) {
      return;
    }
    if (selectedSiteId !== requestedSiteId) {
      setSelectedSiteId(requestedSiteId);
    }
  }, [
    contextError,
    contextLoading,
    requestedSiteId,
    selectedSiteId,
    setSelectedSiteId,
    sites,
  ]);

  useEffect(() => {
    if (contextLoading || contextError || !selectedSiteId) {
      setReviewedList(null);
      setCompetitorsError(null);
      setLoadingCompetitors(false);
      return;
    }
    let cancelled = false;

    async function loadReviewedCompetitors() {
      if (!selectedSiteId) {
        return;
      }
      const siteId = selectedSiteId;
      setLoadingCompetitors(true);
      setCompetitorsError(null);
      try {
        const response = await fetchReviewedCompetitorList(token, businessId, siteId);
        if (cancelled) {
          return;
        }
        setReviewedList(response);
      } catch (error) {
        if (!cancelled) {
          setCompetitorsError(safeCompetitorErrorMessage(error));
          setReviewedList(null);
        }
      } finally {
        if (!cancelled) {
          setLoadingCompetitors(false);
        }
      }
    }

    void loadReviewedCompetitors();
    return () => {
      cancelled = true;
    };
  }, [businessId, contextError, contextLoading, refreshNonce, selectedSiteId, token]);

  useEffect(() => {
    if (!selectedSiteId || contextLoading || contextError) {
      return;
    }
    if (generationInFlight) {
      return;
    }
    if (!latestSuggestion || (generationRunStatus !== "queued" && generationRunStatus !== "running")) {
      return;
    }
    const pollTimer = window.setTimeout(() => {
      setRefreshNonce((current) => current + 1);
    }, COMPETITOR_GENERATION_POLL_INTERVAL_MS);
    return () => {
      window.clearTimeout(pollTimer);
    };
  }, [
    contextError,
    contextLoading,
    generationInFlight,
    generationRunStatus,
    latestSuggestion,
    selectedSiteId,
  ]);

  const handleGenerateCompetitors = useCallback(async () => {
    if (!selectedSiteId) {
      return;
    }
    setGenerationInFlight(true);
    setGenerationError(null);
    setGenerationMessage(null);
    setGenerationWarning(null);
    try {
      const result = await createCompetitorProfileGenerationRun(token, businessId, selectedSiteId, {});
      const responseClassification = classifyGenerationStartResponse(result);
      if (responseClassification.classification === "unexpected_response") {
        setGenerationWarning(responseClassification.message);
      } else {
        setGenerationMessage(responseClassification.message);
      }
      setRefreshNonce((current) => current + 1);
    } catch (error) {
      setGenerationError(safeGenerationErrorMessage(error));
    } finally {
      setGenerationInFlight(false);
    }
  }, [businessId, selectedSiteId, token]);

  const handleDomainFeedbackUpdate = useCallback(async (
    domain: string,
    feedbackStatus: Exclude<CompetitorDomainFeedbackStatus, "manually_seeded">,
    displayName?: string | null,
  ) => {
    if (!selectedSiteId) {
      return;
    }
    const normalizedDomain = normalizeDomainForFeedback(domain);
    if (!normalizedDomain) {
      setFeedbackError("Domain is required to save competitor feedback.");
      return;
    }
    setFeedbackInFlightDomain(normalizedDomain);
    setFeedbackError(null);
    setFeedbackMessage(null);
    try {
      const response = await upsertCompetitorDomainFeedback(
        token,
        businessId,
        selectedSiteId,
        {
          domain: normalizedDomain,
          feedback_status: feedbackStatus,
          display_name: displayName ?? null,
        },
      );
      const responseDomain = normalizeDomainForFeedback((response as { domain?: string }).domain);
      const responseStatus = (response as { feedback_status?: CompetitorDomainFeedbackStatus }).feedback_status;
      if (!responseDomain || !responseStatus) {
        setFeedbackError("Feedback update returned an unexpected response. Refresh to confirm current state.");
        setRefreshNonce((current) => current + 1);
        return;
      }
      setFeedbackMessage(`Saved feedback for ${responseDomain}: ${formatFeedbackStatusLabel(responseStatus)}.`);
      setRefreshNonce((current) => current + 1);
    } catch (error) {
      setFeedbackError(safeFeedbackErrorMessage(error));
    } finally {
      setFeedbackInFlightDomain(null);
    }
  }, [businessId, selectedSiteId, token]);

  const handleManualSeedSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedSiteId) {
      return;
    }
    const normalizedDomain = normalizeDomainForFeedback(manualSeedDomain);
    if (!normalizedDomain) {
      setFeedbackError("Manual seed domain is required.");
      return;
    }
    setManualSeedInFlight(true);
    setFeedbackError(null);
    setFeedbackMessage(null);
    try {
      const response = await createCompetitorDomainManualSeed(
        token,
        businessId,
        selectedSiteId,
        {
          domain: normalizedDomain,
          display_name: manualSeedDisplayName.trim() || null,
          operator_note: manualSeedNote.trim() || null,
        },
      );
      const responseDomain = normalizeDomainForFeedback((response as { domain?: string }).domain);
      if (!responseDomain) {
        setFeedbackError("Manual seed request returned an unexpected response. Refresh to confirm current state.");
        setRefreshNonce((current) => current + 1);
        return;
      }
      setFeedbackMessage(`Manual seed saved for ${responseDomain}.`);
      setManualSeedDomain("");
      setManualSeedDisplayName("");
      setManualSeedNote("");
      setRefreshNonce((current) => current + 1);
    } catch (error) {
      setFeedbackError(safeFeedbackErrorMessage(error));
    } finally {
      setManualSeedInFlight(false);
    }
  }, [businessId, manualSeedDisplayName, manualSeedDomain, manualSeedNote, selectedSiteId, token]);

  if (contextLoading) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Competitors"
            subtitle="Loading reviewed competitor list for your selected site."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  if (contextError) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Competitors"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  if (sites.length === 0) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Competitors"
            subtitle="No SEO sites are configured yet. Add a site first to review competitors."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="wide" density="compact">
      <OperatorPageHero
        title="Competitors"
        subtitle="AI can suggest competitors, but humans choose who counts."
        headingLevel={1}
        data-testid="competitors-page-hero"
        actions={(
          <button
            type="button"
            className="button button-primary"
            onClick={() => {
              void handleGenerateCompetitors();
            }}
            disabled={generationButtonDisabled}
            data-testid="competitors-generate-set-button"
          >
            {generationInFlight ? "Suggesting competitors..." : generationButtonLabel}
          </button>
        )}
        summary={(
          <>
            <SummaryStatCard
              label="Total"
              value={reviewedSummary?.total ?? 0}
              detail="Reviewed competitor rows"
              tone={(reviewedSummary?.total ?? 0) > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Accepted/useful"
              value={reviewedSummary?.accepted_useful ?? 0}
              detail="Trusted competitors"
              tone={(reviewedSummary?.accepted_useful ?? 0) > 0 ? "success" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Needs review"
              value={reviewedSummary?.needs_review ?? 0}
              detail="Pending operator decision"
              tone={(reviewedSummary?.needs_review ?? 0) > 0 ? "warning" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Excluded"
              value={reviewedSummary?.excluded ?? 0}
              detail="Excluded by operator"
              tone={(reviewedSummary?.excluded ?? 0) > 0 ? "warning" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Manual seeds"
              value={reviewedSummary?.manual_seeds ?? 0}
              detail="Operator-seeded domains"
              tone={(reviewedSummary?.manual_seeds ?? 0) > 0 ? "success" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Last suggestion"
              value={reviewedSummary?.last_suggestion_status || "none"}
              detail={latestSuggestion?.run_id ? `Run ${latestSuggestion.run_id}` : "No run yet"}
              tone={
                reviewedSummary?.last_suggestion_status === "failed"
                  ? "warning"
                  : reviewedSummary?.last_suggestion_status
                    ? "success"
                    : "neutral"
              }
              variant="elevated"
            />
          </>
        )}
      >
        <WorkspaceMessageStack data-testid="competitors-generation-guidance">
          <p className="hint muted">
            Suggest competitors using current site, audit, manual-seed, and operator-feedback context.
          </p>
          {generationInFlight ? (
            <p className="hint muted" data-testid="competitors-generation-pending">Suggesting competitors...</p>
          ) : null}
          {generationAlreadyRunning ? (
            <p className="hint muted" data-testid="competitors-generation-running">
              A competitor suggestion run is already queued or running for this site.
            </p>
          ) : null}
          {generationMessage ? (
            <p className="hint" data-testid="competitors-generation-success">{generationMessage}</p>
          ) : null}
          {generationWarning ? (
            <p className="hint warning" data-testid="competitors-generation-warning">{generationWarning}</p>
          ) : null}
          {generationError ? (
            <p className="hint error" data-testid="competitors-generation-error">{generationError}</p>
          ) : null}
          <p className="hint muted" data-testid="competitors-generation-summary-line">
            Local seeds considered: {latestSuggestion?.local_seeds_considered ?? 0}. Suggestions returned: {latestSuggestion?.suggestions_returned ?? 0}. Added to review list: {latestSuggestion?.added_to_review_list ?? 0}. Already known: {latestSuggestion?.already_known ?? 0}. Rejected by quality gate: {latestSuggestion?.rejected_by_quality_gate ?? 0}. Excluded by operator feedback: {latestSuggestion?.excluded_by_operator_feedback ?? 0}.
            {latestSuggestion?.failure_reason ? ` Failure reason: ${latestSuggestion.failure_reason}.` : ""}
          </p>
          <p className="hint muted" data-testid="competitors-admin-governance-hint">
            Suggestions use Admin-configured relevance, local alignment, exclusion, timeout, and prompt-governance rules.
          </p>
        </WorkspaceMessageStack>
      </OperatorPageHero>

      <OperatorPageSectionStack>
        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="Reviewed competitor list"
            subtitle="Review competitor suggestions and decide who counts."
            headingLevel={2}
            variant="support"
          />

          {generationQualitySummary ? (
            <WorkspaceMessageStack>
              <p className="hint muted" data-testid="competitors-generation-quality">
                <strong>{formatGenerationQualityStatus(generationQualitySummary.status)}</strong>
                {" "}({generationQualitySummary.accepted_candidates}/{generationQualitySummary.total_candidates_returned} accepted, {generationQualitySummary.rejected_candidates} rejected)
                {generationQualitySummary.top_reason ? `; reason: ${formatGenerationQualityReason(generationQualitySummary.top_reason)}` : ""}
              </p>
              {generationQualitySummary.status !== "ready" ? (
                <p className={`hint ${generationQualitySummary.status === "blocked" ? "error" : "warning"}`} data-testid="competitors-generation-quality-message">
                  {generationQualitySummary.operator_message}
                </p>
              ) : null}
            </WorkspaceMessageStack>
          ) : null}

          <div className="panel stack section-card-variant-support" data-testid="competitor-feedback-panel">
            <h3 className="heading-reset">Manual seeds</h3>
            <p className="hint muted">
              Add known competitors that should be considered during future suggestions.
            </p>
            <form
              className="competitor-feedback-form-grid"
              onSubmit={(event) => {
                void handleManualSeedSubmit(event);
              }}
              data-testid="competitors-manual-seed-form"
            >
              <label>
                <span>Manual seed domain</span>
                <input
                  type="text"
                  value={manualSeedDomain}
                  onChange={(event) => setManualSeedDomain(event.target.value)}
                  placeholder="competitor.example"
                  data-testid="competitors-manual-seed-domain-input"
                />
              </label>
              <label>
                <span>Display name (optional)</span>
                <input
                  type="text"
                  value={manualSeedDisplayName}
                  onChange={(event) => setManualSeedDisplayName(event.target.value)}
                  placeholder="Known competitor name"
                  data-testid="competitors-manual-seed-display-name-input"
                />
              </label>
              <label>
                <span>Note (optional)</span>
                <input
                  type="text"
                  value={manualSeedNote}
                  onChange={(event) => setManualSeedNote(event.target.value)}
                  placeholder="Context for future generation"
                  data-testid="competitors-manual-seed-note-input"
                />
              </label>
              <div className="form-actions">
                <button
                  type="submit"
                  className="button button-tertiary"
                  disabled={manualSeedInFlight || !selectedSiteId}
                  data-testid="competitors-manual-seed-submit"
                >
                  {manualSeedInFlight ? "Saving seed..." : "Add manual seed"}
                </button>
              </div>
            </form>
            {manualSeedRows.length > 0 ? (
              <p className="hint muted" data-testid="competitors-manual-seed-list">
                Manual seeds: {manualSeedRows.map((item) => item.domain).join(", ")}
              </p>
            ) : null}
          </div>

          {(feedbackMessage || feedbackError) ? (
            <WorkspaceMessageStack>
              {feedbackMessage ? <p className="hint" data-testid="competitors-feedback-success">{feedbackMessage}</p> : null}
              {feedbackError ? <p className="hint error" data-testid="competitors-feedback-error">{feedbackError}</p> : null}
            </WorkspaceMessageStack>
          ) : null}

          {loadingCompetitors || competitorsError ? (
            <WorkspaceMessageStack data-testid="competitors-page-message-stack">
              {loadingCompetitors ? <p className="hint muted">Loading competitors...</p> : null}
              {competitorsError ? <p className="hint error">{competitorsError}</p> : null}
            </WorkspaceMessageStack>
          ) : null}

          <WorkspaceTableShell data-testid="competitors-page-table-shell">
            <table className="table table-dense">
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Name</th>
                  <th>Review state</th>
                  <th>Provenance</th>
                  <th>Confidence</th>
                  <th>Rationale</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {reviewedRows.map((row) => {
                  const domainKey = normalizeDomainForFeedback(row.domain);
                  const actionDisabled = feedbackInFlightDomain === domainKey || manualSeedInFlight || !selectedSiteId;
                  return (
                    <tr key={`reviewed-competitor-${row.domain}`} data-testid={`competitor-row-${row.domain}`}>
                      <td>
                        <strong>{row.domain}</strong>
                      </td>
                      <td>{row.display_name || "-"}</td>
                      <td>
                        <span className={`badge ${reviewStateBadgeClass(row.review_state)}`}>
                          {formatReviewStateLabel(row.review_state)}
                        </span>
                      </td>
                      <td>{formatProvenanceLabel(row.provenance)}</td>
                      <td>{typeof row.confidence_score === "number" ? row.confidence_score.toFixed(2) : "-"}</td>
                      <td>{row.reason_selected || row.operator_note || "-"}</td>
                      <td>{formatDateTime(row.updated_at)}</td>
                      <td>
                        <div className="form-actions competitor-feedback-action-group" data-testid={`competitor-domain-feedback-actions-${row.domain}`}>
                          <button
                            type="button"
                            className="button button-tertiary button-inline"
                            disabled={actionDisabled}
                            onClick={() => {
                              void handleDomainFeedbackUpdate(row.domain, "useful", row.display_name);
                            }}
                          >
                            Mark accepted/useful
                          </button>
                          <button
                            type="button"
                            className="button button-tertiary button-inline"
                            disabled={actionDisabled}
                            onClick={() => {
                              void handleDomainFeedbackUpdate(row.domain, "not_useful", row.display_name);
                            }}
                          >
                            Mark not useful
                          </button>
                          <button
                            type="button"
                            className="button button-tertiary button-inline"
                            disabled={actionDisabled}
                            onClick={() => {
                              void handleDomainFeedbackUpdate(row.domain, "excluded", row.display_name);
                            }}
                          >
                            Exclude
                          </button>
                          {row.review_state === "excluded" ? (
                            <button
                              type="button"
                              className="button button-tertiary button-inline"
                              disabled={actionDisabled}
                              onClick={() => {
                                void handleDomainFeedbackUpdate(row.domain, "not_useful", row.display_name);
                              }}
                            >
                              Restore/reconsider
                            </button>
                          ) : null}
                        </div>
                        {feedbackInFlightDomain === domainKey ? <span className="hint muted">Updating feedback...</span> : null}
                      </td>
                    </tr>
                  );
                })}
                {!loadingCompetitors && reviewedRows.length === 0 ? (
                  <tr>
                    <td colSpan={8}>
                      <WorkspaceEmptyStateCard compact={true}>
                        <p className="hint muted">No competitor rows are available yet. Suggest competitors or add manual seeds.</p>
                      </WorkspaceEmptyStateCard>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </WorkspaceTableShell>
        </SectionCard>

        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Advanced diagnostics"
            subtitle="Set, snapshot, and comparison workflow internals."
            headingLevel={2}
            variant="support"
          />
          <details data-testid="competitors-advanced-diagnostics">
            <summary>Show advanced diagnostics</summary>
            <WorkspaceMessageStack>
              <p className="hint muted">Competitor sets: {diagnostics?.competitor_set_count ?? 0} ({diagnostics?.active_set_count ?? 0} active)</p>
              <p className="hint muted">Latest generation run: {latestSuggestion?.run_id || "none"} ({latestSuggestion?.run_status || "none"})</p>
              <p className="hint muted">
                Latest snapshot run:{" "}
                {diagnostics?.latest_snapshot_run ? (
                  <>
                    <strong>{diagnostics.latest_snapshot_run.status}</strong> ({formatDateTime(diagnostics.latest_snapshot_run.completed_at || diagnostics.latest_snapshot_run.updated_at)}){" "}
                    <Link href={buildSnapshotRunHref(selectedSiteId, diagnostics.latest_snapshot_run.competitor_set_id, diagnostics.latest_snapshot_run.id)}>
                      Open
                    </Link>
                  </>
                ) : "none"}
              </p>
              <p className="hint muted">
                Latest comparison run:{" "}
                {diagnostics?.latest_comparison_run ? (
                  <>
                    <strong>{diagnostics.latest_comparison_run.status}</strong> ({formatDateTime(diagnostics.latest_comparison_run.completed_at || diagnostics.latest_comparison_run.updated_at)}){" "}
                    <Link href={buildComparisonRunHref(selectedSiteId, diagnostics.latest_comparison_run.competitor_set_id, diagnostics.latest_comparison_run.id)}>
                      Open
                    </Link>
                  </>
                ) : "none"}
              </p>
              {diagnostics?.latest_snapshot_run && diagnostics.latest_snapshot_run.status.toLowerCase() !== "completed" ? (
                <p className="hint warning">Latest snapshot run is not completed yet; snapshot-derived diagnostics may be stale.</p>
              ) : null}
            </WorkspaceMessageStack>
          </details>
        </SectionCard>
      </OperatorPageSectionStack>
    </PageContainer>
  );
}

export default function CompetitorsPage() {
  return (
    <Suspense
      fallback={(
        <PageContainer width="wide" density="compact">
          <SectionCard as="div" variant="support" className="role-surface-support">
            <SectionHeader
              title="Competitors"
              subtitle="Loading reviewed competitor list for your selected site."
              headingLevel={1}
              variant="support"
            />
          </SectionCard>
        </PageContainer>
      )}
    >
      <CompetitorsPageContent />
    </Suspense>
  );
}
