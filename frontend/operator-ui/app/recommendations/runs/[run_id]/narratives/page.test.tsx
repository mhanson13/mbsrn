import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import RecommendationRunNarrativeHistoryPage from "./page";
import type {
  Recommendation,
  RecommendationNarrative,
  RecommendationNarrativeListResponse,
  RecommendationRun,
  RecommendationRunReport,
} from "../../../../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: Array<{ id: string; display_name: string }>;
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const navigationState = {
  params: { run_id: "run-1" },
  searchParams: new URLSearchParams("site_id=site-1"),
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchRecommendationRunReport = jest.fn<Promise<RecommendationRunReport>, unknown[]>();
const mockFetchRecommendationRunNarratives = jest.fn<Promise<RecommendationNarrativeListResponse>, unknown[]>();

jest.mock("next/navigation", () => ({
  useParams: () => navigationState.params,
  useSearchParams: () => navigationState.searchParams,
}));

jest.mock("../../../../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../../../../lib/api/client", () => {
  const actual = jest.requireActual("../../../../../lib/api/client");
  return {
    ...actual,
    fetchRecommendationRunReport: (...args: unknown[]) => mockFetchRecommendationRunReport(...args),
    fetchRecommendationRunNarratives: (...args: unknown[]) => mockFetchRecommendationRunNarratives(...args),
  };
});

function baseContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [{ id: "site-1", display_name: "Main Site" }],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
    ...overrides,
  };
}

function buildRecommendation(id: string, title: string): Recommendation {
  return {
    id,
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    audit_run_id: "audit-1",
    comparison_run_id: "comparison-1",
    status: "open",
    category: "SEO",
    severity: "warning",
    priority_score: 80,
    priority_band: "high",
    effort_bucket: "small",
    title,
    rationale: `Rationale for ${title}`,
    eeat_categories: [],
    primary_eeat_category: null,
    decision_reason: null,
    created_at: "2026-03-21T10:00:00Z",
    updated_at: "2026-03-21T10:00:00Z",
  };
}

function buildRun(overrides: Partial<RecommendationRun> = {}): RecommendationRun {
  return {
    id: "run-1",
    business_id: "biz-1",
    site_id: "site-1",
    audit_run_id: "audit-1",
    comparison_run_id: "comparison-1",
    status: "completed",
    total_recommendations: 2,
    critical_recommendations: 0,
    warning_recommendations: 2,
    info_recommendations: 0,
    category_counts_json: { SEO: 2 },
    effort_bucket_counts_json: { small: 2 },
    started_at: "2026-03-21T10:00:00Z",
    completed_at: "2026-03-21T10:05:00Z",
    duration_ms: 300000,
    error_summary: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T09:59:00Z",
    updated_at: "2026-03-21T10:05:00Z",
    ...overrides,
  };
}

function buildRunReport(
  recommendations: Recommendation[] = [
    buildRecommendation("rec-1", "Recommendation One"),
    buildRecommendation("rec-2", "Recommendation Two"),
  ],
): RecommendationRunReport {
  return {
    recommendation_run: buildRun({
      total_recommendations: recommendations.length,
      warning_recommendations: recommendations.length,
    }),
    rollups: {
      by_category: { SEO: recommendations.length },
      by_severity: { warning: recommendations.length },
      by_effort_bucket: { small: recommendations.length },
    },
    recommendations: {
      items: recommendations,
      total: recommendations.length,
    },
  };
}

function buildNarrative(
  version: number,
  overrides: Partial<RecommendationNarrative> = {},
): RecommendationNarrative {
  return {
    id: `narrative-${version}`,
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    version,
    status: "completed",
    narrative_text: `Narrative text version ${version}`,
    top_themes_json: ["titles"],
    sections_json: {
      summary: `Summary ${version}`,
    },
    provider_name: "provider",
    model_name: "model",
    prompt_version: "v1",
    error_message: null,
    created_by_principal_id: "principal-1",
    created_at: `2026-03-2${version}T10:00:00Z`,
    updated_at: `2026-03-2${version}T10:00:00Z`,
    ...overrides,
  };
}

