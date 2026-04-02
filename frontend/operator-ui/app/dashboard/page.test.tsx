import { render, screen, waitFor } from "@testing-library/react";

import DashboardPage from "./page";
import type { RecommendationWorkspaceSummaryResponse } from "../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: Array<{
    id: string;
    display_name: string;
    last_audit_run_id?: string | null;
    last_audit_status?: string | null;
    last_audit_completed_at?: string | null;
  }>;
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockUseAuth = jest.fn();
const mockFetchRecommendationWorkspaceSummary = jest.fn();
const mockFetchAutomationRuns = jest.fn();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../components/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("../../lib/api/client", () => ({
  fetchRecommendationWorkspaceSummary: (...args: unknown[]) =>
    mockFetchRecommendationWorkspaceSummary(...args),
  fetchAutomationRuns: (...args: unknown[]) => mockFetchAutomationRuns(...args),
}));

function baseContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [
      {
        id: "site-1",
        display_name: "Main Site",
        last_audit_run_id: "audit-1",
        last_audit_status: "completed",
        last_audit_completed_at: "2026-03-20T00:00:00Z",
      },
    ],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
    ...overrides,
  };
}

function workspaceSummaryFixture(
  overrides: Partial<RecommendationWorkspaceSummaryResponse> = {},
): RecommendationWorkspaceSummaryResponse {
  return {
    business_id: "biz-1",
    site_id: "site-1",
    state: "completed_with_narrative",
    latest_run: {
      id: "rec-run-1",
      business_id: "biz-1",
      site_id: "site-1",
      audit_run_id: "audit-1",
      comparison_run_id: null,
      status: "completed",
      total_recommendations: 4,
      critical_recommendations: 1,
      warning_recommendations: 2,
      info_recommendations: 1,
      category_counts_json: {},
      effort_bucket_counts_json: {},
      started_at: "2026-03-20T00:00:00Z",
      completed_at: "2026-03-20T00:02:00Z",
      duration_ms: 120000,
      error_summary: null,
      created_by_principal_id: "operator-1",
      created_at: "2026-03-20T00:00:00Z",
      updated_at: "2026-03-20T00:02:00Z",
    },
    latest_completed_run: null,
    recommendations: {
      items: [],
      total: 4,
      filtered_summary: {
        total: 4,
        open: 3,
        accepted: 1,
        dismissed: 0,
        high_priority: 2,
      },
    },
    latest_narrative: null,
    tuning_suggestions: [],
    ...overrides,
  };
}

describe("dashboard operator-focused layout", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseAuth.mockReturnValue({ principal: { role: "operator" } });
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(workspaceSummaryFixture());
    mockFetchAutomationRuns.mockResolvedValue({
      items: [
        {
          id: "automation-run-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "manual",
          started_at: "2026-03-20T00:03:00Z",
          finished_at: "2026-03-20T00:04:00Z",
          error_message: null,
          steps_json: [],
          created_at: "2026-03-20T00:03:00Z",
          updated_at: "2026-03-20T00:04:00Z",
        },
      ],
      total: 1,
    });
  });

  it("renders loading support header", () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ loading: true }));
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(
      screen.getByText("Loading dashboard overview and role-scoped status."),
    ).toBeInTheDocument();
  });

  it("renders error support header", () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ error: "context failed" }));
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText("Error: context failed")).toBeInTheDocument();
  });

  it("renders summary, priority, recent activity, and quick navigation", async () => {
    mockUseOperatorContext.mockReturnValue(baseContext());
    render(<DashboardPage />);

    expect(document.querySelector(".page-container-width-wide")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-summary-strip")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Do this now" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recent activity" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Quick navigation" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sites" })).toHaveAttribute("href", "/sites");
    expect(screen.getByRole("link", { name: "Business Profile" })).toHaveAttribute(
      "href",
      "/business-profile",
    );

    await waitFor(() => {
      expect(mockFetchRecommendationWorkspaceSummary).toHaveBeenCalledWith("token-1", "biz-1", "site-1");
      expect(mockFetchAutomationRuns).toHaveBeenCalledWith("token-1", "biz-1", "site-1");
    });
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-priority-panel")).toHaveTextContent("Review open recommendations");
      expect(screen.getByTestId("dashboard-priority-panel")).toHaveTextContent("Open Recommendations");
    });
  });
});
