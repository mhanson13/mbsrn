import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SiteWorkspacePage from "./[site_id]/page";
import SiteMigrationWorkflowPage from "./[site_id]/migration/page";
import { ApiRequestError } from "../../lib/api/client";
import type {
  AIPromptPreview,
  AutomationRunListResponse,
  BusinessSettings,
  CompetitorComparisonRun,
  CompetitorProfileDraft,
  CompetitorProfileGenerationRun,
  CompetitorProfileGenerationRunDetailResponse,
  CompetitorProfileGenerationRunListResponse,
  CompetitorProfileGenerationSummaryResponse,
  CompetitorDomainListResponse,
  CompetitorSetListResponse,
  CompetitorSnapshotRunListResponse,
  GA4SiteOnboardingStatusResponse,
  GoogleBusinessProfileConnectionStatusResponse,
  MigrationArtifactFilePreview,
  MigrationArtifactDeleteActionResponse,
  MigrationArtifactVersion,
  MigrationDraftReadinessPreflight,
  MigrationDeployActionResponse,
  MigrationHistoryListResponse,
  MigrationPublishActionResponse,
  MigrationRepositoryAdoptActionResponse,
  MigrationArtifactVersionListResponse,
  MigrationWorkspace,
  MigrationWorkspaceSummary,
  RecommendationAnalysisFreshness,
  Recommendation,
  RecommendationListResponse,
  RecommendationNarrative,
  RecommendationTuningImpactPreview,
  RecommendationRun,
  RecommendationRunListResponse,
  RecommendationWorkspaceSummaryResponse,
  SearchConsoleSiteSummaryResponse,
  SEOAuditRunListResponse,
  SEOSite,
  SiteGA4Insights,
  SiteAnalyticsSummaryResponse,
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
const FIXED_NOW_MS = Date.parse("2026-03-21T18:00:00Z");

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchAuditRuns = jest.fn<Promise<SEOAuditRunListResponse>, unknown[]>();
const mockFetchCompetitorSets = jest.fn<Promise<CompetitorSetListResponse>, unknown[]>();
const mockFetchCompetitorDomains = jest.fn<Promise<CompetitorDomainListResponse>, unknown[]>();
const mockFetchCompetitorSnapshotRuns = jest.fn<Promise<CompetitorSnapshotRunListResponse>, unknown[]>();
const mockFetchGoogleBusinessProfileConnection = jest.fn<
  Promise<GoogleBusinessProfileConnectionStatusResponse>,
  unknown[]
>();
const mockFetchSiteCompetitorComparisonRuns = jest.fn<
  Promise<{ items: CompetitorComparisonRun[]; total: number }>,
  unknown[]
>();
const mockFetchRecommendations = jest.fn<Promise<RecommendationListResponse>, unknown[]>();
const mockFetchRecommendationWorkspaceSummary = jest.fn<Promise<RecommendationWorkspaceSummaryResponse>, unknown[]>();
const mockFetchRecommendationRuns = jest.fn<Promise<RecommendationRunListResponse>, unknown[]>();
const mockFetchAutomationRuns = jest.fn<Promise<AutomationRunListResponse>, unknown[]>();
const mockFetchSiteAnalyticsSummary = jest.fn<Promise<SiteAnalyticsSummaryResponse>, unknown[]>();
const mockFetchGA4SiteOnboardingStatus = jest.fn<Promise<GA4SiteOnboardingStatusResponse>, unknown[]>();
const mockFetchSearchConsoleSiteSummary = jest.fn<Promise<SearchConsoleSiteSummaryResponse>, unknown[]>();
const mockCreateRecommendationRun = jest.fn<Promise<RecommendationRun>, unknown[]>();
const mockFetchLatestRecommendationRunNarrative = jest.fn<Promise<RecommendationNarrative>, unknown[]>();
const mockPreviewRecommendationTuningImpact = jest.fn<Promise<RecommendationTuningImpactPreview>, unknown[]>();
const mockFetchBusinessSettings = jest.fn<Promise<BusinessSettings>, unknown[]>();
const mockUpdateBusinessSettings = jest.fn<Promise<BusinessSettings>, unknown[]>();
const mockUpdateSite = jest.fn<Promise<SEOSite>, unknown[]>();
const mockFetchCompetitorProfileGenerationRuns = jest.fn<
  Promise<CompetitorProfileGenerationRunListResponse>,
  unknown[]
>();
const mockFetchCompetitorProfileGenerationRunDetail = jest.fn<
  Promise<CompetitorProfileGenerationRunDetailResponse>,
  unknown[]
>();
const mockFetchCompetitorProfileGenerationSummary = jest.fn<
  Promise<CompetitorProfileGenerationSummaryResponse>,
  unknown[]
>();
const mockCreateCompetitorProfileGenerationRun = jest.fn<
  Promise<CompetitorProfileGenerationRunDetailResponse>,
  unknown[]
>();
const mockRetryCompetitorProfileGenerationRun = jest.fn<
  Promise<CompetitorProfileGenerationRunDetailResponse>,
  unknown[]
>();
const mockAcceptCompetitorProfileDraft = jest.fn<Promise<CompetitorProfileDraft>, unknown[]>();
const mockRejectCompetitorProfileDraft = jest.fn<Promise<CompetitorProfileDraft>, unknown[]>();
const mockEditCompetitorProfileDraft = jest.fn<Promise<CompetitorProfileDraft>, unknown[]>();
const mockBindActionExecutionItemAutomation = jest.fn<Promise<unknown>, unknown[]>();
const mockRunActionExecutionItemAutomation = jest.fn<Promise<unknown>, unknown[]>();
const mockUpsertMigrationWorkspace = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockFetchMigrationWorkspaceSummary = jest.fn<Promise<MigrationWorkspaceSummary>, unknown[]>();
const mockFetchMigrationArtifactVersions = jest.fn<Promise<MigrationArtifactVersionListResponse>, unknown[]>();
const mockFetchMigrationArtifactFilePreview = jest.fn<Promise<MigrationArtifactFilePreview>, unknown[]>();
const mockIngestMigrationSource = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockUpdateMigrationRequirements = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockSuggestMigrationRequirementField = jest.fn<Promise<Record<string, unknown>>, unknown[]>();
const mockUpdateMigrationEnrichedContent = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockUpdateMigrationPublishConfig = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockUpdateMigrationDeployConfig = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockUpdateMigrationAnalyticsConfig = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockDeleteMigrationArtifactVersion = jest.fn<Promise<MigrationArtifactDeleteActionResponse>, unknown[]>();
const mockApproveMigrationArtifactVersion = jest.fn<Promise<MigrationArtifactVersion>, unknown[]>();
const mockPublishMigrationArtifactVersion = jest.fn<Promise<MigrationPublishActionResponse>, unknown[]>();
const mockAdoptMigrationPublishRepository = jest.fn<Promise<MigrationRepositoryAdoptActionResponse>, unknown[]>();
const mockDeployMigrationArtifactVersion = jest.fn<Promise<MigrationDeployActionResponse>, unknown[]>();
const mockRefreshMigrationDeployStatus = jest.fn<Promise<MigrationDeployActionResponse>, unknown[]>();
const mockFetchMigrationPublishHistory = jest.fn<Promise<MigrationHistoryListResponse>, unknown[]>();
const mockFetchMigrationDeployHistory = jest.fn<Promise<MigrationHistoryListResponse>, unknown[]>();
const mockGenerateMigrationDraftArtifacts = jest.fn<Promise<MigrationArtifactVersion>, unknown[]>();
const mockFetchMigrationDraftReadiness = jest.fn<Promise<MigrationDraftReadinessPreflight>, unknown[]>();
const mockFetchMigrationMediaAssets = jest.fn<Promise<Record<string, unknown>>, unknown[]>();
const mockUploadMigrationMediaAsset = jest.fn<Promise<Record<string, unknown>>, unknown[]>();
const mockImportMigrationDiscoveredMediaAssets = jest.fn<Promise<Record<string, unknown>>, unknown[]>();
const mockUpdateMigrationMediaAsset = jest.fn<Promise<Record<string, unknown>>, unknown[]>();
const mockUpdateMigrationMediaAssetLifecycle = jest.fn<Promise<Record<string, unknown>>, unknown[]>();
const mockSuggestMigrationMediaAssetMetadata = jest.fn<Promise<Record<string, unknown>>, unknown[]>();
const mockSuggestMigrationMediaAssetsMetadataBatch = jest.fn<Promise<Record<string, unknown>>, unknown[]>();

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
    fetchGoogleBusinessProfileConnection: (...args: unknown[]) => mockFetchGoogleBusinessProfileConnection(...args),
    fetchSiteCompetitorComparisonRuns: (...args: unknown[]) => mockFetchSiteCompetitorComparisonRuns(...args),
    fetchRecommendations: (...args: unknown[]) => mockFetchRecommendations(...args),
    fetchRecommendationWorkspaceSummary: (...args: unknown[]) => mockFetchRecommendationWorkspaceSummary(...args),
    fetchRecommendationRuns: (...args: unknown[]) => mockFetchRecommendationRuns(...args),
    fetchAutomationRuns: (...args: unknown[]) => mockFetchAutomationRuns(...args),
    fetchSiteAnalyticsSummary: (...args: unknown[]) => mockFetchSiteAnalyticsSummary(...args),
    fetchGA4SiteOnboardingStatus: (...args: unknown[]) => mockFetchGA4SiteOnboardingStatus(...args),
    fetchSearchConsoleSiteSummary: (...args: unknown[]) => mockFetchSearchConsoleSiteSummary(...args),
    createRecommendationRun: (...args: unknown[]) => mockCreateRecommendationRun(...args),
    fetchLatestRecommendationRunNarrative: (...args: unknown[]) =>
      mockFetchLatestRecommendationRunNarrative(...args),
    previewRecommendationTuningImpact: (...args: unknown[]) => mockPreviewRecommendationTuningImpact(...args),
    fetchBusinessSettings: (...args: unknown[]) => mockFetchBusinessSettings(...args),
    updateBusinessSettings: (...args: unknown[]) => mockUpdateBusinessSettings(...args),
    updateSite: (...args: unknown[]) => mockUpdateSite(...args),
    fetchCompetitorProfileGenerationRuns: (...args: unknown[]) =>
      mockFetchCompetitorProfileGenerationRuns(...args),
    fetchCompetitorProfileGenerationRunDetail: (...args: unknown[]) =>
      mockFetchCompetitorProfileGenerationRunDetail(...args),
    fetchCompetitorProfileGenerationSummary: (...args: unknown[]) =>
      mockFetchCompetitorProfileGenerationSummary(...args),
    createCompetitorProfileGenerationRun: (...args: unknown[]) =>
      mockCreateCompetitorProfileGenerationRun(...args),
    retryCompetitorProfileGenerationRun: (...args: unknown[]) =>
      mockRetryCompetitorProfileGenerationRun(...args),
    acceptCompetitorProfileDraft: (...args: unknown[]) => mockAcceptCompetitorProfileDraft(...args),
    rejectCompetitorProfileDraft: (...args: unknown[]) => mockRejectCompetitorProfileDraft(...args),
    editCompetitorProfileDraft: (...args: unknown[]) => mockEditCompetitorProfileDraft(...args),
    bindActionExecutionItemAutomation: (...args: unknown[]) =>
      mockBindActionExecutionItemAutomation(...args),
    runActionExecutionItemAutomation: (...args: unknown[]) =>
      mockRunActionExecutionItemAutomation(...args),
    upsertMigrationWorkspace: (...args: unknown[]) => mockUpsertMigrationWorkspace(...args),
    fetchMigrationWorkspaceSummary: (...args: unknown[]) => mockFetchMigrationWorkspaceSummary(...args),
    fetchMigrationArtifactVersions: (...args: unknown[]) => mockFetchMigrationArtifactVersions(...args),
    fetchMigrationArtifactFilePreview: (...args: unknown[]) => mockFetchMigrationArtifactFilePreview(...args),
    ingestMigrationSource: (...args: unknown[]) => mockIngestMigrationSource(...args),
    updateMigrationRequirements: (...args: unknown[]) => mockUpdateMigrationRequirements(...args),
    suggestMigrationRequirementField: (...args: unknown[]) => mockSuggestMigrationRequirementField(...args),
    updateMigrationEnrichedContent: (...args: unknown[]) => mockUpdateMigrationEnrichedContent(...args),
    updateMigrationPublishConfig: (...args: unknown[]) => mockUpdateMigrationPublishConfig(...args),
    updateMigrationDeployConfig: (...args: unknown[]) => mockUpdateMigrationDeployConfig(...args),
    updateMigrationAnalyticsConfig: (...args: unknown[]) => mockUpdateMigrationAnalyticsConfig(...args),
    deleteMigrationArtifactVersion: (...args: unknown[]) => mockDeleteMigrationArtifactVersion(...args),
    approveMigrationArtifactVersion: (...args: unknown[]) => mockApproveMigrationArtifactVersion(...args),
    publishMigrationArtifactVersion: (...args: unknown[]) => mockPublishMigrationArtifactVersion(...args),
    adoptMigrationPublishRepository: (...args: unknown[]) => mockAdoptMigrationPublishRepository(...args),
    deployMigrationArtifactVersion: (...args: unknown[]) => mockDeployMigrationArtifactVersion(...args),
    refreshMigrationDeployStatus: (...args: unknown[]) => mockRefreshMigrationDeployStatus(...args),
    fetchMigrationPublishHistory: (...args: unknown[]) => mockFetchMigrationPublishHistory(...args),
    fetchMigrationDeployHistory: (...args: unknown[]) => mockFetchMigrationDeployHistory(...args),
    generateMigrationDraftArtifacts: (...args: unknown[]) => mockGenerateMigrationDraftArtifacts(...args),
    fetchMigrationDraftReadiness: (...args: unknown[]) => mockFetchMigrationDraftReadiness(...args),
    fetchMigrationMediaAssets: (...args: unknown[]) => mockFetchMigrationMediaAssets(...args),
    uploadMigrationMediaAsset: (...args: unknown[]) => mockUploadMigrationMediaAsset(...args),
    importMigrationDiscoveredMediaAssets: (...args: unknown[]) => mockImportMigrationDiscoveredMediaAssets(...args),
    updateMigrationMediaAsset: (...args: unknown[]) => mockUpdateMigrationMediaAsset(...args),
    updateMigrationMediaAssetLifecycle: (...args: unknown[]) => mockUpdateMigrationMediaAssetLifecycle(...args),
    suggestMigrationMediaAssetMetadata: (...args: unknown[]) => mockSuggestMigrationMediaAssetMetadata(...args),
    suggestMigrationMediaAssetsMetadataBatch: (...args: unknown[]) =>
      mockSuggestMigrationMediaAssetsMetadataBatch(...args),
  };
});

