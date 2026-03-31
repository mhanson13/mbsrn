import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import RecommendationNarrativeDetailPage from "./page";
import type {
  Recommendation,
  RecommendationNarrative,
  RecommendationRun,
  RecommendationRunReport,
} from "../../../../../../lib/api/types";

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
  params: { run_id: "run-1", narrative_id: "narrative-1" },
  searchParams: new URLSearchParams("site_id=site-1"),
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchRecommendationRunReport = jest.fn<Promise<RecommendationRunReport>, unknown[]>();
const mockFetchRecommendationNarrative = jest.fn<Promise<RecommendationNarrative>, unknown[]>();

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

jest.mock("../../../../../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../../../../../lib/api/client", () => {
  const actual = jest.requireActual("../../../../../../lib/api/client");
  return {
    ...actual,
    fetchRecommendationRunReport: (...args: unknown[]) => mockFetchRecommendationRunReport(...args),
    fetchRecommendationNarrative: (...args: unknown[]) => mockFetchRecommendationNarrative(...args),
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
    total_recommendations: 1,
    critical_recommendations: 0,
    warning_recommendations: 1,
    info_recommendations: 0,
    category_counts_json: { SEO: 1 },
    effort_bucket_counts_json: { small: 1 },
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

function buildNarrative(overrides: Partial<RecommendationNarrative> = {}): RecommendationNarrative {
  return {
    id: "narrative-1",
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    version: 1,
    status: "completed",
    narrative_text: "Narrative text for version 1",
    top_themes_json: [],
    sections_json: null,
    provider_name: "provider",
    model_name: "model",
    prompt_version: "v1",
    error_message: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T10:00:00Z",
    updated_at: "2026-03-21T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  navigationState.params = { run_id: "run-1", narrative_id: "narrative-1" };
  navigationState.searchParams = new URLSearchParams("site_id=site-1");
  mockUseOperatorContext.mockReturnValue(baseContext());
});

describe("recommendation narrative detail page presentation", () => {
  it("renders shared support loading framing", () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ loading: true }));

    render(<RecommendationNarrativeDetailPage />);

    expect(screen.getByRole("heading", { name: "Recommendation Narrative Detail" })).toBeInTheDocument();
    expect(
      screen.getByText("Loading recommendation narrative detail for the selected run."),
    ).toBeInTheDocument();
  });

  it("renders missing identifier support state", () => {
    navigationState.params = { run_id: "run-1", narrative_id: "" };

    render(<RecommendationNarrativeDetailPage />);

    expect(screen.getByRole("heading", { name: "Recommendation Narrative Detail" })).toBeInTheDocument();
    expect(screen.getByText("Recommendation run or narrative identifier is missing.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Recommendations" })).toBeInTheDocument();
  });

  it("renders hero summary and no-data framing for empty themes/sections", async () => {
    mockFetchRecommendationRunReport.mockResolvedValueOnce(buildRunReport());
    mockFetchRecommendationNarrative.mockResolvedValueOnce(buildNarrative());

    render(<RecommendationNarrativeDetailPage />);

    await screen.findByRole("heading", { name: "Narrative Metadata" });
    expect(screen.getByTestId("recommendation-narrative-detail-hero")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-narrative-detail-summary-strip")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-narrative-detail-workflow-context")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Parent Recommendation Run" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Narrative History" })).toBeInTheDocument();
    expect(screen.getByText("Narrative status")).toBeInTheDocument();
    expect(screen.getByText("Prompt lineage")).toBeInTheDocument();
    await screen.findByText("No top themes were recorded for this narrative version.");
    await screen.findByText("No structured sections were returned for this narrative version.");
  });
});