function seedNarrativeHistory(
  narratives: RecommendationNarrative[],
  recommendations: Recommendation[] = [
    buildRecommendation("rec-1", "Recommendation One"),
    buildRecommendation("rec-2", "Recommendation Two"),
  ],
): void {
  mockFetchRecommendationRunReport.mockResolvedValueOnce(buildRunReport(recommendations));
  mockFetchRecommendationRunNarratives.mockResolvedValueOnce({
    items: narratives,
    total: narratives.length,
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  navigationState.params = { run_id: "run-1" };
  navigationState.searchParams = new URLSearchParams("site_id=site-1");
  mockUseOperatorContext.mockReturnValue(baseContext());
});

describe("recommendation narrative history compare", () => {
  it("renders shared support loading framing", () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ loading: true }));

    render(<RecommendationRunNarrativeHistoryPage />);

    expect(screen.getByRole("heading", { name: "Recommendation Narrative History" })).toBeInTheDocument();
    expect(
      screen.getByText("Loading recommendation narrative history for the selected run."),
    ).toBeInTheDocument();
  });

  it("renders missing identifier support state", () => {
    navigationState.params = { run_id: "" };

    render(<RecommendationRunNarrativeHistoryPage />);

    expect(screen.getByRole("heading", { name: "Recommendation Narrative History" })).toBeInTheDocument();
    expect(screen.getByText("Recommendation run identifier is missing.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Recommendations" })).toBeInTheDocument();
  });

  it("renders hero summary strip and no-data narrative state", async () => {
    seedNarrativeHistory([]);

    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Run Context" });
    expect(screen.getByTestId("recommendation-narrative-history-hero")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-narrative-history-summary-strip")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-narrative-history-workflow-context")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Parent Recommendation Run" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Recommendation Queue" })).toBeInTheDocument();
    expect(screen.getByText("Run status")).toBeInTheDocument();
    expect(screen.getByText("Narrative versions")).toBeInTheDocument();
    await screen.findByText("No narrative history records are available for this run yet.");
  });

  it("shows compare controls when two or more versions exist", async () => {
    seedNarrativeHistory([buildNarrative(1), buildNarrative(2)]);
    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Narrative Version Compare" });
    expect(screen.getByLabelText("Base Version")).toBeInTheDocument();
    expect(screen.getByLabelText("Compare Version")).toBeInTheDocument();
  });

  it("shows a disabled state message when fewer than two versions exist", async () => {
    seedNarrativeHistory([buildNarrative(1)]);
    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Narrative Version Compare" });
    expect(screen.getByText("At least two narrative versions are required to compare changes.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Base Version")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Compare Version")).not.toBeInTheDocument();
  });

  it("defaults compare selection to newest versus previous version", async () => {
    seedNarrativeHistory([buildNarrative(1), buildNarrative(3), buildNarrative(2)]);
    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Narrative Version Compare" });
    await waitFor(() => {
      expect(screen.getByLabelText("Base Version")).toHaveValue("narrative-3");
      expect(screen.getByLabelText("Compare Version")).toHaveValue("narrative-2");
    });
  });

  it("updates compare summary when selecting a different version pair", async () => {
    seedNarrativeHistory([
      buildNarrative(1, { sections_json: { summary: "old", removed_only: "x" } }),
      buildNarrative(2, { sections_json: { summary: "mid" } }),
      buildNarrative(3, { sections_json: { summary: "new" } }),
    ]);
    const user = userEvent.setup();
    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Narrative Version Compare" });
    await waitFor(() => expect(screen.getByText("Sections removed: 0")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Compare Version"), "narrative-1");
    await waitFor(() => expect(screen.getByText("Sections removed: 1")).toBeInTheDocument());
  });

  it("renders structured diff summary and structured rows", async () => {
    seedNarrativeHistory([
      buildNarrative(2, {
        sections_json: {
          overview: "new overview",
          added_only: "new section",
          changed_section: { value: "new" },
        },
      }),
      buildNarrative(1, {
        sections_json: {
          overview: "old overview",
          removed_only: "legacy section",
          changed_section: { value: "old" },
        },
      }),
    ]);
    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Structured Change Summary" });
    expect(screen.getByText("Sections added: 1")).toBeInTheDocument();
    expect(screen.getByText("Sections removed: 1")).toBeInTheDocument();
    expect(screen.getByText("Sections changed: 2")).toBeInTheDocument();
    expect(screen.getAllByTestId("narrative-compare-section-row")).toHaveLength(4);
  });

  it("renders text diff summary when only narrative text is available", async () => {
    seedNarrativeHistory([
      buildNarrative(2, {
        sections_json: null,
        narrative_text: "alpha\n\nbeta updated\n\ngamma",
      }),
      buildNarrative(1, {
        sections_json: null,
        narrative_text: "alpha\n\nbeta",
      }),
    ]);
    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Text Change Summary" });
    expect(screen.getByText("Paragraphs added: 1")).toBeInTheDocument();
    expect(screen.getByText("Paragraphs removed: 0")).toBeInTheDocument();
    expect(screen.getByText("Paragraphs changed: 1")).toBeInTheDocument();
    expect(screen.getAllByTestId("narrative-compare-text-row")).toHaveLength(2);
  });

  it("renders recommendation impact links when narrative references include recommendation ids", async () => {
    seedNarrativeHistory(
      [
        buildNarrative(2, {
          sections_json: {
            recommendation_ids: ["rec-1"],
          },
        }),
        buildNarrative(1, {
          sections_json: {
            recommendation_ids: ["rec-2"],
          },
        }),
      ],
      [buildRecommendation("rec-1", "Recommendation One"), buildRecommendation("rec-2", "Recommendation Two")],
    );
    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Recommendation Impact" });
    expect(screen.getByText("Added references: 1")).toBeInTheDocument();
    expect(screen.getByText("Removed references: 1")).toBeInTheDocument();

    const comparePanel = screen.getByTestId("narrative-compare-panel");
    expect(
      within(comparePanel).getByRole("link", { name: "Recommendation One" }),
    ).toHaveAttribute("href", "/recommendations/rec-1?site_id=site-1");
    expect(
      within(comparePanel).getByRole("link", { name: "Recommendation Two" }),
    ).toHaveAttribute("href", "/recommendations/rec-2?site_id=site-1");
  });

  it("shows no-change state when identical versions are selected", async () => {
    seedNarrativeHistory([buildNarrative(2), buildNarrative(1)]);
    const user = userEvent.setup();
    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Narrative Version Compare" });
    await user.selectOptions(screen.getByLabelText("Compare Version"), "narrative-2");

    await screen.findByText("No differences found between these versions.");
  });

  it("preserves existing narrative history and produced recommendations rendering", async () => {
    seedNarrativeHistory([buildNarrative(1), buildNarrative(2)]);
    render(<RecommendationRunNarrativeHistoryPage />);

    await screen.findByRole("heading", { name: "Narrative Versions" });
    expect(screen.getByText("Total Narrative Versions: 2")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Produced Recommendations (2)" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Recommendation One" })).toHaveAttribute(
      "href",
      "/recommendations/rec-1?site_id=site-1",
    );
  });
});