describe("site workspace modernized structure", () => {
  it("renders command-center tabs for workflow launchers and latest activity summaries", async () => {
    render(<SiteWorkspacePage />);

    expect(await screen.findByRole("tab", { name: "Workflows" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Latest Activity" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Migration" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Operator Focus" })).not.toBeInTheDocument();
  });

  it("provides dedicated migration route launch points from the workspace", async () => {
    render(<SiteWorkspacePage />);

    const heroLaunch = await screen.findByTestId("workspace-hero-open-migration-button");
    expect(heroLaunch).toHaveAttribute("href", "/sites/site-1/migration");

    const tabLaunch = screen.getByTestId("workspace-open-migration-shortcut");
    expect(tabLaunch).toHaveAttribute("href", "/sites/site-1/migration");
  });

  it("removes GA4 connect controls from the site workspace and routes profile actions to Sites setup", async () => {
    render(<SiteWorkspacePage />);

    expect(screen.queryByTestId("workspace-ga4-connect-panel")).not.toBeInTheDocument();
    const profileLinks = await screen.findAllByRole("link", { name: "Open Site Setup" });
    expect(profileLinks.length).toBeGreaterThan(0);
    profileLinks.forEach((link) => expect(link).toHaveAttribute("href", "/sites?site_id=site-1#selected-site-setup"));
  });

  it("keeps only compact workflow launchers on the site workspace and links to dedicated routes", async () => {
    render(<SiteWorkspacePage />);

    const recommendationLauncher = await screen.findByTestId("workspace-launcher-recommendations");
    const competitorLauncher = screen.getByTestId("workspace-launcher-competitors");
    const migrationLauncher = screen.getByTestId("workspace-launcher-migration");
    expect(recommendationLauncher).toBeInTheDocument();
    expect(competitorLauncher).toBeInTheDocument();
    expect(migrationLauncher).toBeInTheDocument();

    expect(screen.getByTestId("workspace-open-recommendations-shortcut")).toHaveAttribute("href", "/recommendations");
    expect(screen.getByTestId("workspace-open-competitors-shortcut")).toHaveAttribute(
      "href",
      "/competitors?site_id=site-1",
    );
    expect(screen.getByTestId("workspace-open-migration-shortcut")).toHaveAttribute("href", "/sites/site-1/migration");

    expect(screen.queryByTestId("workspace-recommendation-output-review")).not.toBeInTheDocument();
    expect(screen.queryByTestId("competitor-candidate-pipeline-table")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workspace-timeline-panel")).not.toBeInTheDocument();
  });

  it("keeps a single recommendation tabpanel id in the workspace DOM", async () => {
    render(<SiteWorkspacePage />);
    await screen.findByTestId("workspace-launchers-panel");

    const recommendationPanels = document.querySelectorAll("#workspace-content-recommendations-panel");
    expect(recommendationPanels).toHaveLength(1);
  });

  it("shows compact site-scoped GA4 health in workspace summary metadata", async () => {
    mockFetchSiteAnalyticsSummary.mockResolvedValue(
      buildSiteAnalyticsSummary({
        ga4_health: {
          ga4_configured: false,
          ga4_property_id_present: false,
          ga4_property_verified: null,
          ga4_reachable: false,
          ga4_data_available: null,
          ga4_last_checked_at: null,
          ga4_health_status: "not_configured",
          ga4_health_reason: "not_configured",
          ga4_health_message: "Add a GA4 property ID for this site.",
          ga4_health_source: "site_property",
          ga4_scope_granted: null,
          ga4_required_scope: "https://www.googleapis.com/auth/analytics.readonly",
          ga4_auth_mode: "unknown",
        },
        ga4_insights: {
          status: "not_configured",
          source: "unavailable",
          date_range_label: "Last 28 days vs previous 28 days",
          checked_at: null,
          top_landing_pages: [],
          traffic_trend: null,
          engagement_trend: null,
          message: "Add a GA4 property ID for this site.",
        },
      }),
    );

    render(<SiteWorkspacePage />);

    const ga4SummaryCard = await screen.findByTestId("workspace-summary-ga4-onboarding");
    expect(ga4SummaryCard).toHaveTextContent("Not configured");
    expect(ga4SummaryCard).toHaveTextContent("Add a GA4 property ID for this site.");
  });

  it("renders safely when GA4 health and GA4 insights are null", async () => {
    seedRichWorkspaceData();
    mockFetchSiteAnalyticsSummary.mockResolvedValue(
      buildSiteAnalyticsSummary({
        ga4_health: null,
        ga4_insights: null,
      }),
    );

    render(<SiteWorkspacePage />);

    const ga4SummaryCard = await screen.findByTestId("workspace-summary-ga4-onboarding");
    const topLandingCard = screen.getByTestId("workspace-summary-ga4-top-landing-pages");
    const trafficCard = screen.getByTestId("workspace-summary-traffic");
    const engagementCard = screen.getByTestId("workspace-summary-ga4-engagement-trend");
    const acquisitionChannelCard = screen.getByTestId("workspace-summary-ga4-acquisition-channel");
    const acquisitionSourceCard = screen.getByTestId("workspace-summary-ga4-acquisition-source");
    const acquisitionMixCard = screen.getByTestId("workspace-summary-ga4-acquisition-mix");
    expect(ga4SummaryCard).toHaveTextContent("Reachable");
    expect(topLandingCard).toHaveTextContent("0 pages");
    expect(trafficCard).toHaveTextContent("Available");
    expect(engagementCard).toHaveTextContent("Available");
    expect(acquisitionChannelCard).toBeInTheDocument();
    expect(acquisitionSourceCard).toBeInTheDocument();
    expect(acquisitionMixCard).toBeInTheDocument();
  });

  it("renders compact GA4 insight cards in the workspace snapshot when insights are available", async () => {
    seedRichWorkspaceData();
    mockFetchSiteAnalyticsSummary.mockResolvedValue(
      buildSiteAnalyticsSummary({
        ga4_insights: {
          status: "available",
          source: "site_property",
          date_range_label: "Last 28 days vs previous 28 days",
          checked_at: "2026-03-21T17:35:00Z",
          top_landing_pages: [
            {
              path: "/",
              title: "Home",
              sessions: 220,
              active_users: 180,
              views: 330,
              engagement_rate: 0.61,
              average_engagement_time_seconds: 85,
              trend_label: "improving",
              operator_hint: "Engagement looks healthy. Preserve this page during future migration or content changes.",
            },
            {
              path: "/services",
              title: "Services",
              sessions: 130,
              active_users: 100,
              views: 210,
              engagement_rate: 0.43,
              average_engagement_time_seconds: 62,
              trend_label: "declining",
              operator_hint: "High-traffic page with weaker engagement. Review CTA clarity and above-the-fold content.",
            },
            {
              path: "/contact",
              title: "Contact",
              sessions: 72,
              active_users: 61,
              views: 95,
              engagement_rate: 0.52,
              average_engagement_time_seconds: 58,
              trend_label: "steady",
              operator_hint: "Traffic is steady. Review internal links and CTA clarity for incremental gains.",
            },
            {
              path: "/about",
              title: "About",
              sessions: 50,
              active_users: 40,
              views: 78,
              engagement_rate: 0.49,
              average_engagement_time_seconds: 54,
              trend_label: "steady",
              operator_hint: "Traffic is steady. Review internal links and CTA clarity for incremental gains.",
            },
            {
              path: "/financing",
              title: "Financing",
              sessions: 34,
              active_users: 28,
              views: 52,
              engagement_rate: 0.45,
              average_engagement_time_seconds: 51,
              trend_label: "steady",
              operator_hint: "Traffic is steady. Review internal links and CTA clarity for incremental gains.",
            },
            {
              path: "/blog",
              title: "Blog",
              sessions: 20,
              active_users: 16,
              views: 30,
              engagement_rate: 0.41,
              average_engagement_time_seconds: 44,
              trend_label: "declining",
              operator_hint: "Traffic declined versus the prior period. Check freshness, search visibility, and internal links.",
            },
          ],
          traffic_trend: {
            current_sessions: 530,
            previous_sessions: 460,
            sessions_delta_percent: 15.2,
            current_active_users: 420,
            previous_active_users: 370,
            active_users_delta_percent: 13.5,
            trend_label: "improving",
            operator_hint: "Traffic improved versus the prior period. Preserve winning pages while refining weaker pages.",
          },
          engagement_trend: {
            current_engagement_rate: 0.57,
            previous_engagement_rate: 0.52,
            engagement_rate_delta_percent: 9.6,
            current_average_engagement_time_seconds: 82,
            previous_average_engagement_time_seconds: 75,
            trend_label: "improving",
            operator_hint: "Engagement improved versus the prior period. Keep these content patterns in future updates.",
          },
          message: "GA4 insights are available for this site.",
        },
        ga4_acquisition_insights: {
          status: "available",
          source: "site_scoped_ga4",
          lookback_days: 28,
          top_channels: [
            {
              channel_group: "Organic Search",
              sessions: 280,
              users: 230,
              engagement_rate: 0.58,
            },
            {
              channel_group: "Direct",
              sessions: 120,
              users: 101,
              engagement_rate: 0.49,
            },
          ],
          top_sources: [
            {
              source: "google",
              medium: "organic",
              sessions: 250,
              users: 210,
            },
            {
              source: "yelp.com",
              medium: "referral",
              sessions: 42,
              users: 35,
            },
          ],
          organic_search_summary: {
            sessions: 280,
            share_percent: 57.4,
            trend_direction: "improving",
          },
          referral_summary: {
            sessions: 42,
            top_referrers: ["yelp.com", "angi.com"],
          },
          direct_summary: {
            sessions: 120,
            share_percent: 24.6,
          },
          paid_summary: {
            detected: true,
            sessions: 21,
          },
          operator_hints: [
            "Organic search is the largest traffic channel; protect SEO changes on high-traffic landing pages.",
          ],
          message: "GA4 acquisition insights are available for this site.",
        },
      }),
    );

    render(<SiteWorkspacePage />);

    await waitFor(() => expect(mockFetchSiteAnalyticsSummary).toHaveBeenCalled());

    const topLandingCard = await screen.findByTestId("workspace-summary-ga4-top-landing-pages");
    expect(topLandingCard).toHaveTextContent("Top landing pages");
    const trafficCard = screen.getByTestId("workspace-summary-traffic");
    const engagementCard = screen.getByTestId("workspace-summary-ga4-engagement-trend");
    const acquisitionChannelCard = screen.getByTestId("workspace-summary-ga4-acquisition-channel");
    const acquisitionSourceCard = screen.getByTestId("workspace-summary-ga4-acquisition-source");
    const acquisitionMixCard = screen.getByTestId("workspace-summary-ga4-acquisition-mix");
    await waitFor(() => {
      expect(topLandingCard).toHaveTextContent("5 pages");
      expect(topLandingCard).toHaveTextContent("/ (220 sessions)");
      expect(trafficCard).toHaveTextContent("Traffic trend");
      expect(trafficCard).toHaveTextContent("+15.2% sessions");
      expect(trafficCard).toHaveTextContent("530 sessions vs 460");
      expect(engagementCard).toHaveTextContent("Engagement trend");
      expect(engagementCard).toHaveTextContent("+9.6% engagement");
      expect(engagementCard).toHaveTextContent("Engagement 57%");
      expect(acquisitionChannelCard).toHaveTextContent("Acquisition top channel");
      expect(acquisitionChannelCard).toHaveTextContent("Organic Search");
      expect(acquisitionSourceCard).toHaveTextContent("Acquisition top source");
      expect(acquisitionSourceCard).toHaveTextContent("google / organic");
      expect(acquisitionMixCard).toHaveTextContent("Acquisition mix");
      expect(acquisitionMixCard).toHaveTextContent("Organic 57.4%");
      expect(acquisitionMixCard).toHaveTextContent("Paid detected");
    });
  });

  it("renders safely with partial or malformed GA4 insight payload shapes", async () => {
    seedRichWorkspaceData();
    mockFetchSiteAnalyticsSummary.mockResolvedValue(
      buildSiteAnalyticsSummary({
        ga4_health: {
          ga4_configured: true,
          ga4_property_id_present: true,
          ga4_property_verified: true,
          ga4_reachable: true,
          ga4_data_available: true,
          ga4_last_checked_at: "2026-03-21T17:30:00Z",
          ga4_health_status: "reachable",
          ga4_health_reason: null,
          ga4_health_message: "GA4 is available for recommendation context.",
          ga4_health_source: "site_property",
          ga4_scope_granted: null,
          ga4_required_scope: "https://www.googleapis.com/auth/analytics.readonly",
          ga4_auth_mode: "service_account",
        },
        ga4_insights: {
          status: "available",
          source: "site_property",
          date_range_label: null,
          checked_at: null,
          top_landing_pages: null,
          traffic_trend: { current_sessions: 120 } as unknown as SiteGA4Insights["traffic_trend"],
          engagement_trend: { current_engagement_rate: 0.42 } as unknown as SiteGA4Insights["engagement_trend"],
          message: null,
        },
        ga4_acquisition_insights: {
          status: "available",
          source: "site_scoped_ga4",
          lookback_days: 7,
          top_channels: null,
          top_sources: null,
          organic_search_summary: { sessions: 30 },
          referral_summary: { sessions: 0, top_referrers: null },
          direct_summary: null,
          paid_summary: { detected: false },
          operator_hints: null,
          message: null,
        },
      }),
    );

    render(<SiteWorkspacePage />);

    const topLandingCard = await screen.findByTestId("workspace-summary-ga4-top-landing-pages");
    const trafficCard = screen.getByTestId("workspace-summary-traffic");
    const engagementCard = screen.getByTestId("workspace-summary-ga4-engagement-trend");
    const acquisitionChannelCard = screen.getByTestId("workspace-summary-ga4-acquisition-channel");
    const acquisitionSourceCard = screen.getByTestId("workspace-summary-ga4-acquisition-source");
    const acquisitionMixCard = screen.getByTestId("workspace-summary-ga4-acquisition-mix");
    expect(topLandingCard).toBeInTheDocument();
    expect(trafficCard).toBeInTheDocument();
    expect(engagementCard).toBeInTheDocument();
    expect(acquisitionChannelCard).toBeInTheDocument();
    expect(acquisitionSourceCard).toBeInTheDocument();
    expect(acquisitionMixCard).toBeInTheDocument();
    expect(topLandingCard).not.toHaveTextContent("undefined");
    expect(trafficCard).not.toHaveTextContent("NaN");
    expect(engagementCard).not.toHaveTextContent("NaN");
    expect(acquisitionChannelCard).not.toHaveTextContent("undefined");
    expect(acquisitionMixCard).not.toHaveTextContent("NaN");
  });

  it.each([
    {
      status: "not_configured",
      message: "Add a GA4 property ID for this site before using analytics insights.",
      expectedLabel: "Not configured",
    },
    {
      status: "permission_denied",
      message: "Verify GA4 property access before using analytics insights.",
      expectedLabel: "Permission issue",
    },
    {
      status: "no_data",
      message: "GA4 is reachable, but no recent traffic was returned for this period.",
      expectedLabel: "No recent data",
    },
    {
      status: "unavailable",
      message: "GA4 insights are temporarily unavailable. Retry after a short delay.",
      expectedLabel: "Temporarily unavailable",
    },
  ] as const)(
    "renders safe compact GA4 insight fallback cards for $status",
    async ({ status, message, expectedLabel }) => {
      seedRichWorkspaceData();
      mockFetchSiteAnalyticsSummary.mockResolvedValue(
        buildSiteAnalyticsSummary({
          ga4_insights: {
            status,
            source: status === "not_configured" ? "unavailable" : "site_property",
            date_range_label: "Last 28 days vs previous 28 days",
            checked_at: null,
            top_landing_pages: [],
            traffic_trend: null,
            engagement_trend: null,
            message,
          },
        }),
      );

      render(<SiteWorkspacePage />);

      const topLandingCard = await screen.findByTestId("workspace-summary-ga4-top-landing-pages");
      const trafficCard = screen.getByTestId("workspace-summary-traffic");
      const engagementCard = screen.getByTestId("workspace-summary-ga4-engagement-trend");
      await waitFor(() => {
        expect(topLandingCard).toHaveTextContent(expectedLabel);
        expect(topLandingCard).toHaveTextContent(message);
        expect(trafficCard).toHaveTextContent(expectedLabel);
        expect(engagementCard).toHaveTextContent(expectedLabel);
      });
    },
  );

  it("does not load embedded migration workspace APIs on the main site workspace route", async () => {
    render(<SiteWorkspacePage />);

    await screen.findByRole("tab", { name: "Workflows" });
    expect(screen.queryByTestId("migration-workspace-panel")).not.toBeInTheDocument();
    expect(mockFetchMigrationWorkspaceSummary).not.toHaveBeenCalled();
    expect(mockFetchMigrationArtifactVersions).not.toHaveBeenCalled();
    expect(mockFetchMigrationPublishHistory).not.toHaveBeenCalled();
    expect(mockFetchMigrationDeployHistory).not.toHaveBeenCalled();
  });
});

describe("site migration workflow route", () => {
  it("supports deleting an eligible selected draft artifact", async () => {
    const user = userEvent.setup();
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    render(<SiteMigrationWorkflowPage />);

    const deleteButton = await screen.findByTestId("migration-delete-draft-button");
    expect(deleteButton).toBeEnabled();

    await user.click(deleteButton);

    await waitFor(() =>
      expect(mockDeleteMigrationArtifactVersion).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        "migration-artifact-1",
      ),
    );
    expect(await screen.findByText("Draft artifact v1 deleted.")).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("renders a compact GA4 outcome snapshot for deploy events when available", async () => {
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        ga4_outcome_snapshot: {
          status: "available",
          source: "site_scoped_ga4",
          anchor_type: "migration_deployed",
          anchor_timestamp: "2026-03-01T00:00:00Z",
          before_window: {
            start_date: "2026-02-15",
            end_date: "2026-02-28",
            sessions: 100,
            users: 82,
            engagement_rate: 0.42,
            organic_sessions: 61,
          },
          after_window: {
            start_date: "2026-03-01",
            end_date: "2026-03-14",
            sessions: 131,
            users: 101,
            engagement_rate: 0.48,
            organic_sessions: 79,
          },
          delta: {
            sessions_delta: 31,
            sessions_delta_percent: 31.0,
            engagement_rate_delta_points: 0.06,
            organic_sessions_delta_percent: 29.5,
          },
          outcome_direction: "improved",
          operator_hint: "Observed after deploy: traffic is higher in the post-event window.",
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const outcomeCard = await screen.findByTestId("migration-ga4-outcome-snapshot");
    expect(outcomeCard).toHaveTextContent("GA4 outcome snapshot");
    expect(outcomeCard).toHaveTextContent("Observed after deploy");
    expect(outcomeCard).toHaveTextContent("Status: Available");
    expect(outcomeCard).toHaveTextContent("Before sessions: 100 | After sessions: 131");
    expect(outcomeCard).toHaveTextContent("Observed direction: improved");
    expect(outcomeCard).toHaveTextContent("Observed after deploy: traffic is higher in the post-event window.");
  });

  it("renders pending-after-window GA4 migration outcome safely", async () => {
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        ga4_outcome_snapshot: {
          status: "pending_after_window",
          source: "site_scoped_ga4",
          anchor_type: "migration_published",
          anchor_timestamp: "2026-03-20T00:00:00Z",
          operator_hint: "Not enough time has passed to compare after-publish traffic yet.",
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const outcomeCard = await screen.findByTestId("migration-ga4-outcome-snapshot");
    expect(outcomeCard).toHaveTextContent("Observed after publish");
    expect(outcomeCard).toHaveTextContent("Status: Pending");
    expect(outcomeCard).toHaveTextContent("Not enough time has passed to compare after-publish traffic yet.");
  });

  it("keeps GA4 migration outcome snapshot hidden when no anchor snapshot is available", async () => {
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        ga4_outcome_snapshot: null,
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    await screen.findByTestId("migration-publish-deploy-section");
    expect(screen.queryByTestId("migration-ga4-outcome-snapshot")).not.toBeInTheDocument();
  });

  it("switches selected publish diagnostics context and falls back to latest summary when details are missing", async () => {
    const user = userEvent.setup();
    const publishHistoryWithDetails = {
      timestamp: "2026-03-21T00:20:00Z",
      status: "failed",
      artifact_version_id: "migration-artifact-1",
      failure_category: "provider_error",
      failure_message: "Publish execution failed for this attempt.",
      failure_reason: "authentication_failed",
    };
    const publishHistoryWithoutDetails = {
      timestamp: "2026-03-21T00:10:00Z",
      status: "failed",
      artifact_version_id: "migration-artifact-1",
    };
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        migration_diagnostics: {
          last_publish_failure_category: "target_invalid",
          last_publish_failure_message: "Latest publish summary fallback message.",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({
      items: [publishHistoryWithoutDetails, publishHistoryWithDetails],
      total: 2,
    });

    render(<SiteMigrationWorkflowPage />);

    const scope = await screen.findByTestId("migration-publish-diagnostics-scope");
    expect(scope).toHaveTextContent("2026-03-21T00:20:00Z");

    await user.click(screen.getByText("Show detailed migration failure diagnostics"));
    const diagnostics = screen.getByTestId("migration-publish-diagnostics");
    expect(diagnostics).toHaveTextContent("Context: selected publish attempt");
    expect(diagnostics).toHaveTextContent("Publish failure category: provider error");
    expect(diagnostics).toHaveTextContent("Publish execution failed for this attempt.");
    expect(diagnostics).toHaveTextContent("Publish failure reason: authentication failed");
    expect(diagnostics).not.toHaveTextContent("Latest publish summary fallback message.");
    expect(screen.queryByTestId("migration-publish-diagnostics-fallback-note")).not.toBeInTheDocument();

    const select = screen.getByTestId("migration-publish-history-select") as HTMLSelectElement;
    expect(select.options).toHaveLength(2);
    await user.selectOptions(select, select.options[1].value);

    expect(await screen.findByTestId("migration-publish-diagnostics-scope")).toHaveTextContent(
      "2026-03-21T00:10:00Z",
    );
    expect(screen.getByTestId("migration-publish-diagnostics")).toHaveTextContent(
      "Publish failure category: target invalid",
    );
    expect(screen.getByTestId("migration-publish-diagnostics")).toHaveTextContent(
      "Latest publish summary fallback message.",
    );
    expect(screen.getByTestId("migration-publish-diagnostics-fallback-note")).toBeInTheDocument();
  });

  it("switches selected deploy diagnostics context and falls back when selected record lacks detail", async () => {
    const user = userEvent.setup();
    const deployHistoryWithDetails = {
      timestamp: "2026-03-21T00:30:00Z",
      status: "failed",
      artifact_version_id: "migration-artifact-1",
      workflow_identifier_requested: "deploy-tnmfire-www-prod.yml",
      workflow_file_path: ".github/workflows/deploy-tnmfire-www-prod.yml",
      workflow_exists: false,
      workflow_dispatch_resolution_source: "site_specific_workflow",
      dispatch_service_reason_code: "target_configuration_invalid",
      failure_reason: "workflow_not_dispatchable",
      failure_stage: "workflow_lookup",
    };
    const deployHistoryWithoutDetails = {
      timestamp: "2026-03-21T00:15:00Z",
      status: "failed",
      artifact_version_id: "migration-artifact-1",
    };
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        migration_diagnostics: {
          last_deploy_failure_reason: "workflow_dispatch_not_supported",
          last_deploy_failure_stage: "workflow_dispatch",
          last_deploy_failure_workflow_identifier_requested: "deploy-fallback-www-prod.yml",
          last_deploy_failure_workflow_file_path: ".github/workflows/deploy-fallback-www-prod.yml",
          last_deploy_failure_dispatch_service_reason_code: "target_configuration_invalid",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({
      items: [deployHistoryWithoutDetails, deployHistoryWithDetails],
      total: 2,
    });

    render(<SiteMigrationWorkflowPage />);

    const scope = await screen.findByTestId("migration-deploy-diagnostics-scope");
    expect(scope).toHaveTextContent("2026-03-21T00:30:00Z");

    await user.click(screen.getByText("Show detailed migration failure diagnostics"));
    const diagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(diagnostics).toHaveTextContent("Context: selected deploy attempt");
    expect(diagnostics).toHaveTextContent("Requested workflow identifier: deploy-tnmfire-www-prod.yml");
    expect(diagnostics).toHaveTextContent("Deploy failure reason: workflow not dispatchable");
    expect(diagnostics).toHaveTextContent("Deploy failure stage: workflow lookup");
    expect(diagnostics).not.toHaveTextContent("deploy-fallback-www-prod.yml");
    expect(screen.queryByTestId("migration-deploy-diagnostics-fallback-note")).not.toBeInTheDocument();

    const select = screen.getByTestId("migration-deploy-history-select") as HTMLSelectElement;
    expect(select.options).toHaveLength(2);
    await user.selectOptions(select, select.options[1].value);

    expect(await screen.findByTestId("migration-deploy-diagnostics-scope")).toHaveTextContent(
      "2026-03-21T00:15:00Z",
    );
    expect(screen.getByTestId("migration-deploy-diagnostics")).toHaveTextContent(
      "Requested workflow identifier: deploy-fallback-www-prod.yml",
    );
    expect(screen.getByTestId("migration-deploy-diagnostics")).toHaveTextContent(
      "Deploy failure reason: workflow dispatch not supported",
    );
    expect(screen.getByTestId("migration-deploy-diagnostics")).toHaveTextContent(
      "Deploy failure stage: workflow dispatch",
    );
    expect(screen.getByTestId("migration-deploy-diagnostics-fallback-note")).toBeInTheDocument();
  });

  it("uses selected deploy diagnostics values first and only fills missing fields from latest summary", async () => {
    const user = userEvent.setup();
    const deployHistoryPartialDetails = {
      timestamp: "2026-03-21T00:40:00Z",
      status: "failed",
      artifact_version_id: "migration-artifact-1",
      failure_reason: "workflow_not_dispatchable",
    };
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        migration_diagnostics: {
          last_deploy_failure_reason: "workflow_dispatch_not_supported",
          last_deploy_failure_stage: "workflow_dispatch",
          last_deploy_failure_workflow_identifier_requested: "deploy-fallback-www-prod.yml",
          last_deploy_failure_workflow_file_path: ".github/workflows/deploy-fallback-www-prod.yml",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({
      items: [deployHistoryPartialDetails],
      total: 1,
    });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const diagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(diagnostics).toHaveTextContent("Deploy failure reason: workflow not dispatchable");
    expect(diagnostics).toHaveTextContent("Deploy failure stage: workflow dispatch");
    expect(diagnostics).toHaveTextContent("Requested workflow identifier: deploy-fallback-www-prod.yml");
    expect(screen.getByTestId("migration-deploy-diagnostics-fallback-note")).toBeInTheDocument();
  });

  it("uses latest publish/deploy summary diagnostics when no history row is selected", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        migration_diagnostics: {
          last_publish_failure_category: "target_invalid",
          last_publish_failure_message: "Latest publish summary diagnostics.",
          last_deploy_failure_reason: "workflow_dispatch_not_supported",
          last_deploy_failure_stage: "workflow_dispatch",
          last_deploy_failure_workflow_identifier_requested: "deploy-summary-www-prod.yml",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const publishDiagnostics = screen.getByTestId("migration-publish-diagnostics");
    expect(publishDiagnostics).toHaveTextContent("Context: latest publish summary");
    expect(publishDiagnostics).toHaveTextContent("Publish failure category: target invalid");
    expect(publishDiagnostics).toHaveTextContent("Latest publish summary diagnostics.");
    expect(screen.queryByTestId("migration-publish-diagnostics-fallback-note")).not.toBeInTheDocument();

    const deployDiagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(deployDiagnostics).toHaveTextContent("Context: latest deploy summary");
    expect(deployDiagnostics).toHaveTextContent("Deploy failure reason: workflow dispatch not supported");
    expect(deployDiagnostics).toHaveTextContent("Deploy failure stage: workflow dispatch");
    expect(deployDiagnostics).toHaveTextContent("Requested workflow identifier: deploy-summary-www-prod.yml");
    expect(screen.queryByTestId("migration-deploy-diagnostics-fallback-note")).not.toBeInTheDocument();
  });

  it("surfaces workflow remediation outcome and post-conformance guidance in diagnostics", async () => {
    const user = userEvent.setup();
    const publishHistoryWithRemediation = {
      timestamp: "2026-03-21T00:42:00Z",
      status: "failed",
      artifact_version_id: "migration-artifact-1",
      workflow_remediation_attempted: true,
      workflow_remediation_outcome: "remediation_upgraded_managed_placeholder",
    };
    const deployHistoryWithPostConformance = {
      timestamp: "2026-03-21T00:43:00Z",
      status: "failed",
      artifact_version_id: "migration-artifact-1",
      post_conformance_stage: "workflow_dispatch_succeeded_waiting_for_run",
      post_conformance_reason_text: "Workflow dispatch succeeded but run evidence is still pending.",
      post_conformance_remediation_message:
        "Dispatch succeeded but run evidence is not visible yet. Refresh deploy status.",
    };
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        migration_diagnostics: {
          last_publish_workflow_remediation_attempted: false,
          last_publish_workflow_remediation_outcome: "remediation_already_current",
          last_deploy_post_conformance_stage: "workflow_dispatch_failed",
          last_deploy_post_conformance_reason_text: "Workflow dispatch was rejected by API.",
          last_deploy_post_conformance_remediation_message:
            "GitHub rejected workflow dispatch. Verify repo/workflow/ref access and retry.",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({
      items: [publishHistoryWithRemediation],
      total: 1,
    });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({
      items: [deployHistoryWithPostConformance],
      total: 1,
    });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const publishDiagnostics = screen.getByTestId("migration-publish-diagnostics");
    expect(publishDiagnostics).toHaveTextContent("Workflow remediation attempted: Yes");
    expect(publishDiagnostics).toHaveTextContent(
      "Workflow remediation outcome: remediation upgraded managed placeholder",
    );
    expect(publishDiagnostics).toHaveTextContent(
      "Next step guidance: Managed workflow was upgraded during publish. Retry deploy.",
    );

    const deployDiagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(deployDiagnostics).toHaveTextContent(
      "Post-conformance stage: workflow dispatch succeeded waiting for run",
    );
    expect(deployDiagnostics).toHaveTextContent(
      "Post-conformance detail: Workflow dispatch succeeded but run evidence is still pending.",
    );
    expect(deployDiagnostics).toHaveTextContent(
      "Next step guidance: Dispatch succeeded but run evidence is not visible yet. Refresh deploy status.",
    );
  });

  it("surfaces managed GKE missing-config guidance across deploy readiness and diagnostics", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy target is not enabled."],
        dispatch_service_reason_code: "missing_cluster_location",
        last_failure_reason: "workflow_not_dispatchable",
        last_failure_remediation_hint: "Selected workflow exists but is not dispatchable for this deploy target.",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "tnmfire",
          workflow_id: "deploy-tnmfire-www-prod.yml",
          ref: "main",
        },
      },
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        migration_diagnostics: {
          last_deploy_failure_dispatch_service_reason_code: "missing_cluster_location",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({
      items: [
        {
          timestamp: "2026-04-18T18:41:00Z",
          status: "failed",
          artifact_version_id: "artifact-v7",
          failure_reason: "workflow_not_dispatchable",
          failure_stage: "workflow_lookup",
          dispatch_service_reason_code: "missing_cluster_location",
          failure_remediation_hint: "Selected workflow exists but is not dispatchable for this deploy target.",
        },
      ],
      total: 1,
    });

    render(<SiteMigrationWorkflowPage />);

    const deployReadinessCard = await screen.findByTestId("migration-deploy-readiness");
    expect(within(deployReadinessCard).getByTestId("migration-managed-gke-config-guidance-readiness")).toHaveTextContent(
      "Managed deploy target is missing required admin GKE cluster location configuration. Update admin deployment settings.",
    );
    expect(within(deployReadinessCard).getByTestId("migration-managed-gke-config-source-readiness")).toHaveTextContent(
      "Managed deploy resolves admin platform config first; repo vars/secrets are legacy fallback only.",
    );
    expect(deployReadinessCard).not.toHaveTextContent(
      "Remediation hint: Selected workflow exists but is not dispatchable for this deploy target.",
    );

    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const deployDiagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(
      within(deployDiagnostics).getByTestId("migration-managed-gke-config-guidance-diagnostics"),
    ).toHaveTextContent(
      "Managed deploy target is missing required admin GKE cluster location configuration. Update admin deployment settings.",
    );
    expect(
      within(deployDiagnostics).getByTestId("migration-managed-gke-config-source-diagnostics"),
    ).toHaveTextContent(
      "Managed deploy resolves admin platform config first; repo vars/secrets are legacy fallback only.",
    );

    await user.click(screen.getByText("Show deploy history"));
    const deployHistory = screen.getByTestId("migration-deploy-history");
    expect(deployHistory).toHaveTextContent(
      "Managed deploy target is missing required admin GKE cluster location configuration. Update admin deployment settings.",
    );
    expect(deployHistory).not.toHaveTextContent("Selected workflow exists but is not dispatchable for this deploy target.");
  });

  it("surfaces managed GHCR pull-credential guidance when image pull secrets are missing", async () => {
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy target is not enabled."],
        dispatch_service_reason_code: "image_pull_secret_missing",
        private_image_auth_required: true,
        private_image_credentials_available_in_control_plane: false,
        target_repo_secrets_not_required: true,
        image_pull_secret_not_provisioned: true,
        image_pull_secret_provisioning_unavailable: true,
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "scmechanical",
          workflow_id: "deploy-scmechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadinessCard = await screen.findByTestId("migration-deploy-readiness");
    expect(within(deployReadinessCard).getByTestId("migration-managed-gke-config-guidance-readiness")).toHaveTextContent(
      "Private managed-site image auth is required, but required GHCR pull credentials (GIT_USERID, GIT_EMAIL, GIT_TOKEN) are missing in the MBSRN control-plane runtime. Configure MBSRN deployment settings and verify deploy-prod projects them into the API runtime secret. Target site repositories do not need these secrets.",
    );
    expect(within(deployReadinessCard).getByTestId("migration-private-image-auth-required-readiness")).toHaveTextContent(
      "Private managed image auth required: Yes",
    );
    expect(
      within(deployReadinessCard).getByTestId("migration-private-image-credentials-control-plane-readiness"),
    ).toHaveTextContent("Control-plane GHCR credentials available: No");
    expect(
      within(deployReadinessCard).getByTestId("migration-target-repo-secrets-not-required-readiness"),
    ).toHaveTextContent("Target repo image-pull secrets required: No");
    expect(
      within(deployReadinessCard).getByTestId("migration-image-pull-secret-not-provisioned-readiness"),
    ).toHaveTextContent("Namespace pull secret is not yet confirmed.");
    expect(
      within(deployReadinessCard).getByTestId("migration-image-pull-secret-provisioning-unavailable-readiness"),
    ).toHaveTextContent("Namespace pull-secret provisioning is currently unavailable.");
  });

  it("surfaces certificate-domain mismatch guidance when deploy target manifests point to another hostname", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy target configuration is invalid."],
        dispatch_service_reason_code: "certificate_domain_mismatch",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadinessCard = await screen.findByTestId("migration-deploy-readiness");
    expect(within(deployReadinessCard).getByTestId("migration-managed-gke-config-guidance-readiness")).toHaveTextContent(
      "The deployed certificate does not match the site hostname. This usually means the managed certificate or ingress points at another site's hostname. Republish/deploy after admin verification of generated ingress/certificate resources.",
    );

    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    const deployDiagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(
      within(deployDiagnostics).getByTestId("migration-managed-gke-config-guidance-diagnostics"),
    ).toHaveTextContent(
      "The deployed certificate does not match the site hostname. This usually means the managed certificate or ingress points at another site's hostname. Republish/deploy after admin verification of generated ingress/certificate resources.",
    );
  });

  it("surfaces stale managed-certificate guidance when previous site certs are still present", async () => {
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy target configuration is invalid."],
        dispatch_service_reason_code: "stale_managed_certificate_present",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadinessCard = await screen.findByTestId("migration-deploy-readiness");
    expect(within(deployReadinessCard).getByTestId("migration-managed-gke-config-guidance-readiness")).toHaveTextContent(
      "A previous site's certificate is still present in this environment. This may cause incorrect SSL certificates to be served. Redeploy or remove stale certificates.",
    );
  });

  it("surfaces static IP annotation guidance for managed preview endpoint mode conflicts", async () => {
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy target configuration is invalid."],
        dispatch_service_reason_code: "shared_static_ip_not_allowed_for_per_site_ingress",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadinessCard = await screen.findByTestId("migration-deploy-readiness");
    expect(within(deployReadinessCard).getByTestId("migration-managed-gke-config-guidance-readiness")).toHaveTextContent(
      "Ingress static IP annotation does not match the configured managed preview endpoint mode. Republish managed ingress resources with the expected static IP binding and redeploy.",
    );
  });

  it("surfaces shared preview gateway missing guidance when shared mode lacks static IP config", async () => {
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy target configuration is invalid."],
        dispatch_service_reason_code: "shared_preview_gateway_missing",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "tnmfire",
          workflow_id: "deploy-tnmfire-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadinessCard = await screen.findByTestId("migration-deploy-readiness");
    expect(within(deployReadinessCard).getByTestId("migration-managed-gke-config-guidance-readiness")).toHaveTextContent(
      "Shared preview gateway mode is configured, but no shared preview static IP name is set. Admin must configure the shared preview gateway static IP before deploy can continue.",
    );
  });

  it("surfaces deployed-content-identity mismatch guidance when managed image identity targets another site", async () => {
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy target configuration is invalid."],
        dispatch_service_reason_code: "deployed_content_identity_mismatch",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadinessCard = await screen.findByTestId("migration-deploy-readiness");
    expect(within(deployReadinessCard).getByTestId("migration-managed-gke-config-guidance-readiness")).toHaveTextContent(
      "Managed deployment image identity does not match this site target. Republish managed deploy files before redeploy so the site uses repo-specific generated content.",
    );
  });

  it.each([
    ["managed_workflow_not_yet_republished", "Managed workflow not yet republished", false],
    ["workflow_republished_but_deploy_not_rerun", "Workflow republished but deploy not rerun", false],
    ["deploy_running_old_generic_image", "Deploy running old generic image", false],
    ["deploy_running_expected_site_scoped_image", "Deploy running expected site-scoped image", true],
  ])(
    "surfaces managed site rollout safety state '%s' in deploy readiness",
    async (rolloutState, expectedLabel, fixActive) => {
      const summary = buildMigrationWorkspaceSummary({
        deploy_readiness: {
          ready: fixActive,
          reasons: fixActive ? [] : ["Deploy target configuration is invalid."],
          managed_site_rollout_state: rolloutState,
          managed_site_rollout_message: "Rollout guidance placeholder",
          managed_site_rollout_fix_active: fixActive,
          managed_site_rollout_expected_image_repository: "ghcr.io/mhanson13/sc-mechanical-site-web",
          managed_site_rollout_manifest_image_reference: "ghcr.io/mhanson13/sc-mechanical-site-web:latest",
          managed_site_rollout_observed_deploy_image_reference: fixActive
            ? "ghcr.io/mhanson13/sc-mechanical-site-web:sha123"
            : "ghcr.io/mhanson13/site-web:latest",
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "sc-mechanical",
            workflow_id: "deploy-sc-mechanical-www-prod.yml",
            ref: "main",
          },
        },
      });
      mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
      mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
      mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

      render(<SiteMigrationWorkflowPage />);

      const deployReadinessCard = await screen.findByTestId("migration-deploy-readiness");
      if (fixActive) {
        expect(within(deployReadinessCard).queryByTestId("migration-managed-site-rollout-state-readiness")).not.toBeInTheDocument();
        expect(within(deployReadinessCard).queryByTestId("migration-managed-site-rollout-fix-status-readiness")).not.toBeInTheDocument();
        expect(within(deployReadinessCard).queryByTestId("migration-managed-site-rollout-observed-digest-readiness")).not.toBeInTheDocument();
        expect(within(deployReadinessCard).getByTestId("migration-deploy-readiness-primary-action")).toHaveTextContent(
          "Action: Run deploy for the selected approved and published draft.",
        );
        return;
      }
      expect(within(deployReadinessCard).getByTestId("migration-managed-site-rollout-state-readiness")).toHaveTextContent(
        `Managed site rollout state: ${expectedLabel}`,
      );
      expect(
        within(deployReadinessCard).getByTestId("migration-managed-site-rollout-fix-status-readiness"),
      ).toHaveTextContent(
        fixActive
          ? "Fix active: Yes. Observed deployment image matches expected site-scoped image."
          : "Fix active: No. The fix is not active until observed deployment image matches expected site-scoped image.",
      );
      expect(
        within(deployReadinessCard).getByTestId("migration-managed-site-rollout-observed-digest-readiness"),
      ).toHaveTextContent("Last observed deploy image digest: Digest not reported");
    },
  );

  it("renders deploy image digest safely when identity object is null", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy target configuration is invalid."],
        managed_site_rollout_state: "deploy_running_old_generic_image",
        managed_site_rollout_message: "Rollout guidance placeholder",
        managed_site_rollout_fix_active: false,
        managed_site_rollout_expected_image_repository: "ghcr.io/mhanson13/sc-mechanical-site-web",
        managed_site_rollout_manifest_image_reference: "ghcr.io/mhanson13/sc-mechanical-site-web:latest",
        managed_site_rollout_observed_deploy_image_reference: "ghcr.io/mhanson13/site-web:latest",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({
      items: [
        {
          timestamp: "2026-04-20T00:01:00Z",
          status: "failed",
          artifact_version_id: "artifact-v7",
          site_runtime_image_reference: "ghcr.io/mhanson13/site-web:latest",
          site_runtime_image_identity: null,
        },
      ],
      total: 1,
    });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const diagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(within(diagnostics).getByTestId("migration-managed-site-rollout-observed-digest-diagnostics")).toHaveTextContent(
      "Last observed deploy image digest: Digest not reported",
    );
  });

  it("renders DNS mismatch as blocked in deploy consistency diagnostics", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["DNS record mismatch for managed ingress."],
        dispatch_service_reason_code: "dns_record_mismatch",
        dns_record_matches_ingress: false,
        dns_expected_ip: "34.102.120.10",
        dns_observed_ip: "34.102.120.11",
        ingress_ip: "34.102.120.10",
        deploy_https_ready: false,
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const consistency = screen.getByTestId("migration-deploy-consistency");
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-dns_matches_ingress")).toHaveTextContent(
      "Blocked",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-dns-expected-ip")).toHaveTextContent(
      "dns_expected_ip: 34.102.120.10",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-dns-observed-ip")).toHaveTextContent(
      "dns_observed_ip: 34.102.120.11",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-remediation")).toHaveTextContent(
      "DNS mismatch: update DNS A record to the observed ingress IP.",
    );
  });

  it("surfaces ingress 502 runtime probe diagnostics when backend health is healthy", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Preview hostname is reachable but returned HTTP 502."],
        last_workflow_run_failure_reason_code: "ingress_backend_502",
        service_has_ready_endpoints: true,
        preview_https_status: 502,
        gce_backend_health_status: "HEALTHY",
        service_probe_status: "ok",
        endpoint_probe_status: "ok",
        runtime_probe_status: "ingress_or_edge_convergence",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const diagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(diagnostics).toHaveTextContent("Preview hostname returned HTTP 502.");
    expect(diagnostics).toHaveTextContent("GCE backend health: HEALTHY.");
    expect(diagnostics).toHaveTextContent("Service probe: ok.");
    expect(diagnostics).toHaveTextContent("Endpoint probe: ok.");
    expect(diagnostics).toHaveTextContent("Runtime classification: ingress_or_edge_convergence.");

    const consistency = screen.getByTestId("migration-deploy-consistency");
    expect(within(consistency).getByTestId("migration-deploy-consistency-gce-backend-health-status")).toHaveTextContent(
      "gce_backend_health_status: HEALTHY",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-preview-https-status")).toHaveTextContent(
      "preview_https_status: 502",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-service-probe-status")).toHaveTextContent(
      "service_probe_status: ok",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-runtime-probe-status")).toHaveTextContent(
      "runtime_probe_status: ingress_or_edge_convergence",
    );
  });

  it("surfaces target-repo deploy secret blockers with deploy auth mode diagnostics", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy workflow requires target-repo deploy secret before dispatch."],
        dispatch_service_reason_code: "target_repo_deploy_secret_missing",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "integratedsafetyservices",
          workflow_id: "deploy-integratedsafetyservices-www-prod.yml",
          ref: "main",
          managed_gke_config_details: {
            deploy_auth_mode: "target_repo_actions_secret",
            target_repo_deploy_secret_required: true,
            target_repo_deploy_secret_name: "GCP_DEPLOY_KEY",
            target_repo_deploy_secret_present: false,
          },
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadiness = await screen.findByTestId("migration-deploy-readiness");
    expect(deployReadiness).toHaveTextContent("Deploy auth mode: target repo actions secret");
    expect(deployReadiness).toHaveTextContent("Target repo deploy secret required: Yes");
    expect(deployReadiness).toHaveTextContent("Target repo deploy secret name: GCP_DEPLOY_KEY");
    expect(deployReadiness).toHaveTextContent("Target repo deploy secret present: No");
    expect(deployReadiness).toHaveTextContent("requires target-repo secret GCP_DEPLOY_KEY");

    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    const rawDeployDetails = within(screen.getByTestId("migration-deploy-diagnostics-raw-details"));
    await user.click(rawDeployDetails.getByText("Show raw deploy diagnostics fields"));
    expect(rawDeployDetails.getByText(/deploy_auth_mode:\s*target_repo_actions_secret/i)).toBeInTheDocument();
    expect(rawDeployDetails.getByText(/target_repo_deploy_secret_required:\s*Yes/i)).toBeInTheDocument();
    expect(rawDeployDetails.getByText(/target_repo_deploy_secret_name:\s*GCP_DEPLOY_KEY/i)).toBeInTheDocument();
    expect(rawDeployDetails.getByText(/target_repo_deploy_secret_present:\s*No/i)).toBeInTheDocument();
  });

  it("surfaces static ip retry/list fallback diagnostics when address is still missing", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Static IP address is unavailable after bounded ensure retry."],
        dispatch_service_reason_code: "static_ip_address_missing_after_retry",
        static_ip_status: "IN_USE",
        last_failure_static_ip_error_diagnostics: {
          static_ip_describe_attempts: 8,
          static_ip_list_fallback_attempted: true,
          static_ip_list_fallback_match_count: 0,
          static_ip_list_fallback_address_present: false,
          static_ip_list_fallback_response_keys: ["name", "status", "users"],
        },
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "integratedsafetyservices",
          workflow_id: "deploy-integratedsafetyservices-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadiness = await screen.findByTestId("migration-deploy-readiness");
    expect(deployReadiness).toHaveTextContent("numeric IP address is still unavailable");

    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    const rawDeployDetails = within(screen.getByTestId("migration-deploy-diagnostics-raw-details"));
    await user.click(rawDeployDetails.getByText("Show raw deploy diagnostics fields"));
    expect(rawDeployDetails.getByText(/static_ip_describe_attempts:\s*8/i)).toBeInTheDocument();
    expect(rawDeployDetails.getByText(/static_ip_list_fallback_attempted:\s*Yes/i)).toBeInTheDocument();
    expect(rawDeployDetails.getByText(/static_ip_list_fallback_match_count:\s*0/i)).toBeInTheDocument();
    expect(rawDeployDetails.getByText(/static_ip_list_fallback_address_present:\s*No/i)).toBeInTheDocument();
    expect(
      rawDeployDetails.getByText(/static_ip_list_fallback_response_keys:\s*name, status, users/i),
    ).toBeInTheDocument();
  });

  it("surfaces static ip fallback guidance variants without exposing raw provider payloads", async () => {
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Static IP address lookup is ambiguous after retry."],
        dispatch_service_reason_code: "address_ambiguous_after_retry",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "example-site",
          workflow_id: "deploy-example-site-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadiness = await screen.findByTestId("migration-deploy-readiness");
    expect(within(deployReadiness).getByTestId("migration-managed-gke-config-guidance-readiness")).toHaveTextContent(
      "static IP lookup returned ambiguous matches",
    );
    expect(deployReadiness).not.toHaveTextContent("response body");
    expect(deployReadiness).not.toHaveTextContent("Authorization");
  });

  it("prioritizes current deploy blockers over stale selected-attempt failure text", async () => {
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        blocker_codes: ["deploy_configuration_invalid"],
        reasons: ["Google static IP address is not yet available after bounded retry."],
        last_failure_message:
          "Managed workflow appears republished, but observed deploy image evidence does not yet confirm the site-scoped runtime image.",
        managed_site_rollout_state: "workflow_republished_but_deploy_not_rerun",
        managed_site_rollout_message:
          "Managed workflow appears republished, but observed deploy image evidence does not yet confirm the site-scoped runtime image.",
        managed_site_rollout_fix_active: false,
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "example-site",
          workflow_id: "deploy-example-site-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    const deployReadiness = await screen.findByTestId("migration-deploy-readiness");
    expect(within(deployReadiness).getByTestId("migration-deploy-readiness-primary-action")).toHaveTextContent(
      "Blocker: Deployment target configuration is invalid.",
    );
    expect(within(deployReadiness).getByTestId("migration-managed-site-rollout-guidance-readiness")).toHaveTextContent(
      "Previous deploy evidence (deploy not rerun yet):",
    );
  });

  it("renders FAILED_NOT_VISIBLE with DNS/TLS context in deploy consistency diagnostics", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Certificate is not visible to Google validation."],
        dispatch_service_reason_code: "managed_certificate_failed_not_visible",
        dns_record_matches_ingress: false,
        dns_expected_ip: "34.102.120.10",
        dns_observed_ip: "34.102.120.11",
        tls_certificate_status: "FAILED_NOT_VISIBLE",
        tls_domain_status: "FAILED_NOT_VISIBLE",
        ingress_ip: "34.102.120.10",
        deploy_https_ready: false,
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const consistency = screen.getByTestId("migration-deploy-consistency");
    expect(
      within(consistency).getByTestId("migration-deploy-consistency-gate-managed_certificate_active"),
    ).toHaveTextContent("Blocked");
    expect(within(consistency).getByTestId("migration-deploy-consistency-tls-certificate-status")).toHaveTextContent(
      "tls_certificate_status: FAILED_NOT_VISIBLE",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-tls-domain-status")).toHaveTextContent(
      "tls_domain_status: FAILED_NOT_VISIBLE",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-remediation")).toHaveTextContent(
      "FAILED_NOT_VISIBLE: DNS is not visible to Google certificate validation yet.",
    );
  });

  it("classifies tls provisioning wait-state when static ip and ingress are already aligned", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["ManagedCertificate provisioning is still in progress for expected hostname."],
        dispatch_service_reason_code: "tls_certificate_provisioning",
        dns_record_matches_ingress: true,
        dns_expected_ip: "8.233.146.106",
        dns_observed_ip: "8.233.146.106",
        expected_static_ip_address: "8.233.146.106",
        static_ip_status: "IN_USE",
        ingress_status_ip: "8.233.146.106",
        ingress_status_ip_matches_static_ip: true,
        static_ip_bound_to_expected_forwarding_rule: true,
        ingress_conflict_detected: false,
        tls_certificate_status: "PROVISIONING",
        tls_domain_status: "PROVISIONING",
        observed_managed_certificate_domains: "mbsrn-www.site.mbsrn.com",
        observed_managed_certificate_status: "PROVISIONING",
        observed_managed_certificate_domain_status: "PROVISIONING",
        deploy_https_ready: false,
        preview_probe_attempt: 10,
        preview_probe_elapsed_seconds: 300,
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "mbsrn-www",
          workflow_id: "deploy-mbsrn-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const diagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(diagnostics).toHaveTextContent(/tls is still provisioning/i);
    expect(diagnostics).toHaveTextContent(/wait for managedcertificate to become active/i);

    const consistency = screen.getByTestId("migration-deploy-consistency");
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-ingress_conflict")).toHaveTextContent(
      "Pass",
    );
    expect(
      within(consistency).getByTestId("migration-deploy-consistency-gate-managed_certificate_active"),
    ).toHaveTextContent("Pending");
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-https_probe")).toHaveTextContent(
      "Pending",
    );

    const rawConsistencyDetails = within(consistency).getByTestId("migration-deploy-consistency-raw-details");
    await user.click(within(rawConsistencyDetails).getByText("Show raw deploy consistency fields"));
    expect(
      within(rawConsistencyDetails).getByTestId("migration-deploy-consistency-ingress-status-ip-matches-static-ip"),
    ).toHaveTextContent("ingress_status_ip_matches_static_ip: Yes");
    expect(
      within(rawConsistencyDetails).getByTestId("migration-deploy-consistency-observed-managed-certificate-status"),
    ).toHaveTextContent("observed_managed_certificate_status: PROVISIONING");
  });

  it("renders workflow integrity mismatch as warning with remediation guidance", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Managed workflow signature drift detected."],
        workflow_integrity_status: "mismatch",
        workflow_integrity_reason_code: "managed_workflow_signature_mismatch",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const consistency = screen.getByTestId("migration-deploy-consistency");
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-workflow_integrity")).toHaveTextContent(
      "Warning",
    );
    expect(
      within(consistency).getByTestId("migration-deploy-consistency-workflow-integrity-status"),
    ).toHaveTextContent("workflow_integrity_status: mismatch");
    expect(
      within(consistency).getByTestId("migration-deploy-consistency-workflow-integrity-reason-code"),
    ).toHaveTextContent("workflow_integrity_reason_code: managed_workflow_signature_mismatch");
    expect(within(consistency).getByTestId("migration-deploy-consistency-remediation")).toHaveTextContent(
      "Workflow has been modified outside managed template; behavior may differ from expected deploy contract.",
    );
  });

  it("renders workflow integrity missing as unknown", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Workflow signature has not been embedded yet."],
        workflow_integrity_status: "missing",
        workflow_integrity_reason_code: "managed_workflow_signature_missing",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const consistency = screen.getByTestId("migration-deploy-consistency");
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-workflow_integrity")).toHaveTextContent(
      "Unknown",
    );
  });

  it("does not present deploy_https_ready=false as successful in deploy consistency diagnostics", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["HTTPS verification has not passed."],
        dns_record_matches_ingress: true,
        dns_expected_ip: "34.102.120.10",
        dns_observed_ip: "34.102.120.10",
        tls_certificate_status: "ACTIVE",
        tls_domain_status: "ACTIVE",
        ingress_ip: "34.102.120.10",
        ingress_conflict_detected: false,
        cert_identity_valid: true,
        deploy_https_ready: false,
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const consistency = screen.getByTestId("migration-deploy-consistency");
    expect(within(consistency).getByTestId("migration-deploy-consistency-https-ready")).toHaveTextContent(
      "deploy_https_ready: No",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-https_probe")).toHaveTextContent(
      "Blocked",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-https_probe")).not.toHaveTextContent("Pass");
  });

  it("renders missing consistency fields as pending/unknown without crashing", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Awaiting runtime evidence."],
        ingress_ip: "34.102.120.10",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const consistency = screen.getByTestId("migration-deploy-consistency");
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-dns_matches_ingress")).toHaveTextContent(
      "Pending",
    );
    expect(
      within(consistency).getByTestId("migration-deploy-consistency-gate-managed_certificate_active"),
    ).toHaveTextContent("Unknown");
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-ingress_conflict")).toHaveTextContent(
      "Unknown",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-https_probe")).toHaveTextContent(
      "Pending",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-workflow_integrity")).toHaveTextContent(
      "Unknown",
    );
    const rawConsistencyDetails = within(consistency).getByTestId("migration-deploy-consistency-raw-details");
    expect(rawConsistencyDetails).not.toHaveAttribute("open");
    expect(within(rawConsistencyDetails).getByTestId("migration-deploy-consistency-tls-certificate-status")).not.toBeVisible();
    await user.click(within(rawConsistencyDetails).getByText("Show raw deploy consistency fields"));
    expect(rawConsistencyDetails).toHaveAttribute("open");
    expect(within(rawConsistencyDetails).getByTestId("migration-deploy-consistency-tls-certificate-status")).toHaveTextContent(
      "tls_certificate_status: Not available",
    );
    expect(
      within(rawConsistencyDetails).getByTestId("migration-deploy-consistency-workflow-integrity-status"),
    ).toHaveTextContent("workflow_integrity_status: Not available");
  });

  it("uses selected deploy consistency fields first and backfills missing values from latest summary", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      deploy_readiness: {
        ready: false,
        reasons: ["Deploy evidence is incomplete."],
        dns_record_matches_ingress: false,
        dns_expected_ip: "34.102.120.10",
        dns_observed_ip: "34.102.120.11",
        tls_certificate_status: "PROVISIONING",
        deploy_https_ready: false,
        workflow_integrity_status: "mismatch",
        workflow_integrity_reason_code: "managed_workflow_signature_mismatch",
        target: {
          enabled: true,
          repo_owner: "mhanson13",
          repo_name: "sc-mechanical",
          workflow_id: "deploy-sc-mechanical-www-prod.yml",
          ref: "main",
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({
      items: [
        {
          timestamp: "2026-04-21T00:10:00Z",
          status: "failed",
          artifact_version_id: "migration-artifact-1",
          dns_record_matches_ingress: true,
          dns_expected_ip: "35.201.10.20",
          workflow_integrity_status: "match",
        },
      ],
      total: 1,
    });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const consistency = screen.getByTestId("migration-deploy-consistency");
    expect(within(consistency).getByTestId("migration-deploy-consistency-dns-match")).toHaveTextContent(
      "dns_record_matches_ingress: Yes",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-dns-expected-ip")).toHaveTextContent(
      "dns_expected_ip: 35.201.10.20",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-dns-observed-ip")).toHaveTextContent(
      "dns_observed_ip: 34.102.120.11",
    );
    expect(within(consistency).getByTestId("migration-deploy-consistency-gate-workflow_integrity")).toHaveTextContent(
      "Pass",
    );
    expect(screen.getByTestId("migration-deploy-diagnostics-fallback-note")).toBeInTheDocument();
  });

  it("updates selected draft diagnostics context when artifact selection changes", async () => {
    const user = userEvent.setup();
    const artifactOne = buildMigrationArtifactVersion({ id: "artifact-v1", version: 1 });
    const artifactTwo = buildMigrationArtifactVersion({
      id: "artifact-v2",
      version: 2,
      created_at: "2026-03-21T00:12:00Z",
      updated_at: "2026-03-21T00:12:00Z",
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        workspace: buildMigrationWorkspace({
          latest_generated_artifact_version_id: artifactOne.id,
          latest_generated_artifact_version_number: artifactOne.version,
        }),
        latest_artifact: artifactOne,
      }),
    );
    mockFetchMigrationArtifactVersions.mockResolvedValueOnce({
      items: [artifactOne, artifactTwo],
      total: 2,
    });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    expect(screen.getByTestId("migration-draft-diagnostics")).toHaveTextContent(
      "Context: selected draft artifact v1",
    );

    const artifactSelect = screen.getByLabelText("Artifact version");
    await user.selectOptions(artifactSelect, artifactTwo.id);
    expect(await screen.findByTestId("migration-draft-diagnostics")).toHaveTextContent(
      "Context: selected draft artifact v2",
    );
  });

  it("shows targeted Google reconnect guidance in draft diagnostics without forcing logout messaging", async () => {
    const user = userEvent.setup();
    const baseSummary = buildMigrationWorkspaceSummary();
    const baseContextSummary = baseSummary.context_summary as Record<string, unknown>;
    const baseDiagnostics = (baseContextSummary.migration_diagnostics || {}) as Record<string, unknown>;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        context_summary: {
          ...baseContextSummary,
          migration_diagnostics: {
            ...baseDiagnostics,
            last_draft_failure_reason: "google_reconnect_required",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    expect(await screen.findByTestId("migration-draft-auth-guidance")).toHaveTextContent(
      "Google Search Console / Analytics reconnect is required",
    );
  });

  it("renders draft-readiness preflight warning guidance near generate controls", async () => {
    mockFetchMigrationDraftReadiness.mockResolvedValueOnce(
      buildMigrationDraftReadinessPreflight({
        ready: true,
        warning_reason_codes: ["google_reconnect_required"],
        google_reconnect_required: true,
        google_integration_ready: false,
        operator_action:
          "Draft can be generated now. Reconnect Google Search Console / Analytics to restore live Google signals.",
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const readinessCard = await screen.findByTestId("migration-draft-readiness");
    expect(readinessCard).toHaveTextContent("Status: Ready with warnings");
    expect(readinessCard).toHaveTextContent(
      "Draft can be generated now. Reconnect Google Search Console / Analytics to restore live Google signals.",
    );
  });

  it("blocks generate action when refreshed preflight reports blocking reconnect state", async () => {
    const user = userEvent.setup();
    mockFetchMigrationDraftReadiness
      .mockResolvedValueOnce(buildMigrationDraftReadinessPreflight())
      .mockResolvedValueOnce(
        buildMigrationDraftReadinessPreflight({
          ready: false,
          blocking_reason_codes: ["google_reconnect_required"],
          warning_reason_codes: [],
          google_reconnect_required: true,
          google_integration_ready: false,
          draft_context_ready: false,
          operator_action: "Reconnect Google Search Console / Analytics, then retry draft generation.",
        }),
      );

    render(<SiteMigrationWorkflowPage />);

    const generateButton = await screen.findByRole("button", { name: "Generate Draft Mockup" });
    await user.click(generateButton);

    await waitFor(() => expect(mockGenerateMigrationDraftArtifacts).not.toHaveBeenCalled());
    const reconnectGuidance = await screen.findAllByText(
      "Reconnect Google Search Console / Analytics, then retry draft generation.",
    );
    expect(reconnectGuidance.length).toBeGreaterThan(0);
    expect(screen.getByText("Google Search Console / Analytics reconnect is required for live Google draft signals.")).toBeInTheDocument();
  });

  it("shows app-session-specific guidance when draft diagnostics reason code is app_auth_required", async () => {
    const user = userEvent.setup();
    const baseSummary = buildMigrationWorkspaceSummary();
    const baseContextSummary = baseSummary.context_summary as Record<string, unknown>;
    const baseDiagnostics = (baseContextSummary.migration_diagnostics || {}) as Record<string, unknown>;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        context_summary: {
          ...baseContextSummary,
          migration_diagnostics: {
            ...baseDiagnostics,
            last_draft_failure_reason: "app_auth_required",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    expect(await screen.findByTestId("migration-draft-auth-guidance")).toHaveTextContent(
      "App session expired. Sign back into MBSRN before retrying draft generation.",
    );
  });

  it("shows context-unavailable guidance when draft diagnostics reason code is draft_generation_context_unavailable", async () => {
    const user = userEvent.setup();
    const baseSummary = buildMigrationWorkspaceSummary();
    const baseContextSummary = baseSummary.context_summary as Record<string, unknown>;
    const baseDiagnostics = (baseContextSummary.migration_diagnostics || {}) as Record<string, unknown>;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        context_summary: {
          ...baseContextSummary,
          migration_diagnostics: {
            ...baseDiagnostics,
            last_draft_failure_reason: "draft_generation_context_unavailable",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    expect(await screen.findByTestId("migration-draft-auth-guidance")).toHaveTextContent(
      "Draft context could not be assembled. Retry and contact support if the issue persists.",
    );
  });

  it("shows integration-unavailable guidance when draft diagnostics reason code is google_integration_unavailable", async () => {
    const user = userEvent.setup();
    const baseSummary = buildMigrationWorkspaceSummary();
    const baseContextSummary = baseSummary.context_summary as Record<string, unknown>;
    const baseDiagnostics = (baseContextSummary.migration_diagnostics || {}) as Record<string, unknown>;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        context_summary: {
          ...baseContextSummary,
          migration_diagnostics: {
            ...baseDiagnostics,
            last_draft_failure_reason: "google_integration_unavailable",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    expect(await screen.findByTestId("migration-draft-auth-guidance")).toHaveTextContent(
      "Google integration state could not be read. Retry shortly, then reconnect Google if this persists.",
    );
  });

  it("falls back to latest draft summary diagnostics context when no artifact is selected", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        workspace: buildMigrationWorkspace({
          latest_generated_artifact_version_id: null,
          latest_generated_artifact_version_number: null,
        }),
        latest_artifact: null,
      }),
    );
    mockFetchMigrationArtifactVersions.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    expect(screen.getByTestId("migration-draft-diagnostics")).toHaveTextContent(
      "Context: latest draft summary",
    );
  });

  it("shows blocked delete behavior for artifacts referenced by publish history", async () => {
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({
      items: [
        {
          timestamp: "2026-03-21T00:25:00Z",
          status: "published",
          artifact_version_id: "migration-artifact-1",
        },
      ],
      total: 1,
    });

    render(<SiteMigrationWorkflowPage />);

    const deleteButton = await screen.findByTestId("migration-delete-draft-button");
    expect(deleteButton).toBeDisabled();
    expect(screen.getByText("Artifacts referenced by publish history cannot be deleted.")).toBeInTheDocument();
    expect(mockDeleteMigrationArtifactVersion).not.toHaveBeenCalled();
  });

  it("refreshes migration route state after successful draft deletion", async () => {
    const user = userEvent.setup();
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    const firstArtifact = buildMigrationArtifactVersion();
    mockFetchMigrationWorkspaceSummary
      .mockResolvedValueOnce(
        buildMigrationWorkspaceSummary({
          workspace: buildMigrationWorkspace({
            latest_generated_artifact_version_id: firstArtifact.id,
            latest_generated_artifact_version_number: firstArtifact.version,
          }),
          latest_artifact: firstArtifact,
        }),
      )
      .mockResolvedValueOnce(
        buildMigrationWorkspaceSummary({
          workspace: buildMigrationWorkspace({
            latest_generated_artifact_version_id: null,
            latest_generated_artifact_version_number: null,
          }),
          latest_artifact: null,
        }),
      );
    mockFetchMigrationArtifactVersions
      .mockResolvedValueOnce({ items: [firstArtifact], total: 1 })
      .mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    await user.click(await screen.findByTestId("migration-delete-draft-button"));

    expect(await screen.findByText("Draft artifact v1 deleted.")).toBeInTheDocument();
    await waitFor(() => expect(mockFetchMigrationArtifactVersions).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId("migration-artifact-review-empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("migration-artifact-quality-empty-state")).not.toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("supports multi-page draft preview navigation and resets preview state on artifact change", async () => {
    const user = userEvent.setup();
    const artifactOne = buildMigrationArtifactVersion({
      id: "artifact-preview-1",
      version: 1,
      generated_files_json: [
        {
          path: "index.html",
          media_type: "text/html",
          content:
            "<html><head><title>Artifact One Home</title></head><body><img src=\"assets/images/hero.png\" alt=\"hero\" /><a href=\"about.html\">About</a><a href=\"/sites/site-1\">Workspace</a></body></html>",
          size_bytes: 100,
        },
        {
          path: "about.html",
          media_type: "text/html",
          content: "<html><head><title>Artifact One About</title></head><body>About Draft</body></html>",
          size_bytes: 80,
        },
        {
          path: "assets/images/hero.png",
          media_type: "image/png",
          size_bytes: 68,
        },
      ],
    });
    const artifactTwo = buildMigrationArtifactVersion({
      id: "artifact-preview-2",
      version: 2,
      generated_files_json: [
        {
          path: "landing.html",
          media_type: "text/html",
          content: "<html><head><title>Artifact Two Home</title></head><body>Second Artifact</body></html>",
          size_bytes: 85,
        },
      ],
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        workspace: buildMigrationWorkspace({
          latest_generated_artifact_version_id: artifactOne.id,
          latest_generated_artifact_version_number: artifactOne.version,
        }),
        latest_artifact: artifactOne,
      }),
    );
    mockFetchMigrationArtifactVersions.mockResolvedValueOnce({
      items: [artifactOne, artifactTwo],
      total: 2,
    });

    render(<SiteMigrationWorkflowPage />);

    await user.click(await screen.findByTestId("migration-preview-draft-button"));
    expect(screen.queryByTestId("migration-draft-preview-page-select")).not.toBeInTheDocument();
    expect(screen.queryByTestId("migration-draft-preview-iframe")).not.toBeInTheDocument();
    expect(screen.queryByTestId("migration-draft-preview-surface")).not.toBeInTheDocument();

    const previewFrame = await screen.findByTestId("migration-file-preview-iframe");
    expect(previewFrame).toHaveAttribute("srcDoc", expect.stringContaining("Artifact One Home"));
    expect(previewFrame).toHaveAttribute("srcDoc", expect.stringContaining("data-preview-link-blocked=\"true\""));
    expect(previewFrame).toHaveAttribute(
      "srcDoc",
      expect.stringContaining(
        "/api/businesses/biz-1/seo/sites/site-1/migration/artifact-versions/artifact-preview-1/files/assets/images/hero.png",
      ),
    );
    expect(screen.getByTestId("migration-draft-preview-auth-guidance")).toHaveTextContent(
      "Draft preview route requires operator session context.",
    );

    const previewRail = screen.getByTestId("migration-file-tree");
    await user.click(within(previewRail).getByRole("button", { name: /Artifact One About/i }));
    expect(screen.getByTestId("migration-file-preview-iframe")).toHaveAttribute(
      "srcDoc",
      expect.stringContaining("About Draft"),
    );

    await user.selectOptions(screen.getByLabelText("Artifact version"), artifactTwo.id);
    await waitFor(() =>
      expect(screen.queryByTestId("migration-file-preview-iframe")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("migration-preview-draft-button"));
    expect(await screen.findByTestId("migration-file-preview-iframe")).toHaveAttribute(
      "srcDoc",
      expect.stringContaining("Artifact Two Home"),
    );
  });

  it("shows artifact media materialization and unresolved blockers in draft input summary", async () => {
    const summary = buildMigrationWorkspaceSummary();
    summary.context_summary = {
      ...summary.context_summary,
      draft_input_summary: {
        artifact_media_selected_assets_count: 8,
        artifact_media_materialized_assets_count: 5,
        artifact_media_referenced_paths_count: 4,
        artifact_media_unresolved_references_count: 3,
        artifact_media_selected_not_materialized_count: 3,
        artifact_media_unreferenced_materialized_count: 1,
        artifact_media_ready_for_publish_deploy: false,
        artifact_media_blocker_codes: [
          "selected_media_not_materialized",
          "artifact_internal_media_ids_unresolved",
        ],
      },
    };
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationArtifactVersions.mockResolvedValueOnce({
      items: [summary.latest_artifact as MigrationArtifactVersion],
      total: 1,
    });

    render(<SiteMigrationWorkflowPage />);

    expect(await screen.findByTestId("migration-artifact-media-materialization-summary")).toHaveTextContent(
      "Materialized into artifact files: 5 of 8 selected images.",
    );
    expect(screen.getByTestId("migration-artifact-media-reference-summary")).toHaveTextContent(
      "Referenced by generated pages: 4. Unresolved references: 3.",
    );
    expect(screen.getByTestId("migration-artifact-media-not-materialized-warning")).toHaveTextContent(
      "3 selected images were not materialized into artifact assets.",
    );
    expect(screen.getByTestId("migration-artifact-media-unresolved-warning")).toBeInTheDocument();
    expect(screen.getByTestId("migration-artifact-media-readiness-blockers")).toHaveTextContent(
      "Media readiness blockers:",
    );
  });

  it("renders Section D as a single Draft Artifact Review surface with top action row and quality directly below", async () => {
    render(<SiteMigrationWorkflowPage />);

    const reviewSection = await screen.findByTestId("migration-artifact-review-section");
    expect(screen.getByText("D. Draft Artifact Review")).toBeInTheDocument();
    const artifactSelect = within(reviewSection).getByLabelText("Artifact version");
    const actionRow = within(reviewSection).getByTestId("migration-draft-review-actions-row");
    const qualitySummary = within(reviewSection).getByTestId("migration-artifact-quality-summary");

    expect(actionRow).not.toHaveClass("panel");
    expect(
      (artifactSelect.compareDocumentPosition(actionRow) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
    ).toBe(true);
    expect(
      (actionRow.compareDocumentPosition(qualitySummary) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
    ).toBe(true);

    expect(within(reviewSection).getByTestId("migration-preview-draft-button")).toBeInTheDocument();
    expect(within(reviewSection).getByTestId("migration-approve-draft-button")).toBeInTheDocument();
    expect(within(reviewSection).getByTestId("migration-delete-draft-button")).toBeInTheDocument();
    expect(within(reviewSection).queryByTestId("migration-draft-review-actions")).not.toBeInTheDocument();
    expect(within(reviewSection).queryByPlaceholderText("Approval notes (optional)")).not.toBeInTheDocument();
    expect(within(reviewSection).queryByRole("button", { name: "Publish Approved Draft to GitHub" })).not.toBeInTheDocument();
    expect(within(reviewSection).queryByRole("button", { name: "Request GKE Deploy" })).not.toBeInTheDocument();

    const publishDeploySection = screen.getByTestId("migration-publish-deploy-section");
    expect(within(publishDeploySection).queryByTestId("migration-approve-draft-button")).not.toBeInTheDocument();
    expect(within(publishDeploySection).queryByTestId("migration-delete-draft-button")).not.toBeInTheDocument();
    expect(within(publishDeploySection).getByRole("button", { name: "Publish Approved Draft to GitHub" })).toBeInTheDocument();
    expect(within(publishDeploySection).getByRole("button", { name: "Request GKE Deploy" })).toBeInTheDocument();
  });

  it("renders a combined page and generated-file inspection surface for selected artifacts", async () => {
    const user = userEvent.setup();
    render(<SiteMigrationWorkflowPage />);

    const inspectionSurface = await screen.findByTestId("migration-draft-inspection-surface");
    expect(within(inspectionSurface).getByText("Draft Preview")).toBeInTheDocument();

    await user.click(screen.getByTestId("migration-preview-draft-button"));
    expect(within(inspectionSurface).getByTestId("migration-page-map-list")).toBeInTheDocument();

    await user.click(within(inspectionSurface).getByRole("button", { name: /index\.html/i }));
    expect(within(inspectionSurface).getByText("Selected file: index.html")).toBeInTheDocument();
    expect(within(inspectionSurface).getByTestId("migration-file-preview-iframe")).toBeInTheDocument();
  });

  async function openFullDestinationDiagnostics(
    user: ReturnType<typeof userEvent.setup>,
  ): Promise<HTMLElement> {
    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    const destinationDetails = await screen.findByTestId("migration-destination-secondary-details");
    await user.click(within(destinationDetails).getByText("Show full destination diagnostics"));
    expect(destinationDetails).toHaveAttribute("open");
    return screen.getByTestId("migration-destination-config-diagnostics");
  }

  it("keeps destination summary concise and moves full namespace/policy/runtime fields to advanced diagnostics", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        deploy_readiness: {
          ready: false,
          reasons: ["Deploy target is not enabled."],
          target: {
            enabled: false,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            workflow_id: "deploy-tnmfire-www-prod.yml",
            ref: "main",
            deploy_workflow_mode: "site_repo_template_v1",
            target_environment_key: "gke_prod",
            target_environment_source: "admin_config",
            site_workflow_file_path: ".github/workflows/deploy-tnmfire-www-prod.yml",
            kubernetes_namespace: "site-1",
            managed_resource_quota_expected: true,
            managed_resource_quota_present: true,
            managed_limit_range_expected: true,
            managed_limit_range_present: true,
            managed_network_policy_expected: false,
            managed_network_policy_present: null,
            managed_namespace_policies_aligned: true,
          },
        },
      }),
    );
    render(<SiteMigrationWorkflowPage />);

    const destinationSummary = await screen.findByTestId("migration-destination-summary");
    expect(destinationSummary).toHaveTextContent("Publish Destination");
    expect(destinationSummary).toHaveTextContent("Repository:");
    expect(within(destinationSummary).queryByText("Managed ResourceQuota")).not.toBeInTheDocument();
    expect(within(destinationSummary).queryByText("Managed LimitRange")).not.toBeInTheDocument();
    expect(within(destinationSummary).queryByText("Managed NetworkPolicy")).not.toBeInTheDocument();
    expect(within(destinationSummary).queryByText("Kubernetes namespace")).not.toBeInTheDocument();

    const deployTargetSummary = screen.getByTestId("migration-deploy-target-summary");
    expect(deployTargetSummary).toHaveTextContent("GKE Deploy Target");
    expect(deployTargetSummary).toHaveTextContent("Target environment key");
    expect(within(deployTargetSummary).queryByText("Managed ResourceQuota")).not.toBeInTheDocument();
    expect(within(deployTargetSummary).queryByText("Managed LimitRange")).not.toBeInTheDocument();
    expect(within(deployTargetSummary).queryByText("Managed NetworkPolicy")).not.toBeInTheDocument();
    expect(within(deployTargetSummary).queryByText("Kubernetes namespace")).not.toBeInTheDocument();

    const publishReadiness = screen.getByTestId("migration-publish-readiness");
    const deployReadiness = screen.getByTestId("migration-deploy-readiness");
    expect(within(publishReadiness).queryByText(/Failure category:/i)).not.toBeInTheDocument();
    expect(within(deployReadiness).queryByText(/Deploy failure reason:/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Analytics Insertion Rules")).not.toBeInTheDocument();

    const destinationDiagnostics = await openFullDestinationDiagnostics(user);
    expect(destinationDiagnostics).toHaveTextContent("Kubernetes namespace");
    expect(destinationDiagnostics).toHaveTextContent("Managed ResourceQuota");
    expect(destinationDiagnostics).toHaveTextContent("Managed LimitRange");
    expect(destinationDiagnostics).toHaveTextContent("Managed NetworkPolicy");
  });

  it("keeps concise blockers visible in Section E and retains detailed publish/deploy failure diagnostics under advanced details", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: false,
          reasons: ["Publish target is not enabled."],
          target: {},
          last_failure_category: "config_missing",
          last_failure_reason: "authentication_failed",
          last_failure_stage: "config_validation",
          last_failure_message: "GitHub publish/deploy authentication failed.",
        },
        deploy_readiness: {
          ready: false,
          reasons: ["Deploy target is not enabled."],
          target: {
            enabled: false,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            workflow_id: "deploy-tnmfire-www-prod.yml",
            ref: "main",
            deploy_workflow_mode: "site_repo_template_v1",
            target_environment_key: "gke_prod",
            target_environment_source: "admin_config",
            site_workflow_file_path: ".github/workflows/deploy-tnmfire-www-prod.yml",
            kubernetes_namespace: "site-1",
          },
          last_failure_category: "target_invalid",
          last_failure_reason: "workflow_not_dispatchable",
          last_failure_stage: "workflow_lookup",
          last_failure_message: "GitHub repository or workflow target was not found.",
        },
      }),
    );
    render(<SiteMigrationWorkflowPage />);

    const destinationSummary = await screen.findByTestId("migration-destination-summary");
    expect(within(destinationSummary).getByTestId("migration-destination-publish-blocker")).toHaveTextContent(
      "GitHub publish/deploy authentication failed.",
    );
    const deployTargetSummary = screen.getByTestId("migration-deploy-target-summary");
    expect(within(deployTargetSummary).getByTestId("migration-destination-deploy-blocker")).toHaveTextContent(
      "Deploy target is not enabled.",
    );
    expect(within(destinationSummary).queryByText(/Category:/i)).not.toBeInTheDocument();
    expect(within(destinationSummary).queryByText(/Reason:/i)).not.toBeInTheDocument();
    expect(within(destinationSummary).queryByText(/Stage:/i)).not.toBeInTheDocument();

    await user.click(screen.getByText("Show detailed migration failure diagnostics"));
    const publishDiagnostics = screen.getByTestId("migration-publish-diagnostics");
    const deployDiagnostics = screen.getByTestId("migration-deploy-diagnostics");
    const publishRawDetails = within(publishDiagnostics).getByTestId("migration-publish-diagnostics-raw-details");
    const deployRawDetails = within(deployDiagnostics).getByTestId("migration-deploy-diagnostics-raw-details");
    expect(publishRawDetails).not.toHaveAttribute("open");
    expect(deployRawDetails).not.toHaveAttribute("open");
    await user.click(within(publishRawDetails).getByText("Show raw publish diagnostics fields"));
    await user.click(within(deployRawDetails).getByText("Show raw deploy diagnostics fields"));
    expect(within(publishRawDetails).getByText("Publish failure category: config missing")).toBeVisible();
    expect(within(publishRawDetails).getByText("Publish failure reason: authentication failed")).toBeVisible();
    expect(within(deployRawDetails).getByText("Deploy failure category: target invalid")).toBeVisible();
    expect(within(deployRawDetails).getByText("Deploy failure reason: workflow not dispatchable")).toBeVisible();
    expect(within(deployRawDetails).getByText("Deploy failure stage: workflow lookup")).toBeVisible();

    const secondaryDetails = screen.getByTestId("migration-destination-secondary-details");
    expect(secondaryDetails).not.toHaveAttribute("open");
    const collapsedField = within(secondaryDetails).getByText(/Kubernetes namespace:/i);
    expect(collapsedField).not.toBeVisible();
    await user.click(within(secondaryDetails).getByText("Show full destination diagnostics"));
    expect(secondaryDetails).toHaveAttribute("open");
    expect(within(secondaryDetails).getByText(/Kubernetes namespace:/i)).toBeVisible();
  });

  it("renders compact publish/deploy two-column layouts with summary-left and controls-right ownership", async () => {
    render(<SiteMigrationWorkflowPage />);

    const publishDeploySection = await screen.findByTestId("migration-publish-deploy-section");

    const publishLayout = within(publishDeploySection).getByTestId("migration-publish-layout");
    expect(publishLayout).toHaveClass("migration-publish-deploy-layout");
    const publishLayoutLeft = within(publishLayout).getByTestId("migration-publish-layout-left");
    const publishLayoutRight = within(publishLayout).getByTestId("migration-publish-layout-right");
    expect(within(publishLayoutLeft).getByTestId("migration-destination-summary")).toBeInTheDocument();
    expect(within(publishLayoutLeft).getByTestId("migration-publish-readiness")).toBeInTheDocument();
    expect(within(publishLayoutRight).getByTestId("migration-publish-target-summary")).toBeInTheDocument();
    expect(within(publishLayoutRight).getByRole("button", { name: "Save Publish Repository" })).toBeInTheDocument();
    expect(within(publishLayoutRight).getByRole("button", { name: "Publish Approved Draft to GitHub" })).toBeInTheDocument();

    const deployLayout = within(publishDeploySection).getByTestId("migration-deploy-layout");
    expect(deployLayout).toHaveClass("migration-publish-deploy-layout");
    const deployLayoutLeft = within(deployLayout).getByTestId("migration-deploy-layout-left");
    const deployLayoutRight = within(deployLayout).getByTestId("migration-deploy-layout-right");
    expect(within(deployLayoutLeft).getByTestId("migration-deploy-target-summary")).toBeInTheDocument();
    expect(within(deployLayoutLeft).getByTestId("migration-deploy-readiness")).toBeInTheDocument();
    expect(within(deployLayoutRight).getByRole("button", { name: "Save Deploy Availability" })).toBeInTheDocument();
    expect(within(deployLayoutRight).getByRole("button", { name: "Request GKE Deploy" })).toBeInTheDocument();
    expect(within(deployLayoutRight).getByTestId("migration-refresh-deploy-status-button")).toBeInTheDocument();

    expect(within(publishDeploySection).queryByTestId("migration-publish-diagnostics")).not.toBeInTheDocument();
    expect(within(publishDeploySection).queryByTestId("migration-deploy-diagnostics")).not.toBeInTheDocument();
  });

  it("shows configured repository values in concise destination summary", async () => {
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        workspace: buildMigrationWorkspace({
          publish_config_json: {
            enabled: true,
            repo_owner: null,
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
          },
        }),
        publish_readiness: {
          ready: true,
          reasons: [],
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const destinationSummary = await screen.findByTestId("migration-destination-summary");
    expect(destinationSummary).toHaveTextContent("Repository: mhanson13/tnmfire");
    expect(destinationSummary).not.toHaveTextContent("Operator-set");
  });

  it("does not render hard-coded platform boundary guidance in publish destination panels", async () => {
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        workspace: buildMigrationWorkspace({
          source_url: "https://www.mbsrn.com/",
          publish_config_json: {
            enabled: true,
            repo_owner: null,
            repo_name: "mbsrn-www",
            branch: "main",
            artifact_root: "/",
          },
        }),
        publish_readiness: {
          ready: true,
          reasons: [],
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "mbsrn-www",
            branch: "main",
            artifact_root: "/",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const destinationSummary = await screen.findByTestId("migration-destination-summary");
    expect(within(destinationSummary).queryByTestId("migration-destination-platform-www-boundary")).not.toBeInTheDocument();
    expect(destinationSummary).not.toHaveTextContent("app/control-plane source");

    const publishTargetSummary = screen.getByTestId("migration-publish-target-summary");
    expect(within(publishTargetSummary).queryByTestId("migration-publish-target-platform-www-boundary")).not.toBeInTheDocument();
  });

  it("prioritizes current live runtime evidence over selected workflow failure for current deploy state", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        context_summary: {
          ...buildMigrationWorkspaceSummary().context_summary,
          destination_summary: {
            publish_destination: {
              repository: "mhanson13/lars-construction",
              branch: "main",
              state: "configured",
            },
            deploy_destination: {
              target_repository: "mhanson13/lars-construction",
              ref: "main",
              state: "active_live",
              active_url: "https://lars-construction.site.mbsrn.com/",
              preview_url: "https://lars-construction.site.mbsrn.com/",
              url_source: "current_live_probe",
            },
          },
        },
        deploy_readiness: {
          ready: false,
          reasons: ["Selected workflow attempt failed during ingress evidence collection."],
          selected_workflow_attempt_status: "completed",
          selected_workflow_attempt_conclusion: "failure",
          selected_workflow_failed_step: "Resolve live URL from ingress status",
          selected_workflow_failure_stage: "ingress_evidence",
          selected_workflow_failure_reason: "managed_site_static_ip_address_missing",
          current_deploy_https_ready: true,
          current_live_url: "https://lars-construction.site.mbsrn.com/",
          current_host_reachable: true,
          current_host_reachability_scheme: "https",
          current_cert_identity_valid: true,
          current_live_evidence_checked_at: "2026-05-07T01:20:00Z",
          current_live_evidence_source: "current_live_probe",
          current_live_runtime_status: "success",
          current_live_runtime_source: "current_live_probe",
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "lars-construction",
            workflow_id: "deploy-lars-construction-www-prod.yml",
            ref: "main",
            deploy_workflow_mode: "site_repo_template_v1",
            target_environment_key: "gke_prod",
            target_environment_source: "admin_config",
            site_workflow_file_path: ".github/workflows/deploy-lars-construction-www-prod.yml",
          },
        },
        deploy_history: [
          {
            timestamp: "2026-05-07T01:15:00Z",
            status: "failed",
            artifact_version_id: "migration-artifact-1",
            workflow_run_status: "completed",
            workflow_run_conclusion: "failure",
            workflow_run_failure_reason_code: "managed_site_static_ip_address_missing",
            workflow_run_failure_stage: "ingress_evidence",
            workflow_run_failure_step: "Resolve live URL from ingress status",
            current_live_url: "https://lars-construction.site.mbsrn.com/",
            current_deploy_https_ready: true,
            current_live_evidence_source: "current_live_probe",
            current_live_runtime_source: "current_live_probe",
          },
        ],
      }),
    );
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({
      items: [
        {
          timestamp: "2026-05-07T01:15:00Z",
          status: "failed",
          artifact_version_id: "migration-artifact-1",
          workflow_run_status: "completed",
          workflow_run_conclusion: "failure",
          workflow_run_failure_reason_code: "managed_site_static_ip_address_missing",
          workflow_run_failure_stage: "ingress_evidence",
          workflow_run_failure_step: "Resolve live URL from ingress status",
          current_live_url: "https://lars-construction.site.mbsrn.com/",
          current_deploy_https_ready: true,
          current_live_evidence_source: "current_live_probe",
          current_live_runtime_source: "current_live_probe",
        },
      ],
      total: 1,
    });

    render(<SiteMigrationWorkflowPage />);

    const deployTargetSummary = await screen.findByTestId("migration-deploy-target-summary");
    expect(deployTargetSummary).toHaveTextContent("Deploy evidence state");
    expect(deployTargetSummary).toHaveTextContent("Confirmed Live");
    expect(deployTargetSummary).toHaveTextContent("Live URL (current)");
    expect(deployTargetSummary).toHaveTextContent("https://lars-construction.site.mbsrn.com/");
    expect(deployTargetSummary).toHaveTextContent("Current evidence source");
    expect(deployTargetSummary).toHaveTextContent("current_live_probe");
    expect(within(deployTargetSummary).getByTestId("migration-deploy-current-live-note")).toHaveTextContent(
      "Selected deploy workflow failed during evidence collection, but current live HTTPS evidence is healthy.",
    );
    expect(
      within(screen.getByTestId("migration-deploy-readiness")).getByTestId("migration-deploy-readiness-current-live-note"),
    ).toBeInTheDocument();

    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));

    const deployDiagnostics = screen.getByTestId("migration-deploy-diagnostics");
    expect(deployDiagnostics).toHaveTextContent(/Deploy Diagnostics\s*Success/i);
    expect(deployDiagnostics).toHaveTextContent("Selected workflow attempt: completed · failure");
    expect(deployDiagnostics).toHaveTextContent("Selected workflow failure: managed site static ip address missing");

    const currentLiveCard = screen.getByTestId("migration-current-live-runtime-evidence");
    expect(currentLiveCard).toHaveTextContent("HTTPS Ready: Yes");
    expect(currentLiveCard).toHaveTextContent("Host reachable: Yes");
    expect(currentLiveCard).toHaveTextContent("Scheme: https");
    expect(currentLiveCard).toHaveTextContent("Live URL: https://lars-construction.site.mbsrn.com/");
    expect(currentLiveCard).toHaveTextContent("Source: current_live_probe");

    const deployConsistency = screen.getByTestId("migration-deploy-consistency");
    expect(within(deployConsistency).getByTestId("migration-deploy-consistency-gate-https_probe")).toHaveTextContent(
      "Pass",
    );
    expect(within(deployConsistency).getByTestId("migration-deploy-consistency-gate-ingress_conflict")).toHaveTextContent(
      "Pass",
    );
  });

  it("uses the route site id for deploy status refresh when global site selection differs", async () => {
    const user = userEvent.setup();
    const setSelectedSiteId = jest.fn();
    navigationState.params = { site_id: "site-2" };
    mockUseOperatorContext.mockReturnValue(
      baseContext({
        sites: [
          buildSite({
            id: "site-1",
            display_name: "Lars Construction",
            base_url: "https://lars-construction.com/",
            normalized_domain: "lars-construction.com",
          }),
          buildSite({
            id: "site-2",
            display_name: "S&C Mechanical",
            base_url: "https://sc-mechanical.com/",
            normalized_domain: "sc-mechanical.com",
          }),
        ],
        selectedSiteId: "site-1",
        setSelectedSiteId,
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const refreshButton = await screen.findByTestId("migration-refresh-deploy-status-button");
    await user.click(refreshButton);

    await waitFor(() => expect(mockRefreshMigrationDeployStatus).toHaveBeenCalled());
    expect(mockRefreshMigrationDeployStatus).toHaveBeenLastCalledWith(
      "token-1",
      "biz-1",
      "site-2",
      { artifact_version_id: "migration-artifact-1" },
    );
    expect(setSelectedSiteId).toHaveBeenCalledWith("site-2");
  });

  it("shows repository provisioning guidance in destination diagnostics when publish will auto-create a missing repo", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: true,
          reasons: [],
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
            repository_exists: false,
            repository_auto_create_enabled: true,
            repository_auto_create_available: true,
            repo_ensure_outcome: "would_create_on_publish",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const destinationDiagnostics = await openFullDestinationDiagnostics(user);
    expect(destinationDiagnostics).toHaveTextContent(
      "Missing repository will be auto-created on live publish (admin policy enabled).",
    );
  });

  it("shows repository provisioning guidance in destination diagnostics for branch bootstrap", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: true,
          reasons: [],
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
            repository_exists: true,
            repo_ensure_outcome: "exists",
            preflight_status: "ready_with_actions",
            would_bootstrap_branch: true,
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const destinationDiagnostics = await openFullDestinationDiagnostics(user);
    expect(destinationDiagnostics).toHaveTextContent(
      "Target branch is missing and will be bootstrapped during live publish.",
    );
  });

  it("shows repository provisioning guidance in destination diagnostics for baseline reconciliation", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: true,
          reasons: [],
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
            repository_exists: true,
            repo_ensure_outcome: "exists",
            preflight_status: "ready_with_actions",
            repo_baseline_reconciliation_needed: true,
            readme_present: false,
            gitignore_present: false,
            license_present: false,
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const destinationDiagnostics = await openFullDestinationDiagnostics(user);
    expect(destinationDiagnostics).toHaveTextContent(
      "Repository is MBSRN-managed and missing baseline files (README.md, .gitignore, LICENSE); live publish will reconcile missing files.",
    );
  });

  it("shows repository provisioning guidance in destination diagnostics for workflow write authorization gaps", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: true,
          reasons: [],
          warnings: [
            "GitHub runtime is not authorized to write deploy workflow files in the configured repository. Publish to GitHub can proceed, but deploy workflow provisioning stays unavailable until workflows:write access is granted.",
          ],
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
            repository_exists: true,
            repo_ensure_outcome: "exists",
            preflight_status: "blocked",
            preflight_blocker_code: "github_workflow_write_not_authorized",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const publishReadiness = await screen.findByTestId("migration-publish-readiness");
    expect(publishReadiness).toHaveTextContent("Ready: Yes");
    expect(publishReadiness).toHaveTextContent("deploy workflow provisioning stays unavailable");

    const destinationDiagnostics = await openFullDestinationDiagnostics(user);
    expect(destinationDiagnostics).toHaveTextContent(
      "GitHub runtime is not authorized to write deploy workflow files in the configured repository.",
    );
  });

  it("prioritizes current publish readiness blockers over stale publish failure summaries", async () => {
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: false,
          reasons: ["Selected media were not materialized into artifact assets."],
          last_failure_message: "Deploy workflow provisioning could not be verified.",
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const publishReadiness = await screen.findByTestId("migration-publish-readiness");
    expect(publishReadiness).toHaveTextContent("Blocker: Selected media were not materialized into artifact assets.");
    expect(publishReadiness).not.toHaveTextContent("Blocker: Deploy workflow provisioning could not be verified.");
  });

  it("shows repository ownership guidance in destination diagnostics when mbsrn.key is missing", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: false,
          reasons: ["This repository exists but is not marked as MBSRN-managed (mbsrn.key missing), so publish is blocked."],
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
            repository_exists: true,
            repo_ensure_outcome: "exists",
            preflight_status: "blocked",
            preflight_blocker_code: "github_repo_management_marker_missing",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const destinationDiagnostics = await openFullDestinationDiagnostics(user);
    expect(destinationDiagnostics).toHaveTextContent(
      "This repository exists but is not marked as MBSRN-managed. Adopt it to allow managed publish updates.",
    );
  });

  it("shows adopt repository action for adoption-required publish targets and triggers adoption call", async () => {
    const user = userEvent.setup();
    jest.spyOn(window, "confirm").mockReturnValue(true);
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: false,
          reasons: ["This repository exists but is not marked as MBSRN-managed. Adopt the repository before publish."],
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
            repository_exists: true,
            repo_ensure_outcome: "exists",
            preflight_status: "blocked",
            preflight_blocker_code: "github_repo_adoption_required",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const adoptionButton = await screen.findByTestId("migration-adopt-repository-button");
    expect(adoptionButton).toBeInTheDocument();
    expect(
      screen.getByText(
        "This repository exists but is not marked as MBSRN-managed. Adopt it to allow MBSRN to publish into it.",
      ),
    ).toBeInTheDocument();

    await user.click(adoptionButton);

    await waitFor(() => expect(mockAdoptMigrationPublishRepository).toHaveBeenCalledTimes(1));
  });

  it("shows repository provisioning authorization guidance in destination diagnostics when runtime token cannot create repos", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: false,
          reasons: ["GitHub runtime is not authorized to inspect the configured publish repository target."],
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
            repository_exists: false,
            repository_auto_create_enabled: true,
            repository_ensure_outcome: "check_failed",
            repository_ensure_failure_reason_code: "repo_auto_create_not_authorized",
            repo_ensure_outcome: "failed_not_authorized",
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const destinationDiagnostics = await openFullDestinationDiagnostics(user);
    expect(destinationDiagnostics).toHaveTextContent(
      "Runtime token is not authorized to create repositories under the configured owner.",
    );
  });

  it("shows migration state in the top summary band and removes duplicate primary current-state cards", async () => {
    render(<SiteMigrationWorkflowPage />);

    const summaryBand = await screen.findByTestId("migration-summary-band");
    expect(summaryBand).toHaveTextContent("Migration state");
    expect(summaryBand).toHaveTextContent("Next action");
    expect(summaryBand).toHaveTextContent("Latest draft");
    expect(screen.queryByTestId("migration-current-state")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Current Migration State" })).not.toBeInTheDocument();
  });

  it("keeps provider execution metadata hidden by default and available via Advanced Diagnostics disclosure", async () => {
    const user = userEvent.setup();
    render(<SiteMigrationWorkflowPage />);

    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    const providerDetails = screen.getByTestId("migration-provider-execution-details");
    expect(providerDetails).not.toHaveAttribute("open");

    const providerMetadata = screen.getByTestId("migration-ai-execution-metadata");
    expect(providerMetadata).not.toBeVisible();

    await user.click(within(providerDetails).getByText("Show provider execution details"));
    expect(providerDetails).toHaveAttribute("open");
    expect(screen.getByTestId("migration-ai-execution-metadata")).toBeVisible();
  });

  it("renders reused context as compact status tiles with disclosure-backed detail", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        context_summary: {
          ...buildMigrationWorkspaceSummary().context_summary,
          reused_context: {
            audit: {
              available: true,
              source: "latest_successful_run",
              run_id: "audit-run-1",
              timestamp: "2026-03-21T00:00:00Z",
            },
            recommendations: {
              available: true,
              source: "stale_snapshot",
              run_id: "recommendation-run-1",
              timestamp: "2026-03-11T00:00:00Z",
              count: 1,
            },
            competitors: {
              available: false,
              source: "missing",
              run_id: null,
              timestamp: null,
              count: 0,
            },
          },
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const reusedContext = await screen.findByTestId("migration-reused-context");
    const compactSummary = within(reusedContext).getByTestId("migration-reused-context-compact");
    expect(compactSummary.querySelectorAll(".migration-compact-inline-item")).toHaveLength(3);
    expect(within(compactSummary).getByTestId("migration-reused-context-audit-status")).toHaveTextContent("Available");
    expect(within(compactSummary).getByTestId("migration-reused-context-recommendations-status")).toHaveTextContent("Stale");
    expect(within(compactSummary).getByTestId("migration-reused-context-competitors-status")).toHaveTextContent("Missing");
    expect(within(compactSummary).getByTestId("migration-reused-context-audit-last-run")).toHaveTextContent("Last run:");

    const detailToggle = within(reusedContext).getByText("Show context detail");
    const detailPanel = detailToggle.closest("details");
    expect(detailPanel).not.toBeNull();
    expect(detailPanel as HTMLDetailsElement).not.toHaveAttribute("open");
    expect(within(detailPanel as HTMLDetailsElement).getByText(/^Audit:/i)).not.toBeVisible();
    await user.click(detailToggle);
    expect(detailPanel as HTMLDetailsElement).toHaveAttribute("open");
    expect(within(detailPanel as HTMLDetailsElement).getByText(/^Audit:/i)).toBeVisible();
  });

  it("hides deploy namespace/policy/runtime evidence by default and reveals it only in destination diagnostics", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        deploy_readiness: {
          ready: false,
          reasons: ["Deploy target is not enabled."],
          target: {
            enabled: false,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            workflow_id: "deploy-tnmfire-www-prod.yml",
            ref: "main",
            kubernetes_namespace: "site-1",
            managed_resource_quota_expected: true,
            managed_resource_quota_present: true,
            managed_limit_range_expected: true,
            managed_limit_range_present: true,
            managed_network_policy_expected: false,
            managed_network_policy_present: null,
          },
        },
      }),
    );
    render(<SiteMigrationWorkflowPage />);

    const destinationSummary = await screen.findByTestId("migration-destination-summary");
    expect(within(destinationSummary).queryByText("Kubernetes namespace")).not.toBeInTheDocument();
    expect(within(destinationSummary).queryByText("Managed ResourceQuota")).not.toBeInTheDocument();

    await user.click(screen.getByText("Show detailed migration failure diagnostics"));
    const destinationDetails = screen.getByTestId("migration-destination-secondary-details");
    expect(destinationDetails).not.toHaveAttribute("open");
    expect(within(destinationDetails).getByText(/Kubernetes namespace:/i)).not.toBeVisible();
    expect(within(destinationDetails).getByText(/Managed ResourceQuota:/i)).not.toBeVisible();

    await user.click(within(destinationDetails).getByText("Show full destination diagnostics"));
    expect(destinationDetails).toHaveAttribute("open");
    expect(within(destinationDetails).getByText(/Kubernetes namespace:/i)).toBeVisible();

    const kubernetesPolicyDetails = within(destinationDetails).getByText("Show Kubernetes policy diagnostics");
    await user.click(kubernetesPolicyDetails);
    expect(within(destinationDetails).getByText(/Managed ResourceQuota:/i)).toBeVisible();
  });

  it("renders destination/config diagnostics in grouped categories with nested details", async () => {
    const user = userEvent.setup();
    render(<SiteMigrationWorkflowPage />);

    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    const destinationDetails = screen.getByTestId("migration-destination-secondary-details");
    await user.click(within(destinationDetails).getByText("Show full destination diagnostics"));

    const destinationDiagnostics = await within(destinationDetails).findByTestId("migration-destination-config-diagnostics");
    expect(destinationDiagnostics).toHaveTextContent("Draft artifact");
    expect(destinationDiagnostics).toHaveTextContent("Repository / workflow");
    expect(destinationDiagnostics).toHaveTextContent("Kubernetes runtime");
    expect(destinationDiagnostics).toHaveTextContent("Domain / URL");
    expect(destinationDiagnostics).toHaveTextContent("Preview / deployment evidence");

    const repositoryDetails = within(destinationDiagnostics).getByText("Show repository/workflow details");
    const repositoryDetailPanel = repositoryDetails.closest("details");
    expect(repositoryDetailPanel).not.toBeNull();
    expect(repositoryDetailPanel as HTMLDetailsElement).not.toHaveAttribute("open");
    await user.click(repositoryDetails);
    expect(repositoryDetailPanel as HTMLDetailsElement).toHaveAttribute("open");
  });

  it("does not show stale failure detail lines in publish/deploy readiness cards when both readiness states are ready", async () => {
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        publish_readiness: {
          ready: true,
          reasons: [],
          last_failure_category: "config_missing",
          last_failure_message: "Old publish failure that should not be surfaced in ready state.",
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            branch: "main",
            artifact_root: "/",
          },
        },
        deploy_readiness: {
          ready: true,
          reasons: [],
          last_failure_category: "target_invalid",
          last_failure_reason: "workflow_not_dispatchable",
          last_failure_stage: "workflow_lookup",
          last_failure_message: "Old deploy failure that should not be surfaced in ready state.",
          target: {
            enabled: true,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            workflow_id: "deploy-tnmfire-www-prod.yml",
            ref: "main",
          },
        },
      }),
    );
    render(<SiteMigrationWorkflowPage />);

    const publishReadiness = await screen.findByTestId("migration-publish-readiness");
    const deployReadiness = screen.getByTestId("migration-deploy-readiness");

    expect(within(publishReadiness).getByTestId("migration-publish-readiness-primary-action")).toHaveTextContent(
      "Action: Publish the selected approved draft when operator review is complete.",
    );
    expect(within(deployReadiness).getByTestId("migration-deploy-readiness-primary-action")).toHaveTextContent(
      "Action: Run deploy for the selected approved and published draft.",
    );
    expect(within(publishReadiness).queryByText(/Failure category:/i)).not.toBeInTheDocument();
    expect(within(publishReadiness).queryByText(/Old publish failure/i)).not.toBeInTheDocument();
    expect(within(deployReadiness).queryByText(/Old deploy failure/i)).not.toBeInTheDocument();
    expect(within(deployReadiness).queryByTestId("migration-managed-gke-config-guidance-readiness")).not.toBeInTheDocument();
  });

  it("renders draft input summary and media grouping with operator actions", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        draft_input_summary: {
          recommendations_included_count: 3,
          gsc_signals_included: true,
          ga4_signals_included: true,
          competitor_profiles_included_count: 2,
          operator_requirements_included: true,
          enriched_business_context_included: true,
          source_site_images_discovered_count: 2,
          source_site_images_imported_count: 1,
          operator_uploaded_images_count: 1,
          selected_media_assets_count: 1,
          media_context_included: true,
          generation_safety_profile: "compact_fallback",
          generation_provider_timeout_seconds: 240,
          generation_preflight_mode: "compact_fallback",
          generation_max_final_input_chars: 9000,
          generation_max_difficulty_score: 12,
          generation_compact_fallback_enabled: true,
          generation_compact_fallback_attempted: false,
          generation_budget_capped: false,
          provider_source: "mock",
          mocked_source: true,
        },
        media_assets: {
          source_discovered_count: 2,
          pages_scanned_count: 3,
          source_imported_count: 1,
          operator_uploaded_count: 1,
          selected_assets_count: 1,
          media_asset_categories: ["project_gallery", "service_page"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "srcimg-1",
              normalized_url: "https://legacy.example/images/front.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              fetch_status: "validated_head",
              content_type: "image/jpeg",
              selected_for_draft: true,
            },
          ],
          operator_uploaded: [
            {
              asset_id: "upl-1",
              display_filename: "project-1.jpg",
              provenance: "operator_upload",
              category: "project_gallery",
              selected_for_draft: false,
            },
          ],
          selected_assets: [
            {
              asset_id: "srcimg-1",
              normalized_url: "https://legacy.example/images/front.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: true,
            },
          ],
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValueOnce(
      (summary.context_summary as Record<string, unknown>).media_assets as Record<string, unknown>,
    );

    render(<SiteMigrationWorkflowPage />);

    const draftInputSummary = await screen.findByTestId("migration-draft-input-summary");
    expect(draftInputSummary).toHaveTextContent("Bounded Provenance");
    const boundedProvenance = within(draftInputSummary).getByTestId("migration-draft-input-bounded-provenance");
    expect(boundedProvenance).toHaveTextContent("Media context included");
    expect(boundedProvenance).toHaveTextContent("Yes");
    expect(boundedProvenance).toHaveTextContent("AI context blocks included");
    expect(within(draftInputSummary).queryByText("Source-site images discovered:")).not.toBeInTheDocument();
    expect(within(draftInputSummary).queryByText("Operator uploaded images:")).not.toBeInTheDocument();
    expect(within(draftInputSummary).queryByText(/Provider source:/i)).not.toBeInTheDocument();
    expect(within(draftInputSummary).getByTestId("migration-draft-input-generation-safety-profile")).toHaveTextContent(
      "compact fallback",
    );
    expect(within(draftInputSummary).getByTestId("migration-draft-input-generation-provider-timeout")).toHaveTextContent(
      "240s",
    );
    expect(within(draftInputSummary).getByTestId("migration-draft-input-generation-max-final-input")).toHaveTextContent(
      "9,000",
    );
    expect(within(draftInputSummary).getByTestId("migration-draft-input-generation-compact-limits")).toHaveTextContent(
      "default",
    );

    const mediaSection = await screen.findByTestId("migration-media-section");
    expect(within(mediaSection).getByText("Images")).toBeInTheDocument();
    expect(within(mediaSection).getByText("Discovered source images: 2")).toBeInTheDocument();
    expect(within(mediaSection).getByText("Pages scanned: 3")).toBeInTheDocument();
    expect(within(mediaSection).getByText("Images included in draft: 1")).toBeInTheDocument();
    expect(within(mediaSection).getByRole("button", { name: "Use checked images in draft" })).toBeInTheDocument();
    expect(within(mediaSection).getByRole("button", { name: "Discover / Refresh Source Images" })).toBeInTheDocument();
    expect(within(mediaSection).getByTestId("migration-media-upload-disclosure")).toBeInTheDocument();

    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    expect(within(sourceList).getByText("Site images")).toBeInTheDocument();
    expect(within(sourceList).queryByText("Asset Browser")).not.toBeInTheDocument();
    const imageGrid = within(sourceList).getByTestId("migration-media-image-grid");
    expect(imageGrid).toHaveClass("migration-media-image-grid");
    const sourceImageCard = within(sourceList).getByTestId("migration-media-row-srcimg-1");
    expect(sourceImageCard).toHaveClass("migration-media-card");
    const sourceDetails = within(sourceImageCard).getByTestId("migration-media-details-srcimg-1");
    expect(sourceDetails).not.toHaveAttribute("open");
    expect(within(sourceDetails).getByText("URL: https://legacy.example/images/front.jpg")).not.toBeVisible();
    await user.click(within(sourceDetails).getByText("Image details"));
    expect(within(sourceDetails).getByText("URL: https://legacy.example/images/front.jpg")).toBeInTheDocument();
  });

  it("renders actionable generation safety guidance when preflight blocks before provider call", async () => {
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        draft_input_summary: {
          recommendations_included_count: 2,
          recommendations_available_count: 8,
          generation_safety_profile: "block_before_provider",
          generation_provider_timeout_seconds: 240,
          generation_preflight_mode: "block_before_provider",
          generation_max_final_input_chars: 8500,
          generation_max_difficulty_score: 11,
          generation_compact_fallback_enabled: true,
          generation_compact_fallback_attempted: false,
          generation_budget_capped: true,
          generation_preflight_blocked: true,
          generation_preflight_block_reason: "final_input_chars_exceeded",
          generation_preflight_blocked_setting: "migration_max_final_input_chars",
          generation_preflight_blocked_setting_actual: 9200,
          generation_preflight_blocked_setting_cap: 8500,
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);

    render(<SiteMigrationWorkflowPage />);

    const draftInputSummary = await screen.findByTestId("migration-draft-input-summary");
    expect(
      within(draftInputSummary).getByTestId("migration-draft-input-generation-preflight-blocked"),
    ).toHaveTextContent("final input chars exceeded");
    expect(
      within(draftInputSummary).getByTestId("migration-draft-input-generation-preflight-blocked-message"),
    ).toHaveTextContent("blocked before provider call");
    expect(
      within(draftInputSummary).getByTestId("migration-draft-input-generation-cap-reason"),
    ).toHaveTextContent("final input chars exceeded");
    expect(
      within(draftInputSummary).getByTestId("migration-draft-input-budget-blocked-reason"),
    ).toHaveTextContent("final input chars 9,200 exceeded cap 8,500");
  });

  it("uploads multiple migration images in one action and reports partial failures", async () => {
    const user = userEvent.setup();
    mockUploadMigrationMediaAsset
      .mockResolvedValueOnce({
        asset_id: "upload-1",
        display_filename: "a.jpg",
        provenance: "operator_upload",
        selected_for_draft: true,
      })
      .mockRejectedValueOnce(new ApiRequestError("unsupported media type", { status: 415, detail: null }));

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const uploadDisclosure = within(mediaSection).getByTestId("migration-media-upload-disclosure");
    const uploadSummary = uploadDisclosure.querySelector("summary");
    if (!uploadSummary) {
      throw new Error("Missing migration media upload summary.");
    }
    await user.click(uploadSummary);

    const imageInput = within(uploadDisclosure).getByLabelText("Upload image file");
    const firstFile = new File(["file-one"], "a.jpg", { type: "image/jpeg" });
    const secondFile = new File(["file-two"], "b.png", { type: "image/png" });
    await user.upload(imageInput, [firstFile, secondFile]);

    expect(within(uploadDisclosure).getByTestId("migration-media-upload-selection-count")).toHaveTextContent(
      "Files selected: 2",
    );
    await user.click(within(uploadDisclosure).getByRole("button", { name: "Upload images" }));

    await waitFor(() => expect(mockUploadMigrationMediaAsset).toHaveBeenCalledTimes(2));
    expect(mockUploadMigrationMediaAsset).toHaveBeenNthCalledWith(
      1,
      "token-1",
      "biz-1",
      "site-1",
      expect.objectContaining({
        file: firstFile,
        selectedForDraft: true,
      }),
    );
    expect(mockUploadMigrationMediaAsset).toHaveBeenNthCalledWith(
      2,
      "token-1",
      "biz-1",
      "site-1",
      expect.objectContaining({
        file: secondFile,
        selectedForDraft: true,
      }),
    );
    expect(await screen.findByText("Upload completed. Uploaded: 1 | Failed: 1 | Skipped: 0.")).toBeInTheDocument();
  });

  it("uses singular upload button text when exactly one migration image is selected", async () => {
    const user = userEvent.setup();

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const uploadDisclosure = within(mediaSection).getByTestId("migration-media-upload-disclosure");
    const uploadSummary = uploadDisclosure.querySelector("summary");
    if (!uploadSummary) {
      throw new Error("Missing migration media upload summary.");
    }
    await user.click(uploadSummary);

    const imageInput = within(uploadDisclosure).getByLabelText("Upload image file");
    const singleFile = new File(["file-one"], "single.jpg", { type: "image/jpeg" });
    await user.upload(imageInput, singleFile);

    expect(within(uploadDisclosure).getByTestId("migration-media-upload-selection-count")).toHaveTextContent(
      "Files selected: 1",
    );
    expect(within(uploadDisclosure).getByRole("button", { name: "Upload image" })).toBeInTheDocument();
  });

  it("renders difficulty blocker messaging when preflight fails on difficulty under input cap", async () => {
    const baseSummary = buildMigrationWorkspaceSummary();
    const baseContextSummary = baseSummary.context_summary as Record<string, unknown>;
    const baseDiagnostics = (baseContextSummary.migration_diagnostics || {}) as Record<string, unknown>;
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...baseContextSummary,
        draft_input_summary: {
          recommendations_included_count: 6,
          recommendations_available_count: 81,
          generation_safety_profile: "compact_fallback",
          generation_provider_timeout_seconds: 300,
          generation_preflight_mode: "compact_fallback",
          generation_max_final_input_chars: 32000,
          generation_max_difficulty_score: 18,
          generation_compact_fallback_enabled: true,
          generation_compact_fallback_attempted: true,
          generation_budget_capped: true,
          generation_preflight_blocked: true,
          generation_preflight_block_reason: "difficulty_score_exceeded",
          generation_preflight_blocked_setting: "migration_max_difficulty_score",
          generation_preflight_blocked_setting_actual: 25,
          generation_preflight_blocked_setting_cap: 18,
          generation_provider_call_skipped: true,
        },
        migration_diagnostics: {
          ...baseDiagnostics,
          last_draft_failure_source: "local_preflight",
          last_draft_ai_diagnostics_summary: {
            failure_reason: "request_too_large_or_complex",
            failure_source: "local_validation",
            hint: "Input too large",
            budget_outcome: "precall_rejected",
            context_budget_size_chars: 32000,
            largest_context_block: "media_assets",
            largest_context_block_size_chars: 5175,
          },
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);

    render(<SiteMigrationWorkflowPage />);

    const draftInputSummary = await screen.findByTestId("migration-draft-input-summary");
    expect(
      within(draftInputSummary).getByTestId("migration-draft-input-budget-blocked-reason"),
    ).toHaveTextContent("difficulty score 25 exceeded cap 18");
    expect(
      within(draftInputSummary).getByTestId("migration-draft-input-generation-preflight-blocked-message"),
    ).toHaveTextContent("Blocked setting: migration_max_difficulty_score (25 / cap 18).");
  });

  it("renders combined blocker message when both final input and difficulty exceed preflight caps", async () => {
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        draft_input_summary: {
          generation_preflight_blocked: true,
          generation_preflight_block_reason: "final_input_and_difficulty_exceeded",
          generation_preflight_blocked_setting: "migration_max_final_input_chars,migration_max_difficulty_score",
          generation_preflight_blocked_setting_actual: 35000,
          generation_preflight_blocked_setting_cap: 32000,
        },
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);

    render(<SiteMigrationWorkflowPage />);

    const draftInputSummary = await screen.findByTestId("migration-draft-input-summary");
    expect(
      within(draftInputSummary).getByTestId("migration-draft-input-budget-blocked-reason"),
    ).toHaveTextContent(
      "final input chars 35,000 exceeded cap 32,000 and difficulty score exceeded configured cap",
    );
  });

  it("groups repeated publish/deploy failures and limits history summaries by default", async () => {
    const user = userEvent.setup();
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(buildMigrationWorkspaceSummary());
    mockFetchMigrationPublishHistory.mockResolvedValueOnce({
      items: [
        { timestamp: "2026-04-22T00:00:00Z", status: "failed", artifact_version_id: "a-1", failure_reason: "authentication_failed" },
        { timestamp: "2026-04-21T00:00:00Z", status: "failed", artifact_version_id: "a-1", failure_reason: "authentication_failed" },
        { timestamp: "2026-04-20T00:00:00Z", status: "failed", artifact_version_id: "a-1", failure_reason: "authentication_failed" },
        { timestamp: "2026-04-19T00:00:00Z", status: "failed", artifact_version_id: "a-2", failure_reason: "workflow_not_found" },
        { timestamp: "2026-04-18T00:00:00Z", status: "completed", artifact_version_id: "a-2" },
        { timestamp: "2026-04-17T00:00:00Z", status: "failed", artifact_version_id: "a-3", failure_reason: "workflow_not_found" },
      ],
      total: 6,
    });
    mockFetchMigrationDeployHistory.mockResolvedValueOnce({
      items: [
        { timestamp: "2026-04-22T01:00:00Z", status: "failed", artifact_version_id: "a-1", failure_reason: "dns_mismatch" },
        { timestamp: "2026-04-21T01:00:00Z", status: "failed", artifact_version_id: "a-1", failure_reason: "dns_mismatch" },
        { timestamp: "2026-04-20T01:00:00Z", status: "failed", artifact_version_id: "a-1", failure_reason: "dns_mismatch" },
        { timestamp: "2026-04-19T01:00:00Z", status: "failed", artifact_version_id: "a-2", failure_reason: "workflow_not_dispatchable" },
        { timestamp: "2026-04-18T01:00:00Z", status: "completed", artifact_version_id: "a-2" },
        { timestamp: "2026-04-17T01:00:00Z", status: "failed", artifact_version_id: "a-3", failure_reason: "workflow_not_dispatchable" },
      ],
      total: 6,
    });

    render(<SiteMigrationWorkflowPage />);

    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    await user.click(screen.getByText("Show publish history"));
    const publishHistoryLatest = await screen.findByTestId("migration-publish-history-latest");
    expect(within(publishHistoryLatest).getAllByRole("listitem")).toHaveLength(5);
    const publishGrouped = screen.getByTestId("migration-publish-history-grouped");
    expect(publishGrouped).toHaveTextContent("authentication failed - 3 attempts");

    const publishFullDetails = screen.getByTestId("migration-publish-history-full-details");
    expect(publishFullDetails).not.toHaveAttribute("open");
    await user.click(within(publishFullDetails).getByText("Show full publish history"));
    expect(publishFullDetails).toHaveAttribute("open");
    expect(within(publishFullDetails).getAllByRole("listitem")).toHaveLength(6);

    await user.click(screen.getByText("Show deploy history"));
    const deployHistoryLatest = await screen.findByTestId("migration-deploy-history-latest");
    expect(within(deployHistoryLatest).getAllByRole("listitem")).toHaveLength(5);
    const deployGrouped = screen.getByTestId("migration-deploy-history-grouped");
    expect(deployGrouped).toHaveTextContent("dns mismatch - 3 attempts");

    const deployFullDetails = screen.getByTestId("migration-deploy-history-full-details");
    expect(deployFullDetails).not.toHaveAttribute("open");
    await user.click(within(deployFullDetails).getByText("Show full deploy history"));
    expect(deployFullDetails).toHaveAttribute("open");
    expect(within(deployFullDetails).getAllByRole("listitem")).toHaveLength(6);
  });

  it("removes the standalone enriched section and renders field-level AI suggestion scratchpads", async () => {
    render(<SiteMigrationWorkflowPage />);

    expect(screen.queryByText("Enriched Replacement Content")).not.toBeInTheDocument();
    const requirements = await screen.findByTestId("migration-operator-requirements");
    expect(within(requirements).getByText("Operator Requirements")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-operator-business_objectives")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-operator-requested_pages")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-operator-must_include")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-operator-must_avoid")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-operator-tone")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-operator-calls_to_action")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-operator-additional_notes")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-scratchpad-details-business_objectives")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-scratchpad-details-requested_pages")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-scratchpad-details-must_include")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-scratchpad-details-must_avoid")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-scratchpad-details-tone")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-scratchpad-details-calls_to_action")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirement-scratchpad-details-additional_notes")).toBeInTheDocument();
    expect(within(requirements).getByTestId("migration-requirements-image-reference-hint")).toHaveTextContent(
      "Selected usable Site Images are included automatically in draft context and materialized into artifact assets.",
    );
    expect(within(requirements).getByTestId("migration-requirements-image-reference-hint-secondary")).toHaveTextContent(
      "Generated HTML must use artifact paths such as assets/images/<filename>.",
    );
  });

  it("keeps AI suggestion drafts isolated from operator fields until explicit append/replace and save", async () => {
    const user = userEvent.setup();
    mockSuggestMigrationRequirementField.mockResolvedValueOnce({
      field: "must_include",
      suggestion_status: "completed",
      suggested_value: ["Include local licensing proof", "Include emergency response coverage"],
      reason_code: "requirements_suggestion_completed",
      context_sources_used: ["source_snapshot", "recommendations_summary"],
      retryable: false,
      generated_at: "2026-03-21T00:03:00Z",
    });

    render(<SiteMigrationWorkflowPage />);

    const requirementField = await screen.findByTestId("migration-requirement-field-must_include");
    const operatorTextarea = within(requirementField).getByTestId(
      "migration-requirement-operator-must_include",
    ) as HTMLTextAreaElement;
    expect(operatorTextarea.value).toBe("");

    const scratchpadDetails = within(requirementField).getByTestId(
      "migration-requirement-scratchpad-details-must_include",
    );
    await user.click(within(scratchpadDetails).getByText("AI suggestion draft"));
    await user.click(within(requirementField).getByTestId("migration-requirement-suggest-must_include"));

    await waitFor(() =>
      expect(mockSuggestMigrationRequirementField).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        {
          field: "must_include",
          current_value: null,
          force_refresh: false,
        },
      ),
    );

    const scratchpadTextarea = within(scratchpadDetails).getByTestId(
      "migration-requirement-scratchpad-must_include",
    ) as HTMLTextAreaElement;
    expect(scratchpadTextarea.value).toContain("Include local licensing proof");
    expect(operatorTextarea.value).toBe("");

    await user.type(scratchpadTextarea, "\nUse concise benefit-forward bullet points.");
    expect(operatorTextarea.value).toBe("");

    await user.click(within(scratchpadDetails).getByTestId("migration-requirement-append-must_include"));
    expect(operatorTextarea.value).toContain("Include local licensing proof");

    await user.click(within(scratchpadDetails).getByTestId("migration-requirement-replace-must_include"));
    expect(operatorTextarea.value).toContain("Use concise benefit-forward bullet points.");

    await user.click(screen.getByRole("button", { name: "Save Requirements" }));
    await waitFor(() => expect(mockUpdateMigrationRequirements).toHaveBeenCalledTimes(1));
    expect(mockUpdateMigrationRequirements.mock.calls[0]?.[3]).toEqual(
      expect.objectContaining({
        operator_requirements: expect.objectContaining({
          must_include: expect.arrayContaining(["Include local licensing proof"]),
        }),
      }),
    );

    await user.click(within(scratchpadDetails).getByTestId("migration-requirement-dismiss-must_include"));
    expect(scratchpadTextarea.value).toBe("");

    mockUpdateMigrationRequirements.mockClear();
    await user.click(screen.getByRole("button", { name: "Generate Draft Mockup" }));
    await waitFor(() => expect(mockGenerateMigrationDraftArtifacts).toHaveBeenCalled());
    expect(mockUpdateMigrationRequirements).not.toHaveBeenCalled();
  });

  it("supports AI suggestion helper for additional requirements", async () => {
    const user = userEvent.setup();
    mockSuggestMigrationRequirementField.mockResolvedValueOnce({
      field: "additional_notes",
      suggestion_status: "completed",
      suggested_value: [
        "Prioritize service-area trust proof near the first CTA.",
        "Keep legal/compliance language factual and concise.",
      ],
      reason_code: "requirements_suggestion_completed",
      context_sources_used: ["source_snapshot", "selected_media_summary"],
      retryable: false,
      generated_at: "2026-03-21T00:08:00Z",
    });

    render(<SiteMigrationWorkflowPage />);

    const requirementField = await screen.findByTestId("migration-requirement-field-additional_notes");
    const operatorTextarea = within(requirementField).getByTestId(
      "migration-requirement-operator-additional_notes",
    ) as HTMLTextAreaElement;
    expect(operatorTextarea.value).toBe("");

    const scratchpadDetails = within(requirementField).getByTestId(
      "migration-requirement-scratchpad-details-additional_notes",
    );
    await user.click(within(scratchpadDetails).getByText("AI suggestion draft"));
    await user.click(within(requirementField).getByTestId("migration-requirement-suggest-additional_notes"));

    await waitFor(() =>
      expect(mockSuggestMigrationRequirementField).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {
        field: "additional_notes",
        current_value: null,
        force_refresh: false,
      }),
    );

    const scratchpadTextarea = within(scratchpadDetails).getByTestId(
      "migration-requirement-scratchpad-additional_notes",
    ) as HTMLTextAreaElement;
    expect(scratchpadTextarea.value).toContain("Prioritize service-area trust proof near the first CTA.");

    await user.click(within(scratchpadDetails).getByTestId("migration-requirement-append-additional_notes"));
    expect(operatorTextarea.value).toContain("Prioritize service-area trust proof near the first CTA.");
    expect(operatorTextarea.value).toContain("Keep legal/compliance language factual and concise.");
  });

  it("uses clipboard copy when available and falls back to field-local guidance when unavailable", async () => {
    const user = userEvent.setup();
    mockSuggestMigrationRequirementField.mockResolvedValueOnce({
      field: "business_objectives",
      suggestion_status: "completed",
      suggested_value: ["Increase qualified local quote requests"],
      reason_code: "requirements_suggestion_completed",
      context_sources_used: ["source_snapshot"],
      retryable: false,
      generated_at: "2026-03-21T00:04:00Z",
    });

    const originalClipboard = Object.getOwnPropertyDescriptor(window.navigator, "clipboard");
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    try {
      render(<SiteMigrationWorkflowPage />);

      const requirementField = await screen.findByTestId("migration-requirement-field-business_objectives");
      const scratchpadDetails = within(requirementField).getByTestId(
        "migration-requirement-scratchpad-details-business_objectives",
      );
      await user.click(within(scratchpadDetails).getByText("AI suggestion draft"));
      await user.click(within(requirementField).getByTestId("migration-requirement-suggest-business_objectives"));
      await user.click(within(scratchpadDetails).getByTestId("migration-requirement-copy-business_objectives"));

      await waitFor(() =>
        expect(writeText).toHaveBeenCalledWith("Increase qualified local quote requests"),
      );

      Object.defineProperty(window.navigator, "clipboard", {
        value: undefined,
        configurable: true,
      });

      await user.click(within(scratchpadDetails).getByTestId("migration-requirement-copy-business_objectives"));
      const localError = await within(requirementField).findByTestId(
        "migration-requirement-suggestion-error-business_objectives",
      );
      expect(localError).toHaveTextContent("Clipboard is unavailable in this browser/session.");
    } finally {
      if (originalClipboard) {
        Object.defineProperty(window.navigator, "clipboard", originalClipboard);
      } else {
        Object.defineProperty(window.navigator, "clipboard", {
          value: undefined,
          configurable: true,
        });
      }
    }
  });

  it("renders field-local suggestion failures and keeps global workspace messaging quiet", async () => {
    const user = userEvent.setup();
    mockSuggestMigrationRequirementField.mockRejectedValueOnce(
      new ApiRequestError("Suggestion unavailable", {
        status: 503,
        detail: {
          reason_code: "requirements_suggestion_provider_unavailable",
        },
      }),
    );

    render(<SiteMigrationWorkflowPage />);

    const requirementField = await screen.findByTestId("migration-requirement-field-tone");
    const scratchpadDetails = within(requirementField).getByTestId("migration-requirement-scratchpad-details-tone");
    await user.click(within(scratchpadDetails).getByText("AI suggestion draft"));
    await user.click(within(requirementField).getByTestId("migration-requirement-suggest-tone"));

    const localError = await within(requirementField).findByTestId("migration-requirement-suggestion-error-tone");
    expect(localError).toHaveTextContent("AI provider is currently unavailable for requirement suggestions.");
    expect(screen.queryByTestId("migration-message-stack")).not.toBeInTheDocument();
  });

  it("exports and imports operator requirements JSON with schema validation", async () => {
    const user = userEvent.setup();
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    const createObjectURLMock = jest.fn<string, [Blob]>((_blob) => "blob:requirements-export");
    const revokeObjectURLMock = jest.fn();
    Object.defineProperty(URL, "createObjectURL", {
      value: createObjectURLMock,
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      value: revokeObjectURLMock,
      configurable: true,
    });
    const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    try {
      render(<SiteMigrationWorkflowPage />);

      const requirements = await screen.findByTestId("migration-operator-requirements");
      const mustIncludeInput = within(requirements).getByTestId(
        "migration-requirement-operator-must_include",
      ) as HTMLTextAreaElement;
      const callsToActionInput = within(requirements).getByTestId(
        "migration-requirement-operator-calls_to_action",
      ) as HTMLTextAreaElement;
      const additionalNotesInput = within(requirements).getByTestId(
        "migration-requirement-operator-additional_notes",
      ) as HTMLTextAreaElement;

      await user.type(mustIncludeInput, "Include financing options");
      await user.type(callsToActionInput, "Call now");
      await user.type(additionalNotesInput, "Preserve local licensing references.");

      await user.click(within(requirements).getByTestId("migration-requirements-export"));
      expect(clickSpy).toHaveBeenCalled();
      expect(createObjectURLMock).toHaveBeenCalledTimes(1);
      const exportedBlob = createObjectURLMock.mock.calls[0]?.[0];
      if (!(exportedBlob instanceof Blob)) {
        throw new Error("Expected export to create a Blob payload.");
      }
      const exportedText = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
        reader.onerror = () => reject(new Error("Failed to read exported requirements payload."));
        reader.readAsText(exportedBlob);
      });
      const exportedJson = JSON.parse(exportedText) as Record<string, unknown>;
      expect(exportedJson.schema).toBe("mbsrn.operator_requirements.v1");
      expect(exportedJson.site_id).toBe("site-1");
      expect(exportedJson.business_id).toBe("biz-1");
      const exportedRequirements = exportedJson.requirements as Record<string, unknown>;
      expect(exportedRequirements.must_include).toEqual(["Include financing options"]);
      expect(exportedRequirements.calls_to_action).toEqual(["Call now"]);
      expect(exportedRequirements.additional_notes).toBe("Preserve local licensing references.");
      expect(JSON.stringify(exportedJson).toLowerCase()).not.toContain("token");
      expect(JSON.stringify(exportedJson).toLowerCase()).not.toContain("secret");

      const importInput = within(requirements).getByTestId("migration-requirements-import-input") as HTMLInputElement;
      const importPayload = {
        schema: "mbsrn.operator_requirements.v1",
        exported_at: "2026-03-22T00:00:00Z",
        site_id: "other-site",
        business_id: "other-biz",
        requirements: {
          must_include: ["Include emergency response coverage"],
          additional_notes: "Imported additional requirement note.",
          unknown_field: "ignored",
          token: "ignored",
        },
      };
      const importFile = new File([JSON.stringify(importPayload)], "requirements-import.json", {
        type: "application/json",
      });
      await user.upload(importInput, importFile);

      await waitFor(() =>
        expect(
          (within(requirements).getByTestId("migration-requirement-operator-must_include") as HTMLTextAreaElement).value,
        ).toContain("Include emergency response coverage"),
      );
      expect(
        (within(requirements).getByTestId("migration-requirement-operator-additional_notes") as HTMLTextAreaElement).value,
      ).toContain("Imported additional requirement note.");
      expect(
        (within(requirements).getByTestId("migration-requirement-operator-calls_to_action") as HTMLTextAreaElement).value,
      ).toContain("Call now");
      expect(mockGenerateMigrationDraftArtifacts).not.toHaveBeenCalled();
      expect(mockPublishMigrationArtifactVersion).not.toHaveBeenCalled();
    } finally {
      clickSpy.mockRestore();
      if (originalCreateObjectURL) {
        Object.defineProperty(URL, "createObjectURL", {
          value: originalCreateObjectURL,
          configurable: true,
        });
      } else {
        Object.defineProperty(URL, "createObjectURL", {
          value: undefined,
          configurable: true,
        });
      }
      if (originalRevokeObjectURL) {
        Object.defineProperty(URL, "revokeObjectURL", {
          value: originalRevokeObjectURL,
          configurable: true,
        });
      } else {
        Object.defineProperty(URL, "revokeObjectURL", {
          value: undefined,
          configurable: true,
        });
      }
    }
  });

  it("rejects invalid or wrong-schema operator requirements imports without mutating fields", async () => {
    const user = userEvent.setup();
    render(<SiteMigrationWorkflowPage />);

    const requirements = await screen.findByTestId("migration-operator-requirements");
    const notesInput = within(requirements).getByTestId(
      "migration-requirement-operator-additional_notes",
    ) as HTMLTextAreaElement;
    await user.type(notesInput, "Keep this note.");

    const importInput = within(requirements).getByTestId("migration-requirements-import-input") as HTMLInputElement;

    const invalidJsonFile = new File(["{invalid-json"], "invalid.json", { type: "application/json" });
    await user.upload(importInput, invalidJsonFile);
    await screen.findByText("Import failed: file is not valid JSON.");
    expect(notesInput.value).toBe("Keep this note.");

    const wrongSchemaFile = new File(
      [
        JSON.stringify({
          schema: "wrong.schema.v1",
          requirements: {
            additional_notes: "Should not apply",
          },
        }),
      ],
      "wrong-schema.json",
      { type: "application/json" },
    );
    await user.upload(importInput, wrongSchemaFile);
    await screen.findByText("Import failed: expected schema mbsrn.operator_requirements.v1.");
    expect(notesInput.value).toBe("Keep this note.");
  });

  it("supports media metadata suggestion actions while preserving manual metadata until apply", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        draft_input_summary: {
          recommendations_included_count: 1,
          gsc_signals_included: true,
          ga4_signals_included: true,
          competitor_profiles_included_count: 1,
          operator_requirements_included: true,
          enriched_business_context_included: true,
          source_site_images_discovered_count: 2,
          source_site_images_imported_count: 1,
          operator_uploaded_images_count: 1,
          selected_media_assets_count: 1,
          media_context_included: true,
          media_assets_with_ai_suggestions_count: 1,
          media_assets_with_operator_applied_metadata_count: 0,
          media_suggestion_failures_count: 1,
          provider_source: "mock",
          mocked_source: true,
        },
        media_assets: {
          source_discovered_count: 2,
          source_imported_count: 1,
          operator_uploaded_count: 1,
          selected_assets_count: 1,
          media_asset_categories: ["project_gallery"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "srcimg-1",
              normalized_url: "https://legacy.example/images/front.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: false,
            },
            {
              asset_id: "srcimg-2",
              normalized_url: "https://legacy.example/images/gallery.jpg",
              provenance: "source_site_import",
              import_status: "selected",
              selected_for_draft: true,
              metadata_suggestion: {
                suggestion_status: "failed",
                reason_code: "provider_unavailable",
              },
            },
          ],
          operator_uploaded: [
            {
              asset_id: "upl-1",
              display_filename: "crew-photo.jpg",
              provenance: "operator_upload",
              category: "project_gallery",
              alt_text: "Manual alt text",
              selected_for_draft: true,
              metadata_suggestion: {
                suggestion_status: "completed",
                reason_code: "image_metadata_suggested",
                suggested_alt_text: "AI suggested alt",
                suggested_category: "hero",
              },
            },
          ],
          selected_assets: [
            {
              asset_id: "upl-1",
              display_filename: "crew-photo.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
            },
          ],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);
    mockSuggestMigrationMediaAssetMetadata.mockResolvedValue({
      asset_id: "upl-1",
      display_filename: "crew-photo.jpg",
      provenance: "operator_upload",
      selected_for_draft: true,
      metadata_suggestion: {
        suggestion_status: "completed",
        reason_code: "image_metadata_suggested",
        suggested_alt_text: "AI suggested alt",
        suggested_category: "hero",
      },
    });

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    expect(within(mediaSection).getByRole("button", { name: "Use checked images in draft" })).toBeInTheDocument();
    expect(within(mediaSection).queryByRole("button", { name: "Analyze Selected Images" })).not.toBeInTheDocument();
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    const uploadedRow = within(sourceList).getByTestId("migration-media-row-upl-1");
    expect(within(uploadedRow).getByTestId("migration-media-primary-action-upl-1")).toHaveTextContent("Use in draft");
    await user.click(within(uploadedRow).getByTestId("migration-media-primary-action-upl-1"));
    await waitFor(() =>
      expect(mockSuggestMigrationMediaAssetsMetadataBatch).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {
        asset_ids: ["upl-1"],
        force_refresh: false,
      }),
    );
    await waitFor(() =>
      expect(mockUpdateMigrationMediaAsset).toHaveBeenCalledWith("token-1", "biz-1", "site-1", "upl-1", {
        apply_suggested_metadata: true,
      }),
    );
    expect(mockImportMigrationDiscoveredMediaAssets).not.toHaveBeenCalled();
  });

  it("renders inline previews for usable assets and keeps blocked assets under unsafe filter", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 2,
          source_imported_count: 1,
          operator_uploaded_count: 1,
          selected_assets_count: 2,
          media_asset_categories: ["hero"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "safe-1",
              normalized_url: "https://legacy.example/images/hero.jpg?token=temporary",
              provenance: "source_site_import",
              import_status: "selected",
              alt_text: "Safe hero image",
              selected_for_draft: true,
            },
            {
              asset_id: "blocked-1",
              normalized_url: "http://127.0.0.1/internal.png",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: false,
            },
          ],
          operator_uploaded: [
            {
              asset_id: "uploaded-preview",
              display_filename: "crew.jpg",
              provenance: "operator_upload",
              import_status: "uploaded",
              selected_for_draft: true,
              preview_url: "/api/businesses/biz-1/seo/sites/site-1/migration/media/assets/uploaded-preview/preview",
            },
          ],
          selected_assets: [
            {
              asset_id: "safe-1",
              normalized_url: "https://legacy.example/images/hero.jpg?token=temporary",
              provenance: "source_site_import",
              import_status: "selected",
              alt_text: "Safe hero image",
              selected_for_draft: true,
            },
            {
              asset_id: "uploaded-preview",
              display_filename: "crew.jpg",
              provenance: "operator_upload",
              import_status: "uploaded",
              selected_for_draft: true,
              preview_url: null,
            },
          ],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    const uploadedPreview = within(sourceList).getByRole("img", { name: "crew.jpg" });
    expect(uploadedPreview.getAttribute("src")).toBe(
      "/api/businesses/biz-1/seo/sites/site-1/migration/media/assets/uploaded-preview/preview",
    );

    const previewImage = within(sourceList).getByRole("img", { name: "Safe hero image" });
    expect(previewImage).toHaveAttribute("alt", "Safe hero image");
    const previewSrc = previewImage.getAttribute("src") || "";
    expect(previewSrc).toContain("https://legacy.example/images/hero.jpg");
    expect(previewSrc).not.toContain("token=");
    expect(previewSrc).not.toContain("C:\\");
    expect(previewSrc).not.toContain("base64");

    await user.click(within(sourceList).getByTestId("migration-media-filter-unsafe_rejected"));
    expect(within(sourceList).getByTestId("migration-media-preview-unavailable-blocked-1")).toHaveTextContent(
      "preview_url_unsafe",
    );
  });

  it("preserves safe uploaded preview metadata when selected assets are sparse", async () => {
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 1,
          source_imported_count: 1,
          operator_uploaded_count: 1,
          selected_assets_count: 2,
          media_asset_categories: ["project_gallery", "hero"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "discovered-safe",
              normalized_url: "https://legacy.example/images/discovered-safe.jpg",
              provenance: "source_site_import",
              import_status: "selected",
              selected_for_draft: true,
              alt_text: "Discovered safe preview",
            },
          ],
          operator_uploaded: [
            {
              asset_id: "uploaded-safe-display",
              display_filename: "crew.jpg",
              provenance: "operator_upload",
              import_status: "selected",
              selected_for_draft: true,
              preview_url: "gs://private-bucket/crew.jpg",
              normalized_url: "https://legacy.example/images/uploaded-safe-display.jpg",
            },
          ],
          selected_assets: [
            {
              asset_id: "discovered-safe",
              normalized_url: "https://legacy.example/images/discovered-safe.jpg",
              provenance: "source_site_import",
              import_status: "selected",
              selected_for_draft: true,
              alt_text: "Discovered safe preview",
            },
            {
              asset_id: "uploaded-safe-display",
              display_filename: "crew.jpg",
              provenance: "operator_upload",
              import_status: "selected",
              selected_for_draft: true,
              preview_url: null,
            },
          ],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");

    const uploadedPreview = within(sourceList).getByRole("img", { name: "crew.jpg" });
    expect(uploadedPreview.getAttribute("src")).toContain("https://legacy.example/images/uploaded-safe-display.jpg");
    expect(uploadedPreview.getAttribute("src")).not.toContain("gs://");

    const discoveredPreview = within(sourceList).getByRole("img", { name: "Discovered safe preview" });
    expect(discoveredPreview.getAttribute("src")).toContain("https://legacy.example/images/discovered-safe.jpg");
  });

  it("shows bounded fallback when uploaded image preview URL is unavailable", async () => {
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 0,
          source_imported_count: 0,
          operator_uploaded_count: 1,
          selected_assets_count: 1,
          media_asset_categories: ["project_gallery"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [],
          operator_uploaded: [
            {
              asset_id: "uploaded-missing",
              display_filename: "crew.jpg",
              provenance: "operator_upload",
              import_status: "uploaded",
              selected_for_draft: true,
            },
          ],
          selected_assets: [
            {
              asset_id: "uploaded-missing",
              display_filename: "crew.jpg",
              provenance: "operator_upload",
              import_status: "uploaded",
              selected_for_draft: true,
            },
          ],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    expect(within(sourceList).getByTestId("migration-media-preview-unavailable-uploaded-missing")).toHaveTextContent(
      "storage_preview_not_available",
    );
  });

  it("does not render legacy insert/copy reference controls in the simplified media workflow", async () => {
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 0,
          source_imported_count: 0,
          operator_uploaded_count: 1,
          selected_assets_count: 1,
          media_asset_categories: ["service_page"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [],
          operator_uploaded: [
            {
              asset_id: "img-ref-1",
              display_filename: "backflow-4.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
            },
          ],
          selected_assets: [
            {
              asset_id: "img-ref-1",
              display_filename: "backflow-4.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
            },
          ],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    expect(within(sourceList).queryByTestId("migration-media-reference-token-img-ref-1")).not.toBeInTheDocument();
    expect(within(sourceList).queryByRole("button", { name: /insert into requirements/i })).not.toBeInTheDocument();
    expect(within(sourceList).queryByRole("button", { name: /copy image reference/i })).not.toBeInTheDocument();
  });

  it("shows analysis status details while keeping a single use-in-draft primary action", async () => {
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 0,
          source_imported_count: 0,
          operator_uploaded_count: 3,
          selected_assets_count: 3,
          media_asset_categories: ["project_gallery"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [],
          operator_uploaded: [
            {
              asset_id: "ready-1",
              display_filename: "ready.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
              metadata_suggestion_applied: false,
              metadata_suggestion: {
                suggestion_status: "completed",
                reason_code: "image_metadata_suggested",
              },
            },
            {
              asset_id: "applied-1",
              display_filename: "applied.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
              metadata_suggestion_applied: true,
              metadata_suggestion: {
                suggestion_status: "completed",
                reason_code: "image_metadata_suggested",
              },
            },
            {
              asset_id: "pending-1",
              display_filename: "pending.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
              metadata_suggestion_applied: false,
              metadata_suggestion: {
                suggestion_status: "pending",
              },
            },
          ],
          selected_assets: [
            {
              asset_id: "ready-1",
              display_filename: "ready.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
              metadata_suggestion_applied: false,
              metadata_suggestion: {
                suggestion_status: "completed",
                reason_code: "image_metadata_suggested",
              },
            },
            {
              asset_id: "applied-1",
              display_filename: "applied.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
              metadata_suggestion_applied: true,
              metadata_suggestion: {
                suggestion_status: "completed",
                reason_code: "image_metadata_suggested",
              },
            },
            {
              asset_id: "pending-1",
              display_filename: "pending.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
              metadata_suggestion_applied: false,
              metadata_suggestion: {
                suggestion_status: "pending",
              },
            },
          ],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    expect(within(sourceList).getByTestId("migration-media-primary-action-ready-1")).toHaveTextContent("Use in draft");
    expect(within(sourceList).getByTestId("migration-media-primary-action-pending-1")).toHaveTextContent("Use in draft");
    expect(within(sourceList).getByTestId("migration-media-primary-action-applied-1")).toHaveTextContent("Use in draft");

    const readyDetails = within(sourceList).getByTestId("migration-media-details-ready-1");
    await userEvent.setup().click(within(readyDetails).getByText("Image details"));
    expect(readyDetails).toHaveTextContent("Analysis status: Suggestion ready");

    const appliedDetails = within(sourceList).getByTestId("migration-media-details-applied-1");
    await userEvent.setup().click(within(appliedDetails).getByText("Image details"));
    expect(appliedDetails).toHaveTextContent("Analysis status: Suggestion ready");

    const pendingDetails = within(sourceList).getByTestId("migration-media-details-pending-1");
    await userEvent.setup().click(within(pendingDetails).getByText("Image details"));
    expect(pendingDetails).toHaveTextContent("Analysis status: Suggestion pending");
  });

  it("shows analysis-unavailable guidance without an active analyze action when runtime support is missing", async () => {
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 0,
          source_imported_count: 0,
          operator_uploaded_count: 1,
          selected_assets_count: 1,
          media_asset_categories: ["hero"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [],
          operator_uploaded: [
            {
              asset_id: "runtime-na-1",
              display_filename: "runtime-na.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
              metadata_suggestion: {
                suggestion_status: "not_available",
                reason_code: "image_analysis_not_available",
              },
            },
          ],
          selected_assets: [
            {
              asset_id: "runtime-na-1",
              display_filename: "runtime-na.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
              metadata_suggestion: {
                suggestion_status: "not_available",
                reason_code: "image_analysis_not_available",
              },
            },
          ],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    const runtimeUnavailableRow = within(sourceList).getByTestId("migration-media-row-runtime-na-1");
    expect(within(runtimeUnavailableRow).getByTestId("migration-media-primary-action-runtime-na-1")).toHaveTextContent(
      "Use in draft",
    );
    expect(within(runtimeUnavailableRow).queryByRole("button", { name: "Analyze image" })).not.toBeInTheDocument();

    const details = within(runtimeUnavailableRow).getByTestId("migration-media-details-runtime-na-1");
    await userEvent.setup().click(within(details).getByText("Image details"));
    expect(details).toHaveTextContent("Analysis unavailable in this environment.");
  });

  it("uses checked images in draft bulk action and renders combined result feedback", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 1,
          source_imported_count: 0,
          operator_uploaded_count: 1,
          selected_assets_count: 2,
          media_asset_categories: ["project_gallery", "hero"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "srcimg-remote",
              normalized_url: "https://legacy.example/images/hero.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: true,
              candidate_quality: "useful",
              fetch_status: "validated_head",
              content_type: "image/jpeg",
              metadata_suggestion: {
                suggestion_status: "not_available",
                reason_code: "media_asset_not_imported",
              },
            },
          ],
          operator_uploaded: [
            {
              asset_id: "upl-1",
              display_filename: "crew-photo.jpg",
              provenance: "operator_upload",
              category: "project_gallery",
              alt_text: "Manual alt text",
              selected_for_draft: true,
              metadata_suggestion_applied: true,
              metadata_suggestion: {
                suggestion_status: "completed",
                reason_code: "image_metadata_suggested",
                suggested_alt_text: "AI suggested alt",
              },
            },
          ],
          selected_assets: [
            {
              asset_id: "upl-1",
              display_filename: "crew-photo.jpg",
              provenance: "operator_upload",
              selected_for_draft: true,
              metadata_suggestion_applied: true,
              metadata_suggestion: {
                suggestion_status: "completed",
                reason_code: "image_metadata_suggested",
              },
            },
            {
              asset_id: "srcimg-remote",
              normalized_url: "https://legacy.example/images/hero.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: true,
              candidate_quality: "useful",
              fetch_status: "validated_head",
              content_type: "image/jpeg",
              metadata_suggestion: {
                suggestion_status: "not_available",
                reason_code: "media_asset_not_imported",
              },
            },
          ],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);
    mockImportMigrationDiscoveredMediaAssets.mockResolvedValue({
      batch_status: "completed",
      imported_count: 1,
      failed_count: 0,
      skipped_count: 0,
      disabled_count: 0,
      results: [
        {
          asset_id: "srcimg-remote",
          status: "imported",
          reason_code: "remote_image_imported",
        },
      ],
    });
    mockSuggestMigrationMediaAssetsMetadataBatch.mockResolvedValue({
      batch_status: "partial_success",
      completed_count: 1,
      failed_count: 0,
      skipped_count: 1,
      results: [
        {
          asset_id: "upl-1",
          suggestion_status: "completed",
          reason_code: "image_metadata_suggested",
          retryable: false,
        },
        {
          asset_id: "srcimg-remote",
          suggestion_status: "not_available",
          reason_code: "media_asset_not_imported",
          retryable: false,
        },
      ],
    });

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const batchActionButton = within(mediaSection).getByRole("button", { name: "Use checked images in draft" });
    expect(batchActionButton).toBeInTheDocument();

    await user.click(batchActionButton);
    await waitFor(() =>
      expect(mockImportMigrationDiscoveredMediaAssets).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {
        discovered_image_ids: ["srcimg-remote"],
        selected_for_draft: true,
      }),
    );
    await waitFor(() =>
      expect(mockSuggestMigrationMediaAssetsMetadataBatch).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {
        asset_ids: expect.arrayContaining(["upl-1", "srcimg-remote"]),
        force_refresh: false,
      }),
    );

    const batchFeedback = within(mediaSection).getByTestId("migration-media-batch-feedback");
    expect(batchFeedback).toHaveTextContent("Status: Partial success");
    expect(batchFeedback).toHaveTextContent("Completed: 1 | Failed: 0 | Skipped: 1");
    expect(within(batchFeedback).getByText(/Import before using in draft or AI image analysis/i)).toBeInTheDocument();
  });

  it("uses per-image action to import discovered assets and include them in draft", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 1,
          source_imported_count: 0,
          operator_uploaded_count: 0,
          selected_assets_count: 1,
          media_asset_categories: ["hero"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "srcimg-remote",
              normalized_url: "https://legacy.example/images/hero.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: false,
              candidate_quality: "useful",
              fetch_status: "validated_head",
              content_type: "image/jpeg",
            },
          ],
          operator_uploaded: [],
          selected_assets: [],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);
    mockImportMigrationDiscoveredMediaAssets.mockResolvedValue({
      batch_status: "completed",
      imported_count: 1,
      failed_count: 0,
      skipped_count: 0,
      disabled_count: 0,
      results: [
        {
          asset_id: "srcimg-remote",
          status: "imported",
          reason_code: "remote_image_imported",
        },
      ],
    });

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    expect(within(sourceList).queryByRole("button", { name: "Select for Draft" })).not.toBeInTheDocument();
    expect(within(sourceList).queryByRole("button", { name: "Analyze image" })).not.toBeInTheDocument();
    await user.click(within(sourceList).getByRole("button", { name: "Use in draft" }));

    await waitFor(() =>
      expect(mockImportMigrationDiscoveredMediaAssets).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {
        discovered_image_ids: ["srcimg-remote"],
        selected_for_draft: true,
      }),
    );

    const importFeedback = within(mediaSection).getByTestId("migration-media-import-feedback");
    expect(importFeedback).toHaveTextContent("Status: Completed");
    expect(importFeedback).toHaveTextContent("Imported: 1 | Failed: 0 | Skipped: 0 | Disabled: 0");
  });

  it("renders remove/ignore lifecycle actions and calls lifecycle API with confirmation", async () => {
    const user = userEvent.setup();
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    mockUpdateMigrationMediaAssetLifecycle
      .mockResolvedValueOnce({ asset_id: "srcimg-ignore", status: "ignored", reason_code: "ignored" })
      .mockResolvedValueOnce({ asset_id: "upl-remove", status: "removed", reason_code: "removed" });
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 2,
          source_imported_count: 1,
          operator_uploaded_count: 1,
          selected_assets_count: 1,
          media_asset_categories: ["project_gallery"],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "srcimg-ignore",
              normalized_url: "https://legacy.example/images/ignore.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: false,
              candidate_quality: "useful",
              fetch_status: "validated_head",
              content_type: "image/jpeg",
            },
            {
              asset_id: "srcimg-imported",
              normalized_url: "https://legacy.example/images/imported.jpg",
              provenance: "source_site_import",
              import_status: "imported",
              selected_for_draft: true,
              candidate_quality: "useful",
              fetch_status: "validated_head",
              content_type: "image/jpeg",
              preview_url: "/api/businesses/biz-1/seo/sites/site-1/migration/media/assets/srcimg-imported/preview",
            },
          ],
          operator_uploaded: [
            {
              asset_id: "upl-remove",
              display_filename: "crew-remove.jpg",
              provenance: "operator_upload",
              import_status: "uploaded",
              selected_for_draft: true,
              preview_url: "/api/businesses/biz-1/seo/sites/site-1/migration/media/assets/upl-remove/preview",
            },
          ],
          selected_assets: [
            {
              asset_id: "upl-remove",
              display_filename: "crew-remove.jpg",
              provenance: "operator_upload",
              import_status: "uploaded",
              selected_for_draft: true,
              preview_url: "/api/businesses/biz-1/seo/sites/site-1/migration/media/assets/upl-remove/preview",
            },
          ],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    expect(within(sourceList).getByTestId("migration-media-lifecycle-action-srcimg-ignore")).toHaveTextContent(
      "Ignore",
    );
    expect(within(sourceList).getByTestId("migration-media-lifecycle-action-srcimg-imported")).toHaveTextContent(
      "Remove from workspace",
    );
    expect(within(sourceList).getByTestId("migration-media-lifecycle-action-upl-remove")).toHaveTextContent(
      "Remove image",
    );

    await user.click(within(sourceList).getByTestId("migration-media-lifecycle-action-srcimg-ignore"));
    await waitFor(() =>
      expect(mockUpdateMigrationMediaAssetLifecycle).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        "srcimg-ignore",
        { action: "ignore" },
      ),
    );
    await user.click(within(sourceList).getByTestId("migration-media-lifecycle-action-upl-remove"));
    await waitFor(() =>
      expect(mockUpdateMigrationMediaAssetLifecycle).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        "upl-remove",
        { action: "remove" },
      ),
    );
    confirmSpy.mockRestore();
  });

  it("renders disabled discovered-image import guidance when feature flag is off", async () => {
    const user = userEvent.setup();
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 1,
          source_imported_count: 0,
          operator_uploaded_count: 0,
          selected_assets_count: 1,
          media_asset_categories: [],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "srcimg-disabled",
              normalized_url: "https://legacy.example/images/disabled.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: false,
              candidate_quality: "useful",
              fetch_status: "validated_head",
              content_type: "image/jpeg",
            },
          ],
          operator_uploaded: [],
          selected_assets: [],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);
    mockImportMigrationDiscoveredMediaAssets.mockResolvedValue({
      batch_status: "failed",
      imported_count: 0,
      failed_count: 0,
      skipped_count: 0,
      disabled_count: 1,
      results: [
        {
          asset_id: "srcimg-disabled",
          status: "disabled",
          reason_code: "remote_import_disabled",
        },
      ],
    });

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    await user.click(within(sourceList).getByRole("button", { name: "Use in draft" }));

    const importFeedback = await within(mediaSection).findByTestId("migration-media-import-feedback");
    expect(importFeedback).toHaveTextContent("Disabled: 1");
    expect(
      within(importFeedback).getByText(/Remote source image import is currently disabled for this environment/i),
    ).toBeInTheDocument();
  });

  it("gates discovered not-available actions and de-emphasizes low-value candidates by default", async () => {
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        ...buildMigrationWorkspaceSummary().context_summary,
        media_assets: {
          source_discovered_count: 2,
          source_imported_count: 0,
          operator_uploaded_count: 0,
          selected_assets_count: 0,
          media_asset_categories: [],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "srcimg-useful",
              display_filename: "hero.jpg",
              normalized_url: "https://legacy.example/images/hero.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: false,
              candidate_quality: "useful",
              fetch_status: "validated_head",
              content_type: "image/jpeg",
            },
            {
              asset_id: "srcimg-low",
              display_filename: "transparent_placeholder.png",
              normalized_url: "https://legacy.example/images/transparent_placeholder.png",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: false,
              candidate_quality: "low_value",
              quality_reason: "placeholder_image_detected",
              fetch_status: "validated_head",
              content_type: "image/png",
            },
          ],
          operator_uploaded: [],
          selected_assets: [],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValue(mediaAssetsPayload);

    render(<SiteMigrationWorkflowPage />);

    const mediaSection = await screen.findByTestId("migration-media-section");
    const sourceList = within(mediaSection).getByTestId("migration-media-source-list");
    expect(sourceList).toHaveTextContent("Import before using in draft or AI image analysis.");
    expect(within(sourceList).getByRole("button", { name: "Use in draft" })).toBeInTheDocument();
    expect(within(sourceList).queryByRole("button", { name: "Analyze image" })).not.toBeInTheDocument();
    expect(within(sourceList).queryByRole("button", { name: "Select for Draft" })).not.toBeInTheDocument();
    expect(within(sourceList).queryByRole("button", { name: "Apply suggestions" })).not.toBeInTheDocument();
    expect(sourceList).toHaveTextContent("transparent_placeholder.png");
    expect(sourceList).toHaveTextContent("Quality warning only. Operator can still use this image in draft.");
    expect(within(sourceList).getByRole("button", { name: "Use in draft anyway" })).toBeInTheDocument();
    expect(within(sourceList).queryByRole("button", { name: "Show low-value/rejected" })).not.toBeInTheDocument();
  });

  it("surfaces media-required readiness warning when no usable media is selected", async () => {
    mockFetchMigrationDraftReadiness.mockResolvedValueOnce(
      buildMigrationDraftReadinessPreflight({
        ready: true,
        warning_reason_codes: ["media_required_but_not_selected"],
        media_required_by_operator: true,
        media_requirement_sources: ["operator_requirements.business_objectives:real project photos"],
        selected_usable_media_assets_count: 0,
        media_requirement_satisfied: false,
        media_requirement_warning_reason: "media_required_but_not_selected",
        useful_discovered_images_count: 1,
        operator_action:
          "Draft can be generated, but operator-requested real media is missing. Import/select source images or upload project photos before approval.",
      }),
    );
    const summary = buildMigrationWorkspaceSummary({
      context_summary: {
        media_assets: {
          source_discovered_count: 1,
          pages_scanned_count: 2,
          source_imported_count: 0,
          operator_uploaded_count: 0,
          selected_assets_count: 0,
          media_asset_categories: [],
          selected_assets_trimmed: false,
          diagnostics: [],
          source_discovered: [
            {
              asset_id: "srcimg-useful-only",
              display_filename: "project-hero.jpg",
              normalized_url: "https://legacy.example/images/project-hero.jpg",
              provenance: "source_site_import",
              import_status: "discovered",
              selected_for_draft: false,
              candidate_quality: "useful",
            },
          ],
          operator_uploaded: [],
          selected_assets: [],
        },
      },
    });
    const mediaAssetsPayload = (summary.context_summary as Record<string, unknown>).media_assets as Record<
      string,
      unknown
    >;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(summary);
    mockFetchMigrationMediaAssets.mockResolvedValueOnce(mediaAssetsPayload);

    render(<SiteMigrationWorkflowPage />);

    const readinessCard = await screen.findByTestId("migration-draft-readiness");
    expect(readinessCard).toHaveTextContent(
      "Useful source images were discovered. Use images in draft before approving the draft.",
    );
    const mediaSection = await screen.findByTestId("migration-media-section");
    expect(within(mediaSection).getByTestId("migration-media-required-callout")).toHaveTextContent(
      "Media needed for this draft",
    );
  });

  it("shows required-media warning in artifact quality summary when placeholders are present", async () => {
    const artifactWithMediaWarning = buildMigrationArtifactVersion({
      artifact_quality_evaluation: {
        quality_status: "medium",
        score: 62,
        issue_count: 1,
        operator_summary:
          "Real project images were requested, but no imported/uploaded media was selected. Draft uses placeholders.",
        issues: [
          {
            type: "required_media_missing",
            severity: "warning",
            description:
              "Real project images were requested, but no imported/uploaded media was selected. Draft uses placeholders.",
          },
        ],
      },
      artifact_quality_evaluation_json: {
        quality_status: "medium",
        score: 62,
        issue_count: 1,
        operator_summary:
          "Real project images were requested, but no imported/uploaded media was selected. Draft uses placeholders.",
        issues: [
          {
            type: "required_media_missing",
            severity: "warning",
            description:
              "Real project images were requested, but no imported/uploaded media was selected. Draft uses placeholders.",
          },
        ],
      },
    });
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        workspace: buildMigrationWorkspace({
          latest_generated_artifact_version_id: artifactWithMediaWarning.id,
          latest_generated_artifact_version_number: artifactWithMediaWarning.version,
        }),
        latest_artifact: artifactWithMediaWarning,
      }),
    );
    mockFetchMigrationArtifactVersions.mockResolvedValueOnce({
      items: [artifactWithMediaWarning],
      total: 1,
    });

    render(<SiteMigrationWorkflowPage />);

    const qualitySummary = await screen.findByTestId("migration-artifact-quality-summary");
    expect(within(qualitySummary).getByTestId("migration-artifact-quality-required-media-warning")).toHaveTextContent(
      "Real project images were requested",
    );
    expect(within(qualitySummary).queryByText("No quality issues detected.")).not.toBeInTheDocument();
  });

  it("keeps moved provider/media/destination troubleshooting fields available under Advanced Diagnostics disclosures", async () => {
    const user = userEvent.setup();
    const baseSummary = buildMigrationWorkspaceSummary();
    const baseContextSummary = baseSummary.context_summary as Record<string, unknown>;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        context_summary: {
          ...baseContextSummary,
          migration_diagnostics: {
            last_draft_generation_status: "failed",
            media_diagnostics: ["image_fetch_failed"],
          },
        },
        deploy_readiness: {
          ready: false,
          reasons: ["Deploy target is not enabled."],
          target: {
            enabled: false,
            repo_owner: "mhanson13",
            repo_name: "tnmfire",
            workflow_id: "deploy-tnmfire-www-prod.yml",
            ref: "main",
            kubernetes_namespace: "site-1",
          },
        },
      }),
    );
    render(<SiteMigrationWorkflowPage />);

    await user.click(await screen.findByText("Show detailed migration failure diagnostics"));
    expect(screen.getByTestId("migration-action-diagnostics-shell")).toHaveClass("migration-diagnostics-shell");
    expect(screen.getByTestId("migration-draft-provider-diagnostics-shell")).toHaveClass("migration-diagnostics-shell");
    expect(screen.getByTestId("migration-draft-provider-diagnostics")).toBeInTheDocument();
    expect(screen.getByTestId("migration-media-diagnostics-shell")).toHaveClass("migration-diagnostics-shell");
    expect(screen.getByTestId("migration-publish-history-shell")).toHaveClass("migration-diagnostics-shell");
    expect(screen.getByTestId("migration-deploy-history-shell")).toHaveClass("migration-diagnostics-shell");
    expect(screen.getByTestId("migration-publish-diagnostics-shell")).toHaveClass("migration-diagnostics-shell");
    expect(screen.getByTestId("migration-deploy-diagnostics-shell")).toHaveClass("migration-diagnostics-shell");
    expect(screen.getByTestId("migration-draft-diagnostics-shell")).toHaveClass("migration-diagnostics-shell");

    const providerDetails = screen.getByTestId("migration-provider-execution-details");
    expect(providerDetails).not.toHaveAttribute("open");
    await user.click(within(providerDetails).getByText("Show provider execution details"));
    expect(providerDetails).toHaveAttribute("open");
    expect(screen.getByTestId("migration-ai-execution-metadata")).toBeVisible();

    await user.click(screen.getByText("Show media diagnostics"));
    expect(screen.getByTestId("migration-media-diagnostics")).toHaveTextContent("image_fetch_failed");

    const destinationDetails = screen.getByTestId("migration-destination-secondary-details");
    expect(destinationDetails).not.toHaveAttribute("open");
    await user.click(within(destinationDetails).getByText("Show full destination diagnostics"));
    expect(destinationDetails).toHaveAttribute("open");
    expect(screen.getByTestId("migration-destination-config-diagnostics")).toBeVisible();
  });

  it("renders loading migration workspace state safely when operator context is still loading", () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ loading: true }));
    render(<SiteMigrationWorkflowPage />);

    expect(screen.getByText("Loading migration workspace")).toBeInTheDocument();
    expect(screen.queryByTestId("migration-workspace-panel")).not.toBeInTheDocument();
  });

  it("handles null/empty migration workspace payloads without crashing", async () => {
    const baseSummary = buildMigrationWorkspaceSummary();
    const baseContextSummary = baseSummary.context_summary as Record<string, unknown>;
    mockFetchMigrationWorkspaceSummary.mockResolvedValueOnce(
      buildMigrationWorkspaceSummary({
        workspace: buildMigrationWorkspace({
          source_url: "",
          source_site_status: "not_ingested",
          latest_generated_artifact_version_id: null,
          latest_generated_artifact_version_number: null,
          latest_approved_artifact_version_id: null,
          latest_approved_artifact_version_number: null,
          publish_config_json: null,
          deploy_config_json: null,
        }),
        source_snapshot: null,
        latest_artifact: null,
        context_summary: {
          ...baseContextSummary,
          draft_input_summary: {},
          migration_diagnostics: {},
          media_assets: {
            source_discovered_count: 0,
            source_imported_count: 0,
            operator_uploaded_count: 0,
            selected_assets_count: 0,
            media_asset_categories: [],
            selected_assets_trimmed: false,
            diagnostics: [],
            source_discovered: [],
            operator_uploaded: [],
            selected_assets: [],
          },
        },
      }),
    );
    mockFetchMigrationArtifactVersions.mockResolvedValueOnce({ items: [], total: 0 });

    render(<SiteMigrationWorkflowPage />);

    expect(await screen.findByTestId("migration-workspace-panel")).toBeInTheDocument();
    expect(screen.getByTestId("migration-source-summary-empty-state")).toBeInTheDocument();
    expect(screen.getByTestId("migration-artifact-review-empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("migration-artifact-quality-empty-state")).not.toBeInTheDocument();
  });

  it("renders advanced diagnostics and history with collapsible publish/deploy history panels", async () => {
    const user = userEvent.setup();
    render(<SiteMigrationWorkflowPage />);

    expect(await screen.findByRole("heading", { name: "Advanced Diagnostics & History" })).toBeInTheDocument();
    await user.click(screen.getByText("Show detailed migration failure diagnostics"));
    expect(screen.getByText("Show publish history")).toBeInTheDocument();
    expect(screen.getByText("Show deploy history")).toBeInTheDocument();

    await user.click(screen.getByText("Show publish history"));
    expect(await screen.findByTestId("migration-publish-history")).toBeInTheDocument();

    await user.click(screen.getByText("Show deploy history"));
    expect(await screen.findByTestId("migration-deploy-history")).toBeInTheDocument();
    expect(screen.getByTestId("migration-publish-history-shell")).toHaveAttribute("open");
    expect(screen.getByTestId("migration-deploy-history-shell")).toHaveAttribute("open");

    const deployDiagnosticsShell = screen.getByTestId("migration-deploy-diagnostics-shell");
    expect(within(deployDiagnosticsShell).getByTestId("migration-deploy-consistency-shell")).toHaveClass(
      "migration-diagnostics-shell",
    );
  });
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
    last_audit_completed_at: "2026-03-21T00:32:00Z",
    ...overrides,
  };
}

