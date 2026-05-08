import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AutomationPage from "./page";
import type { AutomationRun } from "../../lib/api/types";
import { ApiRequestError } from "../../lib/api/client";

const mockUseOperatorContext = jest.fn();
const mockUseAuth = jest.fn();
const mockFetchAutomationRuns = jest.fn();
const mockFetchAutomationStatus = jest.fn();
const mockPatchAutomationConfig = jest.fn();
const mockCreateAutomationRun = jest.fn();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../components/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("../../lib/api/client", () => ({
  ...jest.requireActual("../../lib/api/client"),
  fetchAutomationRuns: (...args: unknown[]) => mockFetchAutomationRuns(...args),
  fetchAutomationStatus: (...args: unknown[]) => mockFetchAutomationStatus(...args),
  patchAutomationConfig: (...args: unknown[]) => mockPatchAutomationConfig(...args),
  createAutomationRun: (...args: unknown[]) => mockCreateAutomationRun(...args),
}));

function buildContext(overrides: Record<string, unknown> = {}) {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [
      {
        id: "site-1",
        display_name: "Site One",
      },
    ],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    ...overrides,
  };
}

function buildAutomationRun(overrides: Partial<AutomationRun> = {}): AutomationRun {
  return {
    id: "run-created-1",
    business_id: "biz-1",
    site_id: "site-1",
    status: "running",
    trigger_source: "manual",
    started_at: "2026-03-26T10:00:00Z",
    finished_at: null,
    error_message: null,
    steps_json: [],
    created_at: "2026-03-26T10:00:00Z",
    updated_at: "2026-03-26T10:00:00Z",
    ...overrides,
  };
}

function buildAutomationStatusResponse(overrides: Record<string, unknown> = {}) {
  return {
    business_id: "biz-1",
    site_id: "site-1",
    config: {
      id: "automation-config-1",
      business_id: "biz-1",
      site_id: "site-1",
      config_source: "default",
      is_enabled: false,
      cadence_type: "manual",
      cadence_minutes: null,
      trigger_audit: true,
      trigger_audit_summary: true,
      trigger_competitor_snapshot: false,
      trigger_comparison: false,
      trigger_competitor_summary: false,
      trigger_recommendations: true,
      trigger_recommendation_narrative: false,
      last_run_at: null,
      next_run_at: null,
      last_status: null,
      last_error_message: null,
      created_at: "2026-03-26T09:00:00Z",
      updated_at: "2026-03-26T09:00:00Z",
    },
    latest_run: null,
    ...overrides,
  };
}

