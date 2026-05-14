"use client";

import { Suspense, useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { PageContainer } from "../../components/layout/PageContainer";
import {
  OperatorPageHero,
  OperatorPageSectionStack,
} from "../../components/layout/OperatorPageSurface";
import { OperationalItemCard } from "../../components/layout/OperationalItemCard";
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
  createCompetitorDomainManualSeed,
  createCompetitorProfileGenerationRun,
  fetchCompetitorDomainFeedback,
  upsertCompetitorDomainFeedback,
  fetchCompetitorProfileGenerationRunDetail,
  fetchCompetitorProfileGenerationRuns,
  fetchCompetitorDomains,
  fetchCompetitorProfileGenerationSummary,
  fetchCompetitorSets,
  fetchCompetitorSnapshotRuns,
  fetchSiteCompetitorComparisonRuns,
} from "../../lib/api/client";
import type {
  CompetitorDomain,
  CompetitorDomainFeedback,
  CompetitorDomainFeedbackStatus,
  CompetitorGenerationQualityReason,
  CompetitorGenerationQualitySummary,
  CompetitorProfileGenerationSummaryResponse,
  CompetitorProfileGenerationRun,
  CompetitorSet,
  CompetitorSnapshotRun,
} from "../../lib/api/types";

interface CompetitorSetRow extends CompetitorSet {
  domain_count: number;
  active_domain_count: number;
  source_summary: string;
  latest_domain_updated_at: string | null;
  latest_snapshot_status: string | null;
}

interface CompetitorDomainReviewRow extends CompetitorDomain {
  competitor_set_name: string;
}

interface LatestSiteRun {
  id: string;
  competitor_set_id: string;
  competitor_set_name: string;
  status: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
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

function formatLocation(city: string | null, state: string | null): string {
  const locationParts = [city, state].filter((part) => Boolean(part && part.trim()));
  if (locationParts.length === 0) {
    return "-";
  }
  return locationParts.join(", ");
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
      return "You are not authorized to generate competitor sets.";
    }
    if (error.status === 404) {
      return "Selected site was not found for competitor generation.";
    }
    if (error.status === 422) {
      return "Competitor generation cannot start until site context is ready.";
    }
    if (error.status === 429) {
      return "Competitor generation is temporarily rate-limited. Try again shortly.";
    }
    if (error.status >= 500) {
      return "Competitor generation is temporarily unavailable. Try again shortly.";
    }
  }
  return "Unable to start competitor generation right now. Try again.";
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

function feedbackBadgeClass(status: CompetitorDomainFeedbackStatus | null): string {
  if (status === "useful") {
    return "badge-success";
  }
  if (status === "excluded" || status === "not_useful") {
    return "badge-warn";
  }
  if (status === "manually_seeded") {
    return "badge-muted";
  }
  return "badge-muted";
}

function classifyGenerationStartResponse(
  response: unknown,
): { classification: "success" | "unexpected_response"; message: string } {
  if (!response || typeof response !== "object") {
    return {
      classification: "unexpected_response",
      message:
        "Competitor generation request returned an unexpected response. Refresh inventory to confirm run status.",
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
        "Competitor generation request was accepted, but run details were incomplete. Refresh inventory to confirm status.",
    };
  }
  return {
    classification: "success",
    message: `Competitor generation started (run ${runId}, ${formatRunStatus(runStatus)}).`,
  };
}