function buildBusinessSettings(overrides: Partial<BusinessSettings> = {}): BusinessSettings {
  return {
    id: "biz-1",
    name: "Biz 1",
    notification_phone: "+13035550199",
    notification_email: "owner@example.com",
    sms_enabled: true,
    email_enabled: true,
    customer_auto_ack_enabled: true,
    contractor_alerts_enabled: true,
    seo_audit_crawl_max_pages: 25,
    competitor_candidate_min_relevance_score: 35,
    competitor_candidate_big_box_penalty: 20,
    competitor_candidate_directory_penalty: 35,
    competitor_candidate_local_alignment_bonus: 10,
    competitor_primary_timeout_seconds: null,
    competitor_degraded_timeout_seconds: null,
    migration_draft_timeout_seconds: null,
    ai_prompt_text_competitor: null,
    ai_prompt_text_recommendations: null,
    default_ai_model: null,
    timezone: "America/Denver",
    created_at: "2026-03-20T00:00:00Z",
    updated_at: "2026-03-21T00:00:00Z",
    ...overrides,
  };
}

function buildCompetitorProfileGenerationRun(
  overrides: Partial<CompetitorProfileGenerationRun> = {},
): CompetitorProfileGenerationRun {
  return {
    id: "gen-run-default",
    business_id: "biz-1",
    site_id: "site-1",
    parent_run_id: null,
    status: "completed",
    requested_candidate_count: 5,
    generated_draft_count: 0,
    provider_name: "mock",
    model_name: "mock-seo-competitor-profile-v1",
    prompt_version: "seo-competitor-profile-v1",
    failure_category: null,
    error_summary: null,
    completed_at: "2026-03-21T01:00:00Z",
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:59:00Z",
    updated_at: "2026-03-21T01:00:00Z",
    ...overrides,
  };
}

