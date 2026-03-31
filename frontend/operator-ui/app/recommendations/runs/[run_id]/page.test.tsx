import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import RecommendationRunDetailPage from "./page";
import { ApiRequestError } from "../../../../lib/api/client";
import type {
  Recommendation,
  RecommendationNarrative,
  RecommendationRun,
  RecommendationRunReport,
} from "../../../../lib/api/types";

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
const mockFetchLatestRecommendationRunNarrative = jest.fn<Promise<RecommendationNarrative>, unknown[]>();
const mockFetchCompetitorComparisonReport = jest.fn();

jest.mock("next/link", () => {
  return function MockLink({
    href,
    children,
  }: {
    href: string;
    children: ReactNode;
  }) {
    return <a href={href}>{children}</a>;
  };
});

jest.mock("next/navigation", () => ({
  useParams: () => navigationState.params,
  useSearchParams: () => navigationState.searchParams,
}));

jest.mock("../../../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../../../lib/api/client", () => {
  const actual = jest.requireActual("../../../../lib/api/client");
  return {
    ...actual,
    fetchRecommendationRunReport: (...args: unknown[]) => mockFetchRecommendationRunReport(...args),
    fetchLatestRecommendationRunNarrative: (...args: unknown[]) =>
      mockFetchLatestRecommendationRunNarrative(...args),
    fetchCompetitorComparisonReport: (...args: unknown[]) => mockFetchCompetitorComparisonReport(...args),
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
    comparison_run_id: null,
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
    comparison_run_id: null,
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

function buildRunReport(recommendations: Recommendation[] = [buildRecommendation("rec-1", "Recommendation One")]): RecommendationRunReport {
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
      by_status: { open: recommendations.length },
    },
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  navigationState.params = { run_id: "run-1" };
  navigationState.searchParams = new URLSearchParams("site_id=site-1");
  mockUseOperatorContext.mockReturnValue(baseContext());
});

describe("recommendation run detail page presentation", () => {
  it("renders shared support loading framing when tenant context is loading", () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ loading: true }));

    render(<RecommendationRunDetailPage />);

    expect(screen.getByRole("heading", { name: "Recommendation Run Detail" })).toBeInTheDocument();
    expect(
      screen.getByText("Loading recommendation run detail for the selected business context."),
    ).toBeInTheDocument();
  });

  it("renders missing identifier support state when run id is absent", () => {
    navigationState.params = { run_id: "" };

    render(<RecommendationRunDetailPage />);

    expect(screen.getByRole("heading", { name: "Recommendation Run Detail" })).toBeInTheDocument();
    expect(screen.getByText("Recommendation run identifier is missing.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Recommendations" })).toBeInTheDocument();
  });

  it("renders hero summary strip and no-narrative no-data state", async () => {
    mockFetchRecommendationRunReport.mockResolvedValueOnce(buildRunReport());
    mockFetchLatestRecommendationRunNarrative.mockRejectedValueOnce(
      new ApiRequestError("not found", { status: 404, detail: null }),
    );

    render(<RecommendationRunDetailPage />);

    await screen.findByTestId("recommendation-run-detail-hero");
    expect(screen.getByTestId("recommendation-run-detail-summary-strip")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-run-workflow-context")).toBeInTheDocument();
    const detailFocus = screen.getByTestId("recommendation-run-detail-focus");
    expect(detailFocus).toBeInTheDocument();
    expect(screen.getByText("Run outcome snapshot")).toBeInTheDocument();
    expect(screen.getByText("Why this matters now")).toBeInTheDocument();
    expect(screen.getByText("Can I act now")).toBeInTheDocument();
    expect(screen.getByText("Blocking state")).toBeInTheDocument();
    expect(screen.getByText("After action")).toBeInTheDocument();
    expect(screen.getByText("Evidence preview")).toBeInTheDocument();
    expect(screen.getByText("Evidence trust")).toBeInTheDocument();
    expect(
      screen.getByText("Run produced actionable recommendations that should be reviewed now."),
    ).toBeInTheDocument();
    expect(screen.getByText("Support cue: operator review required")).toBeInTheDocument();
    expect(
      screen.getByText("Yes. Review recommendations and start with the highest-priority items."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Run produced 1 recommendation for operator review."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Yes. Review and apply high-priority recommendations."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Run output is visible now; applied impact appears after the next analysis refresh.",
      ),
    ).toBeInTheDocument();
    const runContextHeading = screen.getByRole("heading", { name: "Run Context" });
    expect(detailFocus.compareDocumentPosition(runContextHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "Recommendation Queue" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Narrative History" })).toBeInTheDocument();
    expect(screen.getByText("Run status")).toBeInTheDocument();
    expect(screen.getByText("Recommendations")).toBeInTheDocument();
    expect(screen.getByText("Latest Narrative")).toBeInTheDocument();
    expect(
      screen.getByText("No generated narrative is currently available for this recommendation run."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Run Context" })).toBeInTheDocument();
  });
});
