import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import AuditRunDetailPage from "./page";

const navigationState = {
  params: { run_id: "audit-run-1" },
};

const mockUseOperatorContext = jest.fn();
const mockFetchAuditRun = jest.fn();
const mockFetchAuditRunSummary = jest.fn();
const mockFetchAuditRunFindings = jest.fn();
const mockFetchRecommendationRuns = jest.fn();

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
}));

jest.mock("../../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../../lib/api/client", () => {
  const actual = jest.requireActual("../../../lib/api/client");
  return {
    ...actual,
    fetchAuditRun: (...args: unknown[]) => mockFetchAuditRun(...args),
    fetchAuditRunSummary: (...args: unknown[]) => mockFetchAuditRunSummary(...args),
    fetchAuditRunFindings: (...args: unknown[]) => mockFetchAuditRunFindings(...args),
    fetchRecommendationRuns: (...args: unknown[]) => mockFetchRecommendationRuns(...args),
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

describe("audit run detail workflow context", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    navigationState.params = { run_id: "audit-run-1" };
    mockUseOperatorContext.mockReturnValue(baseContext());
  });

  it("renders workflow context links for deep-route navigation continuity", async () => {
    mockFetchAuditRun.mockResolvedValueOnce({
      id: "audit-run-1",
      business_id: "biz-1",
      site_id: "site-1",
      status: "completed",
      max_pages: 50,
      max_depth: 2,
      pages_discovered: 12,
      pages_crawled: 10,
      pages_skipped: 2,
      duplicate_urls_skipped: 1,
      errors_encountered: 0,
      crawl_duration_ms: 120000,
      error_summary: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-01T10:00:00Z",
      started_at: "2026-03-01T10:00:10Z",
      completed_at: "2026-03-01T10:02:10Z",
      updated_at: "2026-03-01T10:02:10Z",
    });
    mockFetchAuditRunSummary.mockResolvedValueOnce({
      audit_run_id: "audit-run-1",
      total_findings: 0,
      critical_findings: 0,
      warning_findings: 0,
      info_findings: 0,
      total_pages: 10,
      health_score: 88,
      by_category: {},
      by_severity: {},
      updated_at: "2026-03-01T10:02:10Z",
    });
    mockFetchAuditRunFindings.mockResolvedValueOnce({
      items: [],
      by_category: {},
      by_severity: {},
    });
    mockFetchRecommendationRuns.mockResolvedValueOnce({ items: [], total: 0 });

    render(<AuditRunDetailPage />);

    await screen.findByTestId("audit-run-workflow-context");
    expect(screen.getByRole("link", { name: "Audit Runs" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Recommendation Queue" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Competitor Sets" })).toBeInTheDocument();
  });
});