function buildRecommendation(
  overrides: Partial<Recommendation> = {},
  options: { source?: string } = {},
): Recommendation & { source?: string } {
  const recommendation: Recommendation & { source?: string } = {
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
    priority_rationale: "Priority rationale default for operator triage.",
    evidence_strength: "moderate",
    why_now: "Why now default guidance for operator review.",
    next_action: "Open the target page and apply the first deterministic change.",
    eeat_categories: [],
    primary_eeat_category: null,
    decision_reason: null,
    created_at: "2026-03-21T00:30:00Z",
    updated_at: "2026-03-21T00:31:00Z",
    ...overrides,
    ...(options.source ? { source: options.source } : {}),
  };
  return recommendation;
}

function buildRecommendationNarrative(
  overrides: Partial<RecommendationNarrative> = {},
): RecommendationNarrative {
  return {
    id: "narrative-1",
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    version: 2,
    status: "completed",
    narrative_text: "Narrative for run 1.",
    top_themes_json: ["titles"],
    sections_json: { summary: "AI summary for this run." },
    provider_name: "provider",
    model_name: "model",
    prompt_version: "v2",
    error_message: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:33:00Z",
    updated_at: "2026-03-21T00:33:00Z",
    ...overrides,
  };
}

function buildAIPromptPreview(
  overrides: Partial<AIPromptPreview> = {},
): AIPromptPreview {
  return {
    available: true,
    prompt_type: "recommendation",
    system_prompt: "SYSTEM_PROMPT_TEXT",
    user_prompt: "USER_PROMPT_TEXT",
    model: "gpt-4o-mini",
    prompt_version: "v2",
    truncated: false,
    ...overrides,
  };
}

