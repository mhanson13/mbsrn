import type {
  Recommendation,
  RecommendationNarrative,
  RecommendationThemeGroup,
} from "../../../lib/api/types";
import {
  narrativeSummaryText,
  normalizeBoundedStringList,
  normalizeNarrativeSignalSummary,
  normalizeRecommendationThemeSections,
  recommendationImpactBadgeClass,
  recommendationImpactLabel,
} from "./recommendationWorkspaceHelpers";

function buildRecommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    id: "rec-1",
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    audit_run_id: null,
    comparison_run_id: null,
    status: "open",
    category: "SEO",
    severity: "warning",
    priority_score: 80,
    priority_band: "high",
    effort_bucket: "small",
    title: "Improve title tags",
    rationale: "Rationale",
    eeat_categories: [],
    primary_eeat_category: null,
    decision_reason: null,
    created_at: "2026-03-21T00:00:00Z",
    updated_at: "2026-03-21T00:00:00Z",
    ...overrides,
  };
}

function buildNarrative(overrides: Partial<RecommendationNarrative> = {}): RecommendationNarrative {
  return {
    id: "narrative-1",
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    version: 1,
    status: "completed",
    narrative_text: "Narrative fallback text",
    top_themes_json: [],
    sections_json: null,
    provider_name: "provider",
    model_name: "model",
    prompt_version: "v1",
    error_message: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:00:00Z",
    updated_at: "2026-03-21T00:00:00Z",
    ...overrides,
  };
}

describe("recommendationWorkspaceHelpers", () => {
  it("normalizes bounded string lists with trim, dedupe, truncation, and limit", () => {
    const normalized = normalizeBoundedStringList(
      [
        "  First item  ",
        "first item",
        "",
        "Second entry with more than twelve chars",
        "Third item",
      ],
      2,
      12,
    );

    expect(normalized).toEqual(["First item", "Second entr…"]);
  });

  it("keeps impact label and badge mapping stable", () => {
    const highImpactItem = buildRecommendation();
    const quickWinItem = buildRecommendation({ id: "rec-2", effort_bucket: "small", status: "open" });
    const needsReviewItem = buildRecommendation({ id: "rec-3", effort_bucket: "large", status: "in_progress" });

    expect(recommendationImpactLabel(highImpactItem, 0)).toBe("HIGH IMPACT");
    expect(recommendationImpactLabel(quickWinItem, 1)).toBe("QUICK WIN");
    expect(recommendationImpactLabel(needsReviewItem, 1)).toBe("NEEDS REVIEW");

    expect(recommendationImpactBadgeClass("HIGH IMPACT")).toBe("badge badge-error");
    expect(recommendationImpactBadgeClass("QUICK WIN")).toBe("badge badge-success");
    expect(recommendationImpactBadgeClass("NEEDS REVIEW")).toBe("badge badge-warn");
    expect(recommendationImpactBadgeClass(null)).toBe("badge badge-muted");
  });

  it("groups recommendations by theme ids and falls back ungrouped items to general section", () => {
    const recommendations = [
      buildRecommendation({ id: "rec-1", title: "First" }),
      buildRecommendation({ id: "rec-2", title: "Second" }),
      buildRecommendation({ id: "rec-3", title: "Third" }),
    ];
    const grouped: RecommendationThemeGroup[] = [
      {
        theme: "trust_and_legitimacy",
        label: "Trust priority",
        count: 2,
        recommendation_ids: ["rec-2", "rec-1"],
      },
    ];

    const sections = normalizeRecommendationThemeSections(recommendations, grouped);

    expect(sections).toHaveLength(2);
    expect(sections[0]).toMatchObject({
      theme: "trust_and_legitimacy",
      label: "Trust priority",
    });
    expect(sections[0].items.map((item) => item.id)).toEqual(["rec-2", "rec-1"]);
    expect(sections[1]).toMatchObject({
      theme: "general_site_improvement",
      label: "General site improvement",
    });
    expect(sections[1].items.map((item) => item.id)).toEqual(["rec-3"]);
  });

  it("normalizes narrative summary and signal details safely", () => {
    const summaryNarrative = buildNarrative({
      sections_json: { summary: "  Summary from sections  " },
      narrative_text: "Fallback narrative text",
      signal_summary: {
        support_level: "high",
        evidence_sources: ["site", "competitors", "site", "themes"],
        competitor_signal_used: true,
        site_signal_used: true,
        reference_signal_used: false,
      },
    });

    expect(narrativeSummaryText(summaryNarrative)).toBe("Summary from sections");

    expect(normalizeNarrativeSignalSummary(summaryNarrative)).toEqual({
      supportLevel: "high",
      evidenceSources: ["site", "competitors", "themes"],
      competitorSignalUsed: true,
      siteSignalUsed: true,
      referenceSignalUsed: false,
    });

    const invalidSignalNarrative = buildNarrative({
      signal_summary: {
        support_level: "high",
        evidence_sources: [],
        competitor_signal_used: false,
        site_signal_used: false,
        reference_signal_used: false,
      },
    });
    expect(normalizeNarrativeSignalSummary(invalidSignalNarrative)).toBeNull();
  });
});
