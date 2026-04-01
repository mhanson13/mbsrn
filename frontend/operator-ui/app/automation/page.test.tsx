import { render, screen } from "@testing-library/react";

import AutomationPage from "./page";

const mockUseOperatorContext = jest.fn();
const mockFetchAutomationRuns = jest.fn();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => ({
  fetchAutomationRuns: (...args: unknown[]) => mockFetchAutomationRuns(...args),
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

describe("automation page shared-shell framing", () => {
  beforeEach(() => {
    mockUseOperatorContext.mockReset();
    mockFetchAutomationRuns.mockReset();
  });

  it("renders a no-sites support state when no sites are configured", () => {
    mockUseOperatorContext.mockReturnValue(buildContext({ sites: [], selectedSiteId: null }));

    render(<AutomationPage />);

    expect(screen.getByRole("heading", { name: "Automation Run History" })).toBeInTheDocument();
    expect(
      screen.getByText("No SEO sites are configured yet. Add a site before reviewing automation run history."),
    ).toBeInTheDocument();
  });

  it("renders summary cards and run table for a configured site", async () => {
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
    expect(screen.getByTestId("automation-quick-scan")).toBeInTheDocument();
    const quickScanItem = screen.getByTestId("automation-quick-scan-item-run-1");
    expect(quickScanItem).toHaveTextContent("Automation output ready");
    expect(quickScanItem).toHaveTextContent("completed");
    expect(quickScanItem).toHaveTextContent("No blocker");
    expect(screen.getByText("Total runs")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByTestId("automation-latest-run-summary")).toHaveTextContent("Latest automation outcome");
    expect(screen.getByTestId("automation-latest-run-summary")).toHaveTextContent("Next step:");
    expect(screen.getByText("Review recommendation run output")).toBeInTheDocument();
    expect(screen.getByText("Review latest narrative output")).toBeInTheDocument();
  });
});