function buildRecommendationAnalysisFreshness(
  overrides: Partial<RecommendationAnalysisFreshness> = {},
): RecommendationAnalysisFreshness {
  return {
    status: "fresh",
    analysis_generated_at: "2026-03-21T00:30:00Z",
    last_apply_at: null,
    message: "Analysis is up to date with the latest applied changes.",
    ...overrides,
  };
}

function buildRecommendationWorkspaceSummary(
  overrides: Partial<RecommendationWorkspaceSummaryResponse> = {},
): RecommendationWorkspaceSummaryResponse {
  const latestRun = {
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
    started_at: "2026-03-21T00:29:00Z",
    completed_at: "2026-03-21T00:30:00Z",
    duration_ms: 60000,
    error_summary: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:29:00Z",
    updated_at: "2026-03-21T00:30:00Z",
  };
  return {
    business_id: "biz-1",
    site_id: "site-1",
    state: "completed_with_narrative",
    latest_run: latestRun,
    latest_completed_run: latestRun,
    recommendations: {
      items: [buildRecommendation()],
      total: 1,
    },
    latest_narrative: buildRecommendationNarrative(),
    tuning_suggestions: [],
    ...overrides,
  };
}

function buildGoogleBusinessProfileConnection(
  overrides: Partial<GoogleBusinessProfileConnectionStatusResponse> = {},
): GoogleBusinessProfileConnectionStatusResponse {
  return {
    provider: "google_business_profile",
    connected: true,
    business_id: "biz-1",
    granted_scopes: ["https://www.googleapis.com/auth/business.manage"],
    refresh_token_present: true,
    expires_at: "2026-03-21T03:00:00Z",
    connected_at: "2026-03-21T00:30:00Z",
    last_refreshed_at: "2026-03-21T01:00:00Z",
    reconnect_required: false,
    required_scopes_satisfied: true,
    token_status: "usable",
    ga4_scope_granted: false,
    required_ga4_scope: "https://www.googleapis.com/auth/analytics.readonly",
    ...overrides,
  };
}

