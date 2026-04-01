import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SitesPage from "./page";
import type { AuthPrincipal, SEOSite } from "../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: SEOSite[];
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock<Promise<SEOSite[]>, []>;
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockUseAuth = jest.fn<{ principal: AuthPrincipal | null }, []>();
const mockDeactivateSite = jest.fn<Promise<SEOSite>, unknown[]>();
const mockActivateSite = jest.fn<Promise<SEOSite>, unknown[]>();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../components/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    deactivateSite: (...args: unknown[]) => mockDeactivateSite(...args),
    activateSite: (...args: unknown[]) => mockActivateSite(...args),
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
    last_audit_run_id: null,
    last_audit_status: null,
    last_audit_completed_at: null,
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
    refreshSites: jest.fn<Promise<SEOSite[]>, []>().mockResolvedValue([buildSite()]),
    ...overrides,
  };
}

function setPrincipal(role: "admin" | "operator") {
  mockUseAuth.mockReturnValue({
    principal: {
      business_id: "biz-1",
      principal_id: role === "admin" ? "admin-1" : "operator-1",
      display_name: role === "admin" ? "Admin One" : "Operator One",
      role,
      is_active: true,
    },
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockUseOperatorContext.mockReturnValue(baseContext());
  setPrincipal("admin");
});

describe("sites admin deactivate controls", () => {
  it("requires confirmation before deactivating a site", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);

    render(<SitesPage />);
    expect(screen.getByLabelText("Selected Site")).toHaveClass("operator-select");

    fireEvent.click(screen.getByRole("button", { name: "Deactivate Site" }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(mockDeactivateSite).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("deactivates site and refreshes the site list", async () => {
    const contextValue = baseContext();
    mockUseOperatorContext.mockReturnValue(contextValue);
    mockDeactivateSite.mockResolvedValueOnce(buildSite({ is_active: false }));
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);

    render(<SitesPage />);

    fireEvent.click(screen.getByRole("button", { name: "Deactivate Site" }));

    await waitFor(() => expect(mockDeactivateSite).toHaveBeenCalledWith("token-1", "biz-1", "site-1"));
    await waitFor(() => expect(contextValue.refreshSites).toHaveBeenCalled());
    expect(screen.getByText("Site Main Site deactivated.")).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("hides site deactivate controls for non-admin principals", () => {
    setPrincipal("operator");

    render(<SitesPage />);

    expect(screen.queryByRole("button", { name: "Deactivate Site" })).not.toBeInTheDocument();
    expect(screen.queryByText("Admin Action")).not.toBeInTheDocument();
  });

  it("renders Open Workspace using the shared inline button action style", () => {
    render(<SitesPage />);

    const openWorkspaceAction = screen.getByRole("link", { name: "Open Workspace" });
    expect(openWorkspaceAction).toHaveClass("button", "button-secondary", "button-inline");
    expect(openWorkspaceAction).toHaveAttribute("href", "/sites/site-1");
  });
});
