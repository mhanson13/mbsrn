import { render, screen, waitFor } from "@testing-library/react";

import UserManagementPage from "./page";

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

describe("user management route", () => {
  beforeEach(() => {
    mockFetchPrincipals.mockResolvedValue({
      items: [
        {
          business_id: "biz-1",
          id: "admin-1",
          display_name: "Admin One",
          created_by_principal_id: null,
          updated_by_principal_id: null,
          role: "admin",
          is_active: true,
          last_authenticated_at: "2026-03-20T00:00:00Z",
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 1,
    });
    mockFetchPrincipalIdentities.mockResolvedValue({
      items: [
        {
          id: "identity-1",
          provider: "google",
          provider_subject: "sub-1",
          business_id: "biz-1",
          principal_id: "admin-1",
          email: "admin@example.com",
          email_verified: true,
          is_active: true,
          last_authenticated_at: "2026-03-20T00:00:00Z",
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 1,
    });
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
        principal_id: "admin-1",
        display_name: "Admin One",
        role: "admin",
        is_active: true,
      },
    });
  });

  it("renders user id management and create controls for admins", async () => {
    render(<UserManagementPage />);

    await waitFor(() => {
      expect(mockFetchPrincipals).toHaveBeenCalled();
      expect(mockFetchPrincipalIdentities).toHaveBeenCalled();
    });

    expect(screen.getByRole("heading", { name: "User Mgmt" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "User ID Management" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Create and Link Identity" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create User" })).toBeInTheDocument();
    const emailVerifiedToggle = screen.getByLabelText("Email verified");
    expect(emailVerifiedToggle).toHaveAttribute("type", "checkbox");
    expect(emailVerifiedToggle.closest("label")).toHaveClass("checkbox-chip");
    expect(screen.queryByRole("heading", { name: "Site Management" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "GCP Logs Query" })).not.toBeInTheDocument();
  });

  it("keeps user management route admin-only", () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
    });

    render(<UserManagementPage />);

    expect(screen.getByRole("heading", { name: "User Mgmt" })).toBeInTheDocument();
    expect(screen.getByText("Business administration is available to admin principals only.")).toBeInTheDocument();
  });
});