function buildSiteAnalyticsSummary(
  overrides: Partial<SiteAnalyticsSummaryResponse> = {},
): SiteAnalyticsSummaryResponse {
  return {
    business_id: "biz-1",
    site_id: "site-1",
    available: true,
    status: "ok",
    ga4_status: "connected",
    ga4_error_reason: null,
    ga4_last_successful_fetch_at: "2026-03-21T17:30:00Z",
    ga4_last_data_timestamp: "2026-03-21T16:00:00Z",
    ga4_data_freshness_status: "fresh",
    ga4_health: {
      ga4_configured: true,
      ga4_property_id_present: true,
      ga4_property_verified: true,
      ga4_reachable: true,
      ga4_data_available: true,
      ga4_last_checked_at: "2026-03-21T17:30:00Z",
      ga4_health_status: "reachable",
      ga4_health_reason: null,
      ga4_health_message: "GA4 is available for recommendation context.",
      ga4_health_source: "site_property",
      ga4_scope_granted: null,
      ga4_required_scope: "https://www.googleapis.com/auth/analytics.readonly",
      ga4_auth_mode: "service_account",
    },
    ga4_insights: {
      status: "available",
      source: "site_property",
      date_range_label: "Last 7 days vs previous 7 days",
      checked_at: "2026-03-21T17:30:00Z",
      top_landing_pages: [
        {
          path: "/",
          title: "Home",
          sessions: 140,
          active_users: 112,
          views: 210,
          engagement_rate: 0.58,
          average_engagement_time_seconds: 76,
          trend_label: "improving",
          operator_hint: "Engagement looks healthy. Preserve this page during future migration or content changes.",
        },
      ],
      traffic_trend: {
        current_sessions: 310,
        previous_sessions: 280,
        sessions_delta_percent: 10.7,
        current_active_users: 220,
        previous_active_users: 200,
        active_users_delta_percent: 10,
        trend_label: "improving",
        operator_hint: "Traffic improved versus the prior period. Preserve winning pages while refining weaker pages.",
      },
      engagement_trend: {
        current_engagement_rate: 0.58,
        previous_engagement_rate: 0.54,
        engagement_rate_delta_percent: 7.4,
        current_average_engagement_time_seconds: 76,
        previous_average_engagement_time_seconds: 71,
        trend_label: "improving",
        operator_hint: "Engagement improved versus the prior period. Keep these content patterns in future updates.",
      },
      message: "GA4 insights are available for this site.",
    },
    ga4_acquisition_insights: {
      status: "available",
      source: "site_scoped_ga4",
      lookback_days: 7,
      top_channels: [
        {
          channel_group: "Organic Search",
          sessions: 180,
          users: 150,
          engagement_rate: 0.58,
        },
      ],
      top_sources: [
        {
          source: "google",
          medium: "organic",
          sessions: 172,
          users: 145,
        },
      ],
      organic_search_summary: {
        sessions: 180,
        share_percent: 58.1,
        trend_direction: "improving",
      },
      referral_summary: {
        sessions: 24,
        top_referrers: ["yelp.com"],
      },
      direct_summary: {
        sessions: 102,
        share_percent: 32.9,
      },
      paid_summary: {
        detected: false,
        sessions: 0,
      },
      operator_hints: [
        "Organic search is the largest traffic channel; protect SEO changes on high-traffic landing pages.",
      ],
      message: "GA4 acquisition insights are available for this site.",
    },
    message: null,
    data_source: "ga4_mock",
    site_metrics_summary: {
      current_period_start: "2026-03-15",
      current_period_end: "2026-03-21",
      previous_period_start: "2026-03-08",
      previous_period_end: "2026-03-14",
      users: {
        current: 220,
        previous: 200,
        delta_absolute: 20,
        delta_percent: 10,
      },
      sessions: {
        current: 310,
        previous: 280,
        delta_absolute: 30,
        delta_percent: 10.7,
      },
      pageviews: {
        current: 560,
        previous: 520,
        delta_absolute: 40,
        delta_percent: 7.7,
      },
      organic_search_sessions: {
        current: 180,
        previous: 170,
        delta_absolute: 10,
        delta_percent: 5.9,
      },
    },
    top_pages_summary: [
      {
        page_path: "/",
        pageviews: 140,
        sessions: 100,
        pageviews_previous: 120,
        sessions_previous: 90,
        pageviews_delta_absolute: 20,
        sessions_delta_absolute: 10,
        pageviews_delta_percent: 16.7,
        sessions_delta_percent: 11.1,
      },
    ],
    ...overrides,
  };
}

