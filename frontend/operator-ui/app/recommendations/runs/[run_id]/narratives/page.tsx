"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useOperatorContext } from "../../../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchRecommendationRunNarratives,
  fetchRecommendationRunReport,
} from "../../../../../lib/api/client";
import type {
  Recommendation,
  RecommendationNarrative,
  RecommendationRun,
  RecommendationRunReport,
} from "../../../../../lib/api/types";

const RECOMMENDATION_PREVIEW_LIMIT = 25;
const RECOMMENDATION_RATIONALE_PREVIEW_LIMIT = 140;
const RECOMMENDATION_PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

type NarrativeChangeType = "added" | "removed" | "changed";

interface NarrativeSectionDiffEntry {
  section_name: string;
  change_type: NarrativeChangeType;
  base_value: unknown;
  compare_value: unknown;
}

interface NarrativeTextDiffEntry {
  paragraph_index: number;
  change_type: NarrativeChangeType;
  base_text: string;
  compare_text: string;
}

interface NarrativeComparisonResult {
  structured_available: boolean;
  section_entries: NarrativeSectionDiffEntry[];
  section_added_count: number;
  section_removed_count: number;
  section_changed_count: number;
  text_entries: NarrativeTextDiffEntry[];
  text_added_count: number;
  text_removed_count: number;
  text_changed_count: number;
  added_themes: string[];
  removed_themes: string[];
  recommendation_impact_available: boolean;
  added_recommendation_ids: string[];
  removed_recommendation_ids: string[];
  unchanged_recommendation_ids: string[];
  has_differences: boolean;
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

function truncateText(value: string, limit: number): string {
  const normalized = value.trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit - 1)}…`;
}

function formatStructuredValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function stableSerialize(value: unknown): string {
  if (value === null) {
    return "null";
  }
  if (typeof value === "undefined") {
    return "undefined";
  }
  if (typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(",")}]`;
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .sort((left, right) => left[0].localeCompare(right[0]))
    .map(([key, nestedValue]) => `${JSON.stringify(key)}:${stableSerialize(nestedValue)}`);
  return `{${entries.join(",")}}`;
}

function toSectionRecord(value: RecommendationNarrative["sections_json"]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

function splitNarrativeParagraphs(value: string | null): string[] {
  if (!value) {
    return [];
  }
  const normalized = value.replace(/\r\n/g, "\n").trim();
  if (!normalized) {
    return [];
  }
  const paragraphs = normalized
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
  return paragraphs.length > 0 ? paragraphs : [normalized];
}

function collectRecommendationIdsFromValue(
  value: unknown,
  knownRecommendationIds: Set<string>,
  collected: Set<string>,
): void {
  if (typeof value === "string") {
    const normalized = value.trim();
    if (knownRecommendationIds.has(normalized)) {
      collected.add(normalized);
    }
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      collectRecommendationIdsFromValue(item, knownRecommendationIds, collected);
    }
    return;
  }
  if (value && typeof value === "object") {
    for (const nestedValue of Object.values(value as Record<string, unknown>)) {
      collectRecommendationIdsFromValue(nestedValue, knownRecommendationIds, collected);
    }
  }
}

function isNotFoundError(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 404;
}

function safeNarrativeHistoryErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view recommendation narratives for this run.";
    }
    if (error.status === 404) {
      return "Recommendation run narrative history was not found in your tenant scope.";
    }
  }
  return "Unable to load recommendation narrative history right now. Please try again.";
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

