import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { NavShell } from "./NavShell";

const mockUsePathname = jest.fn<string, []>();
const mockReplace = jest.fn();
const mockUseRouter = jest.fn(() => ({ replace: mockReplace }));
const mockUseSearchParams = jest.fn<URLSearchParams, []>(() => new URLSearchParams());
const mockUseAuth = jest.fn();
const mockUseOperatorContext = jest.fn();

jest.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => mockUseRouter(),
  useSearchParams: () => mockUseSearchParams(),
}));

jest.mock("./AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("./useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../lib/api/client", () => ({
  logoutSession: jest.fn(),
}));

describe("NavShell", () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue("/dashboard");
    mockReplace.mockReset();
    mockUseSearchParams.mockReturnValue(new URLSearchParams());
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      scopeWarning: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
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
        },
      ],
      selectedSiteId: "site-1",
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });
    delete document.documentElement.dataset.theme;
    window.localStorage.clear();
  });

  it("shows Admin navigation label for admin principals", () => {
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "admin-1",
        display_name: "Admin One",
        role: "admin",
        is_active: true,
      },
      clearSession: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    const adminLink = screen.getByRole("link", { name: "Admin" });
    expect(adminLink).toBeInTheDocument();
    expect(adminLink).toHaveAttribute("href", "/admin");
    const userMgmtLink = screen.getByRole("link", { name: "User Mgmt" });
    expect(userMgmtLink).toBeInTheDocument();
    expect(userMgmtLink).toHaveAttribute("href", "/user-mgmt");
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    expect(document.querySelectorAll(".topnav-links")).toHaveLength(1);
    expect(document.querySelector(".topnav-inner")).toBeTruthy();
    expect(document.querySelector(".operator-shell-main-inner")).toBeTruthy();
    expect(document.querySelector(".operator-shell-main-inner-wide")).toBeNull();
    expect(document.querySelector(".operator-shell-main-inner-full")).toBeNull();
    expect(screen.getByTestId("topnav-site-selector-row")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-site-selector-global-workflow-site-selector")).toBeInTheDocument();
    const identifierContext = screen.getByTestId("topnav-context-identifiers");
    expect(identifierContext).toHaveTextContent("Site ID:");
    expect(identifierContext).toHaveTextContent("site-1");
    expect(identifierContext).toHaveTextContent("Business ID:");
    expect(identifierContext).toHaveTextContent("biz-1");
  });

  it("renders a stable account placeholder when principal context is not yet hydrated", () => {
    mockUseAuth.mockReturnValue({
      token: null,
      refreshToken: null,
      principal: null,
      clearSession: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    expect(screen.getByText("Account")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/");
    expect(screen.getByTestId("topnav-theme-toggle")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  });

  it("marks the matching top navigation link as active for nested routes", () => {
    mockUsePathname.mockReturnValue("/sites/site-1");
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    const sitesLink = screen.getByRole("link", { name: "Sites" });
    expect(sitesLink).toHaveClass("topnav-link", "is-active");
    expect(sitesLink).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveClass("is-active");
    expect(document.querySelector(".operator-shell-main-inner-full")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "User Mgmt" })).not.toBeInTheDocument();
    expect(screen.getByTestId("topnav-site-selector-row")).toBeInTheDocument();
    expect(screen.getByTestId("topnav-context-identifiers")).toHaveTextContent("site-1");
  });

  it("applies wide shell width mode for dense workflow routes", () => {
    mockUsePathname.mockReturnValue("/recommendations");
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-2",
        display_name: "Operator Two",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    expect(document.querySelector(".operator-shell-main-inner-wide")).toBeTruthy();
    expect(screen.getByTestId("topnav-site-selector-row")).toBeInTheDocument();
  });

  it("applies wide shell width mode for business profile and admin routes", () => {
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "admin-2",
        display_name: "Admin Two",
        role: "admin",
        is_active: true,
      },
      clearSession: jest.fn(),
    });

    mockUsePathname.mockReturnValue("/business-profile");
    const { rerender } = render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );
    expect(document.querySelector(".operator-shell-main-inner-wide")).toBeTruthy();

    mockUsePathname.mockReturnValue("/admin");
    rerender(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );
    expect(document.querySelector(".operator-shell-main-inner-wide")).toBeTruthy();
    expect(screen.queryByTestId("topnav-site-selector-row")).not.toBeInTheDocument();
  });

  it("updates site context and route query when site selector changes on filtered routes", () => {
    const setSelectedSiteId = jest.fn();
    mockUsePathname.mockReturnValue("/recommendations");
    mockUseSearchParams.mockReturnValue(new URLSearchParams("status=open"));
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      scopeWarning: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
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
        },
        {
          id: "site-2",
          business_id: "biz-1",
          display_name: "Secondary Site",
          base_url: "https://example.org/",
          normalized_domain: "example.org",
          is_active: true,
          is_primary: false,
          last_audit_run_id: null,
          last_audit_status: null,
          last_audit_completed_at: null,
        },
      ],
      selectedSiteId: "site-1",
      setSelectedSiteId,
      refreshSites: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    const selector = screen.getByLabelText("Site");
    fireEvent.change(selector, { target: { value: "site-2" } });

    expect(setSelectedSiteId).toHaveBeenCalledWith("site-2");
    expect(mockReplace).toHaveBeenCalledWith("/recommendations?status=open&site_id=site-2");
  });

  it("derives Business ID from the active selected site record after switching sites", () => {
    const mutableContext = {
      loading: false,
      error: null,
      scopeWarning: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
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
        },
        {
          id: "site-2",
          business_id: "biz-1",
          display_name: "Secondary Site",
          base_url: "https://example.org/",
          normalized_domain: "example.org",
          is_active: true,
          is_primary: false,
          last_audit_run_id: null,
          last_audit_status: null,
          last_audit_completed_at: null,
        },
      ],
      selectedSiteId: "site-1",
      setSelectedSiteId: jest.fn((siteId: string) => {
        mutableContext.selectedSiteId = siteId;
      }),
      refreshSites: jest.fn(),
    };
    mockUsePathname.mockReturnValue("/recommendations");
    mockUseSearchParams.mockReturnValue(new URLSearchParams("status=open"));
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });
    mockUseOperatorContext.mockImplementation(() => mutableContext);

    const { rerender } = render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    expect(screen.getByTestId("topnav-context-identifiers")).toHaveTextContent("Site ID: site-1");
    expect(screen.getByTestId("topnav-context-identifiers")).toHaveTextContent("Business ID: biz-1");

    fireEvent.change(screen.getByLabelText("Site"), { target: { value: "site-2" } });
    rerender(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    expect(screen.getByTestId("topnav-context-identifiers")).toHaveTextContent("Site ID: site-2");
    expect(screen.getByTestId("topnav-context-identifiers")).toHaveTextContent("Business ID: biz-1");
  });

  it("normalizes out-of-scope query site_id to the active authorized site", async () => {
    mockUsePathname.mockReturnValue("/recommendations");
    mockUseSearchParams.mockReturnValue(new URLSearchParams("status=open&site_id=site-999"));
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/recommendations?status=open&site_id=site-1");
    });
    expect(screen.getByTestId("topnav-context-warning")).toHaveTextContent(
      "Requested site is outside your authorized workspace scope.",
    );
  });

  it("shows persisted scope warning from operator context when available", () => {
    mockUsePathname.mockReturnValue("/dashboard");
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      scopeWarning: "Saved workspace site is no longer available in your authorized scope.",
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
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
        },
      ],
      selectedSiteId: "site-1",
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    expect(screen.getByTestId("topnav-context-warning")).toHaveTextContent(
      "Saved workspace site is no longer available in your authorized scope.",
    );
  });

  it("rejects cross-business active selection and rehydrates to an authorized site", async () => {
    const setSelectedSiteId = jest.fn();
    mockUsePathname.mockReturnValue("/recommendations");
    mockUseSearchParams.mockReturnValue(new URLSearchParams("status=open"));
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      scopeWarning: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
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
        },
        {
          id: "site-2",
          business_id: "biz-2",
          display_name: "Cross Business Site",
          base_url: "https://example.org/",
          normalized_domain: "example.org",
          is_active: true,
          is_primary: false,
          last_audit_run_id: null,
          last_audit_status: null,
          last_audit_completed_at: null,
        },
      ],
      selectedSiteId: "site-2",
      setSelectedSiteId,
      refreshSites: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    await waitFor(() => {
      expect(setSelectedSiteId).toHaveBeenCalledWith("site-1");
    });

    const selector = screen.getByLabelText("Site") as HTMLSelectElement;
    expect(Array.from(selector.options).map((option) => option.value)).toEqual(["site-1"]);
  });

  it("toggles theme mode and persists the selection locally", () => {
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    const themeToggle = screen.getByTestId("topnav-theme-toggle");
    fireEvent.click(themeToggle);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("operator-ui-theme")).toBe("dark");

    fireEvent.click(themeToggle);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("operator-ui-theme")).toBe("light");
  });

  it("applies stored light theme preference on mount", async () => {
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });
    document.documentElement.dataset.theme = "dark";
    window.localStorage.setItem("operator-ui-theme", "light");

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe("light");
    });
  });

  it("applies stored dark theme preference on mount", async () => {
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });
    document.documentElement.dataset.theme = "light";
    window.localStorage.setItem("operator-ui-theme", "dark");

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe("dark");
    });
  });

  it("replaces /sites/[site_id] route when switching site from header selector", () => {
    const setSelectedSiteId = jest.fn();
    mockUsePathname.mockReturnValue("/sites/site-1");
    mockUseAuth.mockReturnValue({
      token: "token-1",
      refreshToken: "refresh-1",
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
      clearSession: jest.fn(),
    });
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
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
        },
        {
          id: "site-2",
          business_id: "biz-1",
          display_name: "Secondary Site",
          base_url: "https://example.org/",
          normalized_domain: "example.org",
          is_active: true,
          is_primary: false,
          last_audit_run_id: null,
          last_audit_status: null,
          last_audit_completed_at: null,
        },
      ],
      selectedSiteId: "site-1",
      setSelectedSiteId,
      refreshSites: jest.fn(),
    });

    render(
      <NavShell>
        <div>content</div>
      </NavShell>,
    );

    const selector = screen.getByLabelText("Site");
    fireEvent.change(selector, { target: { value: "site-2" } });

    expect(setSelectedSiteId).toHaveBeenCalledWith("site-2");
    expect(mockReplace).toHaveBeenCalledWith("/sites/site-2");
  });
});
