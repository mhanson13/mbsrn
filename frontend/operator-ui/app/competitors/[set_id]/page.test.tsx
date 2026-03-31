import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import CompetitorSetDetailPage from "./page";

const navigationState = {
  params: { set_id: "set-1" },
  searchParams: new URLSearchParams("site_id=site-1"),
};

const mockUseOperatorContext = jest.fn();
const mockFetchCompetitorSet = jest.fn();
const mockFetchCompetitorDomains = jest.fn();
const mockFetchCompetitorSnapshotRuns = jest.fn();
const mockFetchCompetitorComparisonRuns = jest.fn();
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

jest.mock("../../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../../lib/api/client", () => {
  const actual = jest.requireActual("../../../lib/api/client");
  return {
    ...actual,
    fetchCompetitorSet: (...args: unknown[]) => mockFetchCompetitorSet(...args),
    fetchCompetitorDomains: (...args: unknown[]) => mockFetchCompetitorDomains(...args),
    fetchCompetitorSnapshotRuns: (...args: unknown[]) => mockFetchCompetitorSnapshotRuns(...args),
    fetchCompetitorComparisonRuns: (...args: unknown[]) => mockFetchCompetitorComparisonRuns(...args),
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

describe("competitor set detail workflow context", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    navigationState.params = { set_id: "set-1" };
    navigationState.searchParams = new URLSearchParams("site_id=site-1");
    mockUseOperatorContext.mockReturnValue(baseContext());
  });

  it("renders workflow context with parent and adjacent run links", async () => {
    mockFetchCompetitorSet.mockResolvedValueOnce({
      id: "set-1",
      business_id: "biz-1",
      site_id: "site-1",
      name: "Main competitors",
      city: "Denver",
      state: "CO",
      is_active: true,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-01T10:00:00Z",
      updated_at: "2026-03-01T10:00:00Z",
    });
    mockFetchCompetitorDomains.mockResolvedValueOnce({ items: [] });
    mockFetchCompetitorSnapshotRuns.mockResolvedValueOnce({
      items: [
        {
          id: "snap-1",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-1",
          status: "completed",
          client_audit_run_id: null,
          domains_targeted: 1,
          domains_completed: 1,
          pages_attempted: 5,
          pages_captured: 5,
          pages_skipped: 0,
          errors_encountered: 0,
          max_domains: 5,
          max_pages_per_domain: 10,
          max_depth: 2,
          same_domain_only: true,
          duration_ms: 12000,
          error_summary: null,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-01T10:00:00Z",
          updated_at: "2026-03-01T10:00:00Z",
          started_at: "2026-03-01T10:00:00Z",
          completed_at: "2026-03-01T10:00:10Z",
        },
      ],
    });
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
          total_findings: 3,
          critical_findings: 0,
          warning_findings: 2,
          info_findings: 1,
          client_pages_analyzed: 4,
          competitor_pages_analyzed: 7,
          duration_ms: 9000,
          error_summary: null,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-01T10:10:00Z",
          updated_at: "2026-03-01T10:10:00Z",
          started_at: "2026-03-01T10:10:00Z",
          completed_at: "2026-03-01T10:10:09Z",
        },
      ],
    });
    mockFetchRecommendations.mockResolvedValueOnce({ items: [], total: 0 });

    render(<CompetitorSetDetailPage />);

    await screen.findByTestId("competitor-set-workflow-context");
    const detailFocus = screen.getByTestId("competitor-set-detail-focus");
    expect(detailFocus).toBeInTheDocument();
    const setContextHeading = screen.getByRole("heading", { name: "Set Context" });
    expect(detailFocus.compareDocumentPosition(setContextHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "Competitor Sets" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Latest snapshot run" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Latest comparison run" })).toBeInTheDocument();
  });
});
