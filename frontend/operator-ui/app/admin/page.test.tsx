import { render, screen, waitFor } from "@testing-library/react";

import AdminPage from "./page";
import UsersCompatibilityPage from "../users/page";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: Array<{
    id: string;
    business_id: string;
    display_name: string;
    base_url: string;
    normalized_domain: string;
    is_active: boolean;
    is_primary: boolean;
    last_audit_run_id: string | null;
    last_audit_status: string | null;
    last_audit_completed_at: string | null;
  }>;
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockUseAuth = jest.fn();
const mockFetchPrincipals = jest.fn();
const mockFetchPrincipalIdentities = jest.fn();
const mockFetchBusinessSettings = jest.fn();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../components/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("../../lib/api/client", () => ({
  ApiRequestError: class extends Error {
    status: number;

    constructor(message: string, status = 500) {
      super(message);
      this.status = status;
    }
  },
  activatePrincipalIdentity: jest.fn(),
  activatePrincipal: jest.fn(),
  createPrincipalIdentity: jest.fn(),
  createPrincipal: jest.fn(),
  deactivatePrincipalIdentity: jest.fn(),
  deactivatePrincipal: jest.fn(),
  deleteAdminSite: jest.fn(),
  queryGcpLogs: jest.fn(),
  updateAdminSite: jest.fn(),
  updateBusinessSettings: jest.fn(),
  fetchPrincipalIdentities: (...args: unknown[]) => mockFetchPrincipalIdentities(...args),
  fetchPrincipals: (...args: unknown[]) => mockFetchPrincipals(...args),
  fetchBusinessSettings: (...args: unknown[]) => mockFetchBusinessSettings(...args),
}));

describe("admin route", () => {
  beforeEach(() => {
    mockFetchPrincipals.mockResolvedValue({ items: [], total: 0 });
    mockFetchPrincipalIdentities.mockResolvedValue({ items: [], total: 0 });
    mockFetchBusinessSettings.mockResolvedValue({
      id: "biz-1",
      name: "Biz",
      notification_phone: null,
      notification_email: null,
      sms_enabled: false,
      email_enabled: false,
      customer_auto_ack_enabled: false,
      contractor_alerts_enabled: false,
      seo_audit_crawl_max_pages: 200,
      competitor_candidate_min_relevance_score: 30,
      competitor_candidate_big_box_penalty: 20,
      competitor_candidate_directory_penalty: 20,
      competitor_candidate_local_alignment_bonus: 10,
      competitor_primary_timeout_seconds: null,
      competitor_degraded_timeout_seconds: null,
      ai_prompt_text_competitor: null,
      ai_prompt_text_recommendations: null,
      timezone: "UTC",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [],
      selectedSiteId: null,
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
    });
  });

  it("renders the admin page shell at /admin for non-admin principals", () => {
    render(<AdminPage />);

    expect(screen.getByRole("heading", { name: "Admin" })).toBeInTheDocument();
    expect(screen.getByText("Business administration is available to admin principals only.")).toBeInTheDocument();
    expect(document.querySelector(".page-container-width-wide")).toBeTruthy();
  });

  it("renders admin settings sections without user management blocks", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-1",
        display_name: "Admin One",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    await waitFor(() => {
      expect(mockFetchPrincipals).not.toHaveBeenCalled();
      expect(mockFetchPrincipalIdentities).not.toHaveBeenCalled();
      expect(mockFetchBusinessSettings).toHaveBeenCalled();
    });

    const wrappedSectionHeadings = [
      "SEO Crawl Settings",
      "AI Competitor Candidate Quality",
      "AI Competitor Generation Timeouts",
      "AI Prompt Overrides",
      "Site Management",
      "GCP Logs Query",
      "Admin Console",
    ];
    wrappedSectionHeadings.forEach((heading) => {
      const headingNode = screen.getByRole("heading", { name: heading });
      const section = headingNode.closest("section");
      expect(section).not.toBeNull();
      expect(section).toHaveClass("section-card");
    });

    expect(screen.queryByRole("heading", { name: "User ID Management" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create User" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create and Link Identity" })).not.toBeInTheDocument();
    expect(screen.getByText("Platform operations tools for diagnostics, site maintenance, and safe configuration updates.")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Search Console Property" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Search Console Enabled" })).toBeInTheDocument();
    expect(
      screen.getByText('severity="ERROR" resource.labels.namespace_name="mbsrn" -textPayload =~ "INFO*"'),
    ).toBeInTheDocument();
  });

  it("keeps /users as a compatibility route", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-2",
        display_name: "Admin Two",
        role: "admin",
        is_active: true,
      },
    });
    render(<UsersCompatibilityPage />);
    expect(screen.getByRole("heading", { name: "Admin Overview" })).toBeInTheDocument();
    await waitFor(() => {
      expect(mockFetchPrincipals).toHaveBeenCalled();
      expect(mockFetchPrincipalIdentities).toHaveBeenCalled();
    });
  });
});
