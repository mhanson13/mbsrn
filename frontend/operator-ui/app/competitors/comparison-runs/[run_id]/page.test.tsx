import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import ComparisonRunDetailPage from "./page";

const navigationState = {
  params: { run_id: "cmp-1" },
  searchParams: new URLSearchParams("site_id=site-1&set_id=set-1"),
};

const mockUseOperatorContext = jest.fn();
const mockFetchCompetitorComparisonReport = jest.fn();
const mockFetchCompetitorSnapshotRun = jest.fn();
const mockFetchRecommendationRuns = jest.fn();
const mockFetchRecommendations = jest.fn();

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
    fetchCompetitorComparisonReport: (...args: unknown[]) => mockFetchCompetitorComparisonReport(...args),
    fetchCompetitorSnapshotRun: (...args: unknown[]) => mockFetchCompetitorSnapshotRun(...args),
    fetchRecommendationRuns: (...args: unknown[]) => mockFetchRecommendationRuns(...args),
    fetchRecommendations: (...args: unknown[]) => mockFetchRecommendations(...args),
  };
});

function baseContext(overrides: Record<string, unknown> = {}) {
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

describe("comparison run detail workflow context", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    navigationState.params = { run_id: "cmp-1" };
    navigationState.searchParams = new URLSearchParams("site_id=site-1&set_id=set-1");
    mockUseOperatorContext.mockReturnValue(baseContext());
  });

  it("renders workflow context links with parent and snapshot lineage", async () => {
    mockFetchCompetitorComparisonReport.mockResolvedValueOnce({
      run: {
        id: "cmp-1",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        snapshot_run_id: "snap-1",
        baseline_audit_run_id: "audit-0",
        status: "completed",
        total_findings: 2,
        critical_findings: 0,
        warning_findings: 1,
        info_findings: 1,
        client_pages_analyzed: 2,
        competitor_pages_analyzed: 3,
        finding_type_counts_json: {},
        category_counts_json: {},
        severity_counts_json: {},
        started_at: "2026-03-01T10:02:00Z",
        completed_at: "2026-03-01T10:03:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-01T10:02:00Z",
        updated_at: "2026-03-01T10:03:00Z",
      },
      rollups: {
        client_pages_analyzed: 2,
        competitor_pages_analyzed: 3,
        findings_by_type: {},
        findings_by_category: {},
        findings_by_severity: {},
        metric_rollups: [],
      },
      findings: {
        items: [],
        total: 0,
        by_category: {},
        by_severity: {},
      },
    });
    mockFetchCompetitorSnapshotRun.mockResolvedValueOnce({
      id: "snap-1",
      business_id: "biz-1",
      site_id: "site-1",
      competitor_set_id: "set-1",
      client_audit_run_id: "audit-1",
      status: "completed",
      max_domains: 5,
      max_pages_per_domain: 10,
      max_depth: 2,
      same_domain_only: true,
      domains_targeted: 1,
      domains_completed: 1,
      pages_attempted: 3,
      pages_captured: 3,
      pages_skipped: 0,
      errors_encountered: 0,
      started_at: "2026-03-01T10:00:00Z",
      completed_at: "2026-03-01T10:01:00Z",
      duration_ms: 60000,
      error_summary: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-01T10:00:00Z",
      updated_at: "2026-03-01T10:01:00Z",
    });
    mockFetchRecommendationRuns.mockResolvedValueOnce({ items: [], total: 0 });

    render(<ComparisonRunDetailPage />);

    await screen.findByTestId("comparison-run-workflow-context");
    expect(screen.getByRole("link", { name: "Parent Competitor Set" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Snapshot Run" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Recommendation Queue" })).toBeInTheDocument();
  });
});