function buildGA4OnboardingStatus(
  overrides: Partial<GA4SiteOnboardingStatusResponse> = {},
): GA4SiteOnboardingStatusResponse {
  return {
    business_id: "biz-1",
    site_id: "site-1",
    ga4_onboarding_status: "not_connected",
    ga4_account_id: null,
    ga4_property_id: null,
    ga4_data_stream_id: null,
    ga4_measurement_id: null,
    account_discovery_available: false,
    discovered_account_count: 0,
    auto_provisioning_eligible: false,
    message: "Google Analytics onboarding is not connected for this site yet.",
    ...overrides,
  };
}

function buildSearchConsoleSiteSummary(
  overrides: Partial<SearchConsoleSiteSummaryResponse> = {},
): SearchConsoleSiteSummaryResponse {
  return {
    business_id: "biz-1",
    site_id: "site-1",
    available: true,
    status: "ok",
    sc_last_successful_fetch_at: "2026-03-21T17:45:00Z",
    sc_last_data_timestamp: "2026-03-21T15:00:00Z",
    sc_data_freshness_status: "fresh",
    message: null,
    data_source: "search_console_mock",
    site_metrics_summary: {
      current_period_start: "2026-03-15",
      current_period_end: "2026-03-21",
      previous_period_start: "2026-03-08",
      previous_period_end: "2026-03-14",
      clicks: {
        current: 140,
        previous: 120,
        delta_absolute: 20,
        delta_percent: 16.7,
      },
      impressions: {
        current: 4100,
        previous: 3600,
        delta_absolute: 500,
        delta_percent: 13.9,
      },
      ctr_current: 3.41,
      ctr_previous: 3.33,
      ctr_delta_absolute: 0.08,
      average_position_current: 9.2,
      average_position_previous: 9.8,
      average_position_delta_absolute: -0.6,
    },
    top_pages_summary: [
      {
        page_path: "/",
        clicks: 55,
        clicks_previous: 44,
        clicks_delta_absolute: 11,
        clicks_delta_percent: 25,
        impressions: 1900,
        impressions_previous: 1650,
        impressions_delta_absolute: 250,
        impressions_delta_percent: 15.2,
        ctr: 2.89,
        ctr_previous: 2.67,
        ctr_delta_absolute: 0.22,
        average_position: 8.8,
        average_position_previous: 9.5,
        average_position_delta_absolute: -0.7,
      },
    ],
    top_queries_summary: [
      {
        query: "plumbing services denver",
        clicks: 22,
        impressions: 420,
        ctr: 5.24,
        average_position: 7.3,
      },
    ],
    ...overrides,
  };
}

function buildMigrationWorkspace(overrides: Partial<MigrationWorkspace> = {}): MigrationWorkspace {
  return {
    id: "migration-workspace-1",
    business_id: "biz-1",
    site_id: "site-1",
    source_url: "https://legacy.example/",
    source_site_status: "not_ingested",
    migration_status: "draft",
    operator_requirements_json: {},
    enriched_content_notes_json: {},
    brand_business_facts_snapshot_json: {},
    imported_source_snapshot_json: {},
    latest_generated_artifact_version_id: null,
    latest_generated_artifact_version_number: null,
    latest_approved_artifact_version_id: null,
    latest_approved_artifact_version_number: null,
    publish_config_json: null,
    deploy_config_json: null,
    analytics_config_json: null,
    publish_status: "not_ready",
    deploy_status: "not_ready",
    last_published_artifact_version_id: null,
    last_published_artifact_version_number: null,
    last_published_commit_sha: null,
    last_published_at: null,
    last_published_by_principal_id: null,
    last_deployed_artifact_version_id: null,
    last_deployed_artifact_version_number: null,
    last_deployed_at: null,
    last_deployed_by_principal_id: null,
    publish_history_json: [],
    deploy_history_json: [],
    created_by_principal_id: "principal-1",
    updated_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:00:00Z",
    updated_at: "2026-03-21T00:00:00Z",
    ...overrides,
  };
}

function buildMigrationArtifactVersion(
  overrides: Partial<MigrationArtifactVersion> = {},
): MigrationArtifactVersion {
  const artifactQualityEvaluation = {
    quality_status: "high",
    operator_summary: "High quality draft: core sections and grounding signals are present.",
    issues: [],
    signals: {
      has_business_name: true,
      has_location: true,
      has_service_mentions: true,
      placeholder_detected: false,
      missing_sections: [],
    },
  };
  return {
    id: "migration-artifact-1",
    business_id: "biz-1",
    site_id: "site-1",
    workspace_id: "migration-workspace-1",
    version: 1,
    status: "completed",
    strategy_summary: "Draft migration strategy summary.",
    page_map_json: [{ path: "/", title: "Homepage" }],
    homepage_structure_json: [],
    service_page_suggestions_json: [],
    cta_contact_structure_json: {},
    seo_meta_suggestions_json: {},
    redirect_suggestions_json: [],
    analytics_placeholders_json: [],
    generated_files_json: [
      {
        path: "index.html",
        media_type: "text/html",
        content: "<html><head><!-- ANALYTICS_PLACEHOLDER --></head><body>Draft</body></html>",
        size_bytes: 78,
      },
      {
        path: "styles.css",
        media_type: "text/css",
        content: "body { color: #111; }",
        size_bytes: 20,
      },
    ],
    artifact_quality_evaluation: artifactQualityEvaluation,
    artifact_quality_evaluation_json: artifactQualityEvaluation,
    file_count: 2,
    total_bytes: 98,
    provider_name: "mock",
    model_name: "mock-seo-migration-v1",
    prompt_version: "seo-migration-v1",
    parse_warnings_json: [],
    error_summary: null,
    approval_status: "pending",
    approved_by_principal_id: null,
    approved_at: null,
    approval_notes: null,
    publish_status: "not_published",
    deploy_status: "not_deployed",
    last_published_commit_sha: null,
    last_published_at: null,
    last_publish_error_summary: null,
    last_deployed_at: null,
    last_deploy_error_summary: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:00:00Z",
    updated_at: "2026-03-21T00:00:00Z",
    ...overrides,
  };
}

function buildMigrationWorkspaceSummary(
  overrides: Partial<MigrationWorkspaceSummary> = {},
): MigrationWorkspaceSummary {
  const artifact = buildMigrationArtifactVersion();
  return {
    workspace: buildMigrationWorkspace({
      latest_generated_artifact_version_id: artifact.id,
      latest_generated_artifact_version_number: artifact.version,
      source_site_status: "ingested",
      migration_status: "draft_generated",
      operator_requirements_json: {
        business_objectives: ["Replace weak source content"],
      },
      enriched_content_notes_json: {
        replacement_summary: "Enriched replacement content.",
      },
    }),
    source_snapshot: {
      fetched_at: "2026-03-21T00:00:00Z",
      final_url: "https://legacy.example/",
      status_code: 200,
      content_type: "text/html",
      title: "Legacy Site",
      meta_description: "Legacy brochure description",
      canonical_url: "https://legacy.example/",
      headings: ["Legacy heading"],
      contact_signals: ["Call for quote"],
      phone_numbers: ["+13035550100"],
      emails: ["info@legacy.example"],
      addresses: ["123 Main Street"],
      internal_links: ["https://legacy.example/services"],
      service_blocks: ["Installation and inspection"],
      pages_scanned_count: 1,
      pages_scanned: ["https://legacy.example/"],
      asset_references: { stylesheets: [], scripts: [], images: [] },
      discovered_images: [],
      cleaned_text_blocks: ["Legacy content block"],
      warnings: [],
    },
    context_summary: {
      has_source_snapshot: true,
      has_operator_requirements: true,
      has_enriched_content_notes: true,
      has_audit_summary: true,
      has_recommendation_summary: true,
      has_competitor_summary: true,
      draft_generation_readiness: {
        status: "ready",
        score: 100,
        hard_blocked: false,
        summary: "Ready to generate draft.",
        reasons: [],
        signals: {
          source_site_ingested: true,
          operator_requirements_present: true,
          enriched_content_present: true,
          audit_available: true,
          recommendations_available: true,
          competitors_available: true,
          draft_provider_configured: true,
        },
      },
      reused_context: {
        audit: {
          available: true,
          source: "latest_successful_run",
          run_id: "audit-run-1",
          timestamp: "2026-03-21T00:00:00Z",
        },
        recommendations: {
          available: true,
          source: "latest_generated",
          run_id: "recommendation-run-1",
          timestamp: "2026-03-21T00:01:00Z",
          count: 1,
        },
        competitors: {
          available: true,
          source: "latest_run",
          run_id: "comparison-run-1",
          timestamp: "2026-03-21T00:02:00Z",
          count: 1,
        },
      },
      existing_context_summaries: {
        audit_summary: { id: "audit-summary-1", overall_health_summary: "Audit summary context." },
        recommendation_summary: { id: "recommendation-summary-1", narrative_text: "Recommendation context." },
        competitor_summary: { id: "competitor-summary-1", overall_gap_summary: "Competitor context." },
      },
    },
    latest_artifact: artifact,
    publish_readiness: {
      ready: false,
      reasons: ["Publish target is not enabled."],
      target: {},
    },
          deploy_readiness: {
            ready: false,
            reasons: ["Deploy target is not enabled."],
            target: {
              enabled: false,
              repo_owner: "mhanson13",
              repo_name: "tnmfire",
              workflow_id: "deploy-tnmfire-www-prod.yml",
              ref: "main",
              deploy_workflow_mode: "site_repo_template_v1",
              target_environment_key: "gke_prod",
              target_environment_source: "admin_config",
              site_workflow_file_path: ".github/workflows/deploy-tnmfire-www-prod.yml",
            },
          },
    publish_history: [],
    deploy_history: [],
    draft_only_notice: "Draft artifacts only. Not published and not deployed.",
    ...overrides,
  };
}

function buildMigrationDraftReadinessPreflight(
  overrides: Partial<MigrationDraftReadinessPreflight> = {},
): MigrationDraftReadinessPreflight {
  return {
    ready: true,
    blocking_reason_codes: [],
    warning_reason_codes: [],
    app_auth_ready: true,
    google_integration_ready: null,
    google_reconnect_required: false,
    live_google_data_required: false,
    draft_context_ready: true,
    recommendations_available_count: 1,
    competitor_profiles_available_count: 1,
    selected_media_assets_count: 0,
    source_site_images_discovered_count: 0,
    media_required_by_operator: false,
    media_requirement_sources: [],
    usable_media_assets_count: 0,
    useful_discovered_images_count: 0,
    low_value_discovered_images_count: 0,
    rejected_discovered_images_count: 0,
    selected_usable_media_assets_count: 0,
    media_requirement_satisfied: true,
    media_requirement_warning_reason: null,
    operator_action: "Ready to generate draft.",
    ...overrides,
  };
}

