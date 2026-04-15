import { render, screen } from "@testing-library/react";

import type { SEOSite } from "../../lib/api/types";
import SiteMigrationWorkflowPage from "./[site_id]/migration/page";

const navigationState = {
  params: { site_id: "site-1" },
};

const mockUseOperatorContext = jest.fn();
const mockMigrationPanel = jest.fn();

jest.mock("next/navigation", () => ({
  useParams: () => navigationState.params,
}));

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../components/MigrationWorkspacePanel", () => ({
  MigrationWorkspacePanel: (props: { token: string; businessId: string; siteId: string }) => {
    mockMigrationPanel(props);
    return <div data-testid="migration-workspace-panel">Migration workspace panel</div>;
  },
}));

function buildSite(overrides: Partial<SEOSite> = {}): SEOSite {
  return {
    id: "site-1",
    business_id: "biz-1",
    display_name: "Main Site",
    base_url: "https://example.com/",
    normalized_domain: "example.com",
    is_active: true,
    is_primary: true,
    last_audit_run_id: null,
    last_audit_status: null,
    last_audit_completed_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  navigationState.params = { site_id: "site-1" };
  mockUseOperatorContext.mockReturnValue({
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [buildSite()],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
  });
});

describe("site migration workflow page", () => {
  it("renders the dedicated migration workflow route with migration panel", async () => {
    render(<SiteMigrationWorkflowPage />);

    expect(await screen.findByRole("heading", { name: "Migration Workflow" })).toBeInTheDocument();
    expect(screen.getByTestId("migration-workspace-panel")).toBeInTheDocument();
    expect(mockMigrationPanel).toHaveBeenCalledWith({
      token: "token-1",
      businessId: "biz-1",
      siteId: "site-1",
    });
    expect(screen.getByRole("link", { name: "Back to Site Workspace" })).toHaveAttribute("href", "/sites/site-1");
  });

  it("renders sign-in support state when auth context is missing", async () => {
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "",
      businessId: "",
      sites: [buildSite()],
      selectedSiteId: "site-1",
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });

    render(<SiteMigrationWorkflowPage />);

    expect(await screen.findByText("Sign in required")).toBeInTheDocument();
    expect(screen.queryByTestId("migration-workspace-panel")).not.toBeInTheDocument();
  });

  it("renders unavailable support state when selected site cannot be resolved", async () => {
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [buildSite({ id: "site-2" })],
      selectedSiteId: "site-2",
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });

    render(<SiteMigrationWorkflowPage />);

    expect(await screen.findByText("Migration workflow unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("migration-workspace-panel")).not.toBeInTheDocument();
  });
});

