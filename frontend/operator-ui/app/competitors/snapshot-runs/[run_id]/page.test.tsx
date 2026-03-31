import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import SnapshotRunDetailPage from "./page";

const navigationState = {
  params: { run_id: "snap-1" },
  searchParams: new URLSearchParams("site_id=site-1&set_id=set-1"),
};

const mockUseOperatorContext = jest.fn();
const mockFetchCompetitorSnapshotRun = jest.fn();
const mockFetchCompetitorSnapshotPages = jest.fn();
const mockFetchCompetitorDomains = jest.fn();
const mockFetchCompetitorComparisonRuns = jest.fn();
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
    fetchCompetitorSnapshotRun: (...args: unknown[]) => mockFetchCompetitorSnapshotRun(...args),
    fetchCompetitorSnapshotPages: (...args: unknown[]) => mockFetchCompetitorSnapshotPages(...args),
    fetchCompetitorDomains: (...args: unknown[]) => mockFetchCompetitorDomains(...args),
    fetchCompetitorComparisonRuns: (...args: unknown[]) => mockFetchCompetitorComparisonRuns(...args),
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

describe("snapshot run detail workflow context", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    navigationState.params = { run_id: "snap-1" };
    navigationState.searchParams = new URLSearchParams("site_id=site-1&set_id=set-1");
    mockUseOperatorContext.mockReturnValue(baseContext());
  });

  it("renders workflow context links for parent and adjacent workflow routes", async () => {
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
    mockFetchCompetitorSnapshotPages.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchCompetitorDomains.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchCompetitorComparisonRuns.mockResolvedValueOnce({
      items: [
        {
          id: "cmp-1",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-1",
          snapshot_run_id: "snap-1",
          baseline_audit_run_id: null,
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
      ],
      total: 1,
    });
    mockFetchRecommendationRuns.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SnapshotRunDetailPage />);

    await screen.findByTestId("snapshot-run-workflow-context");
    expect(screen.getByRole("link", { name: "Parent Competitor Set" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Top linked comparison run" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Recommendation Queue" })).toBeInTheDocument();
  });
});
