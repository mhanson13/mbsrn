import { render, screen } from "@testing-library/react";

import type { RecommendationNarrative, RecommendationRun } from "../../../lib/api/types";
import { RecommendationRunHistoryTable } from "./RecommendationRunHistoryTable";

function buildRecommendationRun(overrides: Partial<RecommendationRun> = {}): RecommendationRun {
  return {
    id: "run-1",
    business_id: "biz-1",
    site_id: "site-1",
    audit_run_id: null,
    comparison_run_id: null,
    status: "completed",
    total_recommendations: 4,
    critical_recommendations: 1,
    warning_recommendations: 2,
    info_recommendations: 1,
    category_counts_json: {},
    effort_bucket_counts_json: {},
    started_at: "2026-03-21T00:29:00Z",
    completed_at: "2026-03-21T00:30:00Z",
    duration_ms: 120000,
    error_summary: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:29:00Z",
    updated_at: "2026-03-21T00:30:00Z",
    ...overrides,
  };
}

function buildRecommendationNarrative(
  overrides: Partial<RecommendationNarrative> = {},
): RecommendationNarrative {
  return {
    id: "narrative-1",
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    version: 1,
    status: "completed",
    narrative_text: "Summary",
    top_themes_json: [],
    sections_json: null,
    provider_name: "provider",
    model_name: "model",
    prompt_version: "v1",
    error_message: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:31:00Z",
    updated_at: "2026-03-21T00:31:00Z",
    ...overrides,
  };
}

describe("RecommendationRunHistoryTable", () => {
  const formatDateTime = (value: string | null) => value || "-";
  const buildRecommendationRunHref = (runId: string) => `/recommendations/runs/${runId}`;
  const buildNarrativeHistoryHref = (recommendationRunId: string) =>
    `/recommendations/runs/${recommendationRunId}/narratives`;
  const buildNarrativeDetailHref = (recommendationRunId: string, narrativeId: string) =>
    `/recommendations/runs/${recommendationRunId}/narratives/${narrativeId}`;

  it("renders structured empty state when no runs are available", () => {
    render(
      <RecommendationRunHistoryTable
        recommendationRuns={[]}
        latestNarrativesByRunId={{}}
        siteId="site-1"
        formatDateTime={formatDateTime}
        buildRecommendationRunHref={buildRecommendationRunHref}
        buildNarrativeHistoryHref={buildNarrativeHistoryHref}
        buildNarrativeDetailHref={buildNarrativeDetailHref}
      />,
    );

    expect(screen.getByTestId("workspace-recommendation-runs-empty-state")).toBeInTheDocument();
    expect(screen.getByText(/No recommendation runs available yet/i)).toBeInTheDocument();
  });

  it("renders run history table and latest narrative link when runs exist", () => {
    const run = buildRecommendationRun();
    const narrative = buildRecommendationNarrative();
    render(
      <RecommendationRunHistoryTable
        recommendationRuns={[run]}
        latestNarrativesByRunId={{ [run.id]: narrative }}
        siteId="site-1"
        formatDateTime={formatDateTime}
        buildRecommendationRunHref={buildRecommendationRunHref}
        buildNarrativeHistoryHref={buildNarrativeHistoryHref}
        buildNarrativeDetailHref={buildNarrativeDetailHref}
      />,
    );

    expect(screen.queryByTestId("workspace-recommendation-runs-empty-state")).not.toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "run-1" })).toHaveAttribute("href", "/recommendations/runs/run-1");
    expect(screen.getByRole("link", { name: "Latest v1 (completed)" })).toHaveAttribute(
      "href",
      "/recommendations/runs/run-1/narratives/narrative-1",
    );
  });
});