function buildMigrationArtifactFilePreview(
  overrides: Partial<MigrationArtifactFilePreview> = {},
): MigrationArtifactFilePreview {
  return {
    artifact_version_id: "migration-artifact-1",
    path: "index.html",
    media_type: "text/html",
    content: "<html><head><!-- ANALYTICS_PLACEHOLDER --></head><body>Draft</body></html>",
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

function seedCompetitorProfileGenerationDefaults(): void {
  mockFetchBusinessSettings.mockResolvedValue(buildBusinessSettings());
  mockFetchGoogleBusinessProfileConnection.mockResolvedValue(
    buildGoogleBusinessProfileConnection({
      connected: false,
      refresh_token_present: false,
      expires_at: null,
      connected_at: null,
      last_refreshed_at: null,
      required_scopes_satisfied: false,
      token_status: "reconnect_required",
    }),
  );
  mockUpdateBusinessSettings.mockReset();
  mockUpdateSite.mockResolvedValue(
    buildSite({
      primary_location: "Serving area around ZIP code 80538",
      primary_business_zip: "80538",
    }),
  );
  mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({ items: [], total: 0 });
  mockFetchCompetitorProfileGenerationRunDetail.mockReset();
  mockFetchAutomationRuns.mockResolvedValue({ items: [], total: 0 });
  mockFetchSiteAnalyticsSummary.mockResolvedValue(
    buildSiteAnalyticsSummary({
      available: false,
      status: "not_configured",
      message: "Google Analytics is not configured for this workspace.",
      data_source: null,
      site_metrics_summary: null,
      top_pages_summary: [],
    }),
  );
  mockFetchGA4SiteOnboardingStatus.mockResolvedValue(
    buildGA4OnboardingStatus({
      ga4_onboarding_status: "not_connected",
      account_discovery_available: false,
      discovered_account_count: 0,
      auto_provisioning_eligible: false,
      message: "Google Analytics onboarding discovery is not configured for this workspace.",
    }),
  );
  mockFetchSearchConsoleSiteSummary.mockResolvedValue(
    buildSearchConsoleSiteSummary({
      available: false,
      status: "not_configured",
      message: "Search Console is not configured for this workspace.",
      data_source: null,
      site_metrics_summary: null,
      top_pages_summary: [],
      top_queries_summary: [],
    }),
  );
  mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    state: "no_runs",
    latest_run: null,
    latest_completed_run: null,
    recommendations: { items: [], total: 0 },
    latest_narrative: null,
    tuning_suggestions: [],
  });
  mockFetchCompetitorProfileGenerationSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    lookback_days: 30,
    window_start: "2026-02-20T00:00:00Z",
    window_end: "2026-03-21T00:00:00Z",
    queued_count: 0,
    running_count: 0,
    completed_count: 0,
    failed_count: 0,
    retry_child_runs: 0,
    retried_parent_runs: 0,
    failed_runs_retried: 0,
    failure_category_counts: {},
    total_runs: 0,
    total_raw_candidate_count: 0,
    total_included_candidate_count: 0,
    total_excluded_candidate_count: 0,
    exclusion_counts_by_reason: {
      duplicate: 0,
      low_relevance: 0,
      directory_or_aggregator: 0,
      big_box_mismatch: 0,
      existing_domain_match: 0,
      invalid_candidate: 0,
    },
    latest_run_created_at: null,
    latest_run_completed_at: null,
    latest_completed_run_completed_at: null,
    latest_failed_run_completed_at: null,
  });
  mockCreateCompetitorProfileGenerationRun.mockReset();
  mockRetryCompetitorProfileGenerationRun.mockReset();
  mockAcceptCompetitorProfileDraft.mockReset();
  mockRejectCompetitorProfileDraft.mockReset();
  mockEditCompetitorProfileDraft.mockReset();
  mockBindActionExecutionItemAutomation.mockReset();
  mockRunActionExecutionItemAutomation.mockReset();
  mockBindActionExecutionItemAutomation.mockResolvedValue({
    action_execution_item_id: "activated-lineage-1",
    automation_binding_state: "bound",
    bound_automation_id: "automation-config-1",
    automation_bound_at: "2026-03-21T02:00:00Z",
    automation_ready: true,
    automation_template_key: "performance_check_followup",
  });
  mockRunActionExecutionItemAutomation.mockResolvedValue({
    action_execution_item_id: "activated-lineage-1",
    automation_binding_state: "bound",
    bound_automation_id: "automation-config-1",
    automation_bound_at: "2026-03-21T02:00:00Z",
    automation_execution_state: "requested",
    automation_execution_requested_at: "2026-03-21T02:05:00Z",
    last_automation_run_id: "automation-run-workspace-1",
    automation_last_executed_at: null,
    automation_ready: true,
    automation_template_key: "performance_check_followup",
  });
  const defaultMigrationWorkspace = buildMigrationWorkspace();
  const defaultMigrationArtifact = buildMigrationArtifactVersion();
  mockUpsertMigrationWorkspace.mockReset();
  mockFetchMigrationWorkspaceSummary.mockReset();
  mockFetchMigrationArtifactVersions.mockReset();
  mockFetchMigrationArtifactFilePreview.mockReset();
  mockIngestMigrationSource.mockReset();
  mockUpdateMigrationRequirements.mockReset();
  mockSuggestMigrationRequirementField.mockReset();
  mockUpdateMigrationEnrichedContent.mockReset();
  mockUpdateMigrationPublishConfig.mockReset();
  mockUpdateMigrationDeployConfig.mockReset();
  mockUpdateMigrationAnalyticsConfig.mockReset();
  mockDeleteMigrationArtifactVersion.mockReset();
  mockApproveMigrationArtifactVersion.mockReset();
  mockPublishMigrationArtifactVersion.mockReset();
  mockAdoptMigrationPublishRepository.mockReset();
  mockDeployMigrationArtifactVersion.mockReset();
  mockRefreshMigrationDeployStatus.mockReset();
  mockFetchMigrationPublishHistory.mockReset();
  mockFetchMigrationDeployHistory.mockReset();
  mockGenerateMigrationDraftArtifacts.mockReset();
  mockFetchMigrationDraftReadiness.mockReset();
  mockFetchMigrationMediaAssets.mockReset();
  mockUploadMigrationMediaAsset.mockReset();
  mockImportMigrationDiscoveredMediaAssets.mockReset();
  mockUpdateMigrationMediaAsset.mockReset();
  mockUpdateMigrationMediaAssetLifecycle.mockReset();
  mockSuggestMigrationMediaAssetMetadata.mockReset();
  mockSuggestMigrationMediaAssetsMetadataBatch.mockReset();
  mockUpsertMigrationWorkspace.mockResolvedValue(defaultMigrationWorkspace);
  mockFetchMigrationWorkspaceSummary.mockResolvedValue(
    buildMigrationWorkspaceSummary({
      workspace: {
        ...defaultMigrationWorkspace,
        latest_generated_artifact_version_id: defaultMigrationArtifact.id,
        latest_generated_artifact_version_number: defaultMigrationArtifact.version,
      },
      latest_artifact: defaultMigrationArtifact,
    }),
  );
  mockFetchMigrationArtifactVersions.mockResolvedValue({
    items: [defaultMigrationArtifact],
    total: 1,
  });
  mockFetchMigrationArtifactFilePreview.mockResolvedValue(
    buildMigrationArtifactFilePreview({ artifact_version_id: defaultMigrationArtifact.id }),
  );
  mockFetchMigrationPublishHistory.mockResolvedValue({ items: [], total: 0 });
  mockFetchMigrationDeployHistory.mockResolvedValue({ items: [], total: 0 });
  mockFetchMigrationDraftReadiness.mockResolvedValue(buildMigrationDraftReadinessPreflight());
  mockFetchMigrationMediaAssets.mockResolvedValue({});
  mockImportMigrationDiscoveredMediaAssets.mockResolvedValue({
    batch_status: "completed",
    imported_count: 0,
    failed_count: 0,
    skipped_count: 0,
    disabled_count: 0,
    results: [],
  });
  mockSuggestMigrationMediaAssetsMetadataBatch.mockResolvedValue({
    batch_status: "completed",
    completed_count: 1,
    failed_count: 0,
    skipped_count: 0,
    results: [
      {
        asset_id: "upl-1",
        suggestion_status: "completed",
        reason_code: "image_metadata_suggested",
        retryable: false,
      },
    ],
  });
  mockUpdateMigrationMediaAssetLifecycle.mockResolvedValue({
    asset_id: "upl-1",
    status: "removed",
    reason_code: "removed",
  });
  mockIngestMigrationSource.mockResolvedValue({
    ...defaultMigrationWorkspace,
    source_site_status: "ingested",
    migration_status: "source_ingested",
  });
  mockUpdateMigrationRequirements.mockResolvedValue({
    ...defaultMigrationWorkspace,
    migration_status: "requirements_captured",
  });
  mockSuggestMigrationRequirementField.mockResolvedValue({
    field: "business_objectives",
    suggestion_status: "completed",
    suggested_value: ["Clarify local service differentiation."],
    reason_code: "requirements_suggestion_completed",
    context_sources_used: ["source_snapshot", "operator_requirements"],
    retryable: false,
    generated_at: "2026-03-21T00:00:00Z",
  });
  mockUpdateMigrationEnrichedContent.mockResolvedValue({
    ...defaultMigrationWorkspace,
    migration_status: "enriched_content_captured",
  });
  mockUpdateMigrationPublishConfig.mockResolvedValue(defaultMigrationWorkspace);
  mockUpdateMigrationDeployConfig.mockResolvedValue(defaultMigrationWorkspace);
  mockUpdateMigrationAnalyticsConfig.mockResolvedValue(defaultMigrationWorkspace);
  mockDeleteMigrationArtifactVersion.mockResolvedValue({
    workspace: defaultMigrationWorkspace,
    deleted_artifact_version_id: defaultMigrationArtifact.id,
    deleted_artifact_version_number: defaultMigrationArtifact.version,
  });
  mockApproveMigrationArtifactVersion.mockResolvedValue(
    buildMigrationArtifactVersion({
      approval_status: "approved",
      approved_by_principal_id: "principal-1",
      approved_at: "2026-03-21T00:10:00Z",
    }),
  );
  mockPublishMigrationArtifactVersion.mockResolvedValue({
    workspace: buildMigrationWorkspace({
      publish_status: "published",
      migration_status: "published_to_github",
      last_published_artifact_version_id: defaultMigrationArtifact.id,
      last_published_artifact_version_number: defaultMigrationArtifact.version,
      last_published_commit_sha: "abc123",
      last_published_at: "2026-03-21T00:12:00Z",
      latest_approved_artifact_version_id: defaultMigrationArtifact.id,
      latest_approved_artifact_version_number: defaultMigrationArtifact.version,
    }),
    artifact: buildMigrationArtifactVersion({
      id: defaultMigrationArtifact.id,
      approval_status: "approved",
      publish_status: "published",
      last_published_commit_sha: "abc123",
      last_published_at: "2026-03-21T00:12:00Z",
    }),
    readiness: { ready: true, reasons: [] },
    result: { status: "published" },
  });
  mockAdoptMigrationPublishRepository.mockResolvedValue({
    workspace: defaultMigrationWorkspace,
    readiness: { ready: true, reasons: [] },
    result: {
      marker_written: true,
      adoption_outcome: "marker_written",
      reason_code: "github_repo_management_marker_written",
    },
  });
  mockDeployMigrationArtifactVersion.mockResolvedValue({
    workspace: buildMigrationWorkspace({
      deploy_status: "deploy_requested",
      migration_status: "deploy_requested",
      last_deployed_artifact_version_id: defaultMigrationArtifact.id,
      last_deployed_artifact_version_number: defaultMigrationArtifact.version,
      last_deployed_at: "2026-03-21T00:14:00Z",
      latest_approved_artifact_version_id: defaultMigrationArtifact.id,
      latest_approved_artifact_version_number: defaultMigrationArtifact.version,
    }),
    artifact: buildMigrationArtifactVersion({
      id: defaultMigrationArtifact.id,
      approval_status: "approved",
      publish_status: "published",
      deploy_status: "deploy_requested",
      last_deployed_at: "2026-03-21T00:14:00Z",
    }),
    readiness: { ready: true, reasons: [] },
    result: { status: "deploy_requested" },
  });
  mockRefreshMigrationDeployStatus.mockResolvedValue({
    workspace: buildMigrationWorkspace({
      deploy_status: "deploy_requested",
      migration_status: "deploy_requested",
      last_deployed_artifact_version_id: defaultMigrationArtifact.id,
      last_deployed_artifact_version_number: defaultMigrationArtifact.version,
      last_deployed_at: "2026-03-21T00:14:00Z",
      latest_approved_artifact_version_id: defaultMigrationArtifact.id,
      latest_approved_artifact_version_number: defaultMigrationArtifact.version,
    }),
    artifact: buildMigrationArtifactVersion({
      id: defaultMigrationArtifact.id,
      approval_status: "approved",
      publish_status: "published",
      deploy_status: "deploy_requested",
      last_deployed_at: "2026-03-21T00:14:00Z",
    }),
    readiness: { ready: true, reasons: [] },
    result: {
      action: "deploy_status_refresh",
      status: "no_change",
      no_change_reason: "workflow_run_in_progress",
      workflow_run_status: "in_progress",
      workflow_run_conclusion: null,
      resolved_live_url: null,
      url_source: "unknown",
      url_source_detail: null,
    },
  });
  mockGenerateMigrationDraftArtifacts.mockResolvedValue(defaultMigrationArtifact);
  mockUploadMigrationMediaAsset.mockResolvedValue({
    asset_id: "upload-1",
    display_filename: "uploaded.jpg",
    provenance: "operator_upload",
    selected_for_draft: true,
  });
  mockUpdateMigrationMediaAsset.mockResolvedValue({
    asset_id: "upload-1",
    display_filename: "uploaded.jpg",
    provenance: "operator_upload",
    selected_for_draft: true,
  });
  mockSuggestMigrationMediaAssetMetadata.mockResolvedValue({
    asset_id: "upload-1",
    display_filename: "uploaded.jpg",
    provenance: "operator_upload",
    selected_for_draft: true,
    metadata_suggestion: {
      suggestion_status: "completed",
      reason_code: "image_metadata_suggested",
      suggested_alt_text: "Suggested alt text",
      suggested_category: "project_gallery",
    },
  });
}

function seedRichWorkspaceData(): void {
  mockFetchSearchConsoleSiteSummary.mockResolvedValue(
    buildSearchConsoleSiteSummary({
      available: false,
      status: "not_configured",
      message: "Search Console is not configured for this workspace.",
      data_source: null,
      site_metrics_summary: null,
      top_pages_summary: [],
      top_queries_summary: [],
    }),
  );
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
        created_at: "2026-03-21T00:31:00Z",
        updated_at: "2026-03-21T00:32:00Z",
        started_at: "2026-03-21T00:31:30Z",
        completed_at: "2026-03-21T00:32:00Z",
        crawl_duration_ms: 30000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 25,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-2",
        business_id: "biz-1",
        site_id: "site-1",
        status: "failed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:08:00Z",
        updated_at: "2026-03-21T00:09:00Z",
        started_at: "2026-03-21T00:08:20Z",
        completed_at: "2026-03-21T00:09:00Z",
        crawl_duration_ms: 40000,
        error_summary: "crawl failed",
        created_by_principal_id: "principal-1",
        pages_crawled: 18,
        pages_skipped: 2,
        duplicate_urls_skipped: 0,
        errors_encountered: 3,
      },
      {
        id: "audit-3",
        business_id: "biz-1",
        site_id: "site-1",
        status: "running",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 10,
        created_at: "2026-03-21T00:07:00Z",
        updated_at: "2026-03-21T00:08:00Z",
        started_at: "2026-03-21T00:08:00Z",
        completed_at: null,
        crawl_duration_ms: null,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 5,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-4",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:06:00Z",
        updated_at: "2026-03-21T00:07:00Z",
        started_at: "2026-03-21T00:06:10Z",
        completed_at: "2026-03-21T00:07:00Z",
        crawl_duration_ms: 50000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-5",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:05:00Z",
        updated_at: "2026-03-21T00:06:00Z",
        started_at: "2026-03-21T00:05:10Z",
        completed_at: "2026-03-21T00:06:00Z",
        crawl_duration_ms: 50000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-6",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:04:00Z",
        updated_at: "2026-03-21T00:05:00Z",
        started_at: "2026-03-21T00:04:20Z",
        completed_at: "2026-03-21T00:05:00Z",
        crawl_duration_ms: 40000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-7",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:03:00Z",
        updated_at: "2026-03-21T00:04:00Z",
        started_at: "2026-03-21T00:03:20Z",
        completed_at: "2026-03-21T00:04:00Z",
        crawl_duration_ms: 40000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-8",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:02:00Z",
        updated_at: "2026-03-21T00:03:00Z",
        started_at: "2026-03-21T00:02:20Z",
        completed_at: "2026-03-21T00:03:00Z",
        crawl_duration_ms: 40000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
    ],
    total: 8,
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
        started_at: "2026-03-21T00:19:00Z",
        completed_at: "2026-03-21T00:20:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:19:00Z",
        updated_at: "2026-03-21T00:20:00Z",
      },
      {
        id: "snapshot-2",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-1",
        status: "failed",
        max_domains: 10,
        max_pages_per_domain: 2,
        max_depth: 1,
        same_domain_only: true,
        domains_targeted: 1,
        domains_completed: 0,
        pages_attempted: 1,
        pages_captured: 0,
        pages_skipped: 0,
        errors_encountered: 1,
        started_at: "2026-03-21T00:17:00Z",
        completed_at: "2026-03-21T00:18:00Z",
        duration_ms: 60000,
        error_summary: "snapshot failed",
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:17:00Z",
        updated_at: "2026-03-21T00:18:00Z",
      },
      {
        id: "snapshot-3",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-1",
        status: "running",
        max_domains: 10,
        max_pages_per_domain: 2,
        max_depth: 1,
        same_domain_only: true,
        domains_targeted: 1,
        domains_completed: 0,
        pages_attempted: 0,
        pages_captured: 0,
        pages_skipped: 0,
        errors_encountered: 0,
        started_at: "2026-03-21T00:17:00Z",
        completed_at: null,
        duration_ms: null,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:16:00Z",
        updated_at: "2026-03-21T00:17:00Z",
      },
    ],
    total: 3,
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
        started_at: "2026-03-21T00:24:00Z",
        completed_at: "2026-03-21T00:25:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:24:00Z",
        updated_at: "2026-03-21T00:25:00Z",
      },
      {
        id: "comparison-2",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        snapshot_run_id: "snapshot-2",
        baseline_audit_run_id: "audit-1",
        status: "failed",
        total_findings: 0,
        critical_findings: 0,
        warning_findings: 0,
        info_findings: 0,
        client_pages_analyzed: 0,
        competitor_pages_analyzed: 0,
        finding_type_counts_json: {},
        category_counts_json: {},
        severity_counts_json: {},
        started_at: "2026-03-21T00:21:00Z",
        completed_at: "2026-03-21T00:22:00Z",
        duration_ms: 60000,
        error_summary: "comparison failed",
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:21:00Z",
        updated_at: "2026-03-21T00:22:00Z",
      },
    ],
    total: 2,
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
        eeat_categories: [],
        primary_eeat_category: null,
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
        total_recommendations: 4,
        critical_recommendations: 1,
        warning_recommendations: 2,
        info_recommendations: 1,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      {
        id: "run-2",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "open",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:27:00Z",
        completed_at: null,
        duration_ms: null,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:27:00Z",
        updated_at: "2026-03-21T00:27:00Z",
      },
      {
        id: "run-3",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-2",
        status: "failed",
        total_recommendations: 0,
        critical_recommendations: 0,
        warning_recommendations: 0,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:26:00Z",
        completed_at: "2026-03-21T00:26:30Z",
        duration_ms: 30000,
        error_summary: "run failed",
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:26:00Z",
        updated_at: "2026-03-21T00:26:30Z",
      },
    ],
    total: 3,
  });

  mockFetchAutomationRuns.mockResolvedValue({
    items: [
      {
        id: "automation-run-1",
        business_id: "biz-1",
        site_id: "site-1",
        automation_config_id: "automation-config-1",
        trigger_source: "scheduled",
        status: "completed",
        started_at: "2026-03-21T00:28:00Z",
        finished_at: "2026-03-21T00:30:00Z",
        error_message: null,
        steps_json: [
          {
            step_name: "recommendation_run",
            status: "completed",
            started_at: "2026-03-21T00:29:00Z",
            finished_at: "2026-03-21T00:29:45Z",
            linked_output_id: "run-1",
            error_message: null,
          },
          {
            step_name: "recommendation_narrative",
            status: "completed",
            started_at: "2026-03-21T00:29:45Z",
            finished_at: "2026-03-21T00:30:00Z",
            linked_output_id: "narrative-1",
            error_message: null,
          },
        ],
        created_at: "2026-03-21T00:28:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
    ],
    total: 1,
  });

  const narrativesByRunId: Record<string, RecommendationNarrative> = {
    "run-1": {
      id: "narrative-1",
      business_id: "biz-1",
      site_id: "site-1",
      recommendation_run_id: "run-1",
      version: 2,
      status: "completed",
      narrative_text: "Narrative for run 1.",
      top_themes_json: ["titles"],
      sections_json: { summary: "one" },
      provider_name: "provider",
      model_name: "model",
      prompt_version: "v1",
      error_message: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:33:00Z",
      updated_at: "2026-03-21T00:33:00Z",
    },
    "run-2": {
      id: "narrative-2",
      business_id: "biz-1",
      site_id: "site-1",
      recommendation_run_id: "run-2",
      version: 1,
      status: "failed",
      narrative_text: null,
      top_themes_json: [],
      sections_json: null,
      provider_name: "provider",
      model_name: "model",
      prompt_version: "v1",
      error_message: "provider failed",
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:31:00Z",
      updated_at: "2026-03-21T00:31:00Z",
    },
    "run-3": {
      id: "narrative-3",
      business_id: "biz-1",
      site_id: "site-1",
      recommendation_run_id: "run-3",
      version: 1,
      status: "completed",
      narrative_text: "Narrative for run 3.",
      top_themes_json: ["technical"],
      sections_json: { summary: "three" },
      provider_name: "provider",
      model_name: "model",
      prompt_version: "v1",
      error_message: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:29:30Z",
      updated_at: "2026-03-21T00:29:30Z",
    },
  };

  mockFetchLatestRecommendationRunNarrative.mockImplementation((...args: unknown[]) => {
    const runId = String(args[3] || "");
    const narrative = narrativesByRunId[runId];
    if (!narrative) {
      return Promise.reject(new Error(`Unexpected run id: ${runId}`));
    }
    return Promise.resolve(narrative);
  });

  mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    state: "completed_with_narrative",
    latest_run: {
      id: "run-1",
      business_id: "biz-1",
      site_id: "site-1",
      audit_run_id: "audit-1",
      comparison_run_id: "comparison-1",
      status: "completed",
      total_recommendations: 4,
      critical_recommendations: 1,
      warning_recommendations: 2,
      info_recommendations: 1,
      category_counts_json: {},
      effort_bucket_counts_json: {},
      started_at: "2026-03-21T00:29:00Z",
      completed_at: "2026-03-21T00:30:00Z",
      duration_ms: 60000,
      error_summary: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:29:00Z",
      updated_at: "2026-03-21T00:30:00Z",
    },
    latest_completed_run: {
      id: "run-1",
      business_id: "biz-1",
      site_id: "site-1",
      audit_run_id: "audit-1",
      comparison_run_id: "comparison-1",
      status: "completed",
      total_recommendations: 4,
      critical_recommendations: 1,
      warning_recommendations: 2,
      info_recommendations: 1,
      category_counts_json: {},
      effort_bucket_counts_json: {},
      started_at: "2026-03-21T00:29:00Z",
      completed_at: "2026-03-21T00:30:00Z",
      duration_ms: 60000,
      error_summary: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:29:00Z",
      updated_at: "2026-03-21T00:30:00Z",
    },
    recommendations: {
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
          eeat_categories: [],
          primary_eeat_category: null,
          decision_reason: null,
          created_at: "2026-03-21T00:30:00Z",
          updated_at: "2026-03-21T00:31:00Z",
        },
      ],
      total: 1,
      by_status: { open: 1 },
      by_category: { SEO: 1 },
      by_severity: { warning: 1 },
      by_effort_bucket: { small: 1 },
      by_priority_band: { high: 1 },
    },
    latest_narrative: narrativesByRunId["run-1"],
    tuning_suggestions: [],
  });
}

function seedGroupedTimelineWorkspaceData(): void {
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
        created_at: "2026-03-21T10:30:00Z",
        updated_at: "2026-03-21T11:00:00Z",
        started_at: "2026-03-21T10:45:00Z",
        completed_at: "2026-03-21T11:00:00Z",
        crawl_duration_ms: 900000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 25,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-2",
        business_id: "biz-1",
        site_id: "site-1",
        status: "failed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 12,
        created_at: "2026-03-21T08:45:00Z",
        updated_at: "2026-03-21T09:00:00Z",
        started_at: "2026-03-21T08:50:00Z",
        completed_at: "2026-03-21T09:00:00Z",
        crawl_duration_ms: 600000,
        error_summary: "crawl failed",
        created_by_principal_id: "principal-1",
        pages_crawled: 10,
        pages_skipped: 2,
        duplicate_urls_skipped: 0,
        errors_encountered: 1,
      },
      {
        id: "audit-3",
        business_id: "biz-1",
        site_id: "site-1",
        status: "running",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 8,
        created_at: "2026-03-21T07:30:00Z",
        updated_at: "2026-03-21T08:00:00Z",
        started_at: "2026-03-21T08:00:00Z",
        completed_at: null,
        crawl_duration_ms: null,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 4,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-4",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T06:45:00Z",
        updated_at: "2026-03-21T07:00:00Z",
        started_at: "2026-03-21T06:50:00Z",
        completed_at: "2026-03-21T07:00:00Z",
        crawl_duration_ms: 600000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-5",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 18,
        created_at: "2026-03-20T21:30:00Z",
        updated_at: "2026-03-20T22:00:00Z",
        started_at: "2026-03-20T21:40:00Z",
        completed_at: "2026-03-20T22:00:00Z",
        crawl_duration_ms: 1200000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 18,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-6",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 16,
        created_at: "2026-03-20T20:30:00Z",
        updated_at: "2026-03-20T21:00:00Z",
        started_at: "2026-03-20T20:45:00Z",
        completed_at: "2026-03-20T21:00:00Z",
        crawl_duration_ms: 900000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 16,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-7",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 14,
        created_at: "2026-03-20T19:45:00Z",
        updated_at: "2026-03-20T20:00:00Z",
        started_at: "2026-03-20T19:50:00Z",
        completed_at: "2026-03-20T20:00:00Z",
        crawl_duration_ms: 600000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 14,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-8",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 10,
        created_at: "2026-03-18T11:45:00Z",
        updated_at: "2026-03-18T12:00:00Z",
        started_at: "2026-03-18T11:50:00Z",
        completed_at: "2026-03-18T12:00:00Z",
        crawl_duration_ms: 600000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 10,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
    ],
    total: 8,
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
        started_at: "2026-03-21T09:50:00Z",
        completed_at: "2026-03-21T10:00:00Z",
        duration_ms: 600000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T09:50:00Z",
        updated_at: "2026-03-21T10:00:00Z",
      },
      {
        id: "snapshot-2",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-5",
        status: "failed",
        max_domains: 10,
        max_pages_per_domain: 2,
        max_depth: 1,
        same_domain_only: true,
        domains_targeted: 1,
        domains_completed: 0,
        pages_attempted: 1,
        pages_captured: 0,
        pages_skipped: 0,
        errors_encountered: 1,
        started_at: "2026-03-20T22:30:00Z",
        completed_at: "2026-03-20T23:00:00Z",
        duration_ms: 1800000,
        error_summary: "snapshot failed",
        created_by_principal_id: "principal-1",
        created_at: "2026-03-20T22:30:00Z",
        updated_at: "2026-03-20T23:00:00Z",
      },
      {
        id: "snapshot-3",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-7",
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
        started_at: "2026-03-20T18:30:00Z",
        completed_at: "2026-03-20T19:00:00Z",
        duration_ms: 1800000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-20T18:30:00Z",
        updated_at: "2026-03-20T19:00:00Z",
      },
    ],
    total: 3,
  });

  mockFetchSiteCompetitorComparisonRuns.mockResolvedValue({
    items: [],
    total: 0,
  });

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
  mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    state: "no_runs",
    latest_run: null,
    latest_completed_run: null,
    recommendations: { items: [], total: 0 },
    latest_narrative: null,
    tuning_suggestions: [],
  });

  mockFetchRecommendationRuns.mockResolvedValue({
    items: [],
    total: 0,
  });

  mockFetchLatestRecommendationRunNarrative.mockReset();
}

function seedCompetitorProfileGenerationWorkspaceData(): void {
  seedRichWorkspaceData();

  const run = buildCompetitorProfileGenerationRun({
    id: "gen-run-1",
    status: "completed",
    generated_draft_count: 2,
  });

  const draftOne: CompetitorProfileDraft = {
    id: "draft-1",
    business_id: "biz-1",
    site_id: "site-1",
    generation_run_id: "gen-run-1",
    suggested_name: "Example Alternatives",
    suggested_domain: "example-alternatives.com",
    competitor_type: "direct",
    summary: "Direct overlap in service intent.",
    why_competitor: "Competes for service keywords.",
    evidence: "Heuristic evidence",
    confidence_score: 0.82,
    source: "ai_generated",
    review_status: "pending",
    edited_fields_json: null,
    review_notes: null,
    reviewed_by_principal_id: null,
    reviewed_at: null,
    accepted_competitor_set_id: null,
    accepted_competitor_domain_id: null,
    created_at: "2026-03-21T01:00:00Z",
    updated_at: "2026-03-21T01:00:00Z",
  };

  const draftTwo: CompetitorProfileDraft = {
    id: "draft-2",
    business_id: "biz-1",
    site_id: "site-1",
    generation_run_id: "gen-run-1",
    suggested_name: "Example Marketplace",
    suggested_domain: "example-marketplace.com",
    competitor_type: "marketplace",
    summary: "Marketplace competitor for discovery-stage traffic.",
    why_competitor: "Marketplace terms overlap",
    evidence: "SERP pattern overlap",
    confidence_score: 0.66,
    source: "ai_generated",
    review_status: "pending",
    edited_fields_json: null,
    review_notes: null,
    reviewed_by_principal_id: null,
    reviewed_at: null,
    accepted_competitor_set_id: null,
    accepted_competitor_domain_id: null,
    created_at: "2026-03-21T01:00:00Z",
    updated_at: "2026-03-21T01:00:00Z",
  };

  mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
    items: [run],
    total: 1,
  });
  mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
    run,
    drafts: [draftOne, draftTwo],
    total_drafts: 2,
  });
  mockFetchCompetitorProfileGenerationSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    lookback_days: 30,
    window_start: "2026-02-20T00:00:00Z",
    window_end: "2026-03-21T00:00:00Z",
    queued_count: 0,
    running_count: 0,
    completed_count: 1,
    failed_count: 0,
    retry_child_runs: 0,
    retried_parent_runs: 0,
    failed_runs_retried: 0,
    failure_category_counts: {},
    total_runs: 1,
    total_raw_candidate_count: 2,
    total_included_candidate_count: 2,
    total_excluded_candidate_count: 0,
    exclusion_counts_by_reason: {
      duplicate: 0,
      low_relevance: 0,
      directory_or_aggregator: 0,
      big_box_mismatch: 0,
      existing_domain_match: 0,
      invalid_candidate: 0,
    },
    latest_run_created_at: "2026-03-21T00:59:00Z",
    latest_run_completed_at: "2026-03-21T01:00:00Z",
    latest_completed_run_completed_at: "2026-03-21T01:00:00Z",
    latest_failed_run_completed_at: null,
  });
  mockCreateCompetitorProfileGenerationRun.mockResolvedValue({
    run: buildCompetitorProfileGenerationRun({
      ...run,
      id: "gen-run-2",
      status: "queued",
      created_at: "2026-03-21T01:15:00Z",
      completed_at: null,
      updated_at: "2026-03-21T01:15:00Z",
    }),
    drafts: [],
    total_drafts: 0,
  });
  mockRetryCompetitorProfileGenerationRun.mockResolvedValue({
    run: buildCompetitorProfileGenerationRun({
      ...run,
      id: "gen-run-3",
      parent_run_id: "gen-run-1",
      status: "queued",
      created_at: "2026-03-21T01:16:00Z",
      completed_at: null,
      updated_at: "2026-03-21T01:16:00Z",
    }),
    drafts: [],
    total_drafts: 0,
  });
  mockAcceptCompetitorProfileDraft.mockResolvedValue({
    ...draftOne,
    review_status: "accepted",
    accepted_competitor_set_id: "set-1",
    accepted_competitor_domain_id: "domain-new-1",
    reviewed_by_principal_id: "principal-1",
    reviewed_at: "2026-03-21T01:20:00Z",
  });
  mockRejectCompetitorProfileDraft.mockResolvedValue({
    ...draftTwo,
    review_status: "rejected",
    reviewed_by_principal_id: "principal-1",
    reviewed_at: "2026-03-21T01:21:00Z",
    review_notes: "Not relevant",
  });
  mockEditCompetitorProfileDraft.mockResolvedValue({
    ...draftOne,
    suggested_name: "Edited Competitor Name",
    review_status: "edited",
    edited_fields_json: { suggested_name: "Edited Competitor Name" },
    reviewed_by_principal_id: "principal-1",
    reviewed_at: "2026-03-21T01:22:00Z",
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(Date, "now").mockReturnValue(FIXED_NOW_MS);
  window.sessionStorage.clear();
  navigationState.params = { site_id: "site-1" };
  mockUseOperatorContext.mockReturnValue(baseContext());
  seedCompetitorProfileGenerationDefaults();
});

afterEach(() => {
  jest.restoreAllMocks();
});

async function switchToActivityTab(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const activityTab = await screen.findByRole("tab", { name: "Activity" });
  if (activityTab.getAttribute("aria-selected") !== "true") {
    await user.click(activityTab);
  }
  await waitFor(() => expect(activityTab).toHaveAttribute("aria-selected", "true"));
}


