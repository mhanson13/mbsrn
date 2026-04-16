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
  MigrationDeployActionResponse,
  MigrationHistoryListResponse,
  MigrationPublishActionResponse,
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
const mockUpdateMigrationEnrichedContent = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockUpdateMigrationPublishConfig = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockUpdateMigrationDeployConfig = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockUpdateMigrationAnalyticsConfig = jest.fn<Promise<MigrationWorkspace>, unknown[]>();
const mockDeleteMigrationArtifactVersion = jest.fn<Promise<MigrationArtifactDeleteActionResponse>, unknown[]>();
const mockApproveMigrationArtifactVersion = jest.fn<Promise<MigrationArtifactVersion>, unknown[]>();
const mockPublishMigrationArtifactVersion = jest.fn<Promise<MigrationPublishActionResponse>, unknown[]>();
const mockDeployMigrationArtifactVersion = jest.fn<Promise<MigrationDeployActionResponse>, unknown[]>();
const mockRefreshMigrationDeployStatus = jest.fn<Promise<MigrationDeployActionResponse>, unknown[]>();
const mockFetchMigrationPublishHistory = jest.fn<Promise<MigrationHistoryListResponse>, unknown[]>();
const mockFetchMigrationDeployHistory = jest.fn<Promise<MigrationHistoryListResponse>, unknown[]>();
const mockGenerateMigrationDraftArtifacts = jest.fn<Promise<MigrationArtifactVersion>, unknown[]>();

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
    updateMigrationEnrichedContent: (...args: unknown[]) => mockUpdateMigrationEnrichedContent(...args),
    updateMigrationPublishConfig: (...args: unknown[]) => mockUpdateMigrationPublishConfig(...args),
    updateMigrationDeployConfig: (...args: unknown[]) => mockUpdateMigrationDeployConfig(...args),
    updateMigrationAnalyticsConfig: (...args: unknown[]) => mockUpdateMigrationAnalyticsConfig(...args),
    deleteMigrationArtifactVersion: (...args: unknown[]) => mockDeleteMigrationArtifactVersion(...args),
    approveMigrationArtifactVersion: (...args: unknown[]) => mockApproveMigrationArtifactVersion(...args),
    publishMigrationArtifactVersion: (...args: unknown[]) => mockPublishMigrationArtifactVersion(...args),
    deployMigrationArtifactVersion: (...args: unknown[]) => mockDeployMigrationArtifactVersion(...args),
    refreshMigrationDeployStatus: (...args: unknown[]) => mockRefreshMigrationDeployStatus(...args),
    fetchMigrationPublishHistory: (...args: unknown[]) => mockFetchMigrationPublishHistory(...args),
    fetchMigrationDeployHistory: (...args: unknown[]) => mockFetchMigrationDeployHistory(...args),
    generateMigrationDraftArtifacts: (...args: unknown[]) => mockGenerateMigrationDraftArtifacts(...args),
  };
});

