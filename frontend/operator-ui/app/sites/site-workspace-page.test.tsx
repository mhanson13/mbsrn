import { render, screen, waitFor } from "@testing-library/react";

import SiteWorkspacePage from "./[site_id]/page";
import type {
  CompetitorComparisonRun,
  CompetitorDomainListResponse,
  CompetitorSetListResponse,
  CompetitorSnapshotRunListResponse,
  RecommendationListResponse,
  RecommendationNarrative,
  RecommendationRunListResponse,
  SEOAuditRunListResponse,
  SEOSite,
} from "../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: SEOSite[];
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const navigationState = {
  params: { site_id: "site-1" },
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchAuditRuns = jest.fn<Promise<SEOAuditRunListResponse>, unknown[]>();
const mockFetchCompetitorSets = jest.fn<Promise<CompetitorSetListResponse>, unknown[]>();
const mockFetchCompetitorDomains = jest.fn<Promise<CompetitorDomainListResponse>, unknown[]>();
const mockFetchCompetitorSnapshotRuns = jest.fn<Promise<CompetitorSnapshotRunListResponse>, unknown[]>();
const mockFetchSiteCompetitorComparisonRuns = jest.fn<
  Promise<{ items: CompetitorComparisonRun[]; total: number }>,
  unknown[]
>();
const mockFetchRecommendations = jest.fn<Promise<RecommendationListResponse>, unknown[]>();
const mockFetchRecommendationRuns = jest.fn<Promise<RecommendationRunListResponse>, unknown[]>();
const mockFetchLatestRecommendationRunNarrative = jest.fn<Promise<RecommendationNarrative>, unknown[]>();

jest.mock("next/navigation", () => ({
  useParams: () => navigationState.params,
}));

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    fetchAuditRuns: (...args: unknown[]) => mockFetchAuditRuns(...args),
    fetchCompetitorSets: (...args: unknown[]) => mockFetchCompetitorSets(...args),
    fetchCompetitorDomains: (...args: unknown[]) => mockFetchCompetitorDomains(...args),
    fetchCompetitorSnapshotRuns: (...args: unknown[]) => mockFetchCompetitorSnapshotRuns(...args),
    fetchSiteCompetitorComparisonRuns: (...args: unknown[]) => mockFetchSiteCompetitorComparisonRuns(...args),
    fetchRecommendations: (...args: unknown[]) => mockFetchRecommendations(...args),
    fetchRecommendationRuns: (...args: unknown[]) => mockFetchRecommendationRuns(...args),
    fetchLatestRecommendationRunNarrative: (...args: unknown[]) =>
      mockFetchLatestRecommendationRunNarrative(...args),
  };
});

function buildSite(overrides: Partial<SEOSite> = {}): SEOSite {
  return {
    id: "site-1",
    business_id: "biz-1",
    display_name: "Main Site",
    base_url: "https://example.com/",
    normalized_domain: "example.com",
    is_active: true,
    is_primary: true,
    last_audit_run_id: "audit-1",
    last_audit_status: "completed",
    last_audit_completed_at: "2026-03-21T00:00:00Z",
    ...overrides,
  };
}

function baseContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [buildSite()],
    selectedSiteId: null,
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  navigationState.params = { site_id: "site-1" };
  mockUseOperatorContext.mockReturnValue(baseContext());
});