function buildRecommendationDetailHref(item: Recommendation): string {
  const params = new URLSearchParams();
  params.set("site_id", item.site_id);
  return `/recommendations/${item.id}?${params.toString()}`;
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

function buildParentRunHref(
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
    ? `/recommendations/runs/${recommendationRunId}?${query}`
    : `/recommendations/runs/${recommendationRunId}`;
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

function buildComparisonRunHref(comparisonRunId: string, siteId: string): string {
  const params = new URLSearchParams();
  if (siteId) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query ? `/competitors/comparison-runs/${comparisonRunId}?${query}` : `/competitors/comparison-runs/${comparisonRunId}`;
}

export default function RecommendationRunNarrativeHistoryPage() {
  const params = useParams<{ run_id: string }>();
  const searchParams = useSearchParams();
  const recommendationRunId = (params?.run_id || "").trim();
  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const context = useOperatorContext();

  const queueContextParams = useMemo(() => parseQueueContextSearchParams(searchParams), [searchParams]);

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
  const [narratives, setNarratives] = useState<RecommendationNarrative[]>([]);
  const [resolvedSiteId, setResolvedSiteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [selectedBaseNarrativeId, setSelectedBaseNarrativeId] = useState<string | null>(null);
  const [selectedCompareNarrativeId, setSelectedCompareNarrativeId] = useState<string | null>(null);

  const run: RecommendationRun | null = report?.recommendation_run || null;

  const parentRunHref = useMemo(() => {
    if (!recommendationRunId) {
      return "/recommendations";
    }
    const siteId = run?.site_id || resolvedSiteId || requestedSiteId;
    return buildParentRunHref(recommendationRunId, siteId || "", queueContextParams);
  }, [queueContextParams, recommendationRunId, requestedSiteId, resolvedSiteId, run?.site_id]);

  const sortedNarratives = useMemo(() => {
    return [...narratives].sort((left, right) => {
      if (right.version !== left.version) {
        return right.version - left.version;
      }
      return right.created_at.localeCompare(left.created_at);
    });
  }, [narratives]);

  const latestNarrative = sortedNarratives[0] || null;

  const selectedBaseNarrative = useMemo(() => {
    if (sortedNarratives.length === 0) {
      return null;
    }
    if (selectedBaseNarrativeId) {
      const matched = sortedNarratives.find((item) => item.id === selectedBaseNarrativeId);
      if (matched) {
        return matched;
      }
    }
    return sortedNarratives[0];
  }, [selectedBaseNarrativeId, sortedNarratives]);

  const selectedCompareNarrative = useMemo(() => {
    if (sortedNarratives.length < 2) {
      return null;
    }
    if (selectedCompareNarrativeId) {
      const matched = sortedNarratives.find((item) => item.id === selectedCompareNarrativeId);
      if (matched) {
        return matched;
      }
    }
    const fallback =
      sortedNarratives.find((item) => item.id !== selectedBaseNarrative?.id) || sortedNarratives[1];
    return fallback || null;
  }, [selectedBaseNarrative?.id, selectedCompareNarrativeId, sortedNarratives]);

  const selectedSiteDisplayName = useMemo(() => {
    if (!run) {
      return null;
    }
    const match = context.sites.find((site) => site.id === run.site_id);
    return match?.display_name || null;
  }, [context.sites, run]);

  const producedRecommendations = useMemo(() => {
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

  const producedRecommendationsById = useMemo(() => {
    const byId = new Map<string, Recommendation>();
    for (const item of report?.recommendations.items || []) {
      byId.set(item.id, item);
    }
    return byId;
  }, [report?.recommendations.items]);

  const knownRecommendationIds = useMemo(
    () => new Set(producedRecommendationsById.keys()),
    [producedRecommendationsById],
  );

  const narrativeComparison = useMemo<NarrativeComparisonResult | null>(() => {
    if (!selectedBaseNarrative || !selectedCompareNarrative) {
      return null;
    }

    const baseSections = toSectionRecord(selectedBaseNarrative.sections_json);
    const compareSections = toSectionRecord(selectedCompareNarrative.sections_json);
    const structuredAvailable = Object.keys(baseSections).length > 0 || Object.keys(compareSections).length > 0;

    const sectionEntries: NarrativeSectionDiffEntry[] = [];
    let sectionAddedCount = 0;
    let sectionRemovedCount = 0;
    let sectionChangedCount = 0;

    const sectionNames = Array.from(new Set([...Object.keys(baseSections), ...Object.keys(compareSections)])).sort(
      (left, right) => left.localeCompare(right),
    );
    for (const sectionName of sectionNames) {
      const hasBaseValue = Object.prototype.hasOwnProperty.call(baseSections, sectionName);
      const hasCompareValue = Object.prototype.hasOwnProperty.call(compareSections, sectionName);
      const baseValue = hasBaseValue ? baseSections[sectionName] : null;
      const compareValue = hasCompareValue ? compareSections[sectionName] : null;

      if (hasBaseValue && !hasCompareValue) {
        sectionAddedCount += 1;
        sectionEntries.push({
          section_name: sectionName,
          change_type: "added",
          base_value: baseValue,
          compare_value: null,
        });
        continue;
      }
      if (!hasBaseValue && hasCompareValue) {
        sectionRemovedCount += 1;
        sectionEntries.push({
          section_name: sectionName,
          change_type: "removed",
          base_value: null,
          compare_value: compareValue,
        });
        continue;
      }

      if (stableSerialize(baseValue) !== stableSerialize(compareValue)) {
        sectionChangedCount += 1;
        sectionEntries.push({
          section_name: sectionName,
          change_type: "changed",
          base_value: baseValue,
          compare_value: compareValue,
        });
      }
    }

    const baseParagraphs = splitNarrativeParagraphs(selectedBaseNarrative.narrative_text);
    const compareParagraphs = splitNarrativeParagraphs(selectedCompareNarrative.narrative_text);
    const maxParagraphs = Math.max(baseParagraphs.length, compareParagraphs.length);
    const textEntries: NarrativeTextDiffEntry[] = [];
    let textAddedCount = 0;
    let textRemovedCount = 0;
    let textChangedCount = 0;

    for (let index = 0; index < maxParagraphs; index += 1) {
      const baseText = baseParagraphs[index] || "";
      const compareText = compareParagraphs[index] || "";
      const hasBase = baseText.length > 0;
      const hasCompare = compareText.length > 0;

      if (hasBase && !hasCompare) {
        textAddedCount += 1;
        textEntries.push({
          paragraph_index: index + 1,
          change_type: "added",
          base_text: baseText,
          compare_text: "",
        });
        continue;
      }
      if (!hasBase && hasCompare) {
        textRemovedCount += 1;
        textEntries.push({
          paragraph_index: index + 1,
          change_type: "removed",
          base_text: "",
          compare_text: compareText,
        });
        continue;
      }
      if (hasBase && hasCompare && baseText !== compareText) {
        textChangedCount += 1;
        textEntries.push({
          paragraph_index: index + 1,
          change_type: "changed",
          base_text: baseText,
          compare_text: compareText,
        });
      }
    }

    const normalizedBaseThemes = [...new Set(selectedBaseNarrative.top_themes_json.map((item) => item.trim()).filter(Boolean))];
    const normalizedCompareThemes = [...new Set(selectedCompareNarrative.top_themes_json.map((item) => item.trim()).filter(Boolean))];
    const compareThemeSet = new Set(normalizedCompareThemes);
    const baseThemeSet = new Set(normalizedBaseThemes);
    const addedThemes = normalizedBaseThemes.filter((item) => !compareThemeSet.has(item));
    const removedThemes = normalizedCompareThemes.filter((item) => !baseThemeSet.has(item));

    const baseRecommendationIds = new Set<string>();
    const compareRecommendationIds = new Set<string>();
    collectRecommendationIdsFromValue(selectedBaseNarrative.sections_json, knownRecommendationIds, baseRecommendationIds);
    collectRecommendationIdsFromValue(selectedCompareNarrative.sections_json, knownRecommendationIds, compareRecommendationIds);

    const addedRecommendationIds = [...baseRecommendationIds]
      .filter((item) => !compareRecommendationIds.has(item))
      .sort((left, right) => left.localeCompare(right));
    const removedRecommendationIds = [...compareRecommendationIds]
      .filter((item) => !baseRecommendationIds.has(item))
      .sort((left, right) => left.localeCompare(right));
    const unchangedRecommendationIds = [...baseRecommendationIds]
      .filter((item) => compareRecommendationIds.has(item))
      .sort((left, right) => left.localeCompare(right));
    const recommendationImpactAvailable =
      baseRecommendationIds.size > 0 || compareRecommendationIds.size > 0;

    const hasDifferences =
      sectionEntries.length > 0 ||
      textEntries.length > 0 ||
      addedThemes.length > 0 ||
      removedThemes.length > 0 ||
      addedRecommendationIds.length > 0 ||
      removedRecommendationIds.length > 0;

    return {
      structured_available: structuredAvailable,
      section_entries: sectionEntries,
      section_added_count: sectionAddedCount,
      section_removed_count: sectionRemovedCount,
      section_changed_count: sectionChangedCount,
      text_entries: textEntries,
      text_added_count: textAddedCount,
      text_removed_count: textRemovedCount,
      text_changed_count: textChangedCount,
      added_themes: addedThemes,
      removed_themes: removedThemes,
      recommendation_impact_available: recommendationImpactAvailable,
      added_recommendation_ids: addedRecommendationIds,
      removed_recommendation_ids: removedRecommendationIds,
      unchanged_recommendation_ids: unchangedRecommendationIds,
      has_differences: hasDifferences,
    };
  }, [knownRecommendationIds, selectedBaseNarrative, selectedCompareNarrative]);

  useEffect(() => {
    if (context.loading || context.error || !recommendationRunId) {
      setReport(null);
      setNarratives([]);
      setResolvedSiteId(null);
      setLoading(false);
      setError(null);
      setNotFound(false);
      return;
    }

    if (candidateSiteIds.length === 0) {
      setReport(null);
      setNarratives([]);
      setResolvedSiteId(null);
      setLoading(false);
      setError("No site context is available to resolve this recommendation run.");
      setNotFound(false);
      return;
    }

    let cancelled = false;

    async function loadDetail() {
      setLoading(true);
      setError(null);
      setNotFound(false);
      setReport(null);
      setNarratives([]);
      setResolvedSiteId(null);

      try {
        for (const siteId of candidateSiteIds) {
          let reportResult: RecommendationRunReport;
          try {
            reportResult = await fetchRecommendationRunReport(
              context.token,
              context.businessId,
              siteId,
              recommendationRunId,
            );
          } catch (innerError) {
            if (isNotFoundError(innerError)) {
              continue;
            }
            throw innerError;
          }

          let narrativesResult: RecommendationNarrative[];
          try {
            const response = await fetchRecommendationRunNarratives(
              context.token,
              context.businessId,
              siteId,
              recommendationRunId,
            );
            narrativesResult = response.items;
          } catch (innerError) {
            if (isNotFoundError(innerError)) {
              continue;
            }
            throw innerError;
          }

          if (cancelled) {
            return;
          }

          setReport(reportResult);
          setNarratives(narrativesResult);
          setResolvedSiteId(siteId);
          return;
        }

        if (!cancelled) {
          setNotFound(true);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(safeNarrativeHistoryErrorMessage(loadError));
        }
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
    return <section className="panel">Loading recommendation narrative history...</section>;
  }
  if (context.error) {
    return <section className="panel">Unable to load tenant context. Refresh and sign in again.</section>;
  }
  if (!recommendationRunId) {
    return (
      <section className="panel stack">
        <h1>Recommendation Narrative History</h1>
        <p className="hint warning">Recommendation run identifier is missing.</p>
        <p>
          <Link href={backToRecommendationsHref}>Back to Recommendations</Link>
        </p>
      </section>
    );
  }

  return (
    <section className="stack">
      <div className="panel stack">
        <p>
          <Link href={parentRunHref}>Back to Recommendation Run</Link>
        </p>
        <p>
          <Link href={backToRecommendationsHref}>Back to Recommendations</Link>
        </p>
        <h1>Recommendation Narrative History</h1>
        <p>
          Recommendation Run ID: <code>{recommendationRunId}</code>
        </p>
        {resolvedSiteId ? (
          <p>
            Resolved Site ID: <code>{resolvedSiteId}</code>
          </p>
        ) : null}
        {loading ? <p className="hint muted">Loading recommendation narrative history...</p> : null}
        {!loading && notFound ? (
          <p className="hint warning">Recommendation run narrative history not found or not accessible in your tenant scope.</p>
        ) : null}
        {!loading && error ? <p className="hint error">{error}</p> : null}
      </div>

      {!loading && !notFound && !error && run ? (
        <>
          <div className="panel stack">
            <h2>Run Context</h2>
            <p>
              Business ID: <code>{run.business_id}</code>
            </p>
            <p>
              Site ID: <code>{run.site_id}</code>
              {selectedSiteDisplayName ? <> ({selectedSiteDisplayName})</> : null}
            </p>
            <p>Status: {run.status}</p>
            <p>Created: {formatDateTime(run.created_at)}</p>
            <p>Started: {formatDateTime(run.started_at)}</p>
            <p>Completed: {formatDateTime(run.completed_at)}</p>
            <p>Updated: {formatDateTime(run.updated_at)}</p>
            <p>Error Summary: {run.error_summary || "-"}</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
              <Link href={parentRunHref}>Parent Recommendation Run</Link>
              <Link href={backToRecommendationsHref}>Recommendation Queue</Link>
              {run.audit_run_id ? <Link href={`/audits/${run.audit_run_id}`}>Linked Audit Run</Link> : null}
              {run.comparison_run_id ? (
                <Link href={buildComparisonRunHref(run.comparison_run_id, run.site_id)}>Linked Comparison Run</Link>
              ) : null}
            </div>
          </div>

          <div className="panel stack">
            <h2>Narrative Summary</h2>
            <p>Total Narrative Versions: {sortedNarratives.length}</p>
            {!latestNarrative ? (
              <p className="hint muted">No narrative history records are available for this run yet.</p>
            ) : (
              <>
                <p>
                  Latest Version: {latestNarrative.version} ({latestNarrative.status})
                </p>
                <p>
                  Latest Provider/Model: {latestNarrative.provider_name} / {latestNarrative.model_name}
                </p>
                <p>Latest Created: {formatDateTime(latestNarrative.created_at)}</p>
                <p>
                  Latest Themes:{" "}
                  {latestNarrative.top_themes_json.length > 0
                    ? latestNarrative.top_themes_json.slice(0, 5).join(", ")
                    : "-"}
                </p>
                <p>
                  <Link
                    href={buildNarrativeDetailHref(
                      recommendationRunId,
                      latestNarrative.id,
                      run.site_id,
                      queueContextParams,
                    )}
                  >
                    Open Latest Narrative Detail
                  </Link>
                </p>
              </>
            )}
          </div>

          <div className="panel stack">
            <h2>Narrative Versions</h2>
            {sortedNarratives.length === 0 ? (
              <p className="hint muted">
                No recommendation narrative versions have been generated for this run yet.
              </p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Provider / Model</th>
                    <th>Themes</th>
                    <th>Sections</th>
                    <th>Error</th>
                    <th>Open</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedNarratives.map((item) => (
                    <tr key={item.id}>
                      <td>{item.version}</td>
                      <td>{item.status}</td>
                      <td>{formatDateTime(item.created_at)}</td>
                      <td>{item.provider_name} / {item.model_name}</td>
                      <td>{item.top_themes_json.length > 0 ? item.top_themes_json.slice(0, 3).join(", ") : "-"}</td>
                      <td>{item.sections_json ? Object.keys(item.sections_json).length : 0}</td>
                      <td>{item.error_message || "-"}</td>
                      <td>
                        <Link
                          href={buildNarrativeDetailHref(
                            recommendationRunId,
                            item.id,
                            run.site_id,
                            queueContextParams,
                          )}
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel stack" data-testid="narrative-compare-panel">
            <h2>Narrative Version Compare</h2>
            {sortedNarratives.length < 2 ? (
              <p className="hint muted">At least two narrative versions are required to compare changes.</p>
            ) : (
              <>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "end" }}>
                  <label className="stack" style={{ minWidth: "220px" }}>
                    <span>Base Version</span>
                    <select
                      aria-label="Base Version"
                      value={selectedBaseNarrative?.id || ""}
                      onChange={(event) => setSelectedBaseNarrativeId(event.target.value)}
                    >
                      {sortedNarratives.map((item) => (
                        <option key={`base-${item.id}`} value={item.id}>
                          v{item.version} · {item.status} · {formatDateTime(item.created_at)}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="stack" style={{ minWidth: "220px" }}>
                    <span>Compare Version</span>
                    <select
                      aria-label="Compare Version"
                      value={selectedCompareNarrative?.id || ""}
                      onChange={(event) => setSelectedCompareNarrativeId(event.target.value)}
                    >
                      {sortedNarratives.map((item) => (
                        <option key={`compare-${item.id}`} value={item.id}>
                          v{item.version} · {item.status} · {formatDateTime(item.created_at)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                {selectedBaseNarrative && selectedCompareNarrative && narrativeComparison ? (
                  <>
                    <p>
                      Base: v{selectedBaseNarrative.version} ({selectedBaseNarrative.status}) at{" "}
                      {formatDateTime(selectedBaseNarrative.created_at)}
                    </p>
                    <p>
                      Compare: v{selectedCompareNarrative.version} ({selectedCompareNarrative.status}) at{" "}
                      {formatDateTime(selectedCompareNarrative.created_at)}
                    </p>

                    {narrativeComparison.structured_available ? (
                      <div className="stack">
                        <h3>Structured Change Summary</h3>
                        <p>Sections added: {narrativeComparison.section_added_count}</p>
                        <p>Sections removed: {narrativeComparison.section_removed_count}</p>
                        <p>Sections changed: {narrativeComparison.section_changed_count}</p>
                      </div>
                    ) : (
                      <div className="stack">
                        <h3>Text Change Summary</h3>
                        <p>Paragraphs added: {narrativeComparison.text_added_count}</p>
                        <p>Paragraphs removed: {narrativeComparison.text_removed_count}</p>
                        <p>Paragraphs changed: {narrativeComparison.text_changed_count}</p>
                      </div>
                    )}

                    <div className="stack">
                      <h3>Theme Changes</h3>
                      <p>
                        Added themes:{" "}
                        {narrativeComparison.added_themes.length > 0
                          ? narrativeComparison.added_themes.join(", ")
                          : "-"}
                      </p>
                      <p>
                        Removed themes:{" "}
                        {narrativeComparison.removed_themes.length > 0
                          ? narrativeComparison.removed_themes.join(", ")
                          : "-"}
                      </p>
                    </div>

                    {narrativeComparison.recommendation_impact_available ? (
                      <div className="stack">
                        <h3>Recommendation Impact</h3>
                        <p>Added references: {narrativeComparison.added_recommendation_ids.length}</p>
                        <p>Removed references: {narrativeComparison.removed_recommendation_ids.length}</p>
                        <p>Unchanged references: {narrativeComparison.unchanged_recommendation_ids.length}</p>

                        {narrativeComparison.added_recommendation_ids.length > 0 ? (
                          <div className="stack">
                            <p>Added recommendation references</p>
                            <ul>
                              {narrativeComparison.added_recommendation_ids.map((itemId) => {
                                const recommendation = producedRecommendationsById.get(itemId);
                                return (
                                  <li key={`rec-added-${itemId}`}>
                                    {recommendation ? (
                                      <Link href={buildRecommendationDetailHref(recommendation)}>
                                        {recommendation.title}
                                      </Link>
                                    ) : (
                                      <code>{itemId}</code>
                                    )}{" "}
                                    <span className="hint muted"><code>{itemId}</code></span>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        ) : null}

                        {narrativeComparison.removed_recommendation_ids.length > 0 ? (
                          <div className="stack">
                            <p>Removed recommendation references</p>
                            <ul>
                              {narrativeComparison.removed_recommendation_ids.map((itemId) => {
                                const recommendation = producedRecommendationsById.get(itemId);
                                return (
                                  <li key={`rec-removed-${itemId}`}>
                                    {recommendation ? (
                                      <Link href={buildRecommendationDetailHref(recommendation)}>
                                        {recommendation.title}
                                      </Link>
                                    ) : (
                                      <code>{itemId}</code>
                                    )}{" "}
                                    <span className="hint muted"><code>{itemId}</code></span>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    {narrativeComparison.structured_available ? (
                      <div className="stack">
                        <h3>Structured Differences</h3>
                        {narrativeComparison.section_entries.length === 0 ? (
                          <p className="hint muted">No structured section differences were detected.</p>
                        ) : (
                          <table className="table">
                            <thead>
                              <tr>
                                <th>Change</th>
                                <th>Section</th>
                                <th>Compare Value</th>
                                <th>Base Value</th>
                              </tr>
                            </thead>
                            <tbody>
                              {narrativeComparison.section_entries.map((item) => (
                                <tr
                                  key={`section-diff-${item.section_name}-${item.change_type}`}
                                  data-testid="narrative-compare-section-row"
                                >
                                  <td>{item.change_type}</td>
                                  <td>{item.section_name}</td>
                                  <td>
                                    <pre style={{ margin: 0, whiteSpace: "pre-wrap", overflowX: "auto" }}>
                                      {item.change_type === "added" ? "-" : formatStructuredValue(item.compare_value)}
                                    </pre>
                                  </td>
                                  <td>
                                    <pre style={{ margin: 0, whiteSpace: "pre-wrap", overflowX: "auto" }}>
                                      {item.change_type === "removed" ? "-" : formatStructuredValue(item.base_value)}
                                    </pre>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    ) : (
                      <div className="stack">
                        <h3>Text Differences</h3>
                        {narrativeComparison.text_entries.length === 0 ? (
                          <p className="hint muted">No text paragraph differences were detected.</p>
                        ) : (
                          <div className="stack">
                            {narrativeComparison.text_entries.map((item) => (
                              <div
                                key={`text-diff-${item.paragraph_index}-${item.change_type}`}
                                className="panel stack"
                                style={{ padding: "0.75rem" }}
                                data-testid="narrative-compare-text-row"
                              >
                                <p>
                                  Paragraph {item.paragraph_index} ({item.change_type})
                                </p>
                                <p>
                                  <strong>Compare</strong>
                                </p>
                                <p style={{ whiteSpace: "pre-wrap" }}>{item.compare_text || "-"}</p>
                                <p>
                                  <strong>Base</strong>
                                </p>
                                <p style={{ whiteSpace: "pre-wrap" }}>{item.base_text || "-"}</p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {!narrativeComparison.has_differences ? (
                      <p className="hint muted">No differences found between these versions.</p>
                    ) : null}
                  </>
                ) : null}
              </>
            )}
          </div>

          <div className="panel stack">
            <h2>Produced Recommendations ({report?.recommendations.total || 0})</h2>
            {producedRecommendations.length === 0 ? (
              <p className="hint muted">No produced recommendations are available for this run.</p>
            ) : (
              <>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Priority</th>
                      <th>Status</th>
                      <th>Category</th>
                      <th>Source</th>
                      <th>Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {producedRecommendations.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <Link href={buildRecommendationDetailHref(item)}>{item.title}</Link>
                          <br />
                          <span className="hint muted"><code>{item.id}</code></span>
                        </td>
                        <td>
                          {item.priority_score} ({item.priority_band})
                        </td>
                        <td>{item.status}</td>
                        <td>{item.category}</td>
                        <td>{deriveRecommendationSourceType(item)}</td>
                        <td>{truncateText(item.rationale, RECOMMENDATION_RATIONALE_PREVIEW_LIMIT)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(report?.recommendations.total || 0) > producedRecommendations.length ? (
                  <p className="hint muted">
                    Showing the top {producedRecommendations.length} recommendations by priority out of{" "}
                    {report?.recommendations.total || 0}.
                  </p>
                ) : null}
              </>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}