describe("automation page shared-shell framing", () => {
  beforeEach(() => {
    mockUseOperatorContext.mockReset();
    mockUseAuth.mockReset();
    mockFetchAutomationRuns.mockReset();
    mockFetchAutomationStatus.mockReset();
    mockPatchAutomationConfig.mockReset();
    mockCreateAutomationRun.mockReset();
    mockUseAuth.mockReturnValue({
      principal: {
        role: "admin",
      },
    });
    mockFetchAutomationStatus.mockResolvedValue(buildAutomationStatusResponse());
    window.history.replaceState({}, "", "/automation");
  });

  it("renders a no-sites support state when no sites are configured", () => {
    mockUseOperatorContext.mockReturnValue(buildContext({ sites: [], selectedSiteId: null }));

    render(<AutomationPage />);

    expect(screen.getByRole("heading", { name: "Automation Run History" })).toBeInTheDocument();
    expect(
      screen.getByText("No SEO sites are configured yet. Add a site before reviewing automation run history."),
    ).toBeInTheDocument();
  });

  it("renders actionable empty state and creates a run from the empty-state CTA", async () => {
    const user = userEvent.setup();
    const createdRun = buildAutomationRun({ id: "run-created-1", status: "running" });
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValue({ items: [createdRun], total: 1 });
    mockCreateAutomationRun.mockResolvedValueOnce(createdRun);

    render(<AutomationPage />);

    const emptyState = await screen.findByTestId("automation-empty-state");
    expect(emptyState).toHaveTextContent("No automation runs yet");
    const runButton = screen.getByTestId("automation-empty-state-run-button");
    expect(runButton).toHaveTextContent("Run SEO automation");

    await user.click(runButton);

    await waitFor(() =>
      expect(mockCreateAutomationRun).toHaveBeenCalledWith("token-1", "biz-1", "site-1"),
    );
    expect(await screen.findByText("run-created-1")).toBeInTheDocument();
  });

  it("shows recommendation trigger context and syncs site context from query params", async () => {
    const setSelectedSiteId = jest.fn();
    window.history.replaceState(
      {},
      "",
      "/automation?site_id=site-1&recommendation_id=rec-7&recommendation_title=Fix%20service%20page%20copy",
    );
    mockUseOperatorContext.mockReturnValue(
      buildContext({
        selectedSiteId: "site-2",
        setSelectedSiteId,
        sites: [
          { id: "site-1", display_name: "Site One" },
          { id: "site-2", display_name: "Site Two" },
        ],
      }),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({ items: [], total: 0 });

    render(<AutomationPage />);

    const triggerContext = await screen.findByTestId("automation-trigger-context");
    expect(triggerContext).toHaveTextContent("Triggered from recommendation: Fix service page copy (rec-7)");
    await waitFor(() => expect(setSelectedSiteId).toHaveBeenCalledWith("site-1"));
  });

  it("maps automation config missing failures to actionable operator guidance", async () => {
    const user = userEvent.setup();
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({ items: [], total: 0 });
    mockCreateAutomationRun.mockRejectedValueOnce(
      new ApiRequestError("SEO automation config not found", {
        status: 404,
        detail: null,
      }),
    );

    render(<AutomationPage />);

    await user.click(await screen.findByTestId("automation-empty-state-run-button"));

    expect(await screen.findByTestId("automation-empty-state-run-error")).toHaveTextContent(
      "Automation configuration was missing and could not be prepared for this site. Retry in a moment.",
    );
  });

  it("maps site-context mismatch failures to a re-selection message", async () => {
    const user = userEvent.setup();
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({ items: [], total: 0 });
    mockCreateAutomationRun.mockRejectedValueOnce(
      new ApiRequestError("SEO site not found", {
        status: 404,
        detail: null,
      }),
    );

    render(<AutomationPage />);

    await user.click(await screen.findByTestId("automation-empty-state-run-button"));

    expect(await screen.findByTestId("automation-empty-state-run-error")).toHaveTextContent(
      "This site context could not be resolved. Re-select the site and try again.",
    );
  });

  it("renders summary cards and run table for a configured site", async () => {
    const user = userEvent.setup();
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "run-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "recommendation_apply",
          started_at: "2026-03-25T10:00:00Z",
          finished_at: "2026-03-25T10:01:00Z",
          error_message: null,
          steps_json: [
            {
              step_name: "recommendation_run",
              status: "completed",
              started_at: "2026-03-25T10:00:05Z",
              finished_at: "2026-03-25T10:00:45Z",
              linked_output_id: "rec-run-99",
              error_message: null,
              pages_analyzed_count: 42,
              issues_found_count: 12,
              recommendations_generated_count: 5,
            },
            {
              step_name: "recommendation_narrative",
              status: "completed",
              started_at: "2026-03-25T10:00:45Z",
              finished_at: "2026-03-25T10:00:59Z",
              linked_output_id: "narrative-99",
              error_message: null,
            },
          ],
          created_at: "2026-03-25T10:00:00Z",
          updated_at: "2026-03-25T10:01:00Z",
        },
      ],
      total: 1,
    });

    render(<AutomationPage />);

    await screen.findByText("run-1");
    expect(document.querySelector(".page-container-width-wide")).toBeTruthy();
    expect(screen.getByTestId("automation-page-hero")).toBeInTheDocument();
    expect(screen.getByTestId("automation-control-grid")).toBeInTheDocument();
    expect(screen.getByTestId("automation-primary-actions")).toBeInTheDocument();
    expect(screen.getByTestId("automation-quick-scan")).toBeInTheDocument();
    const quickScanItem = screen.getByTestId("automation-quick-scan-item-run-1");
    expect(quickScanItem).toHaveTextContent("Workflow output ready");
    expect(quickScanItem).toHaveTextContent("completed");
    expect(quickScanItem).toHaveTextContent("No blocker");
    expect(screen.getByText("Total runs")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByTestId("automation-non-publishing-banner")).toHaveTextContent(
      "This automation analyzes your site and generates recommendations. It does not make changes to your website.",
    );
    expect(screen.getByTestId("automation-boundary-note")).toHaveTextContent(
      "Use Audit Runs for findings and history, Recommendations for decisioning, and Competitors for profile generation/review.",
    );
    expect(screen.getByTestId("automation-boundary-links")).toHaveTextContent("Open dedicated workflow pages");
    expect(screen.getByRole("link", { name: "Open Audit Runs" })).toHaveAttribute("href", "/audits");
    expect(screen.getByRole("link", { name: "Open Recommendations" })).toHaveAttribute(
      "href",
      "/recommendations?site_id=site-1",
    );
    expect(screen.getByRole("link", { name: "Open Competitors" })).toHaveAttribute(
      "href",
      "/competitors?site_id=site-1",
    );
    expect(screen.getByTestId("automation-config-summary")).toHaveTextContent("Automation configuration");
    expect(screen.getByTestId("automation-config-summary")).toHaveTextContent(
      "Configure which automation outputs are generated for this site. Changes apply to future runs only.",
    );
    expect(screen.getByTestId("automation-config-summary")).toHaveTextContent("Config source: Default system configuration");
    expect(screen.getByTestId("automation-config-group-site-audit")).toHaveTextContent("Site audit");
    expect(screen.getByTestId("automation-config-group-site-audit")).toHaveTextContent(
      "Audit summary is most useful when Audit run is enabled.",
    );
    expect(screen.getByTestId("automation-config-group-competitor-analysis")).toHaveTextContent("Competitor analysis");
    expect(screen.getByTestId("automation-config-group-recommendations")).toHaveTextContent("Recommendations");
    expect(screen.getByTestId("automation-config-edit-button")).toHaveTextContent("Edit step settings");
    expect(screen.getByTestId("automation-latest-run-summary")).toHaveTextContent("Latest automation outcome");
    expect(screen.getByTestId("automation-latest-run-status-strip")).toBeInTheDocument();
    expect(screen.getByTestId("automation-latest-run-summary")).toHaveTextContent("Complete");
    expect(screen.getByTestId("automation-latest-run-summary")).toHaveTextContent("Next step:");
    expect(screen.getByText("Open recommendation run output")).toBeInTheDocument();
    expect(screen.getByText("Review latest narrative output")).toBeInTheDocument();
    const latestControls = screen.getByTestId("automation-latest-run-controls");
    expect(latestControls).toHaveTextContent("Review output");
    expect(latestControls).toHaveTextContent("Mark completed");
    expect(latestControls).toHaveTextContent("Mark as completed after confirming output and follow-up tasks.");
    const outputReview = screen.getByTestId("automation-latest-run-output-review");
    expect(outputReview).toHaveTextContent(
      "This automation analyzes your site and generates recommendations. It does not make changes to your website.",
    );
    await user.click(within(outputReview).getAllByText("View details")[0]);
    expect(outputReview).toHaveTextContent("Pages analyzed: 42");
    expect(outputReview).toHaveTextContent("Issues found: 12");
    expect(outputReview).toHaveTextContent("Recommendations generated: 5");
  });

  it("renders canonical terminal outcome summary and step reason signals", async () => {
    const user = userEvent.setup();
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "run-with-skips-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "manual",
          started_at: "2026-03-25T10:00:00Z",
          finished_at: "2026-03-25T10:02:00Z",
          error_message: null,
          outcome_summary: {
            summary_title: "Automation completed with skips",
            summary_text:
              "Automation completed with skips. 1 completed, 2 skipped, 0 failed. Skipped step signal: Skipped because competitor snapshot output was not completed.",
            pages_analyzed_count: 42,
            issues_found_count: 12,
            recommendations_generated_count: 4,
            steps_completed_count: 1,
            steps_skipped_count: 2,
            steps_failed_count: 0,
            terminal_outcome: "completed_with_skips",
          },
          steps_json: [
            {
              step_name: "audit_run",
              status: "completed",
              started_at: "2026-03-25T10:00:01Z",
              finished_at: "2026-03-25T10:00:40Z",
              linked_output_id: "audit-run-1",
              error_message: null,
              pages_analyzed_count: 42,
              issues_found_count: 12,
            },
            {
              step_name: "comparison_run",
              status: "skipped",
              started_at: null,
              finished_at: "2026-03-25T10:01:00Z",
              linked_output_id: null,
              error_message: "Snapshot run is not completed; comparison step skipped",
              reason_summary: "Skipped because competitor snapshot output was not completed.",
            },
          ],
          created_at: "2026-03-25T10:00:00Z",
          updated_at: "2026-03-25T10:02:00Z",
        },
      ],
      total: 1,
    });

    render(<AutomationPage />);

    await screen.findByTestId("automation-latest-run-summary");
    const latestSummary = screen.getByTestId("automation-latest-run-summary");
    expect(latestSummary).toHaveTextContent("Completed with skips");
    expect(latestSummary).toHaveTextContent("Partial");
    expect(latestSummary).toHaveTextContent(
      "Competitor data not available at run time; insights may be limited.",
    );
    expect(latestSummary).toHaveTextContent("1 completed");
    expect(latestSummary).toHaveTextContent("2 skipped");
    expect(latestSummary).toHaveTextContent(
      "Review skipped steps and rerun after prerequisites are available.",
    );
    expect(latestSummary).toHaveTextContent("Skipped because competitor snapshot output was not completed.");

    const quickScanItem = screen.getByTestId("automation-quick-scan-item-run-with-skips-1");
    await user.click(within(quickScanItem).getByRole("button", { name: "Show details" }));
    expect(quickScanItem).toHaveTextContent("Reason: Skipped because competitor snapshot output was not completed.");
  });

  it("shows disabled-step config context in structured step detail messaging", async () => {
    const user = userEvent.setup();
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "run-disabled-steps-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "manual",
          started_at: "2026-03-25T10:00:00Z",
          finished_at: "2026-03-25T10:02:00Z",
          error_message: null,
          steps_json: [
            {
              step_name: "competitor_snapshot_run",
              status: "skipped",
              started_at: null,
              finished_at: "2026-03-25T10:01:00Z",
              linked_output_id: null,
              error_message: "disabled by config",
              reason_summary: "Skipped because this step is disabled in automation configuration.",
            },
          ],
          created_at: "2026-03-25T10:00:00Z",
          updated_at: "2026-03-25T10:02:00Z",
        },
      ],
      total: 1,
    });

    render(<AutomationPage />);

    const quickScanItem = await screen.findByTestId("automation-quick-scan-item-run-disabled-steps-1");
    await user.click(within(quickScanItem).getByRole("button", { name: "Show details" }));

    expect(quickScanItem).toHaveTextContent("Step: Competitor snapshot");
    expect(quickScanItem).toHaveTextContent("Status: skipped");
    expect(quickScanItem).toHaveTextContent("Reason: Disabled in automation configuration");
    expect(quickScanItem).toHaveTextContent("Config source: Default system configuration");
  });

  it("edits and saves automation step settings with targeted patch payload", async () => {
    const user = userEvent.setup();
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({ items: [], total: 0 });
    mockPatchAutomationConfig.mockResolvedValueOnce(
      buildAutomationStatusResponse({
        config: {
          ...buildAutomationStatusResponse().config,
          trigger_competitor_snapshot: true,
        },
      }).config,
    );

    render(<AutomationPage />);

    await user.click(await screen.findByTestId("automation-config-edit-button"));
    expect(screen.getByTestId("automation-config-group-competitor-analysis")).toHaveTextContent(
      "Competitor comparison and summary rely on competitor snapshot output.",
    );
    expect(screen.getByTestId("automation-config-group-recommendations")).toHaveTextContent(
      "Generates narrative guidance from recommendation output. Disable when structured recommendation data is enough.",
    );
    const snapshotToggle = screen.getByRole("checkbox", { name: "Competitor snapshot" });
    expect(snapshotToggle).not.toBeChecked();
    await user.click(snapshotToggle);
    expect(snapshotToggle).toBeChecked();
    await user.click(screen.getByTestId("automation-config-save-button"));

    await waitFor(() =>
      expect(mockPatchAutomationConfig).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        { trigger_competitor_snapshot: true },
      ),
    );
    expect(await screen.findByText("Automation configuration updated.")).toBeInTheDocument();
  });

  it("keeps automation configuration read-only for non-admin operators", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        role: "operator",
      },
    });
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({ items: [], total: 0 });

    render(<AutomationPage />);

    const summary = await screen.findByTestId("automation-config-summary");
    expect(summary).toHaveTextContent("Read-only view. Contact admin to change automation settings.");
    expect(summary).toHaveTextContent("Site audit");
    expect(summary).toHaveTextContent("Competitor analysis");
    expect(summary).toHaveTextContent("Recommendations");
    expect(screen.queryByTestId("automation-config-edit-button")).not.toBeInTheDocument();
  });

  it("renders config source label from backend-provided config_source", async () => {
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({ items: [], total: 0 });
    mockFetchAutomationStatus.mockResolvedValueOnce(
      buildAutomationStatusResponse({
        config: {
          ...buildAutomationStatusResponse().config,
          config_source: "site",
          is_enabled: false,
          cadence_type: "manual",
          cadence_minutes: null,
          trigger_audit: true,
          trigger_audit_summary: true,
          trigger_competitor_snapshot: false,
          trigger_comparison: false,
          trigger_competitor_summary: false,
          trigger_recommendations: true,
          trigger_recommendation_narrative: false,
        },
      }),
    );

    render(<AutomationPage />);

    const summary = await screen.findByTestId("automation-config-summary");
    expect(summary).toHaveTextContent("Config source: Site-specific configuration");
  });

  it("renders disabled waiting controls with explicit reason while automation is in progress", async () => {
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "run-waiting-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "running",
          trigger_source: "manual",
          started_at: "2026-03-25T10:05:00Z",
          finished_at: null,
          error_message: null,
          steps_json: [
            {
              step_name: "audit_run",
              status: "running",
              started_at: "2026-03-25T10:05:05Z",
              finished_at: null,
              linked_output_id: null,
              error_message: null,
            },
          ],
          created_at: "2026-03-25T10:05:00Z",
          updated_at: "2026-03-25T10:05:30Z",
        },
      ],
      total: 1,
    });

    render(<AutomationPage />);

    await screen.findByText("run-waiting-1");
    const latestControls = screen.getByTestId("automation-latest-run-controls");
    const statusButton = within(latestControls).getByRole("button", { name: "View automation status" });
    expect(statusButton).toBeDisabled();
    expect(latestControls).toHaveTextContent(
      "Automation is currently in progress. Review status while waiting for completion.",
    );
    expect(screen.getByTestId("automation-polling-status")).toHaveTextContent(
      "Status refreshes automatically every few seconds.",
    );
  });

  it("captures output review decisions locally for output-ready runs", async () => {
    const user = userEvent.setup();
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "run-output-ready-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "recommendation_apply",
          started_at: "2026-03-25T10:00:00Z",
          finished_at: "2026-03-25T10:01:00Z",
          error_message: null,
          steps_json: [
            {
              step_name: "recommendation_run",
              status: "completed",
              started_at: "2026-03-25T10:00:05Z",
              finished_at: "2026-03-25T10:00:45Z",
              linked_output_id: "rec-run-321",
              error_message: null,
            },
          ],
          created_at: "2026-03-25T10:00:00Z",
          updated_at: "2026-03-25T10:01:00Z",
        },
      ],
      total: 1,
    });

    render(<AutomationPage />);

    const outputReview = await screen.findByTestId("automation-latest-run-output-review");
    await user.click(within(outputReview).getByRole("button", { name: "Accept" }));

    expect(await screen.findByText("Decision captured: accepted")).toBeInTheDocument();
    expect(screen.getByTestId("automation-latest-run-summary")).toHaveTextContent("Completed / acted on");
    expect(screen.getByTestId("automation-latest-run-summary")).toHaveTextContent(
      "Track execution impact or move to the next recommended action.",
    );
  });
});