describe("site workspace", () => {
  it("renders site-centric sections and cross-links using existing site-scoped APIs", async () => {
    const contextValue = baseContext();
    mockUseOperatorContext.mockReturnValue(contextValue);

    mockFetchAuditRuns.mockResolvedValue({
      items: [
        {
          id: "audit-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          max_pages: 25,
          max_depth: 2,
          pages_discovered: 25,
          created_at: "2026-03-21T00:00:00Z",
          updated_at: "2026-03-21T00:05:00Z",
          started_at: "2026-03-21T00:00:30Z",
          completed_at: "2026-03-21T00:05:00Z",
          crawl_duration_ms: 270000,
          error_summary: null,
          created_by_principal_id: "principal-1",
          pages_crawled: 25,
          pages_skipped: 0,
          duplicate_urls_skipped: 0,
          errors_encountered: 0,
        },
      ],
      total: 1,
    });
    mockFetchCompetitorSets.mockResolvedValue({
      items: [
        {
          id: "set-1",
          business_id: "biz-1",
          site_id: "site-1",
          name: "Primary Competitors",
          city: null,
          state: null,
          is_active: true,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-21T00:00:00Z",
        },
      ],
      total: 1,
    });
    mockFetchCompetitorDomains.mockResolvedValue({
      items: [
        {
          id: "domain-1",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-1",
          domain: "competitor.com",
          base_url: "https://competitor.com/",
          display_name: "Competitor",
          source: "manual",
          is_active: true,
          notes: null,
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-21T00:00:00Z",
        },
      ],
      total: 1,
    });
    mockFetchCompetitorSnapshotRuns.mockResolvedValue({
      items: [
        {
          id: "snapshot-1",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-1",
          client_audit_run_id: "audit-1",
          status: "completed",
          max_domains: 10,
          max_pages_per_domain: 2,
          max_depth: 1,
          same_domain_only: true,
          domains_targeted: 1,
          domains_completed: 1,
          pages_attempted: 2,
          pages_captured: 2,
          pages_skipped: 0,
          errors_encountered: 0,
          started_at: "2026-03-21T00:10:00Z",
          completed_at: "2026-03-21T00:12:00Z",
          duration_ms: 120000,
          error_summary: null,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-21T00:10:00Z",
          updated_at: "2026-03-21T00:12:00Z",
        },
      ],
      total: 1,
    });
    mockFetchSiteCompetitorComparisonRuns.mockResolvedValue({
      items: [
        {
          id: "comparison-1",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-1",
          snapshot_run_id: "snapshot-1",
          baseline_audit_run_id: "audit-1",
          status: "completed",
          total_findings: 4,
          critical_findings: 1,
          warning_findings: 2,
          info_findings: 1,
          client_pages_analyzed: 10,
          competitor_pages_analyzed: 10,
          finding_type_counts_json: {},
          category_counts_json: {},
          severity_counts_json: {},
          started_at: "2026-03-21T00:20:00Z",
          completed_at: "2026-03-21T00:25:00Z",
          duration_ms: 300000,
          error_summary: null,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-21T00:20:00Z",
          updated_at: "2026-03-21T00:25:00Z",
        },
      ],
      total: 1,
    });
    mockFetchRecommendations.mockResolvedValue({
      items: [
        {
          id: "rec-1",
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
          title: "Fix title tags",
          rationale: "Title tags are missing core keywords.",
          decision_reason: null,
          created_at: "2026-03-21T00:30:00Z",
          updated_at: "2026-03-21T00:31:00Z",
        },
      ],
      total: 1,
      filtered_summary: {
        total: 1,
        open: 1,
        accepted: 0,
        dismissed: 0,
        high_priority: 1,
      },
    });
    mockFetchRecommendationRuns.mockResolvedValue({
      items: [
        {
          id: "run-1",
          business_id: "biz-1",
          site_id: "site-1",
          audit_run_id: "audit-1",
          comparison_run_id: "comparison-1",
          status: "completed",
          total_recommendations: 1,
          critical_recommendations: 0,
          warning_recommendations: 1,
          info_recommendations: 0,
          category_counts_json: {},
          effort_bucket_counts_json: {},
          started_at: "2026-03-21T00:28:00Z",
          completed_at: "2026-03-21T00:32:00Z",
          duration_ms: 240000,
          error_summary: null,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-21T00:28:00Z",
          updated_at: "2026-03-21T00:32:00Z",
        },
      ],
      total: 1,
    });
    mockFetchLatestRecommendationRunNarrative.mockResolvedValue({
      id: "narrative-1",
      business_id: "biz-1",
      site_id: "site-1",
      recommendation_run_id: "run-1",
      version: 2,
      status: "completed",
      narrative_text: "Narrative body.",
      top_themes_json: ["titles", "metadata"],
      sections_json: { summary: "text" },
      provider_name: "provider",
      model_name: "model",
      prompt_version: "v1",
      error_message: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:33:00Z",
      updated_at: "2026-03-21T00:33:00Z",
    });

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Site SEO Workspace" });
    await screen.findByRole("heading", { name: "Site Activity Timeline" });
    await screen.findByRole("heading", { name: "Recent Audit Runs" });
    await screen.findByRole("heading", { name: "Competitor Readiness" });
    await screen.findByRole("heading", { name: "Recommendation Queue" });
    await screen.findByRole("heading", { name: "Recommendation Runs and Narratives" });
    const timelineRows = screen.getAllByTestId("site-activity-row");
    expect(timelineRows[0]).toHaveTextContent("Recommendation Narrative");
    expect(timelineRows[0]).toHaveTextContent("Narrative v2 (run-1)");
    expect(timelineRows[1]).toHaveTextContent("Recommendation Run");
    expect(timelineRows[1]).toHaveTextContent("Recommendation Run run-1");
    expect(timelineRows[2]).toHaveTextContent("Comparison Run");
    expect(timelineRows[2]).toHaveTextContent("Comparison comparison-1");
    expect(timelineRows[3]).toHaveTextContent("Snapshot Run");
    expect(timelineRows[3]).toHaveTextContent("Snapshot snapshot-1");
    expect(timelineRows[4]).toHaveTextContent("Audit Run");
    expect(timelineRows[4]).toHaveTextContent("Audit audit-1");
    expect(screen.getByRole("link", { name: "Narrative v2 (run-1)" })).toHaveAttribute(
      "href",
      "/recommendations/runs/run-1/narratives/narrative-1?site_id=site-1",
    );
    expect(screen.getByRole("link", { name: "Comparison comparison-1" })).toHaveAttribute(
      "href",
      "/competitors/comparison-runs/comparison-1?site_id=site-1&set_id=set-1",
    );
    expect(screen.getByRole("link", { name: "Snapshot snapshot-1" })).toHaveAttribute(
      "href",
      "/competitors/snapshot-runs/snapshot-1?site_id=site-1&set_id=set-1",
    );
    expect(screen.getByRole("link", { name: "Audit audit-1" })).toHaveAttribute("href", "/audits/audit-1");
    expect(screen.getByRole("link", { name: "Open Competitor Surfaces" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Latest v2/ })).toBeInTheDocument();
    await waitFor(() => expect(contextValue.setSelectedSiteId).toHaveBeenCalledWith("site-1"));
  });

  it("shows safe empty timeline state when no site activity exists", async () => {
    mockFetchAuditRuns.mockResolvedValue({ items: [], total: 0 });
    mockFetchCompetitorSets.mockResolvedValue({ items: [], total: 0 });
    mockFetchSiteCompetitorComparisonRuns.mockResolvedValue({ items: [], total: 0 });
    mockFetchRecommendations.mockResolvedValue({
      items: [],
      total: 0,
      filtered_summary: {
        total: 0,
        open: 0,
        accepted: 0,
        dismissed: 0,
        high_priority: 0,
      },
    });
    mockFetchRecommendationRuns.mockResolvedValue({ items: [], total: 0 });

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Site Activity Timeline" });
    await screen.findByText("No recent site activity events are available for this site yet.");
    expect(screen.queryAllByTestId("site-activity-row")).toHaveLength(0);
  });

  it("shows safe not-found state for inaccessible site ids", async () => {
    navigationState.params = { site_id: "site-missing" };

    render(<SiteWorkspacePage />);

    await screen.findByText("This site was not found or is not accessible in your tenant scope.");
    expect(mockFetchAuditRuns).not.toHaveBeenCalled();
  });
});
