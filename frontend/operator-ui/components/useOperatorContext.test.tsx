import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { useOperatorContext } from "./useOperatorContext";

const mockPush = jest.fn();
const mockUseAuth = jest.fn();
const mockFetchSites = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

jest.mock("./AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("../lib/api/client", () => ({
  fetchSites: (...args: unknown[]) => mockFetchSites(...args),
}));

const SITE_STORAGE_KEY = "mbsrn.operator.selected_site_id.biz-1";

const DEFAULT_SITE_RESPONSE = {
  items: [
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
  total: 2,
};

function seedFetchSites(response = DEFAULT_SITE_RESPONSE) {
  mockFetchSites.mockImplementation(() =>
    new Promise((resolve) => {
      setTimeout(() => resolve(response), 0);
    }),
  );
}

function OperatorContextProbe() {
  const context = useOperatorContext();
  return (
    <div>
      <p data-testid="selected-site-id">{context.selectedSiteId || "none"}</p>
      <p data-testid="business-id">{context.businessId || "none"}</p>
      <p data-testid="sites-count">{context.sites.length}</p>
      <p data-testid="scope-warning">{context.scopeWarning || "none"}</p>
      <button type="button" onClick={() => context.setSelectedSiteId("site-2")}>
        Select Site 2
      </button>
    </div>
  );
}

describe("useOperatorContext", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.sessionStorage.clear();
    window.localStorage.clear();
    mockUseAuth.mockReturnValue({
      token: "token-1",
      principal: {
        business_id: "biz-1",
        principal_id: "principal-1",
        display_name: "Operator",
        role: "admin",
        is_active: true,
      },
      clearSession: jest.fn(),
    });
    seedFetchSites();
  });

  it("persists selected site across remount/navigation", async () => {
    const firstRender = render(<OperatorContextProbe />);
    await waitFor(() => {
      expect(screen.getByTestId("selected-site-id")).toHaveTextContent("site-1");
    });

    fireEvent.click(screen.getByRole("button", { name: "Select Site 2" }));
    await waitFor(() => {
      expect(screen.getByTestId("selected-site-id")).toHaveTextContent("site-2");
    });
    expect(window.localStorage.getItem(SITE_STORAGE_KEY)).toBe("site-2");
    expect(window.sessionStorage.getItem(SITE_STORAGE_KEY)).toBe("site-2");

    firstRender.unmount();

    render(<OperatorContextProbe />);
    await waitFor(() => {
      expect(screen.getByTestId("selected-site-id")).toHaveTextContent("site-2");
    });
    expect(screen.getByTestId("business-id")).toHaveTextContent("biz-1");
  });

  it("restores selected site from localStorage when available", async () => {
    window.localStorage.setItem(SITE_STORAGE_KEY, "site-2");

    render(<OperatorContextProbe />);
    await waitFor(() => {
      expect(screen.getByTestId("selected-site-id")).toHaveTextContent("site-2");
    });
  });

  it("falls back safely when persisted site is invalid", async () => {
    window.localStorage.setItem(SITE_STORAGE_KEY, "missing-site");
    window.sessionStorage.setItem(SITE_STORAGE_KEY, "missing-site");

    render(<OperatorContextProbe />);
    await waitFor(() => {
      expect(screen.getByTestId("selected-site-id")).toHaveTextContent("site-1");
    });
    await waitFor(() => {
      expect(screen.getByTestId("scope-warning")).toHaveTextContent(
        "Saved workspace site is no longer available in your authorized scope.",
      );
    });
  });

  it("filters out cross-business sites and rejects invalid manual selection attempts", async () => {
    seedFetchSites({
      items: [
        DEFAULT_SITE_RESPONSE.items[0],
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
      total: 2,
    });

    render(<OperatorContextProbe />);
    await waitFor(() => {
      expect(screen.getByTestId("selected-site-id")).toHaveTextContent("site-1");
    });

    expect(screen.getByTestId("sites-count")).toHaveTextContent("1");
    expect(screen.getByTestId("scope-warning")).toHaveTextContent(
      "Some sites were hidden because they are outside your authorized business scope.",
    );

    fireEvent.click(screen.getByRole("button", { name: "Select Site 2" }));
    expect(screen.getByTestId("selected-site-id")).toHaveTextContent("site-1");
    expect(screen.getByTestId("scope-warning")).toHaveTextContent(
      "Selected workspace site is unavailable in your authorized scope.",
    );
  });
});
