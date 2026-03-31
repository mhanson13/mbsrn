import { render, screen } from "@testing-library/react";

import AuditsPage from "./page";

const mockUseOperatorContext = jest.fn();
const mockFetchAuditRuns = jest.fn();
const mockPush = jest.fn();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => ({
  fetchAuditRuns: (...args: unknown[]) => mockFetchAuditRuns(...args),
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

    await screen.findByText("run-1");
    expect(screen.getByText("Total runs")).toBeInTheDocument();
    expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
  });
});
