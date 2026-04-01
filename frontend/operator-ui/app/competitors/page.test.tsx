import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import CompetitorsPage from "./page";
import type {
  CompetitorComparisonRunListResponse,
  CompetitorDomainListResponse,
  CompetitorSetListResponse,
  CompetitorSnapshotRunListResponse,
} from "../../lib/api/types";

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
  searchParams: new URLSearchParams(),
  push: jest.fn(),
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchCompetitorSets = jest.fn<Promise<CompetitorSetListResponse>, unknown[]>();
const mockFetchCompetitorDomains = jest.fn<Promise<CompetitorDomainListResponse>, unknown[]>();
const mockFetchCompetitorSnapshotRuns = jest.fn<Promise<CompetitorSnapshotRunListResponse>, unknown[]>();
const mockFetchSiteCompetitorComparisonRuns = jest.fn<Promise<CompetitorComparisonRunListResponse>, unknown[]>();

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
  useRouter: () => ({
    push: navigationState.push,
  }),
  useSearchParams: () => navigationState.searchParams,
}));

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    fetchCompetitorSets: (...args: unknown[]) => mockFetchCompetitorSets(...args),
    fetchCompetitorDomains: (...args: unknown[]) => mockFetchCompetitorDomains(...args),
    fetchCompetitorSnapshotRuns: (...args: unknown[]) => mockFetchCompetitorSnapshotRuns(...args),
    fetchSiteCompetitorComparisonRuns: (...args: unknown[]) => mockFetchSiteCompetitorComparisonRuns(...args),
  };
});

function baseOperatorContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [{ id: "site-1", display_name: "Site One" }],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  navigationState.searchParams = new URLSearchParams();
  mockUseOperatorContext.mockReturnValue(baseOperatorContext());
  mockFetchCompetitorSnapshotRuns.mockResolvedValue({
    items: [],
    total: 0,
  });
  mockFetchSiteCompetitorComparisonRuns.mockResolvedValue({
    items: [],
    total: 0,
  });
});