function runActivityTimestamp(
  run: Pick<LatestSiteRun, "completed_at" | "updated_at" | "created_at">,
): number {
  const activityAt = run.completed_at || run.updated_at || run.created_at;
  const parsed = Date.parse(activityAt);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function latestByActivity<T extends Pick<LatestSiteRun, "completed_at" | "updated_at" | "created_at">>(
  runs: T[],
): T | null {
  if (runs.length === 0) {
    return null;
  }
  let latest = runs[0];
  let latestTimestamp = runActivityTimestamp(latest);
  for (let index = 1; index < runs.length; index += 1) {
    const candidate = runs[index];
    const candidateTimestamp = runActivityTimestamp(candidate);
    if (candidateTimestamp > latestTimestamp) {
      latest = candidate;
      latestTimestamp = candidateTimestamp;
    }
  }
  return latest;
}

function formatRunStatus(status: string): string {
  const cleaned = status.trim();
  return cleaned || "unknown";
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

function formatGenerationQualityReason(reason: CompetitorGenerationQualityReason | null): string {
  if (!reason) {
    return "unknown";
  }
  const labels: Record<CompetitorGenerationQualityReason, string> = {
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

function CompetitorsPageContent() {
  const router = useRouter();
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
  const [competitorSets, setCompetitorSets] = useState<CompetitorSetRow[]>([]);
  const [loadingCompetitors, setLoadingCompetitors] = useState(false);
  const [competitorsError, setCompetitorsError] = useState<string | null>(null);
  const [competitorSetCount, setCompetitorSetCount] = useState(0);
  const [latestSnapshotRun, setLatestSnapshotRun] = useState<LatestSiteRun | null>(null);
  const [latestComparisonRun, setLatestComparisonRun] = useState<LatestSiteRun | null>(null);
  const [readinessWarning, setReadinessWarning] = useState<string | null>(null);
  const [generationSummary, setGenerationSummary] = useState<CompetitorProfileGenerationSummaryResponse | null>(null);
  const [generationInFlight, setGenerationInFlight] = useState(false);
  const [generationMessage, setGenerationMessage] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [generationWarning, setGenerationWarning] = useState<string | null>(null);
  const [generationQualitySummary, setGenerationQualitySummary] = useState<CompetitorGenerationQualitySummary | null>(
    null,
  );
  const [latestGenerationRunStatus, setLatestGenerationRunStatus] = useState<string | null>(null);
  const [competitorDomains, setCompetitorDomains] = useState<CompetitorDomainReviewRow[]>([]);
  const [domainFeedbackByDomain, setDomainFeedbackByDomain] = useState<Record<string, CompetitorDomainFeedback>>({});
  const [feedbackInFlightDomain, setFeedbackInFlightDomain] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [manualSeedDomain, setManualSeedDomain] = useState("");
  const [manualSeedDisplayName, setManualSeedDisplayName] = useState("");
  const [manualSeedNote, setManualSeedNote] = useState("");
  const [manualSeedInFlight, setManualSeedInFlight] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const totalDomainCount = useMemo(
    () => competitorSets.reduce((total, item) => total + item.domain_count, 0),
    [competitorSets],
  );
  const activeSetCount = useMemo(
    () => competitorSets.filter((item) => item.is_active).length,
    [competitorSets],
  );
  const activeDomainCount = useMemo(
    () => competitorSets.reduce((total, item) => total + item.active_domain_count, 0),
    [competitorSets],
  );
  const manualSeedFeedbackItems = useMemo(
    () => Object.values(domainFeedbackByDomain)
      .filter((item) => item.feedback_status === "manually_seeded")
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
    [domainFeedbackByDomain],
  );
  const generationQueuedCount = generationSummary?.queued_count ?? 0;
  const generationRunningCount = generationSummary?.running_count ?? 0;
  const generationAlreadyRunning = generationQueuedCount + generationRunningCount > 0;
  const generationButtonLabel = activeSetCount > 0 ? "Refresh competitor set" : "Generate competitor set";
  const generationButtonDisabled = !selectedSiteId || generationInFlight;

  function buildSetDetailHref(setItem: CompetitorSetRow): string {
    const params = new URLSearchParams();
    params.set("site_id", setItem.site_id);
    return `/competitors/${setItem.id}?${params.toString()}`;
  }

  function buildSnapshotRunHref(run: LatestSiteRun): string {
    const params = new URLSearchParams();
    params.set("set_id", run.competitor_set_id);
    if (selectedSiteId) {
      params.set("site_id", selectedSiteId);
    }
    return `/competitors/snapshot-runs/${run.id}?${params.toString()}`;
  }

  function buildComparisonRunHref(run: LatestSiteRun): string {
    const params = new URLSearchParams();
    params.set("set_id", run.competitor_set_id);
    if (selectedSiteId) {
      params.set("site_id", selectedSiteId);
    }
    return `/competitors/comparison-runs/${run.id}?${params.toString()}`;
  }

  const readinessGuidance = useMemo(() => {
    if (contextLoading || loadingCompetitors) {
      return "Loading competitor readiness for this site.";
    }
    if (contextError || competitorsError) {
      return "Competitor readiness is temporarily unavailable due to a data-loading issue.";
    }
    if (!selectedSiteId) {
      return "No site is currently selected.";
    }
    if (competitorSetCount === 0) {
      return "This site has no competitor sets configured yet.";
    }
    if (totalDomainCount === 0) {
      return "Competitor sets exist, but no competitor domains are configured yet.";
    }
    if (!latestSnapshotRun) {
      return "Competitor domains exist, but no snapshot run has been recorded yet.";
    }
    if (formatRunStatus(latestSnapshotRun.status).toLowerCase() !== "completed") {
      return `Latest snapshot run is ${formatRunStatus(latestSnapshotRun.status)}. Comparison results may not be available yet.`;
    }
    if (!latestComparisonRun) {
      return "Snapshot results exist, but no comparison run has been recorded yet.";
    }
    if (formatRunStatus(latestComparisonRun.status).toLowerCase() !== "completed") {
      return `Latest comparison run is ${formatRunStatus(latestComparisonRun.status)}. Findings may still be in progress.`;
    }
    return "This site has configured competitor data and recent comparison activity.";
  }, [
    competitorSetCount,
    competitorsError,
    contextError,
    contextLoading,
    latestComparisonRun,
    latestSnapshotRun,
    loadingCompetitors,
    selectedSiteId,
    totalDomainCount,
  ]);

  const tableEmptyReason = useMemo(() => {
    if (competitorsError) {
      return "Competitor data is currently unavailable for this site.";
    }
    if (!selectedSiteId) {
      return "No site is selected. Choose a site to inspect competitors.";
    }
    if (competitorSetCount === 0) {
      return "This site has no competitor sets configured yet.";
    }
    return "Competitor sets are configured, but none are currently visible.";
  }, [competitorSetCount, competitorsError, selectedSiteId]);

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
      setCompetitorSets([]);
      setCompetitorSetCount(0);
      setLatestSnapshotRun(null);
      setLatestComparisonRun(null);
      setReadinessWarning(null);
      setCompetitorsError(null);
      setLoadingCompetitors(false);
      setGenerationSummary(null);
      setGenerationQualitySummary(null);
      setLatestGenerationRunStatus(null);
      setCompetitorDomains([]);
      setDomainFeedbackByDomain({});
      return;
    }
    let cancelled = false;
    const activeSiteId = selectedSiteId;

    async function loadCompetitors() {
      setLoadingCompetitors(true);
      setCompetitorsError(null);
      setLatestSnapshotRun(null);
      setLatestComparisonRun(null);
      setReadinessWarning(null);
      try {
        let nextGenerationSummary: CompetitorProfileGenerationSummaryResponse | null = null;
        let nextGenerationQualitySummary: CompetitorGenerationQualitySummary | null = null;
        let nextLatestGenerationRunStatus: string | null = null;
        try {
          nextGenerationSummary = await fetchCompetitorProfileGenerationSummary(
            token,
            businessId,
            activeSiteId,
          );
        } catch {
          nextGenerationSummary = null;
        }
        try {
          const generationRuns = await fetchCompetitorProfileGenerationRuns(
            token,
            businessId,
            activeSiteId,
          );
          const latestGenerationRun = latestByActivity<CompetitorProfileGenerationRun>(generationRuns.items);
          if (latestGenerationRun) {
            nextLatestGenerationRunStatus = latestGenerationRun.status;
            const normalizedStatus = latestGenerationRun.status.trim().toLowerCase();
            if (normalizedStatus === "completed" || normalizedStatus === "failed") {
              const generationDetail = await fetchCompetitorProfileGenerationRunDetail(
                token,
                businessId,
                activeSiteId,
                latestGenerationRun.id,
              );
              nextGenerationQualitySummary = generationDetail.quality_summary ?? null;
            }
          }
        } catch {
          nextGenerationQualitySummary = null;
          nextLatestGenerationRunStatus = null;
        }
        if (!cancelled) {
          setGenerationSummary(nextGenerationSummary);
          setGenerationQualitySummary(nextGenerationQualitySummary);
          setLatestGenerationRunStatus(nextLatestGenerationRunStatus);
        }

        let nextDomainFeedbackByDomain: Record<string, CompetitorDomainFeedback> = {};
        try {
          const feedbackResponse = await fetchCompetitorDomainFeedback(
            token,
            businessId,
            activeSiteId,
          );
          nextDomainFeedbackByDomain = feedbackResponse.items.reduce<Record<string, CompetitorDomainFeedback>>(
            (accumulator, item) => {
              const domainKey = normalizeDomainForFeedback(item.domain);
              if (!domainKey || accumulator[domainKey]) {
                return accumulator;
              }
              accumulator[domainKey] = item;
              return accumulator;
            },
            {},
          );
        } catch {
          nextDomainFeedbackByDomain = {};
        }

        const setResponse = await fetchCompetitorSets(token, businessId, activeSiteId);
        if (cancelled) {
          return;
        }

        setCompetitorSetCount(setResponse.total);
        if (setResponse.items.length === 0) {
          setCompetitorSets([]);
          setCompetitorDomains([]);
          setDomainFeedbackByDomain(nextDomainFeedbackByDomain);
          return;
        }

        let snapshotStatusUnavailable = false;
        const setNameById = new Map<string, string>();
        for (const setItem of setResponse.items) {
          setNameById.set(setItem.id, setItem.name);
        }

        const setDetails = await Promise.all(
          setResponse.items.map(async (setItem) => {
            const domainsResponse = await fetchCompetitorDomains(
              token,
              businessId,
              setItem.id,
            );
            let latestSnapshotCandidate: CompetitorSnapshotRun | null = null;
            try {
              const snapshotRunsResponse = await fetchCompetitorSnapshotRuns(
                token,
                businessId,
                setItem.id,
              );
              latestSnapshotCandidate = latestByActivity(snapshotRunsResponse.items);
            } catch {
              snapshotStatusUnavailable = true;
            }
            const sourceSet = new Set<string>();
            let latestDomainUpdatedAt: string | null = null;
            let activeDomainCount = 0;

            for (const domain of domainsResponse.items) {
              if (domain.source.trim()) {
                sourceSet.add(domain.source.trim());
              }
              if (domain.is_active) {
                activeDomainCount += 1;
              }
              if (!latestDomainUpdatedAt || domain.updated_at > latestDomainUpdatedAt) {
                latestDomainUpdatedAt = domain.updated_at;
              }
            }

            return {
              row: {
                ...setItem,
                domain_count: domainsResponse.total,
                active_domain_count: activeDomainCount,
                source_summary: sourceSet.size > 0 ? [...sourceSet].sort().join(", ") : "-",
                latest_domain_updated_at: latestDomainUpdatedAt,
                latest_snapshot_status: latestSnapshotCandidate ? latestSnapshotCandidate.status : null,
              },
              domains: domainsResponse.items.map((domain) => ({
                ...domain,
                competitor_set_name: setItem.name,
              })),
              latestSnapshotCandidate,
            };
          }),
        );

        const rows = setDetails.map((item) => item.row);
        const domainRows = setDetails
          .flatMap((item) => item.domains)
          .sort((left, right) => left.domain.localeCompare(right.domain));
        let nextLatestSnapshotRun: LatestSiteRun | null = null;
        let nextLatestComparisonRun: LatestSiteRun | null = null;
        let nextReadinessWarning: string | null = null;
        const latestSnapshotCandidate = latestByActivity(
          setDetails
            .map((item) => item.latestSnapshotCandidate)
            .filter((item): item is CompetitorSnapshotRun => item !== null),
        );
        if (latestSnapshotCandidate) {
          nextLatestSnapshotRun = {
            id: latestSnapshotCandidate.id,
            competitor_set_id: latestSnapshotCandidate.competitor_set_id,
            competitor_set_name:
              setNameById.get(latestSnapshotCandidate.competitor_set_id) ||
              latestSnapshotCandidate.competitor_set_id,
            status: latestSnapshotCandidate.status,
            created_at: latestSnapshotCandidate.created_at,
            updated_at: latestSnapshotCandidate.updated_at,
            completed_at: latestSnapshotCandidate.completed_at,
          };
        }

        let comparisonStatusUnavailable = false;
        try {
          const comparisonRunsResponse = await fetchSiteCompetitorComparisonRuns(
            token,
            businessId,
            activeSiteId,
          );
          const latestComparisonCandidate = latestByActivity(comparisonRunsResponse.items);
          if (latestComparisonCandidate) {
            nextLatestComparisonRun = {
              id: latestComparisonCandidate.id,
              competitor_set_id: latestComparisonCandidate.competitor_set_id,
              competitor_set_name:
                setNameById.get(latestComparisonCandidate.competitor_set_id) ||
                latestComparisonCandidate.competitor_set_id,
              status: latestComparisonCandidate.status,
              created_at: latestComparisonCandidate.created_at,
              updated_at: latestComparisonCandidate.updated_at,
              completed_at: latestComparisonCandidate.completed_at,
            };
          }
        } catch {
          comparisonStatusUnavailable = true;
        }

        if (snapshotStatusUnavailable && comparisonStatusUnavailable) {
          nextReadinessWarning = "Snapshot and comparison run status are temporarily unavailable.";
        } else if (snapshotStatusUnavailable) {
          nextReadinessWarning = "Snapshot run status is temporarily unavailable.";
        } else if (comparisonStatusUnavailable) {
          nextReadinessWarning = "Comparison run status is temporarily unavailable.";
        }

        if (!cancelled) {
          setLatestSnapshotRun(nextLatestSnapshotRun);
          setLatestComparisonRun(nextLatestComparisonRun);
          setReadinessWarning(nextReadinessWarning);
          setCompetitorSets(rows);
          setCompetitorDomains(domainRows);
          setDomainFeedbackByDomain(nextDomainFeedbackByDomain);
        }
      } catch (err) {
        if (!cancelled) {
          setCompetitorsError(safeCompetitorErrorMessage(err));
        }
      } finally {
        if (!cancelled) {
          setLoadingCompetitors(false);
        }
      }
    }
    void loadCompetitors();
    return () => {
      cancelled = true;
    };
  }, [businessId, contextError, contextLoading, refreshNonce, selectedSiteId, token]);

  const handleGenerateCompetitorSet = useCallback(async () => {
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
    } catch (err) {
      setGenerationError(safeGenerationErrorMessage(err));
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
      setFeedbackMessage(
        `Saved feedback for ${responseDomain}: ${formatFeedbackStatusLabel(responseStatus)}.`,
      );
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
            title="Competitor Intelligence"
            subtitle="Loading competitor set readiness for your selected site."
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
            title="Competitor Intelligence"
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
            title="Competitor Intelligence"
            subtitle="No SEO sites are configured yet. Add a site first to view competitors."
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
        title="Competitor Intelligence"
        subtitle="Track competitor set readiness, run status, and domain coverage for the selected site."
        headingLevel={1}
        data-testid="competitors-page-hero"
        actions={(
          <button
            type="button"
            className="button button-primary"
            onClick={() => {
              void handleGenerateCompetitorSet();
            }}
            disabled={generationButtonDisabled}
            data-testid="competitors-generate-set-button"
          >
            {generationInFlight ? "Generating competitor set..." : generationButtonLabel}
          </button>
        )}
        summary={(
          <>
            <SummaryStatCard
              label="Competitor sets"
              value={competitorSetCount}
              detail={`${activeSetCount} active`}
              tone={competitorSetCount > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Domains"
              value={totalDomainCount}
              detail={`${activeDomainCount} active domains`}
              tone={totalDomainCount > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Snapshot status"
              value={latestSnapshotRun ? formatRunStatus(latestSnapshotRun.status) : "none"}
              detail={latestSnapshotRun ? latestSnapshotRun.competitor_set_name : "No snapshot run yet"}
              tone={
                latestSnapshotRun?.status?.toLowerCase() === "completed"
                  ? "success"
                  : latestSnapshotRun
                    ? "warning"
                    : "neutral"
              }
              variant="elevated"
            />
            <SummaryStatCard
              label="Comparison status"
              value={latestComparisonRun ? formatRunStatus(latestComparisonRun.status) : "none"}
              detail={latestComparisonRun ? latestComparisonRun.competitor_set_name : "No comparison run yet"}
              tone={
                latestComparisonRun?.status?.toLowerCase() === "completed"
                  ? "success"
                  : latestComparisonRun
                    ? "warning"
                : "neutral"
              }
              variant="elevated"
            />
          </>
        )}
      >
        <WorkspaceMessageStack data-testid="competitors-generation-guidance">
          <p className="hint muted">
            Generate a reviewed competitor set for the selected site using existing site, audit, and business context.
          </p>
          {generationInFlight ? (
            <p className="hint muted" data-testid="competitors-generation-pending">
              {activeSetCount > 0 ? "Refreshing competitor set..." : "Generating competitor set..."}
            </p>
          ) : null}
          {generationAlreadyRunning ? (
            <p className="hint muted" data-testid="competitors-generation-running">
              A competitor generation run is already queued or running for this site.
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
        </WorkspaceMessageStack>
      </OperatorPageHero>

      <OperatorPageSectionStack>
        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="Competitor set inventory"
            subtitle="Review readiness diagnostics and open competitor sets, snapshot runs, and comparison runs."
            headingLevel={2}
            variant="support"
          />

          <div className="panel stack section-card-variant-support">
            <h2 className="heading-reset">Readiness</h2>
            <WorkspaceMetadataGrid>
              <WorkspaceMetadataItem label="Active Sets">
                <span className="hint muted">{activeSetCount}/{competitorSetCount}</span>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Competitor Domains">
                <span className="hint muted">{totalDomainCount}</span>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Active Domains">
                <span className="hint muted">{activeDomainCount}</span>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Latest Snapshot Run">
                {latestSnapshotRun ? (
                  <span className="hint muted">
                    <strong>{formatRunStatus(latestSnapshotRun.status)}</strong>{" "}
                    ({formatDateTime(latestSnapshotRun.completed_at || latestSnapshotRun.updated_at || latestSnapshotRun.created_at)})
                    {" "}for {latestSnapshotRun.competitor_set_name}{" "}
                    <Link href={buildSnapshotRunHref(latestSnapshotRun)}>View</Link>
                  </span>
                ) : (
                  <span className="hint muted">none</span>
                )}
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Latest Comparison Run">
                {latestComparisonRun ? (
                  <span className="hint muted">
                    <strong>{formatRunStatus(latestComparisonRun.status)}</strong>{" "}
                    ({formatDateTime(latestComparisonRun.completed_at || latestComparisonRun.updated_at || latestComparisonRun.created_at)})
                    {" "}for {latestComparisonRun.competitor_set_name}{" "}
                    <Link href={buildComparisonRunHref(latestComparisonRun)}>View</Link>
                  </span>
                ) : (
                  <span className="hint muted">none</span>
                )}
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Generation Quality">
                {generationQualitySummary ? (
                  <span className="hint muted" data-testid="competitors-generation-quality">
                    <strong>{formatGenerationQualityStatus(generationQualitySummary.status)}</strong>{" "}
                    ({generationQualitySummary.accepted_candidates}/{generationQualitySummary.total_candidates_returned} accepted,{" "}
                    {generationQualitySummary.rejected_candidates} rejected)
                    {generationQualitySummary.top_reason ? (
                      <>. Reason: {formatGenerationQualityReason(generationQualitySummary.top_reason)}</>
                    ) : null}
                  </span>
                ) : latestGenerationRunStatus ? (
                  <span className="hint muted" data-testid="competitors-generation-quality-pending">
                    Quality pending. Latest generation run is {formatRunStatus(latestGenerationRunStatus)}.
                  </span>
                ) : (
                  <span className="hint muted">none</span>
                )}
              </WorkspaceMetadataItem>
            </WorkspaceMetadataGrid>
            <WorkspaceMessageStack>
              {readinessWarning ? <p className="hint warning">{readinessWarning}</p> : null}
              {generationQualitySummary?.status === "partial" ? (
                <p className="hint warning" data-testid="competitors-generation-quality-message">
                  {generationQualitySummary.operator_message}
                </p>
              ) : null}
              {generationQualitySummary?.status === "blocked" ? (
                <p className="hint error" data-testid="competitors-generation-quality-message">
                  {generationQualitySummary.operator_message}
                </p>
              ) : null}
              <p className="hint muted">{readinessGuidance}</p>
            </WorkspaceMessageStack>
          </div>

          <WorkspaceActionBar variant="secondary">
            <span className="hint muted">Competitor Sets: {competitorSetCount}</span>
            <span className="hint muted">Domains Across Sets: {totalDomainCount}</span>
          </WorkspaceActionBar>

          <div className="stack" data-testid="competitor-quick-scan">
            <h3 className="heading-reset">Set quick scan</h3>
            <p className="hint muted">
              Summary-first cards highlight readiness and the next set to review before opening full tables.
            </p>
            {competitorSets.length === 0 && !loadingCompetitors ? (
              <WorkspaceEmptyStateCard compact={true}>
                <p className="hint muted">No competitor sets available for quick scan.</p>
              </WorkspaceEmptyStateCard>
            ) : null}
            {competitorSets.length > 0 ? (
              <div className="operational-item-list">
                {competitorSets.slice(0, 6).map((item) => {
                  const snapshotStatus = item.latest_snapshot_status
                    ? formatRunStatus(item.latest_snapshot_status)
                    : "No snapshot";
                  return (
                    <OperationalItemCard
                      key={`competitor-quick-scan-${item.id}`}
                      data-testid={`competitor-quick-scan-item-${item.id}`}
                      title={`Set: ${item.name}`}
                      identity={<code>{item.id}</code>}
                      chips={(
                        <>
                          <span className={`badge ${item.is_active ? "badge-success" : "badge-muted"}`}>
                            {item.is_active ? "Active set" : "Inactive set"}
                          </span>
                          <span className="badge badge-muted">{item.active_domain_count}/{item.domain_count} active domains</span>
                          <span className={`badge ${snapshotStatus.toLowerCase() === "completed" ? "badge-success" : "badge-warn"}`}>
                            Snapshot: {snapshotStatus}
                          </span>
                        </>
                      )}
                      summary={`Location: ${formatLocation(item.city, item.state)}. Provenance: ${item.source_summary}.`}
                      primaryAction={
                        <Link href={buildSetDetailHref(item)} className="button button-tertiary button-inline">
                          Open set detail
                        </Link>
                      }
                      secondaryMeta={
                        <>
                          <span className="hint muted">Latest domain update: {formatDateTime(item.latest_domain_updated_at)}</span>
                        </>
                      }
                      expandedDetail={
                        <>
                          <p className="hint muted">
                            <span className="text-strong">Business:</span> {item.business_id}
                          </p>
                          <p className="hint muted">
                            <span className="text-strong">Site:</span> {item.site_id}
                          </p>
                          <p className="hint muted">
                            <span className="text-strong">Created:</span> {formatDateTime(item.created_at)}
                          </p>
                          <p className="hint muted">
                            <span className="text-strong">Updated:</span> {formatDateTime(item.updated_at)}
                          </p>
                        </>
                      }
                    />
                  );
                })}
              </div>
            ) : null}
          </div>

          <div className="panel stack section-card-variant-support" data-testid="competitor-feedback-panel">
            <h3 className="heading-reset">Operator review and corrections</h3>
            <p className="hint muted">
              Mark accepted competitor domains as useful or not useful, exclude bad domains from future generation,
              and seed known competitors for this site.
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

            {manualSeedFeedbackItems.length > 0 ? (
              <p className="hint muted" data-testid="competitors-manual-seed-list">
                Manual seeds:{" "}
                {manualSeedFeedbackItems.map((item) => item.domain).join(", ")}
              </p>
            ) : null}

            {(feedbackMessage || feedbackError) ? (
              <WorkspaceMessageStack>
                {feedbackMessage ? (
                  <p className="hint" data-testid="competitors-feedback-success">{feedbackMessage}</p>
                ) : null}
                {feedbackError ? (
                  <p className="hint error" data-testid="competitors-feedback-error">{feedbackError}</p>
                ) : null}
              </WorkspaceMessageStack>
            ) : null}

            <WorkspaceTableShell data-testid="competitors-domain-feedback-table-shell">
              <table className="table table-dense">
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>Set</th>
                    <th>Current feedback</th>
                    <th>Updated</th>
                    <th>Review actions</th>
                  </tr>
                </thead>
                <tbody>
                  {competitorDomains.map((domainItem) => {
                    const domainKey = normalizeDomainForFeedback(domainItem.domain);
                    const feedbackItem = domainFeedbackByDomain[domainKey] || null;
                    const feedbackStatus = feedbackItem?.feedback_status ?? null;
                    const actionDisabled = feedbackInFlightDomain === domainKey || manualSeedInFlight || !selectedSiteId;
                    return (
                      <tr key={domainItem.id} data-testid={`competitor-domain-feedback-row-${domainItem.id}`}>
                        <td>
                          <strong>{domainItem.domain}</strong>
                          {domainItem.display_name ? <><br /><span className="hint muted">{domainItem.display_name}</span></> : null}
                        </td>
                        <td>{domainItem.competitor_set_name}</td>
                        <td>
                          <span className={`badge ${feedbackBadgeClass(feedbackStatus)}`}>
                            {formatFeedbackStatusLabel(feedbackStatus)}
                          </span>
                        </td>
                        <td>{formatDateTime(feedbackItem?.updated_at || domainItem.updated_at)}</td>
                        <td>
                          <div
                            className="form-actions competitor-feedback-action-group"
                            data-testid={`competitor-domain-feedback-actions-${domainItem.id}`}
                          >
                            <button
                              type="button"
                              className="button button-tertiary button-inline"
                              disabled={actionDisabled}
                              onClick={() => {
                                void handleDomainFeedbackUpdate(domainItem.domain, "useful", domainItem.display_name);
                              }}
                            >
                              Mark useful
                            </button>
                            <button
                              type="button"
                              className="button button-tertiary button-inline"
                              disabled={actionDisabled}
                              onClick={() => {
                                void handleDomainFeedbackUpdate(domainItem.domain, "not_useful", domainItem.display_name);
                              }}
                            >
                              Mark not useful
                            </button>
                            <button
                              type="button"
                              className="button button-tertiary button-inline"
                              disabled={actionDisabled}
                              onClick={() => {
                                void handleDomainFeedbackUpdate(domainItem.domain, "excluded", domainItem.display_name);
                              }}
                            >
                              Exclude
                            </button>
                          </div>
                          {feedbackInFlightDomain === domainKey ? (
                            <span className="hint muted">Updating feedback...</span>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                  {!loadingCompetitors && competitorDomains.length === 0 ? (
                    <tr>
                      <td colSpan={5}>No competitor domains are available yet for review.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </WorkspaceTableShell>
          </div>

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
                  <th>Set</th>
                  <th>Business</th>
                  <th>Site</th>
                  <th>Location</th>
                  <th>Status</th>
                  <th>Domains</th>
                  <th>Provenance</th>
                  <th>Created By</th>
                  <th>Created</th>
                  <th>Updated</th>
                  <th>Latest Domain Update</th>
                </tr>
              </thead>
              <tbody>
                {competitorSets.map((item) => (
                  <tr
                    key={item.id}
                    role="link"
                    tabIndex={0}
                    className="clickable-row"
                    onClick={() => router.push(buildSetDetailHref(item))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        router.push(buildSetDetailHref(item));
                      }
                    }}
                  >
                    <td>
                      <strong>{item.name}</strong>
                      <br />
                      <span className="hint muted">{item.id}</span>
                    </td>
                    <td>{item.business_id}</td>
                    <td>{item.site_id}</td>
                    <td>{formatLocation(item.city, item.state)}</td>
                    <td>{item.is_active ? "active" : "inactive"}</td>
                    <td>
                      {item.active_domain_count}/{item.domain_count} active
                    </td>
                    <td>{item.source_summary}</td>
                    <td>{item.created_by_principal_id || "-"}</td>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{formatDateTime(item.updated_at)}</td>
                    <td>{formatDateTime(item.latest_domain_updated_at)}</td>
                  </tr>
                ))}
                {!loadingCompetitors && competitorSets.length === 0 ? (
                  <tr>
                    <td colSpan={11}>
                      {tableEmptyReason}
                    </td>
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

export default function CompetitorsPage() {
  return (
    <Suspense
      fallback={(
        <PageContainer width="wide" density="compact">
          <SectionCard as="div" variant="support" className="role-surface-support">
            <SectionHeader
              title="Competitor Intelligence"
              subtitle="Loading competitor set readiness for your selected site."
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