describe("site workspace modernized structure", () => {
  it("keeps recommendations and activity tabs while removing embedded migration/operator-focus tabs", async () => {
    render(<SiteWorkspacePage />);

    expect(await screen.findByRole("tab", { name: "Recommendations" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Activity" })).toBeInTheDocument();
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

  it("removes GA4 connect controls from the site workspace and points profile actions to Google Profile", async () => {
    render(<SiteWorkspacePage />);

    expect(screen.queryByTestId("workspace-ga4-connect-panel")).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Open Google Profile" })).toHaveAttribute("href", "/google-profile");
  });

  it("does not load embedded migration workspace APIs on the main site workspace route", async () => {
    render(<SiteWorkspacePage />);

    await screen.findByRole("tab", { name: "Recommendations" });
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
            "<html><head><title>Artifact One Home</title></head><body><a href=\"about.html\">About</a></body></html>",
          size_bytes: 100,
        },
        {
          path: "about.html",
          media_type: "text/html",
          content: "<html><head><title>Artifact One About</title></head><body>About Draft</body></html>",
          size_bytes: 80,
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
    const pageSelect = await screen.findByTestId("migration-draft-preview-page-select");
    const previewFrame = screen.getByTestId("migration-draft-preview-iframe");
    expect(previewFrame).toHaveAttribute("srcDoc", expect.stringContaining("Artifact One Home"));

    await user.selectOptions(pageSelect, "about.html");
    expect(screen.getByTestId("migration-draft-preview-iframe")).toHaveAttribute(
      "srcDoc",
      expect.stringContaining("About Draft"),
    );

    await user.selectOptions(screen.getByLabelText("Artifact version"), artifactTwo.id);
    await waitFor(() =>
      expect(screen.queryByTestId("migration-draft-preview-iframe")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("migration-preview-draft-button"));
    expect(await screen.findByTestId("migration-draft-preview-iframe")).toHaveAttribute(
      "srcDoc",
      expect.stringContaining("Artifact Two Home"),
    );
  });

  it("keeps draft review actions in Section D and out of publish/deploy controls", async () => {
    render(<SiteMigrationWorkflowPage />);

    const reviewSection = await screen.findByTestId("migration-artifact-review-section");
    expect(within(reviewSection).getByTestId("migration-preview-draft-button")).toBeInTheDocument();
    expect(within(reviewSection).getByTestId("migration-approve-draft-button")).toBeInTheDocument();
    expect(within(reviewSection).getByTestId("migration-delete-draft-button")).toBeInTheDocument();

    const publishDeploySection = screen.getByTestId("migration-publish-deploy-section");
    expect(within(publishDeploySection).queryByTestId("migration-approve-draft-button")).not.toBeInTheDocument();
    expect(within(publishDeploySection).queryByTestId("migration-delete-draft-button")).not.toBeInTheDocument();
  });

  it("renders a combined page and generated-file inspection surface for selected artifacts", async () => {
    const user = userEvent.setup();
    render(<SiteMigrationWorkflowPage />);

    const inspectionSurface = await screen.findByTestId("migration-draft-inspection-surface");
    expect(within(inspectionSurface).getByText("Page & File Inspection")).toBeInTheDocument();
    expect(within(inspectionSurface).getByTestId("migration-page-map-list")).toBeInTheDocument();

    await user.click(within(inspectionSurface).getByRole("button", { name: "index.html" }));
    expect(within(inspectionSurface).getByText("Selected file: index.html")).toBeInTheDocument();
    expect(within(inspectionSurface).getByTestId("migration-file-preview-iframe")).toBeInTheDocument();
  });

  it("consolidates destination metadata labels and removes analytics insertion rules from migration route", async () => {
    render(<SiteMigrationWorkflowPage />);

    const destinationSummary = await screen.findByTestId("migration-destination-summary");
    expect(within(destinationSummary).getByTestId("migration-destination-admin-block")).toBeInTheDocument();
    expect(within(destinationSummary).getByTestId("migration-destination-operator-block")).toBeInTheDocument();
    expect(within(destinationSummary).getByTestId("migration-destination-derived-block")).toBeInTheDocument();
    expect(within(destinationSummary).getByTestId("migration-destination-runtime-block")).toBeInTheDocument();
    expect(within(destinationSummary).getAllByText("Admin-set").length).toBeGreaterThan(0);
    expect(within(destinationSummary).getAllByText("Runtime").length).toBeGreaterThan(0);

    const publishReadiness = screen.getByTestId("migration-publish-readiness");
    const deployReadiness = screen.getByTestId("migration-deploy-readiness");
    expect(within(publishReadiness).queryByText("GitHub account/owner")).not.toBeInTheDocument();
    expect(within(deployReadiness).queryByText("Workflow identifier")).not.toBeInTheDocument();
    expect(within(publishReadiness).queryByText(/Runtime publisher:/i)).not.toBeInTheDocument();
    expect(within(deployReadiness).queryByText(/Runtime publisher:/i)).not.toBeInTheDocument();

    expect(screen.queryByText("Analytics Insertion Rules")).not.toBeInTheDocument();
  });

  it("keeps destination blockers always visible and secondary diagnostics behind disclosure", async () => {
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
    expect(within(destinationSummary).getByTestId("migration-destination-blockers")).toBeInTheDocument();
    expect(within(destinationSummary).getByTestId("migration-destination-publish-failure-category")).toHaveTextContent(
      /Category:\s*config missing/i,
    );
    expect(within(destinationSummary).getByTestId("migration-destination-publish-failure-reason")).toHaveTextContent(
      /Reason:\s*authentication failed/i,
    );
    expect(within(destinationSummary).getByTestId("migration-destination-publish-failure-stage")).toHaveTextContent(
      /Stage:\s*config validation/i,
    );
    expect(within(destinationSummary).getByTestId("migration-destination-deploy-failure-category")).toHaveTextContent(
      /Category:\s*target invalid/i,
    );
    expect(within(destinationSummary).getByTestId("migration-destination-deploy-failure-reason")).toHaveTextContent(
      /Reason:\s*workflow not dispatchable/i,
    );
    expect(within(destinationSummary).getByTestId("migration-destination-deploy-failure-stage")).toHaveTextContent(
      /Stage:\s*workflow lookup/i,
    );
    expect(within(destinationSummary).getByText(/GitHub publish\/deploy authentication failed\./i)).toBeInTheDocument();
    expect(within(destinationSummary).getByText(/GitHub repository or workflow target was not found\./i)).toBeInTheDocument();

    const secondaryDetails = within(destinationSummary).getByTestId("migration-destination-secondary-details");
    expect(secondaryDetails).not.toHaveAttribute("open");

    const collapsedUrlSource = within(destinationSummary).getByText("URL source");
    expect(collapsedUrlSource).not.toBeVisible();
    await user.click(within(destinationSummary).getByText("Show additional destination diagnostics"));
    expect(secondaryDetails).toHaveAttribute("open");
    expect(within(destinationSummary).getByText("Draft entry file")).toBeVisible();
    expect(within(destinationSummary).getByText("URL source")).toBeVisible();
  });

  it("shows operator-set destination labels when repository overrides are configured", async () => {
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
    expect(within(destinationSummary).getAllByText("Operator-set").length).toBeGreaterThan(0);
    expect(within(destinationSummary).getByText("mhanson13/tnmfire")).toBeInTheDocument();
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
      asset_references: { stylesheets: [], scripts: [], images: [] },
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
  mockUpdateMigrationEnrichedContent.mockReset();
  mockUpdateMigrationPublishConfig.mockReset();
  mockUpdateMigrationDeployConfig.mockReset();
  mockUpdateMigrationAnalyticsConfig.mockReset();
  mockDeleteMigrationArtifactVersion.mockReset();
  mockApproveMigrationArtifactVersion.mockReset();
  mockPublishMigrationArtifactVersion.mockReset();
  mockDeployMigrationArtifactVersion.mockReset();
  mockRefreshMigrationDeployStatus.mockReset();
  mockFetchMigrationPublishHistory.mockReset();
  mockFetchMigrationDeployHistory.mockReset();
  mockGenerateMigrationDraftArtifacts.mockReset();
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
  mockIngestMigrationSource.mockResolvedValue({
    ...defaultMigrationWorkspace,
    source_site_status: "ingested",
    migration_status: "source_ingested",
  });
  mockUpdateMigrationRequirements.mockResolvedValue({
    ...defaultMigrationWorkspace,
    migration_status: "requirements_captured",
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


describe("site workspace ai competitor profile drafts", () => {
  function buildDraft(
    id: string,
    name: string,
    domain: string,
    sourceType: CompetitorProfileDraft["source_type"],
    provenanceClassification: CompetitorProfileDraft["provenance_classification"] | undefined = undefined,
  ): CompetitorProfileDraft {
    return {
      id,
      business_id: "biz-1",
      site_id: "site-1",
      generation_run_id: "gen-run-filter-test",
      suggested_name: name,
      suggested_domain: domain,
      competitor_type: "direct",
      summary: `${name} summary`,
      why_competitor: `${name} rationale`,
      evidence: `${name} evidence`,
      confidence_score: 0.72,
      source: "ai_generated",
      source_type: sourceType,
      provenance_classification: provenanceClassification,
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
  }

  it("renders generate control and latest draft review table", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Competitor Profiles" });
    expect(screen.getByRole("button", { name: "Generate Competitor Profiles" })).toBeInTheDocument();
    expect(await screen.findByText(/Latest Run:/i)).toBeInTheDocument();
    const metadataLine = screen.getByText((_, element) => {
      if (!element || element.tagName.toLowerCase() !== "p") {
        return false;
      }
      const text = element.textContent || "";
      return (
        text.includes("Provider:") &&
        text.includes("Model:") &&
        text.includes("Prompt Version:")
      );
    });
    expect(metadataLine).toHaveTextContent(/Provider:\s*mock/);
    expect(metadataLine).toHaveTextContent(/Model:\s*mock-seo-competitor-profile-v1/);
    expect(metadataLine).toHaveTextContent(/Prompt Version:\s*seo-competitor-profile-v1/);
    expect(screen.getByText(/Last 30d: queued 0 \| running 0 \| completed 1 \| failed 0/)).toBeInTheDocument();
    expect(screen.getByText(/Candidate telemetry \(1 runs\): raw 2 \| included 2 \| excluded 0/)).toBeInTheDocument();
    expect(screen.queryByText(/Exclusion reasons:/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("rejected-competitor-candidates-debug")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tuning-rejected-competitor-candidates-debug")).not.toBeInTheDocument();
    expect(screen.queryByTestId("competitor-candidate-pipeline-summary-debug")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("competitor-profile-draft-row")).toHaveLength(2);
    expect(screen.getAllByText(/Why this competitor:/i).length).toBeGreaterThan(0);
    expect(
      screen.queryByText("Expanded search was used after the initial pass returned no usable competitors."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Some competitors were included under relaxed local-service matching rules."),
    ).not.toBeInTheDocument();
    expect(mockFetchCompetitorProfileGenerationRuns).toHaveBeenCalled();
    expect(mockFetchCompetitorProfileGenerationRunDetail).toHaveBeenCalled();
    expect(mockFetchCompetitorProfileGenerationSummary).toHaveBeenCalled();
  });

  it("toggles synthetic scaffold visibility and reports hidden counts", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    const run = buildCompetitorProfileGenerationRun({
      id: "gen-run-filter-test",
      status: "completed",
      generated_draft_count: 6,
    });
    const drafts: CompetitorProfileDraft[] = [
      buildDraft("draft-real-1", "Real Competitor 1", "real-1.example", "places", "places_ai_enriched"),
      buildDraft("draft-real-2", "Real Competitor 2", "real-2.example", "search", "ai_only"),
      buildDraft("draft-real-3", "Real Competitor 3", "real-3.example", "search", "ai_only"),
      buildDraft("draft-real-4", "Real Competitor 4", "real-4.example", "places", "places_ai_enriched"),
      buildDraft("draft-synth-1", "Synthetic Scaffold A", "review-scaffold-1.invalid", "synthetic", "synthetic_fallback"),
      buildDraft("draft-synth-2", "Synthetic Scaffold B", "review-scaffold-2.invalid", "synthetic", "synthetic_fallback"),
    ];

    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({ items: [run], total: 1 });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run,
      drafts,
      total_drafts: drafts.length,
    });

    render(<SiteWorkspacePage />);

    await screen.findAllByTestId("competitor-profile-draft-row");
    const toggle = screen.getByRole("checkbox", { name: "Hide synthetic scaffolds" });
    expect(toggle).not.toBeChecked();
    expect(screen.getAllByTestId("competitor-profile-draft-row")).toHaveLength(6);
    expect(screen.getByText("Synthetic Scaffold A")).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toBeChecked();
    expect(screen.getAllByTestId("competitor-profile-draft-row")).toHaveLength(4);
    expect(screen.queryByText("Synthetic Scaffold A")).not.toBeInTheDocument();
    expect(screen.getByTestId("hidden-synthetic-scaffolds-count")).toHaveTextContent(
      "2 synthetic scaffold rows hidden.",
    );

    await user.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(screen.getAllByTestId("competitor-profile-draft-row")).toHaveLength(6);
    expect(screen.getByText("Synthetic Scaffold A")).toBeInTheDocument();
  });

  it("defaults synthetic scaffold filter on when at least five non-synthetic drafts exist", async () => {
    seedRichWorkspaceData();
    const run = buildCompetitorProfileGenerationRun({
      id: "gen-run-filter-default-on",
      status: "completed",
      generated_draft_count: 6,
    });
    const drafts: CompetitorProfileDraft[] = [
      buildDraft("draft-real-a", "Real Competitor A", "real-a.example", "places", "places_ai_enriched"),
      buildDraft("draft-real-b", "Real Competitor B", "real-b.example", "search", "ai_only"),
      buildDraft("draft-real-c", "Real Competitor C", "real-c.example", "search", "ai_only"),
      buildDraft("draft-real-d", "Real Competitor D", "real-d.example", "places", "places_ai_enriched"),
      buildDraft("draft-real-e", "Real Competitor E", "real-e.example", "search", "ai_only"),
      buildDraft("draft-synth-z", "Synthetic Scaffold Z", "review-scaffold-z.invalid", "synthetic", "synthetic_fallback"),
    ];
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({ items: [run], total: 1 });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run,
      drafts,
      total_drafts: drafts.length,
    });

    render(<SiteWorkspacePage />);

    await screen.findAllByTestId("competitor-profile-draft-row");
    const toggle = screen.getByRole("checkbox", { name: "Hide synthetic scaffolds" });
    expect(toggle).toBeChecked();
    expect(screen.getAllByTestId("competitor-profile-draft-row")).toHaveLength(5);
    expect(screen.queryByText("Synthetic Scaffold Z")).not.toBeInTheDocument();
    expect(screen.getByTestId("hidden-synthetic-scaffolds-count")).toHaveTextContent(
      "1 synthetic scaffold row hidden.",
    );
  });

  it("keeps recommendation trust-tier evidence rendering unchanged when competitor synthetic filter toggles", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        recommendations: {
          items: [
            buildRecommendation({
              id: "rec-linkage-stability",
              title: "Recommendation with linkage trust tiers",
              competitor_linkage_summary: "Mixed competitor evidence is available.",
              competitor_evidence_links: [
                {
                  competitor_draft_id: "draft-verified",
                  competitor_name: "Verified Fire Systems",
                  competitor_domain: "verified-fire.example",
                  confidence_level: "high",
                  source_type: "places",
                  verification_status: "verified",
                  trust_tier: "trusted_verified",
                  evidence_summary: "Strong nearby verified competitor overlap.",
                },
                {
                  competitor_draft_id: "draft-unverified",
                  competitor_name: "Unverified Alarm Co",
                  competitor_domain: "unverified-alarm.example",
                  confidence_level: "medium",
                  source_type: "search",
                  verification_status: "unverified",
                  trust_tier: "informational_unverified",
                  evidence_summary: "Requires operator verification before trusted use.",
                },
              ],
            }),
          ],
          total: 1,
        },
      }),
    );

    const run = buildCompetitorProfileGenerationRun({
      id: "gen-run-filter-and-linkage",
      status: "completed",
      generated_draft_count: 6,
    });
    const drafts: CompetitorProfileDraft[] = [
      buildDraft("draft-r1", "Real One", "real-one.example", "places", "places_ai_enriched"),
      buildDraft("draft-r2", "Real Two", "real-two.example", "search", "ai_only"),
      buildDraft("draft-r3", "Real Three", "real-three.example", "search", "ai_only"),
      buildDraft("draft-r4", "Real Four", "real-four.example", "places", "places_ai_enriched"),
      buildDraft("draft-r5", "Real Five", "real-five.example", "search", "ai_only"),
      buildDraft("draft-s1", "Synthetic One", "review-scaffold-s1.invalid", "synthetic", "synthetic_fallback"),
    ];
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({ items: [run], total: 1 });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run,
      drafts,
      total_drafts: drafts.length,
    });

    render(<SiteWorkspacePage />);

    await screen.findAllByTestId("competitor-profile-draft-row");
    const linkageLine = await screen.findByTestId("recommendation-competitor-linkage");
    expect(linkageLine).toHaveTextContent("Verified competitor");
    expect(linkageLine).toHaveTextContent("Unverified competitor");

    const toggle = screen.getByRole("checkbox", { name: "Hide synthetic scaffolds" });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(screen.getByTestId("recommendation-competitor-linkage")).toHaveTextContent("Verified competitor");
    expect(screen.getByTestId("recommendation-competitor-linkage")).toHaveTextContent("Unverified competitor");
  });

  it("reconstructs the latest completed run on page load and shows drafts without polling state", async () => {
    seedRichWorkspaceData();
    const olderRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-older",
      status: "failed",
      generated_draft_count: 0,
      failure_category: "provider_request",
      error_summary: "Older run failed",
      created_at: "2026-03-21T01:00:00Z",
      updated_at: "2026-03-21T01:01:00Z",
      completed_at: "2026-03-21T01:01:00Z",
    });
    const latestRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-latest",
      status: "completed",
      generated_draft_count: 1,
      created_at: "2026-03-21T02:00:00Z",
      updated_at: "2026-03-21T02:01:00Z",
      completed_at: "2026-03-21T02:01:00Z",
    });
    const latestDraft: CompetitorProfileDraft = {
      id: "draft-latest-1",
      business_id: "biz-1",
      site_id: "site-1",
      generation_run_id: latestRun.id,
      suggested_name: "Reloaded Competitor",
      suggested_domain: "reloaded-competitor.example",
      competitor_type: "direct",
      summary: "Recovered from backend state on load.",
      why_competitor: "Service overlap and local intent.",
      evidence: "Backend detail payload",
      confidence_score: 0.79,
      source: "ai_generated",
      review_status: "pending",
      edited_fields_json: null,
      review_notes: null,
      reviewed_by_principal_id: null,
      reviewed_at: null,
      accepted_competitor_set_id: null,
      accepted_competitor_domain_id: null,
      created_at: "2026-03-21T02:01:00Z",
      updated_at: "2026-03-21T02:01:00Z",
    };
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [olderRun, latestRun],
      total: 2,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: latestRun,
      drafts: [latestDraft],
      total_drafts: 1,
    });

    render(<SiteWorkspacePage />);

    await screen.findAllByTestId("competitor-profile-draft-row");
    expect(screen.getByTestId("competitor-profile-status-strip")).toHaveTextContent("Latest run status");
    expect(mockFetchCompetitorProfileGenerationRunDetail).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      latestRun.id,
    );
    expect(screen.getByText(/Latest Run:/i)).toHaveTextContent("gen-run-latest");
    expect(screen.getByText(/Latest Run:/i)).toHaveTextContent("(completed)");
    expect(screen.queryByText("Generation is in progress for this run.")).not.toBeInTheDocument();
  });

  it("uses terminal run detail as source of truth when run list status is stale", async () => {
    seedRichWorkspaceData();
    const staleRunningRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-stale-status",
      status: "running",
      generated_draft_count: 0,
      completed_at: null,
      created_at: "2026-03-21T02:30:00Z",
      updated_at: "2026-03-21T02:30:00Z",
    });
    const completedDetailRun = buildCompetitorProfileGenerationRun({
      ...staleRunningRun,
      status: "completed",
      generated_draft_count: 1,
      completed_at: "2026-03-21T02:31:00Z",
      updated_at: "2026-03-21T02:31:00Z",
    });
    const completedDraft: CompetitorProfileDraft = {
      id: "draft-stale-resolved-1",
      business_id: "biz-1",
      site_id: "site-1",
      generation_run_id: staleRunningRun.id,
      suggested_name: "Stale State Competitor",
      suggested_domain: "stale-state-competitor.example",
      competitor_type: "direct",
      summary: "Detail endpoint returned completed state.",
      why_competitor: "Same local service intent.",
      evidence: "Run detail",
      confidence_score: 0.73,
      source: "ai_generated",
      review_status: "pending",
      edited_fields_json: null,
      review_notes: null,
      reviewed_by_principal_id: null,
      reviewed_at: null,
      accepted_competitor_set_id: null,
      accepted_competitor_domain_id: null,
      created_at: "2026-03-21T02:31:00Z",
      updated_at: "2026-03-21T02:31:00Z",
    };

    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [staleRunningRun],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: completedDetailRun,
      drafts: [completedDraft],
      total_drafts: 1,
    });

    render(<SiteWorkspacePage />);

    await screen.findAllByTestId("competitor-profile-draft-row");
    expect(screen.getByText(/Latest Run:/i)).toHaveTextContent("(completed)");
    expect(screen.queryByText("Generation is in progress for this run.")).not.toBeInTheDocument();
  });

  it("renders non-zero exclusion reason aggregates in summary", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    mockFetchCompetitorProfileGenerationSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      lookback_days: 30,
      window_start: "2026-02-20T00:00:00Z",
      window_end: "2026-03-21T00:00:00Z",
      queued_count: 0,
      running_count: 0,
      completed_count: 2,
      failed_count: 1,
      retry_child_runs: 0,
      retried_parent_runs: 0,
      failed_runs_retried: 0,
      failure_category_counts: {},
      total_runs: 3,
      total_raw_candidate_count: 8,
      total_included_candidate_count: 2,
      total_excluded_candidate_count: 6,
      preview_accuracy_rate: 0.8,
      avg_error_margin: 1.2,
      last_n_preview_accuracy: {
        window_size: 10,
        sample_size: 5,
        direction_correct_count: 4,
        accuracy_rate: 0.8,
        avg_error_margin: 1.2,
      },
      exclusion_counts_by_reason: {
        duplicate: 1,
        low_relevance: 2,
        directory_or_aggregator: 2,
        big_box_mismatch: 1,
        existing_domain_match: 0,
        invalid_candidate: 0,
      },
      latest_run_created_at: "2026-03-21T00:59:00Z",
      latest_run_completed_at: "2026-03-21T01:00:00Z",
      latest_completed_run_completed_at: "2026-03-21T01:00:00Z",
      latest_failed_run_completed_at: null,
    });

    render(<SiteWorkspacePage />);

    await screen.findByText(/Candidate telemetry \(3 runs\): raw 8 \| included 2 \| excluded 6/);
    expect(
      screen.getByText(/Preview accuracy \(last 5\): 80% directionally correct \| avg error margin 1.2/),
    ).toBeInTheDocument();
    const exclusionChips = screen.getByTestId("competitor-exclusion-reason-chips");
    expect(exclusionChips).toHaveTextContent("big box mismatch 1");
    expect(exclusionChips).toHaveTextContent("directory or aggregator 2");
    expect(exclusionChips).toHaveTextContent("duplicate 1");
    expect(exclusionChips).toHaveTextContent("low relevance 2");
  });

  it("renders rejected competitor candidates debug details when run detail includes deterministic rejections", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    const run = buildCompetitorProfileGenerationRun({
      id: "gen-run-debug-rejections",
      status: "completed",
      generated_draft_count: 1,
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [run],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run,
      drafts: [
        {
          id: "draft-valid",
          business_id: "biz-1",
          site_id: "site-1",
          generation_run_id: run.id,
          suggested_name: "Valid Competitor",
          suggested_domain: "valid-competitor.example",
          competitor_type: "direct",
          summary: "Valid draft summary",
          why_competitor: "Valid rationale",
          evidence: "Valid evidence",
          confidence_score: 0.7,
          source: "ai_generated",
          confidence_level: "high",
          source_type: "places",
          provenance_classification: "places_ai_enriched",
          provenance_explanation:
            "Discovered from nearby business seed data and enriched for service/location fit.",
          operator_evidence_summary: "Ranks as a strong local match from nearby-business discovery.",
          review_status: "pending",
          edited_fields_json: null,
          review_notes: null,
          reviewed_by_principal_id: null,
          reviewed_at: null,
          accepted_competitor_set_id: null,
          accepted_competitor_domain_id: null,
          created_at: "2026-03-21T01:00:00Z",
          updated_at: "2026-03-21T01:00:00Z",
        },
      ],
      total_drafts: 1,
      rejected_candidate_count: 3,
      rejected_candidates: [
        {
          domain: "parked-candidate.com",
          reasons: ["parked_domain"],
          summary: "Unclear overlap.",
        },
        {
          domain: "out-of-market.example",
          reasons: ["out_of_market", "insufficient_overlap_evidence"],
          summary: "Appears to serve a different region.",
        },
      ],
      candidate_pipeline_summary: {
        proposed_candidate_count: 5,
        rejected_by_eligibility_count: 3,
        eligible_candidate_count: 2,
        rejected_by_tuning_count: 1,
        survived_tuning_count: 1,
        removed_by_existing_domain_match_count: 0,
        removed_by_deduplication_count: 0,
        removed_by_final_limit_count: 0,
        final_candidate_count: 1,
        relaxed_filtering_applied: true,
      },
      tuning_rejected_candidate_count: 3,
      tuning_rejected_candidates: [
        {
          domain: "directory.example",
          reasons: ["directory_or_aggregator_penalty"],
          final_score: 42,
          summary: "Directory-heavy listing site.",
        },
        {
          domain: "big-box.example",
          reasons: ["big_box_mismatch_penalty"],
          final_score: 39,
          summary: "National chain mismatch.",
        },
      ],
      tuning_rejection_reason_counts: {
        below_minimum_relevance_score: 1,
        directory_or_aggregator_penalty: 1,
        big_box_mismatch_penalty: 1,
        insufficient_local_alignment: 1,
      },
      provider_attempt_count: 2,
      provider_degraded_retry_used: true,
      provider_attempts: [
        {
          attempt_number: 1,
          execution_mode: "fast_path",
          provider_call_type: "non_tool",
          degraded_mode: false,
          reduced_context_mode: false,
          requested_candidate_count: 5,
          outcome: "timeout",
          failure_kind: "timeout",
          request_duration_ms: 30250,
          timeout_seconds: 30,
          web_search_enabled: true,
          prompt_size_risk: "normal",
          prompt_total_chars: 11200,
          context_json_chars: 4200,
          user_prompt_chars: 10400,
          endpoint_path: "/responses",
          search_escalation_triggered: true,
          escalation_reason: "zero_valid_competitors",
        },
        {
          attempt_number: 2,
          execution_mode: "full",
          provider_call_type: "tool_enabled",
          degraded_mode: true,
          reduced_context_mode: true,
          requested_candidate_count: 3,
          outcome: "success",
          failure_kind: null,
          request_duration_ms: 5400,
          timeout_seconds: 30,
          web_search_enabled: true,
          prompt_size_risk: "normal",
          prompt_total_chars: 8200,
          context_json_chars: 2600,
          user_prompt_chars: 7600,
          endpoint_path: "/responses",
          search_escalation_triggered: false,
          escalation_reason: null,
        },
      ],
      outcome_summary: {
        status_level: "recovered",
        message: "Competitor generation recovered after provider instability.",
        used_synthetic_fallback: false,
        used_timeout_recovery: true,
        had_schema_repair_or_discard: false,
        used_google_places_seeds: true,
      },
      response_contract_summary: {
        status: "accepted_with_warnings",
        summary: "Limited number of strong competitors identified.",
        retryable: false,
      },
      ai_diagnostics_summary: {
        failure_category: "remote_timeout",
        failure_reason: "provider_timeout",
        failure_source: "remote_provider",
        retryable: true,
        hint: "Provider timeout",
        budget_outcome: "trimmed_provider_submission",
        retry_suppressed: false,
        trimming_pass_count: 1,
        difficulty_bucket: "medium",
        input_size_bucket: "medium",
        degraded_state: "degraded",
      },
    });

    render(<SiteWorkspacePage />);

    const debugBlock = await screen.findByTestId("rejected-competitor-candidates-debug");
    expect(within(debugBlock).getByText(/Rejected competitor candidates \(debug\)/i)).toBeInTheDocument();
    expect(within(debugBlock).getByText(/: 3/)).toBeInTheDocument();
    expect(within(debugBlock).getByText("parked-candidate.com")).toBeInTheDocument();
    expect(within(debugBlock).getByText("parked domain")).toBeInTheDocument();
    expect(within(debugBlock).getByText("out of market")).toBeInTheDocument();
    expect(within(debugBlock).getByText("insufficient overlap evidence")).toBeInTheDocument();
    expect(
      within(debugBlock).getByText("Showing 2 of 3 rejected candidates."),
    ).toBeInTheDocument();
    const summaryStrip = screen.getByTestId("competitor-summary-strip");
    expect(summaryStrip).toHaveTextContent("Total candidates 5");
    expect(summaryStrip).toHaveTextContent("Eligible 2");
    expect(summaryStrip).toHaveTextContent("Final returned 1");
    expect(summaryStrip).toHaveTextContent("Excluded 4");
    expect(summaryStrip).toHaveTextContent("Failure count 1");
    expect(summaryStrip).toHaveTextContent("Retry count 1");

    const pipelineDebug = screen.getByTestId("competitor-candidate-pipeline-summary-debug");
    expect(within(pipelineDebug).getByText(/Candidate pipeline/i)).toBeInTheDocument();
    const pipelineTable = within(pipelineDebug).getByTestId("competitor-candidate-pipeline-table");
    expect(within(pipelineTable).getByText("Proposed")).toBeInTheDocument();
    expect(within(pipelineTable).getByText("Rejected by eligibility")).toBeInTheDocument();
    expect(within(pipelineTable).getByText("Eligible")).toBeInTheDocument();
    expect(within(pipelineTable).getByText("Removed by tuning")).toBeInTheDocument();
    expect(within(pipelineTable).getByText("Survived tuning")).toBeInTheDocument();
    expect(within(pipelineTable).getByText("Removed by existing-domain match")).toBeInTheDocument();
    expect(within(pipelineTable).getByText("Removed by deduplication")).toBeInTheDocument();
    expect(within(pipelineTable).getByText("Removed by final limit")).toBeInTheDocument();
    expect(within(pipelineTable).getByText("Final returned")).toBeInTheDocument();
    const draftRows = screen.getAllByTestId("competitor-profile-draft-row");
    expect(draftRows).toHaveLength(1);
    expect(within(draftRows[0]).getByText(/Nearby seed \+ AI enrichment/i)).toBeInTheDocument();
    expect(
      within(draftRows[0]).getByText(/Discovered from nearby business seed data and enriched/i),
    ).toBeInTheDocument();
    expect(within(draftRows[0]).getByTestId("competitor-confidence-source-chips")).toHaveTextContent(
      "High confidence",
    );
    expect(within(draftRows[0]).getByTestId("competitor-confidence-source-chips")).toHaveTextContent("Nearby seed");
    expect(within(draftRows[0]).getByTestId("competitor-operator-evidence-summary")).toHaveTextContent(
      "Evidence signal: Ranks as a strong local match",
    );

    const tuningDebug = screen.getByTestId("tuning-rejected-competitor-candidates-debug");
    expect(within(tuningDebug).getByText(/Removed by tuning \(debug\)/i)).toBeInTheDocument();
    expect(within(tuningDebug).getByText(/: 3/)).toBeInTheDocument();
    expect(within(tuningDebug).getByText("directory.example")).toBeInTheDocument();
    expect(within(tuningDebug).getByText("directory or aggregator penalty")).toBeInTheDocument();
    expect(within(tuningDebug).getByText("big box mismatch penalty")).toBeInTheDocument();
    expect(within(tuningDebug).getByText("Showing 2 of 3 removed-by-tuning candidates.")).toBeInTheDocument();

    const providerAttemptsDebug = screen.getByTestId("competitor-provider-attempts-debug");
    expect(within(providerAttemptsDebug).getByText(/Provider attempts \(debug\)/i)).toBeInTheDocument();
    expect(within(providerAttemptsDebug).getByText(/: 2/)).toBeInTheDocument();
    expect(within(providerAttemptsDebug).getByText("Degraded timeout retry used: yes")).toBeInTheDocument();
    expect(within(providerAttemptsDebug).getByText("degraded_retry")).toBeInTheDocument();
    expect(within(providerAttemptsDebug).getByText("Success")).toBeInTheDocument();
    expect(within(providerAttemptsDebug).getByText("timeout")).toBeInTheDocument();
    expect(within(providerAttemptsDebug).getByText("11,200")).toBeInTheDocument();

    const outcomeSummary = screen.getByTestId("competitor-run-outcome-summary");
    expect(within(outcomeSummary).getByText(/proposed 5 \| returned 1 \| rejected 4/i)).toHaveTextContent(
      "proposed 5 | returned 1 | rejected 4 | degraded mode yes | search-backed yes",
    );
    expect(within(outcomeSummary).getByTestId("competitor-operator-outcome-summary")).toHaveTextContent(
      "Outcome: Recovered. Competitor generation recovered after provider instability.",
    );
    expect(within(outcomeSummary).getByText("Recovered after provider timeout during this run.")).toBeInTheDocument();
    expect(
      within(outcomeSummary).getByText(
        "Nearby business seed discovery was used before AI enrichment in this run.",
      ),
    ).toBeInTheDocument();
    expect(within(outcomeSummary).getByText(/Run notes:/i)).toHaveTextContent("degraded retry mode used");
    expect(within(outcomeSummary).getByText(/Filtering:/i)).toHaveTextContent(
      "Filtering: proposed 5 | filtered out 4 | duplicates removed 0 | final returned 1",
    );
    expect(
      within(outcomeSummary).getByText(
        "Expanded search was used after the initial pass returned no usable competitors.",
      ),
    ).toBeInTheDocument();
    expect(
      within(outcomeSummary).getByText("Some competitors were included under relaxed local-service matching rules."),
    ).toBeInTheDocument();
    expect(within(outcomeSummary).getByTestId("competitor-response-contract-summary")).toHaveTextContent(
      "Quality gate: Accepted with warnings. Results refined for quality. Limited number of strong competitors identified.",
    );
    expect(within(outcomeSummary).getByTestId("competitor-ai-diagnostics-summary")).toHaveTextContent(
      "AI diagnostics: remote_timeout / provider_timeout — Provider timeout (retryable: yes)",
    );
    expect(within(outcomeSummary).getByText(/Only 1 valid competitor remained after filtering\./i)).toHaveTextContent(
      "strict validation filtered weak candidates",
    );
  });

  it("renders search-unavailable low-result guidance from run telemetry", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    const run = buildCompetitorProfileGenerationRun({
      id: "gen-run-search-unavailable",
      status: "completed",
      generated_draft_count: 1,
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [run],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run,
      drafts: [
        {
          id: "draft-valid-only",
          business_id: "biz-1",
          site_id: "site-1",
          generation_run_id: run.id,
          suggested_name: "Valid Candidate",
          suggested_domain: "valid-only.example",
          competitor_type: "direct",
          summary: "Valid summary",
          why_competitor: "Valid rationale",
          evidence: "Valid evidence",
          confidence_score: 0.78,
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
        },
      ],
      total_drafts: 1,
      rejected_candidate_count: 3,
      rejected_candidates: [
        {
          domain: "missing-name.example",
          reasons: ["missing_business_name"],
          summary: "Missing business name.",
        },
        {
          domain: "malformed-domain",
          reasons: ["malformed_url"],
          summary: "Malformed URL.",
        },
      ],
      candidate_pipeline_summary: {
        proposed_candidate_count: 5,
        rejected_by_eligibility_count: 3,
        eligible_candidate_count: 2,
        rejected_by_tuning_count: 1,
        survived_tuning_count: 1,
        removed_by_existing_domain_match_count: 0,
        removed_by_deduplication_count: 0,
        removed_by_final_limit_count: 0,
        final_candidate_count: 1,
      },
      tuning_rejected_candidate_count: 1,
      tuning_rejected_candidates: [
        {
          domain: "directory.example",
          reasons: ["directory_or_aggregator_penalty"],
          final_score: 42,
          summary: "Directory-heavy listing site.",
        },
      ],
      tuning_rejection_reason_counts: {
        below_minimum_relevance_score: 0,
        directory_or_aggregator_penalty: 1,
        big_box_mismatch_penalty: 0,
        insufficient_local_alignment: 0,
      },
      provider_attempt_count: 1,
      provider_degraded_retry_used: false,
      provider_attempts: [
        {
          attempt_number: 1,
          degraded_mode: false,
          reduced_context_mode: false,
          requested_candidate_count: 5,
          outcome: "success",
          failure_kind: null,
          request_duration_ms: 1900,
          timeout_seconds: 30,
          web_search_enabled: false,
          prompt_size_risk: "normal",
          prompt_total_chars: 9800,
          context_json_chars: 3200,
          user_prompt_chars: 8600,
          endpoint_path: "/chat/completions",
        },
      ],
      outcome_summary: {
        status_level: "normal",
        message: "Competitor generation completed normally with provider output.",
        used_synthetic_fallback: false,
        used_timeout_recovery: false,
        had_schema_repair_or_discard: true,
        used_google_places_seeds: false,
      },
    });

    render(<SiteWorkspacePage />);

    const outcomeSummary = await screen.findByTestId("competitor-run-outcome-summary");
    expect(within(outcomeSummary).getByText(/proposed 5 \| returned 1 \| rejected 4/i)).toHaveTextContent(
      "proposed 5 | returned 1 | rejected 4 | degraded mode no | search-backed no",
    );
    expect(within(outcomeSummary).getByText(/Filtering:/i)).toHaveTextContent(
      "Filtering: proposed 5 | filtered out 4 | duplicates removed 0 | final returned 1",
    );
    expect(within(outcomeSummary).getByTestId("competitor-operator-outcome-summary")).toHaveTextContent(
      "Outcome: Normal. Competitor generation completed normally with provider output.",
    );
    expect(
      within(outcomeSummary).getByText(
        "Some malformed provider candidate entries were safely discarded during parsing.",
      ),
    ).toBeInTheDocument();
    expect(within(outcomeSummary).getByText(/Run notes:/i)).toHaveTextContent(
      "search-backed discovery unavailable",
    );
    expect(within(outcomeSummary).getByText(/Only 1 valid competitor remained after filtering\./i)).toHaveTextContent(
      "This may indicate strict validation filtered weak candidates, search-backed discovery was unavailable.",
    );
    expect(
      screen.queryByText("Expanded search was used after the initial pass returned no usable competitors."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Nearby business seed discovery was used before AI enrichment in this run."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Some competitors were included under relaxed local-service matching rules."),
    ).not.toBeInTheDocument();
  });

  it("shows a synthetic fallback indicator when degraded fallback output was used", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    const run = buildCompetitorProfileGenerationRun({
      id: "gen-run-synthetic-fallback",
      status: "completed",
      generated_draft_count: 1,
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [run],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run,
      drafts: [
        {
          id: "draft-fallback-1",
          business_id: "biz-1",
          site_id: "site-1",
          generation_run_id: run.id,
          suggested_name: "Local Service Option 1",
          suggested_domain: "review-scaffold-1.invalid",
          competitor_type: "local",
          summary: "Fallback placeholder generated from local context.",
          why_competitor: "Deterministic fallback output for operator review.",
          evidence: "Synthetic fallback path.",
          confidence_score: 0.28,
          source: "ai_forced_fallback",
          provenance_classification: "synthetic_fallback",
          provenance_explanation:
            "Synthetic review scaffold generated because reliable live competitor discovery was unavailable.",
          review_status: "pending",
          edited_fields_json: null,
          review_notes: null,
          reviewed_by_principal_id: null,
          reviewed_at: null,
          accepted_competitor_set_id: null,
          accepted_competitor_domain_id: null,
          created_at: "2026-03-21T01:00:00Z",
          updated_at: "2026-03-21T01:00:00Z",
        },
      ],
      total_drafts: 1,
      provider_attempt_count: 1,
      provider_degraded_retry_used: true,
      provider_attempts: [
        {
          attempt_number: 2,
          execution_mode: "fallback",
          provider_call_type: "non_tool",
          degraded_mode: true,
          reduced_context_mode: true,
          requested_candidate_count: 5,
          outcome: "success",
          failure_kind: null,
          request_duration_ms: 1600,
          timeout_seconds: 30,
          web_search_enabled: false,
          prompt_size_risk: "normal",
          prompt_total_chars: 7200,
          context_json_chars: 2400,
          user_prompt_chars: 6800,
          endpoint_path: "/chat/completions",
        },
      ],
      outcome_summary: {
        status_level: "degraded",
        message: "Fallback placeholders were generated from local context. Review and confirm before accepting.",
        used_synthetic_fallback: true,
        used_timeout_recovery: false,
        had_schema_repair_or_discard: false,
        used_google_places_seeds: false,
      },
    });

    render(<SiteWorkspacePage />);

    const outcomeSummary = await screen.findByTestId("competitor-run-outcome-summary");
    expect(within(outcomeSummary).getByTestId("competitor-operator-outcome-summary")).toHaveTextContent(
      "Outcome: Degraded (synthetic fallback). Fallback placeholders were generated from local context.",
    );
    const rows = screen.getAllByTestId("competitor-profile-draft-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Source: Synthetic fallback");
    expect(rows[0]).toHaveTextContent("No verified website (review scaffold)");
    expect(rows[0]).toHaveTextContent(
      "Selection basis: Synthetic review scaffold generated because reliable live competitor",
    );
    expect(
      screen.queryByText("Nearby business seed discovery was used before AI enrichment in this run."),
    ).not.toBeInTheDocument();
  });

  it("handles missing per-competitor provenance fields without showing misleading labels", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    const run = buildCompetitorProfileGenerationRun({
      id: "gen-run-no-provenance-fields",
      status: "completed",
      generated_draft_count: 1,
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [run],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run,
      drafts: [
        {
          id: "draft-no-provenance",
          business_id: "biz-1",
          site_id: "site-1",
          generation_run_id: run.id,
          suggested_name: "Legacy Draft Without Provenance",
          suggested_domain: "legacy-no-provenance.example",
          competitor_type: "direct",
          summary: "Legacy summary",
          why_competitor: "Legacy rationale",
          evidence: "Legacy evidence",
          confidence_score: 0.61,
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
        },
      ],
      total_drafts: 1,
      provider_attempt_count: 1,
      provider_degraded_retry_used: false,
      provider_attempts: [
        {
          attempt_number: 1,
          degraded_mode: false,
          reduced_context_mode: false,
          requested_candidate_count: 5,
          outcome: "success",
          failure_kind: null,
          request_duration_ms: 1200,
          timeout_seconds: 30,
          web_search_enabled: false,
          prompt_size_risk: "normal",
          prompt_total_chars: 9000,
          context_json_chars: 3000,
          user_prompt_chars: 7600,
          endpoint_path: "/chat/completions",
        },
      ],
      outcome_summary: {
        status_level: "normal",
        message: "Competitor generation completed normally with provider output.",
        used_synthetic_fallback: false,
        used_timeout_recovery: false,
        had_schema_repair_or_discard: false,
        used_google_places_seeds: false,
      },
    });

    render(<SiteWorkspacePage />);

    const rows = await screen.findAllByTestId("competitor-profile-draft-row");
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).queryByText(/Source:/i)).not.toBeInTheDocument();
    expect(within(rows[0]).queryByText(/Selection basis:/i)).not.toBeInTheDocument();
    expect(within(rows[0]).queryByTestId("competitor-confidence-source-chips")).not.toBeInTheDocument();
  });

  it("triggers generation and refreshes visible drafts", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    const user = userEvent.setup();
    const initialRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-existing",
      status: "completed",
      generated_draft_count: 0,
      completed_at: "2026-03-21T01:00:00Z",
      created_at: "2026-03-21T00:59:00Z",
      updated_at: "2026-03-21T01:00:00Z",
    });
    const queuedRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-new",
      status: "queued",
      generated_draft_count: 0,
      completed_at: null,
      created_at: "2026-03-21T01:15:00Z",
      updated_at: "2026-03-21T01:15:00Z",
    });
    const completedRun = buildCompetitorProfileGenerationRun({
      ...queuedRun,
      status: "completed",
      generated_draft_count: 1,
      completed_at: "2026-03-21T01:16:00Z",
      updated_at: "2026-03-21T01:16:00Z",
    });
    const completedDraft: CompetitorProfileDraft = {
      id: "draft-new-1",
      business_id: "biz-1",
      site_id: "site-1",
      generation_run_id: queuedRun.id,
      suggested_name: "Auto Refreshed Competitor",
      suggested_domain: "auto-refreshed.example",
      competitor_type: "direct",
      summary: "Auto-refreshed summary",
      why_competitor: "Auto-refreshed rationale",
      evidence: "Auto-refreshed evidence",
      confidence_score: 0.81,
      source: "ai_generated",
      review_status: "pending",
      edited_fields_json: null,
      review_notes: null,
      reviewed_by_principal_id: null,
      reviewed_at: null,
      accepted_competitor_set_id: null,
      accepted_competitor_domain_id: null,
      created_at: "2026-03-21T01:16:00Z",
      updated_at: "2026-03-21T01:16:00Z",
    };

    mockCreateCompetitorProfileGenerationRun.mockResolvedValue({
      run: queuedRun,
      drafts: [],
      total_drafts: 0,
    });
    mockFetchCompetitorProfileGenerationRuns
      .mockResolvedValueOnce({ items: [initialRun], total: 1 })
      .mockResolvedValueOnce({ items: [queuedRun], total: 1 })
      .mockResolvedValue({ items: [completedRun], total: 1 });
    mockFetchCompetitorProfileGenerationRunDetail
      .mockResolvedValueOnce({
        run: initialRun,
        drafts: [],
        total_drafts: 0,
      })
      .mockResolvedValueOnce({
        run: queuedRun,
        drafts: [],
        total_drafts: 0,
      })
      .mockResolvedValue({
        run: completedRun,
        drafts: [completedDraft],
        total_drafts: 1,
      });

    render(<SiteWorkspacePage />);

    await screen.findByRole("button", { name: "Generate Competitor Profiles" });
    await user.click(screen.getByRole("button", { name: "Generate Competitor Profiles" }));

    await screen.findByText("Competitor profile generation queued. Drafts will appear after the run completes.");
    expect(mockCreateCompetitorProfileGenerationRun).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      { candidate_count: 10 },
    );
    await waitFor(
      () => {
        expect(
          screen.getByText("Competitor profile generation completed. Results refreshed automatically."),
        ).toBeInTheDocument();
      },
      { timeout: 12000 },
    );
    expect(screen.queryByText("Competitor profile generation queued. Drafts will appear after the run completes.")).not.toBeInTheDocument();
    await waitFor(
      () => {
        expect(screen.getAllByTestId("competitor-profile-draft-row")).toHaveLength(1);
      },
      { timeout: 12000 },
    );
  });

  it("polls queued/running runs and renders drafts after completion", async () => {
    seedRichWorkspaceData();
    const runningRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-async-1",
      status: "running",
      generated_draft_count: 0,
      completed_at: null,
      created_at: "2026-03-21T01:30:00Z",
      updated_at: "2026-03-21T01:30:00Z",
    });
    const completedRun = buildCompetitorProfileGenerationRun({
      ...runningRun,
      status: "completed",
      generated_draft_count: 1,
      completed_at: "2026-03-21T01:31:30Z",
      updated_at: "2026-03-21T01:31:30Z",
    });
    const completedDraft: CompetitorProfileDraft = {
      id: "draft-async-1",
      business_id: "biz-1",
      site_id: "site-1",
      generation_run_id: runningRun.id,
      suggested_name: "Async Competitor",
      suggested_domain: "async-competitor.example",
      competitor_type: "direct",
      summary: "Completed async summary",
      why_competitor: "Completed async rationale",
      evidence: "Completed async evidence",
      confidence_score: 0.74,
      source: "ai_generated",
      review_status: "pending",
      edited_fields_json: null,
      review_notes: null,
      reviewed_by_principal_id: null,
      reviewed_at: null,
      accepted_competitor_set_id: null,
      accepted_competitor_domain_id: null,
      created_at: "2026-03-21T01:31:30Z",
      updated_at: "2026-03-21T01:31:30Z",
    };

    mockFetchCompetitorProfileGenerationRuns
      .mockResolvedValueOnce({ items: [runningRun], total: 1 })
      .mockResolvedValueOnce({ items: [runningRun], total: 1 })
      .mockResolvedValue({ items: [completedRun], total: 1 });
    mockFetchCompetitorProfileGenerationRunDetail
      .mockResolvedValueOnce({
        run: runningRun,
        drafts: [],
        total_drafts: 0,
      })
      .mockResolvedValueOnce({
        run: runningRun,
        drafts: [],
        total_drafts: 0,
      })
      .mockResolvedValue({
        run: completedRun,
        drafts: [completedDraft],
        total_drafts: 1,
      });

    render(<SiteWorkspacePage />);

    await screen.findByText("Generation is in progress for this run.");
    await waitFor(
      () => {
        expect(mockFetchCompetitorProfileGenerationRuns.mock.calls.length).toBeGreaterThanOrEqual(3);
      },
      { timeout: 8000 },
    );
    await waitFor(
      () => {
        expect(screen.getAllByTestId("competitor-profile-draft-row")).toHaveLength(1);
      },
      { timeout: 8000 },
    );
    await waitFor(
      () => {
        expect(screen.queryByText("Generation is in progress for this run.")).not.toBeInTheDocument();
      },
      { timeout: 8000 },
    );
    expect(
      screen.getByText("Competitor profile generation completed. Results refreshed automatically."),
    ).toBeInTheDocument();
  });

  it("accept/reject/edit actions update draft states", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findAllByTestId("competitor-profile-draft-row");
    const firstDraftRow = screen.getAllByTestId("competitor-profile-draft-row")[0];

    await user.click(within(firstDraftRow).getByRole("button", { name: "Edit" }));
    const nameInput = screen.getByLabelText("Suggested Name");
    await user.clear(nameInput);
    await user.type(nameInput, "Edited Competitor Name");
    await user.click(screen.getByRole("button", { name: "Save Edits" }));
    await screen.findByText("Draft edits saved. Accept explicitly to create competitor records.");
    expect(mockEditCompetitorProfileDraft).toHaveBeenCalled();

    await user.click(within(firstDraftRow).getByRole("button", { name: "Accept" }));
    await screen.findByText("Draft accepted and added to competitors.");
    expect(mockAcceptCompetitorProfileDraft).toHaveBeenCalled();

    const enabledRejectButton = screen
      .getAllByTestId("competitor-profile-draft-row")
      .map((row) => within(row).getByRole("button", { name: "Reject" }))
      .find((button) => !button.hasAttribute("disabled"));
    expect(enabledRejectButton).toBeDefined();
    await user.click(enabledRejectButton as HTMLButtonElement);
    await screen.findByText("Draft rejected. No competitor record was created.");
    expect(mockRejectCompetitorProfileDraft).toHaveBeenCalled();
  });

  it("renders recommendation narrative ai diagnostics summary when available", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        latest_narrative: buildRecommendationNarrative({
          ai_diagnostics_summary: {
            failure_category: "remote_timeout",
            failure_reason: "provider_timeout",
            failure_source: "remote_provider",
            retryable: true,
            hint: "Provider timeout",
            budget_outcome: "provider_submission",
            retry_suppressed: false,
            trimming_pass_count: null,
            difficulty_bucket: "medium",
            input_size_bucket: "medium",
            degraded_state: "degraded",
          },
        }),
      }),
    );

    render(<SiteWorkspacePage />);

    const summary = await screen.findByTestId("recommendation-ai-diagnostics-summary");
    expect(summary).toHaveTextContent(
      "AI diagnostics: remote_timeout / provider_timeout — Provider timeout (retryable: yes)",
    );
  });

  it("removes legacy recommendation metadata table headers from the workspace recommendation surface", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();

    render(<SiteWorkspacePage />);

    const recommendationsTab = await screen.findByRole("tab", { name: "Recommendations" });
    await user.click(recommendationsTab);

    const runsHeading = await screen.findByRole("heading", { name: "Recommendation Runs and Narratives" });
    const runsSection = runsHeading.closest("section");
    expect(runsSection).toBeTruthy();
    const runsScope = within(runsSection as HTMLElement);
    expect(runsScope.queryByRole("columnheader", { name: "Category" })).not.toBeInTheDocument();
    expect(runsScope.queryByRole("columnheader", { name: "Severity" })).not.toBeInTheDocument();
    expect(runsScope.queryByRole("columnheader", { name: "Priority" })).not.toBeInTheDocument();
    const workspaceItemCount = (runsSection as HTMLElement).querySelectorAll(
      '[data-testid^="recommendation-workspace-item-"]',
    ).length;
    expect(workspaceItemCount).toBeGreaterThan(0);
    expect(screen.queryByText(/^Why this was suggested$/i)).not.toBeInTheDocument();
  });

  it("requires explicit synthetic scaffold confirmation and verified domain before acceptance", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();

    const syntheticRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-synth",
      status: "completed",
      generated_draft_count: 1,
    });
    const syntheticDraft: CompetitorProfileDraft = {
      id: "draft-synth-1",
      business_id: "biz-1",
      site_id: "site-1",
      generation_run_id: "gen-run-synth",
      suggested_name: "Review scaffold: fire protection competitors (Longmont, CO)",
      suggested_domain: "review-scaffold-1.invalid",
      competitor_type: "direct",
      summary: "Synthetic scaffold only.",
      why_competitor: "Review and confirm before promotion.",
      evidence: "Synthetic scaffold only.",
      confidence_score: 0.3,
      source: "ai_forced_fallback",
      source_type: "synthetic",
      provenance_classification: "synthetic_fallback",
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
      items: [syntheticRun],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: syntheticRun,
      drafts: [syntheticDraft],
      total_drafts: 1,
    });
    mockAcceptCompetitorProfileDraft.mockResolvedValue({
      ...syntheticDraft,
      suggested_name: "Verified Synthetic Competitor",
      suggested_domain: "verified-synthetic-site.example",
      review_status: "accepted",
      accepted_competitor_set_id: "set-1",
      accepted_competitor_domain_id: "domain-1",
      reviewed_by_principal_id: "principal-1",
      reviewed_at: "2026-03-21T01:30:00Z",
    });

    render(<SiteWorkspacePage />);

    await screen.findByText("Confirm synthetic scaffold review");
    const syntheticRow = screen.getAllByTestId("competitor-profile-draft-row")[0];
    expect(within(syntheticRow).getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(within(syntheticRow).getByRole("button", { name: "Accept as Unverified" })).toBeDisabled();

    await user.click(within(syntheticRow).getByRole("button", { name: "Edit" }));

    const domainInput = screen.getByLabelText("Suggested Domain");
    await user.clear(domainInput);
    await user.type(domainInput, "verified-synthetic-site.example");

    const acceptEditedButton = screen.getByRole("button", { name: "Accept Edited" });
    expect(acceptEditedButton).toBeDisabled();

    await user.click(within(syntheticRow).getByRole("checkbox", { name: "Confirm synthetic scaffold review" }));
    expect(acceptEditedButton).toBeEnabled();

    await user.click(acceptEditedButton);
    await screen.findByText("Draft accepted and added to competitors.");
    expect(mockAcceptCompetitorProfileDraft).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      "gen-run-synth",
      "draft-synth-1",
      expect.objectContaining({
        confirm_synthetic_scaffold: true,
        suggested_domain: "verified-synthetic-site.example",
      }),
    );
  });

  it("supports accepting a synthetic scaffold as unverified without a verified domain", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();

    const syntheticRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-synth-unverified",
      status: "completed",
      generated_draft_count: 1,
    });
    const syntheticDraft: CompetitorProfileDraft = {
      id: "draft-synth-unverified-1",
      business_id: "biz-1",
      site_id: "site-1",
      generation_run_id: "gen-run-synth-unverified",
      suggested_name: "Review scaffold: local fire alarm competitors (Longmont, CO)",
      suggested_domain: "review-scaffold-1.invalid",
      competitor_type: "direct",
      summary: "Synthetic scaffold only.",
      why_competitor: "Review and confirm before promotion.",
      evidence: "Synthetic scaffold only.",
      confidence_score: 0.32,
      source: "ai_forced_fallback",
      source_type: "synthetic",
      provenance_classification: "synthetic_fallback",
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
      items: [syntheticRun],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: syntheticRun,
      drafts: [syntheticDraft],
      total_drafts: 1,
    });
    mockAcceptCompetitorProfileDraft.mockResolvedValue({
      ...syntheticDraft,
      review_status: "accepted",
      review_notes: "Accepted as unverified competitor.",
      accepted_competitor_set_id: "set-1",
      accepted_competitor_domain_id: "domain-2",
      reviewed_by_principal_id: "principal-1",
      reviewed_at: "2026-03-21T01:40:00Z",
    });

    render(<SiteWorkspacePage />);

    await screen.findByText("Confirm synthetic scaffold review");
    await user.click(screen.getByRole("checkbox", { name: "Confirm synthetic scaffold review" }));
    await user.click(screen.getByRole("button", { name: "Accept as Unverified" }));

    await screen.findByText("Draft accepted as unverified competitor scaffold.");
    expect(screen.getByText("Accepted as unverified competitor")).toBeInTheDocument();
    expect(mockAcceptCompetitorProfileDraft).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      "gen-run-synth-unverified",
      "draft-synth-unverified-1",
      expect.objectContaining({
        confirm_synthetic_scaffold: true,
        accept_as_unverified: true,
      }),
    );
  });

  it("renders safe failed-generation context", async () => {
    seedRichWorkspaceData();
    const failedRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-failed",
      status: "failed",
      generated_draft_count: 0,
      failure_category: "provider_config",
      error_summary: "Competitor profile generation failed",
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [failedRun],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: failedRun,
      drafts: [],
      total_drafts: 0,
    });

    render(<SiteWorkspacePage />);

    await screen.findByText("Competitor profile generation failed");
    expect(mockFetchCompetitorProfileGenerationRunDetail).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      "gen-run-failed",
    );
    expect(screen.getByText(/Failure Category:/i)).toHaveTextContent("provider config");
    expect(screen.getByText("This run did not produce any reviewable drafts.")).toBeInTheDocument();
    expect(screen.queryByText("Generation is in progress for this run.")).not.toBeInTheDocument();
  });

  it("shows retry action for failed generation runs", async () => {
    seedRichWorkspaceData();
    const failedRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-failed",
      status: "failed",
      generated_draft_count: 0,
      failure_category: "provider_config",
      error_summary: "Competitor profile generation failed",
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [failedRun],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: failedRun,
      drafts: [],
      total_drafts: 0,
    });

    render(<SiteWorkspacePage />);

    await screen.findByText("Competitor profile generation failed");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("retries a failed generation run and promotes the new queued run", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    const failedRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-failed",
      status: "failed",
      generated_draft_count: 0,
      failure_category: "provider_config",
      error_summary: "Competitor profile generation failed",
    });
    const retriedRun = buildCompetitorProfileGenerationRun({
      ...failedRun,
      id: "gen-run-retry-1",
      parent_run_id: "gen-run-failed",
      status: "queued",
      error_summary: null,
      completed_at: null,
      created_at: "2026-03-21T01:02:00Z",
      updated_at: "2026-03-21T01:02:00Z",
    });
    mockFetchCompetitorProfileGenerationRuns
      .mockResolvedValueOnce({
        items: [failedRun],
        total: 1,
      })
      .mockResolvedValue({
        items: [retriedRun],
        total: 1,
      });
    mockFetchCompetitorProfileGenerationRunDetail
      .mockResolvedValueOnce({
        run: failedRun,
        drafts: [],
        total_drafts: 0,
      })
      .mockResolvedValue({
        run: retriedRun,
        drafts: [],
        total_drafts: 0,
      });
    mockRetryCompetitorProfileGenerationRun.mockResolvedValue({
      run: retriedRun,
      drafts: [],
      total_drafts: 0,
    });

    render(<SiteWorkspacePage />);

    await screen.findByRole("button", { name: "Retry" });
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await screen.findByText("Retry queued. Drafts will appear after the run completes.");
    expect(mockRetryCompetitorProfileGenerationRun).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      "gen-run-failed",
    );
    await waitFor(() => {
      expect(screen.getByText(/Latest Run:/i)).toHaveTextContent("gen-run-retry-1");
    });
    expect(screen.getByText(/Retry of run/i)).toHaveTextContent("gen-run-failed");
    expect(screen.getByText("Generation is in progress for this run.")).toBeInTheDocument();
  });

  it("renders safe retry error state when retry request fails", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    const failedRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-failed",
      status: "failed",
      generated_draft_count: 0,
      failure_category: "provider_config",
      error_summary: "Competitor profile generation failed",
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [failedRun],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: failedRun,
      drafts: [],
      total_drafts: 0,
    });
    mockRetryCompetitorProfileGenerationRun.mockRejectedValue(
      new ApiRequestError("Retry is not allowed for this run", {
        status: 422,
        detail: null,
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("button", { name: "Retry" });
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await screen.findByText("Retry is not allowed for this run");
    expect(screen.getByText(/Latest Run:/i)).toHaveTextContent("gen-run-failed");
  });

  it("renders canonical lineage hints for workspace recommendation action review", async () => {
    seedRichWorkspaceData();
    const recommendationWithLineage = buildRecommendation({
      id: "rec-lineage-1",
      title: "Lineage-backed recommendation",
      action_lineage: {
        source_action_id: "rec-lineage-1",
        chained_drafts: [
          {
            id: "draft-lineage-1",
            source_action_id: "rec-lineage-1",
            action_type: "measure_performance",
            title: "Measure performance after rollout",
            description: "Track outcome after applying the recommendation.",
            draft_state: "pending",
            activation_state: "activated",
            activated_action_id: "activated-lineage-1",
            automation_ready: true,
            automation_template_key: "performance_check_followup",
            created_at: "2026-03-21T01:20:00Z",
          },
        ],
        activated_actions: [
          {
            id: "activated-lineage-1",
            source_draft_id: "draft-lineage-1",
            source_action_id: "rec-lineage-1",
            action_type: "measure_performance",
            title: "Measure performance after rollout",
            description: "Track outcome after applying the recommendation.",
            state: "pending",
            automation_ready: true,
            automation_template_key: "performance_check_followup",
            automation_binding_state: "bound",
            bound_automation_id: "automation-config-1",
            automation_bound_at: "2026-03-21T01:22:00Z",
            automation_execution_state: "requested",
            automation_execution_requested_at: "2026-03-21T01:23:00Z",
            last_automation_run_id: "automation-run-workspace-1",
            automation_run_status: "running",
            automation_run_started_at: "2026-03-21T01:23:00Z",
            created_at: "2026-03-21T01:21:00Z",
          },
        ],
        counts: {
          chained_draft_count: 1,
          activated_action_count: 1,
          automation_ready_count: 1,
        },
      },
    });
    const workspaceSummary = buildRecommendationWorkspaceSummary({
      recommendations: {
        items: [recommendationWithLineage],
        total: 1,
      },
      grouped_recommendations: [
        {
          theme: "trust_and_legitimacy",
          label: "Trust and legitimacy",
          count: 1,
          recommendation_ids: ["rec-lineage-1"],
        },
      ],
      start_here: {
        recommendation_id: "rec-lineage-1",
        title: recommendationWithLineage.title,
        reason: "Start with this recommendation for the clearest workflow impact.",
        context_flags: ["competitor_backed"],
        theme: "trust_and_legitimacy",
        theme_label: "Trust and legitimacy",
      },
    });
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(workspaceSummary);
    mockFetchRecommendations.mockResolvedValue({
      items: [recommendationWithLineage],
      total: 1,
    });

    render(<SiteWorkspacePage />);

    const outputReview = await screen.findByTestId("workspace-recommendation-output-review");
    expect(outputReview).toHaveTextContent("Next-step lineage:");
    expect(outputReview).toHaveTextContent("Activated");
    expect(outputReview).toHaveTextContent("Automation-ready");
    expect(outputReview).toHaveTextContent("Linked action activated-lineage-1 is currently pending.");
    expect(outputReview).toHaveTextContent("Uses template: performance_check_followup");
    expect(outputReview).toHaveTextContent("Execution requested");
    expect(screen.getByTestId("workspace-recommendation-execution-polling-status")).toBeInTheDocument();
  });

  it("binds automation for an unbound automation-ready activated next step", async () => {
    seedRichWorkspaceData();
    const recommendationWithLineage = buildRecommendation({
      id: "rec-lineage-bind-1",
      title: "Lineage binding recommendation",
      action_lineage: {
        source_action_id: "rec-lineage-bind-1",
        chained_drafts: [
          {
            id: "draft-lineage-bind-1",
            source_action_id: "rec-lineage-bind-1",
            action_type: "measure_performance",
            title: "Measure performance after rollout",
            description: "Track outcome after applying the recommendation.",
            draft_state: "pending",
            activation_state: "activated",
            activated_action_id: "activated-lineage-1",
            automation_ready: true,
            automation_template_key: "performance_check_followup",
            created_at: "2026-03-21T01:20:00Z",
          },
        ],
        activated_actions: [
          {
            id: "activated-lineage-1",
            source_draft_id: "draft-lineage-bind-1",
            source_action_id: "rec-lineage-bind-1",
            action_type: "measure_performance",
            title: "Measure performance after rollout",
            description: "Track outcome after applying the recommendation.",
            state: "pending",
            automation_ready: true,
            automation_template_key: "performance_check_followup",
            automation_binding_state: "unbound",
            bound_automation_id: null,
            automation_bound_at: null,
            created_at: "2026-03-21T01:21:00Z",
          },
        ],
        counts: {
          chained_draft_count: 1,
          activated_action_count: 1,
          automation_ready_count: 1,
        },
      },
    });
    const workspaceSummary = buildRecommendationWorkspaceSummary({
      recommendations: {
        items: [recommendationWithLineage],
        total: 1,
      },
      grouped_recommendations: [
        {
          theme: "trust_and_legitimacy",
          label: "Trust and legitimacy",
          count: 1,
          recommendation_ids: ["rec-lineage-bind-1"],
        },
      ],
      start_here: {
        recommendation_id: "rec-lineage-bind-1",
        title: recommendationWithLineage.title,
        reason: "Start with this recommendation for the clearest workflow impact.",
        context_flags: ["competitor_backed"],
        theme: "trust_and_legitimacy",
        theme_label: "Trust and legitimacy",
      },
    });
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(workspaceSummary);
    mockFetchRecommendations.mockResolvedValue({
      items: [recommendationWithLineage],
      total: 1,
    });

    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    const outputReview = await screen.findByTestId("workspace-recommendation-output-review");
    const bindButton = within(outputReview).getByRole("button", { name: "Bind automation" });
    await user.click(bindButton);

    await waitFor(() =>
      expect(mockBindActionExecutionItemAutomation).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        "activated-lineage-1",
        "automation-config-1",
      ),
    );
  });

});