describe("competitors page site-scoped loading", () => {
  it("renders readiness state for a configured site", async () => {
    mockFetchCompetitorSets.mockResolvedValueOnce({
      items: [
        {
          id: "set-1",
          business_id: "biz-1",
          site_id: "site-1",
          name: "Front Range",
          city: "Denver",
          state: "CO",
          is_active: true,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 1,
    });
    mockFetchCompetitorDomains.mockResolvedValueOnce({
      items: [
        {
          id: "domain-1",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-1",
          domain: "competitor.example",
          base_url: "https://competitor.example/",
          display_name: "Competitor",
          source: "manual",
          is_active: true,
          notes: null,
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 1,
    });
    mockFetchCompetitorSnapshotRuns.mockResolvedValueOnce({
      items: [
        {
          id: "snapshot-1",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-1",
          client_audit_run_id: null,
          status: "completed",
          max_domains: 5,
          max_pages_per_domain: 3,
          max_depth: 1,
          same_domain_only: true,
          domains_targeted: 1,
          domains_completed: 1,
          pages_attempted: 1,
          pages_captured: 1,
          pages_skipped: 0,
          errors_encountered: 0,
          started_at: "2026-03-20T00:00:00Z",
          completed_at: "2026-03-20T00:01:00Z",
          duration_ms: 1000,
          error_summary: null,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:01:00Z",
        },
      ],
      total: 1,
    });
    mockFetchSiteCompetitorComparisonRuns.mockResolvedValueOnce({
      items: [
        {
          id: "comparison-1",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-1",
          snapshot_run_id: "snapshot-1",
          baseline_audit_run_id: null,
          status: "completed",
          total_findings: 2,
          critical_findings: 0,
          warning_findings: 1,
          info_findings: 1,
          client_pages_analyzed: 1,
          competitor_pages_analyzed: 1,
          finding_type_counts_json: {},
          category_counts_json: {},
          severity_counts_json: {},
          started_at: "2026-03-20T00:02:00Z",
          completed_at: "2026-03-20T00:03:00Z",
          duration_ms: 1000,
          error_summary: null,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-20T00:02:00Z",
          updated_at: "2026-03-20T00:03:00Z",
        },
      ],
      total: 1,
    });

    render(<CompetitorsPage />);

    const frontRangeRows = await screen.findAllByText("Front Range");
    expect(frontRangeRows.length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Site")).toHaveClass("operator-select");
    expect(document.querySelector(".page-container-width-wide")).toBeTruthy();
    expect(screen.getByTestId("competitor-quick-scan")).toBeInTheDocument();
    const quickScanItem = screen.getByTestId("competitor-quick-scan-item-set-1");
    expect(quickScanItem).toHaveTextContent("Active set");
    expect(quickScanItem).toHaveTextContent("Snapshot: completed");
    expect(mockFetchCompetitorSets).toHaveBeenCalledWith("token-1", "biz-1", "site-1");
    expect(screen.getByText("Competitor Sets: 1")).toBeInTheDocument();
    expect(screen.getByText("Active Sets: 1/1")).toBeInTheDocument();
    expect(screen.getByText("Competitor Domains: 1")).toBeInTheDocument();
    expect(screen.getByText("This site has configured competitor data and recent comparison activity.")).toBeInTheDocument();
  });

  it("applies URL site_id context so competitors load for the linked site", async () => {
    navigationState.searchParams = new URLSearchParams("site_id=site-2");
    const contextState = baseOperatorContext({
      sites: [
        { id: "site-1", display_name: "Site One" },
        { id: "site-2", display_name: "Site Two" },
      ],
      selectedSiteId: "site-1",
    });
    contextState.setSelectedSiteId.mockImplementation((nextSiteId: string) => {
      contextState.selectedSiteId = nextSiteId;
    });
    mockUseOperatorContext.mockImplementation(() => contextState);

    mockFetchCompetitorSets.mockImplementation(async (_token, _businessId, siteId) => {
      if (siteId === "site-2") {
        return {
          items: [
            {
              id: "set-2",
              business_id: "biz-1",
              site_id: "site-2",
              name: "Metro Competitors",
              city: "Aurora",
              state: "CO",
              is_active: true,
              created_by_principal_id: "principal-2",
              created_at: "2026-03-20T00:00:00Z",
              updated_at: "2026-03-20T00:00:00Z",
            },
          ],
          total: 1,
        };
      }
      return { items: [], total: 0 };
    });
    mockFetchCompetitorDomains.mockResolvedValue({
      items: [],
      total: 0,
    });

    const view = render(<CompetitorsPage />);

    await waitFor(() => expect(contextState.setSelectedSiteId).toHaveBeenCalledWith("site-2"));

    view.rerender(<CompetitorsPage />);
    await screen.findByText("Metro Competitors");
    expect(mockFetchCompetitorSets).toHaveBeenCalledWith("token-1", "biz-1", "site-2");
  });

  it("shows explicit empty-state reason when no competitor sets are configured", async () => {
    mockFetchCompetitorSets.mockResolvedValueOnce({
      items: [],
      total: 0,
    });

    render(<CompetitorsPage />);

    const matches = await screen.findAllByText("This site has no competitor sets configured yet.");
    expect(matches.length).toBeGreaterThan(0);
  });

  it("shows explicit readiness guidance when domains exist but snapshot has not run", async () => {
    mockFetchCompetitorSets.mockResolvedValueOnce({
      items: [
        {
          id: "set-3",
          business_id: "biz-1",
          site_id: "site-1",
          name: "No Snapshot Yet",
          city: null,
          state: null,
          is_active: true,
          created_by_principal_id: null,
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 1,
    });
    mockFetchCompetitorDomains.mockResolvedValueOnce({
      items: [
        {
          id: "domain-3",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-3",
          domain: "nosnapshot.example",
          base_url: "https://nosnapshot.example/",
          display_name: null,
          source: "manual",
          is_active: true,
          notes: null,
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 1,
    });

    render(<CompetitorsPage />);

    await screen.findByText("No Snapshot Yet");
    expect(screen.getByText("Competitor domains exist, but no snapshot run has been recorded yet.")).toBeInTheDocument();
  });
});
