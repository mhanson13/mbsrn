import { render, screen } from "@testing-library/react";

import DashboardPage from "./page";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: Array<{ id: string; display_name: string; last_audit_run_id?: string | null; last_audit_status?: string | null }>;
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockUseAuth = jest.fn();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../components/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

function baseContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [
      {
        id: "site-1",
        display_name: "Main Site",
        last_audit_run_id: "audit-1",
        last_audit_status: "completed",
      },
    ],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
    ...overrides,
  };
}

describe("dashboard shared support-state framing", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseAuth.mockReturnValue({ principal: { role: "operator" } });
  });

  it("renders loading support header", () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ loading: true }));
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(
      screen.getByText("Loading dashboard overview and role-scoped status."),
    ).toBeInTheDocument();
  });

  it("renders error support header", () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ error: "context failed" }));
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText("Error: context failed")).toBeInTheDocument();
  });

  it("renders dashboard hero and navigation links for healthy context", () => {
    mockUseOperatorContext.mockReturnValue(baseContext());
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    const recommendationOutcomeHeading = screen.getByRole("heading", { name: "Recommendation decisiveness cues" });
    expect(recommendationOutcomeHeading).toBeInTheDocument();
    const recommendationOutcomeSection = recommendationOutcomeHeading.closest("section");
    expect(recommendationOutcomeSection).not.toBeNull();
    expect(recommendationOutcomeSection).toHaveTextContent(
      "Why now: High-value next step Ready now indicates the top item to review first.",
    );
    expect(recommendationOutcomeSection).toHaveTextContent(
      "Blocking: Waiting on visibility or Manual follow-up required means action is recorded but confirmation is still pending.",
    );
    expect(recommendationOutcomeSection).toHaveTextContent(
      "After action: Review before applying for undecided items; after apply, verify visibility on the next refresh.",
    );
    expect(recommendationOutcomeSection).toHaveTextContent(
      "Evidence preview: queue/detail views show one compact proof line plus a trust-safe support cue.",
    );
    expect(recommendationOutcomeSection).toHaveTextContent(
      "Choice support: Best immediate move Quick win Lower-immediacy background item clarify what to do first versus what can be deferred.",
    );
    expect(recommendationOutcomeSection).toHaveTextContent(
      "Lifecycle stage: Needs review / pending Applied / completed Background item / revisit later keeps revisit timing explicit without opening detail pages.",
    );
    expect(recommendationOutcomeSection).toHaveTextContent(
      "Freshness posture: Fresh enough to act Review soon Pending refresh Possibly outdated shows whether a refresh is likely needed before action.",
    );
    expect(screen.getByRole("link", { name: "Sites" })).toHaveAttribute("href", "/sites");
    expect(screen.getByRole("link", { name: "Google Business Profile" })).toHaveAttribute(
      "href",
      "/business-profile",
    );
  });
});
