import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AuditsPage from "./page";

const mockUseOperatorContext = jest.fn();
const mockFetchAuditRuns = jest.fn();
const mockCreateAuditRun = jest.fn();
const mockPush = jest.fn();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => ({
  fetchAuditRuns: (...args: unknown[]) => mockFetchAuditRuns(...args),
  createAuditRun: (...args: unknown[]) => mockCreateAuditRun(...args),
  ApiRequestError: class extends Error {
    status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
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

describe("audits page shared-shell framing", () => {
  beforeEach(() => {
    mockPush.mockReset();
    mockFetchAuditRuns.mockReset();
    mockCreateAuditRun.mockReset();
    mockUseOperatorContext.mockReset();
  });

  it("renders a no-sites support state when no sites are configured", () => {
    mockUseOperatorContext.mockReturnValue(buildContext({ sites: [], selectedSiteId: null }));

    render(<AuditsPage />);

    expect(screen.getByRole("heading", { name: "Audit Runs" })).toBeInTheDocument();
    expect(
      screen.getByText("No SEO sites are configured yet. Add a site first to view audit runs."),
    ).toBeInTheDocument();
  });

  it("renders summary cards and run table for a configured site", async () => {
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAuditRuns.mockResolvedValueOnce({
      items: [
        {
          id: "run-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          created_at: "2026-03-25T10:00:00Z",
          started_at: "2026-03-25T10:00:20Z",
          completed_at: "2026-03-25T10:01:20Z",
          pages_crawled: 4,
          errors_encountered: 0,
          error_summary: null,
        },
      ],
      total: 1,
    });

    render(<AuditsPage />);

    await screen.findByTestId("audit-quick-scan-item-run-1");
    expect(document.querySelector(".page-container-width-wide")).toBeTruthy();
    expect(screen.getByTestId("audits-page-hero")).toHaveClass("operator-page-hero-surface");
    expect(screen.getByTestId("audits-page-actions")).toBeInTheDocument();
    expect(screen.getByTestId("audits-run-audit-button")).toHaveTextContent("Run Audit");
    expect(screen.getByRole("link", { name: "Open Recommendations" })).toHaveAttribute(
      "href",
      "/recommendations?site_id=site-1",
    );
    expect(screen.getByTestId("audits-open-latest-findings-link")).toHaveAttribute("href", "/audits/run-1");
    expect(screen.getByTestId("audits-boundary-note")).toHaveTextContent(
      "Audit Runs own evidence and history. Recommendation decisions stay on the Recommendations page.",
    );
    expect(screen.getByTestId("audit-quick-scan")).toBeInTheDocument();
    const quickScanItem = screen.getByTestId("audit-quick-scan-item-run-1");
    expect(quickScanItem).toHaveTextContent("completed");
    expect(quickScanItem).toHaveTextContent("0 errors");
    expect(screen.getByText("Total runs")).toBeInTheDocument();
    expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Run ID" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Business" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Site" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Started" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Completed" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Created" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Duration" })).toBeInTheDocument();
    expect(screen.getByText("1m 00s")).toBeInTheDocument();
    expect(screen.getByTestId("audits-page-table-shell")).toHaveClass("workspace-table-shell");
  });

  it("starts an audit run from the page action and surfaces success guidance", async () => {
    const user = userEvent.setup();
    mockUseOperatorContext.mockReturnValue(buildContext());
    mockFetchAuditRuns.mockResolvedValueOnce({ items: [], total: 0 });
    mockCreateAuditRun.mockResolvedValueOnce({
      id: "run-2",
      business_id: "biz-1",
      site_id: "site-1",
      status: "queued",
      max_pages: 100,
      max_depth: 3,
      pages_discovered: 0,
      created_at: "2026-03-25T12:00:00Z",
      updated_at: "2026-03-25T12:00:00Z",
      started_at: null,
      completed_at: null,
      crawl_duration_ms: null,
      error_summary: null,
      created_by_principal_id: "principal-1",
      pages_crawled: 0,
      pages_skipped: 0,
      duplicate_urls_skipped: 0,
      errors_encountered: 0,
    });

    render(<AuditsPage />);

    await user.click(await screen.findByTestId("audits-run-audit-button"));

    expect(mockCreateAuditRun).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {});
    expect(await screen.findByTestId("audits-run-audit-success")).toHaveTextContent(
      "Audit run started. Refresh the run detail as new findings complete.",
    );
    expect(screen.getByTestId("audit-quick-scan-item-run-2")).toBeInTheDocument();
  });
});
