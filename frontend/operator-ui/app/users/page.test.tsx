import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import UsersCompatibilityPage from "./page";
import { ApiRequestError } from "../../lib/api/client";
import type { BusinessSettings, PrincipalIdentityListResponse, PrincipalListResponse } from "../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockUseAuth = jest.fn();
const mockFetchPrincipals = jest.fn<Promise<PrincipalListResponse>, unknown[]>();
const mockFetchPrincipalIdentities = jest.fn<Promise<PrincipalIdentityListResponse>, unknown[]>();
const mockFetchBusinessSettings = jest.fn<Promise<BusinessSettings>, unknown[]>();
const mockUpdateBusinessSettings = jest.fn<Promise<BusinessSettings>, unknown[]>();
const mockCreatePrincipal = jest.fn<Promise<unknown>, unknown[]>();
const mockCreatePrincipalIdentity = jest.fn<Promise<unknown>, unknown[]>();
const mockDeactivatePrincipal = jest.fn<Promise<unknown>, unknown[]>();
const mockActivatePrincipal = jest.fn<Promise<unknown>, unknown[]>();
const mockDeactivatePrincipalIdentity = jest.fn<Promise<unknown>, unknown[]>();
const mockActivatePrincipalIdentity = jest.fn<Promise<unknown>, unknown[]>();

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
    fetchPrincipals: (...args: unknown[]) => mockFetchPrincipals(...args),
    fetchPrincipalIdentities: (...args: unknown[]) => mockFetchPrincipalIdentities(...args),
    fetchBusinessSettings: (...args: unknown[]) => mockFetchBusinessSettings(...args),
    updateBusinessSettings: (...args: unknown[]) => mockUpdateBusinessSettings(...args),
    createPrincipal: (...args: unknown[]) => mockCreatePrincipal(...args),
    createPrincipalIdentity: (...args: unknown[]) => mockCreatePrincipalIdentity(...args),
    deactivatePrincipal: (...args: unknown[]) => mockDeactivatePrincipal(...args),
    activatePrincipal: (...args: unknown[]) => mockActivatePrincipal(...args),
    deactivatePrincipalIdentity: (...args: unknown[]) => mockDeactivatePrincipalIdentity(...args),
    activatePrincipalIdentity: (...args: unknown[]) => mockActivatePrincipalIdentity(...args),
  };
});

function baseOperatorContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    ...overrides,
  };
}

function buildBusinessSettings(overrides: Partial<BusinessSettings> = {}): BusinessSettings {
  return {
    id: "biz-1",
    name: "Business One",
    notification_phone: "+13035550100",
    notification_email: "owner@example.com",
    sms_enabled: true,
    email_enabled: true,
    customer_auto_ack_enabled: true,
    contractor_alerts_enabled: true,
    seo_audit_crawl_max_pages: 25,
    competitor_candidate_min_relevance_score: 35,
    competitor_candidate_big_box_penalty: 20,
    competitor_candidate_directory_penalty: 35,
    competitor_candidate_local_alignment_bonus: 10,
    timezone: "America/Denver",
    created_at: "2026-03-20T00:00:00Z",
    updated_at: "2026-03-20T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockUseOperatorContext.mockReturnValue(baseOperatorContext());
  mockUseAuth.mockReturnValue({
    principal: {
      business_id: "biz-1",
      principal_id: "admin-1",
      display_name: "Admin One",
      role: "admin",
      is_active: true,
    },
  });
  mockFetchBusinessSettings.mockResolvedValue(buildBusinessSettings());
});

function principalsResponse(isOperatorActive: boolean): PrincipalListResponse {
  return {
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
      {
        business_id: "biz-1",
        id: "operator-1",
        display_name: "Operator One",
        created_by_principal_id: "admin-1",
        updated_by_principal_id: "admin-1",
        role: "operator",
        is_active: isOperatorActive,
        last_authenticated_at: null,
        created_at: "2026-03-20T00:00:00Z",
        updated_at: "2026-03-20T00:00:00Z",
      },
    ],
    total: 2,
  };
}

function identitiesResponse(isOperatorIdentityActive: boolean = true): PrincipalIdentityListResponse {
  return {
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
      {
        id: "identity-2",
        provider: "google",
        provider_subject: "sub-2",
        business_id: "biz-1",
        principal_id: "operator-1",
        email: "operator@example.com",
        email_verified: true,
        is_active: isOperatorIdentityActive,
        last_authenticated_at: null,
        created_at: "2026-03-20T00:00:00Z",
        updated_at: "2026-03-20T00:00:00Z",
      },
    ],
    total: 2,
  };
}

describe("admin page compatibility route", () => {
  it("renders all principals and identity completeness details", async () => {
    mockFetchPrincipals.mockResolvedValueOnce({
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
        {
          business_id: "biz-1",
          id: "operator-1",
          display_name: "Operator One",
          created_by_principal_id: "admin-1",
          updated_by_principal_id: "admin-1",
          role: "operator",
          is_active: true,
          last_authenticated_at: null,
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
        {
          business_id: "biz-1",
          id: "inactive-1",
          display_name: "Inactive One",
          created_by_principal_id: "admin-1",
          updated_by_principal_id: "admin-1",
          role: "operator",
          is_active: false,
          last_authenticated_at: null,
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 3,
    });

    mockFetchPrincipalIdentities.mockResolvedValueOnce({
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
        {
          id: "identity-2",
          provider: "google",
          provider_subject: "sub-2",
          business_id: "biz-1",
          principal_id: "operator-1",
          email: "operator@example.com",
          email_verified: true,
          is_active: true,
          last_authenticated_at: null,
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 2,
    });

    render(<UsersCompatibilityPage />);

    await screen.findByText("inactive-1");
    expect(screen.getByText("Principals: 3")).toBeInTheDocument();
    expect(screen.getByText("Sign-In Identities: 2")).toBeInTheDocument();
    expect(screen.getByText("Principals Without Identity: 1")).toBeInTheDocument();
    expect(screen.getByText(/admin@example\.com/)).toBeInTheDocument();
    expect(screen.getByText(/operator@example\.com/)).toBeInTheDocument();
  });

  it("still renders principal rows when identity fetch fails", async () => {
    mockFetchPrincipals.mockResolvedValueOnce({
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
    mockFetchPrincipalIdentities.mockRejectedValueOnce(new Error("identity service unavailable"));

    render(<UsersCompatibilityPage />);

    await screen.findByText("admin-1");
    expect(screen.getByText("Sign-in identity details are temporarily unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Principals: 1")).toBeInTheDocument();
  });

  it("requires confirmation before deactivating a user", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.click(screen.getAllByRole("button", { name: "Deactivate" })[1]);

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockDeactivatePrincipal).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("deactivates a user and refreshes list state", async () => {
    mockFetchPrincipals
      .mockResolvedValueOnce(principalsResponse(true))
      .mockResolvedValueOnce(principalsResponse(false));
    mockFetchPrincipalIdentities
      .mockResolvedValueOnce(identitiesResponse())
      .mockResolvedValueOnce(identitiesResponse());
    mockDeactivatePrincipal.mockResolvedValueOnce({
      ...principalsResponse(false).items[1],
    });
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.click(screen.getAllByRole("button", { name: "Deactivate" })[1]);

    await waitFor(() => expect(mockDeactivatePrincipal).toHaveBeenCalledWith("token-1", "biz-1", "operator-1"));
    await screen.findByText("Principal action: User operator-1 deactivated.");
    expect(screen.getByRole("button", { name: "Reactivate" })).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("requires confirmation before deactivating an identity", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.click(screen.getAllByRole("button", { name: "Deactivate Identity" })[1]);

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockDeactivatePrincipalIdentity).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("deactivates an identity and refreshes list state", async () => {
    mockFetchPrincipals
      .mockResolvedValueOnce(principalsResponse(true))
      .mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities
      .mockResolvedValueOnce(identitiesResponse(true))
      .mockResolvedValueOnce(identitiesResponse(false));
    mockDeactivatePrincipalIdentity.mockResolvedValueOnce({
      ...identitiesResponse(false).items[1],
    });
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.click(screen.getAllByRole("button", { name: "Deactivate Identity" })[1]);

    await waitFor(() =>
      expect(mockDeactivatePrincipalIdentity).toHaveBeenCalledWith("token-1", "biz-1", "identity-2"),
    );
    await screen.findByText("Identity action: Identity operator@example.com deactivated.");
    expect(screen.getByText("operator@example.com (inactive)")).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("creates and links a sign-in identity to a selected principal", async () => {
    mockFetchPrincipals
      .mockResolvedValueOnce(principalsResponse(true))
      .mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities
      .mockResolvedValueOnce(identitiesResponse())
      .mockResolvedValueOnce({
        items: [
          ...identitiesResponse().items,
          {
            id: "identity-3",
            provider: "google",
            provider_subject: "sub-3",
            business_id: "biz-1",
            principal_id: "operator-1",
            email: "operator-new@example.com",
            email_verified: true,
            is_active: true,
            last_authenticated_at: null,
            created_at: "2026-03-21T00:00:00Z",
            updated_at: "2026-03-21T00:00:00Z",
          },
        ],
        total: 3,
      });
    mockCreatePrincipalIdentity.mockResolvedValueOnce({
      id: "identity-3",
      provider: "google",
      provider_subject: "sub-3",
      business_id: "biz-1",
      principal_id: "operator-1",
      email: "operator-new@example.com",
      email_verified: true,
      is_active: true,
      last_authenticated_at: null,
      created_at: "2026-03-21T00:00:00Z",
      updated_at: "2026-03-21T00:00:00Z",
    });

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Principal"), { target: { value: "operator-1" } });
    fireEvent.change(screen.getByLabelText("Provider Subject"), { target: { value: "sub-3" } });
    fireEvent.change(screen.getByLabelText("Email (optional)"), { target: { value: "operator-new@example.com" } });
    fireEvent.click(screen.getByLabelText("Email verified"));
    fireEvent.click(screen.getByRole("button", { name: "Create and Link Identity" }));

    await waitFor(() =>
      expect(mockCreatePrincipalIdentity).toHaveBeenCalledWith("token-1", "biz-1", {
        provider: "google",
        provider_subject: "sub-3",
        principal_id: "operator-1",
        email: "operator-new@example.com",
        email_verified: true,
        is_active: true,
      }),
    );
    await screen.findByText('Identity linked to principal "operator-1".');
    expect(screen.getByText("operator-new@example.com (active)")).toBeInTheDocument();
  });

  it("prevents duplicate identity linking when mapping already exists", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Principal"), { target: { value: "operator-1" } });
    fireEvent.change(screen.getByLabelText("Provider Subject"), { target: { value: "sub-2" } });

    expect(screen.getByText("This identity is already linked to the selected principal.")).toBeInTheDocument();
    const submitButton = screen.getByRole("button", { name: "Create and Link Identity" });
    expect(submitButton).toBeDisabled();
    fireEvent.click(submitButton);
    expect(mockCreatePrincipalIdentity).not.toHaveBeenCalled();
  });

  it("shows a safe error when create and link fails", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockCreatePrincipalIdentity.mockRejectedValueOnce(
      new ApiRequestError("Identity subject is already mapped to a different principal.", {
        status: 422,
        detail: null,
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Principal"), { target: { value: "operator-1" } });
    fireEvent.change(screen.getByLabelText("Provider Subject"), { target: { value: "sub-3" } });
    fireEvent.click(screen.getByRole("button", { name: "Create and Link Identity" }));

    await screen.findByText(
      "Unable to create sign-in identity. Verify provider, subject, and principal mapping.",
    );
    expect(screen.queryByText("Identity subject is already mapped to a different principal.")).not.toBeInTheDocument();
  });

  it("hides user management controls for non-admin principals", () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "operator-2",
        display_name: "Operator Two",
        role: "operator",
        is_active: true,
      },
    });

    render(<UsersCompatibilityPage />);

    expect(screen.getByText("Business administration is available to admin principals only.")).toBeInTheDocument();
    expect(screen.queryByText("Create User")).not.toBeInTheDocument();
    expect(screen.queryByText("Create and Link Identity")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deactivate Identity" })).not.toBeInTheDocument();
  });

  it("updates the SEO crawl page limit for admins", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: 80,
        updated_at: "2026-03-22T00:00:00Z",
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        seo_audit_crawl_max_pages: 80,
      }),
    );
    await screen.findByText("SEO crawl page limit updated to 80.");
  });

  it("accepts crawl page limit at lower bound (5)", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: 5,
        updated_at: "2026-03-22T00:00:00Z",
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        seo_audit_crawl_max_pages: 5,
      }),
    );
    await screen.findByText("SEO crawl page limit updated to 5.");
  });

  it("accepts crawl page limit at upper bound (250)", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: 250,
        updated_at: "2026-03-22T00:00:00Z",
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        seo_audit_crawl_max_pages: 250,
      }),
    );
    await screen.findByText("SEO crawl page limit updated to 250.");
  });

  it("rejects crawl page limit below minimum (4)", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    expect(mockUpdateBusinessSettings).not.toHaveBeenCalled();
    expect(
      screen.getByText("Crawl page limit must be an integer between 5 and 250."),
    ).toBeInTheDocument();
  });

  it("rejects crawl page limit above maximum (251)", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), { target: { value: "251" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    expect(mockUpdateBusinessSettings).not.toHaveBeenCalled();
    expect(
      screen.getByText("Crawl page limit must be an integer between 5 and 250."),
    ).toBeInTheDocument();
  });

  it("shows competitor quality tuning values from business settings", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockFetchBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        competitor_candidate_min_relevance_score: 42,
        competitor_candidate_big_box_penalty: 18,
        competitor_candidate_directory_penalty: 31,
        competitor_candidate_local_alignment_bonus: 12,
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    expect(screen.getByLabelText("Minimum Relevance Score")).toHaveValue(42);
    expect(screen.getByLabelText("Big-Box Mismatch Penalty")).toHaveValue(18);
    expect(screen.getByLabelText("Directory/Aggregator Penalty")).toHaveValue(31);
    expect(screen.getByLabelText("Local Alignment Bonus")).toHaveValue(12);
  });

  it("updates competitor candidate quality settings for admins", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        competitor_candidate_min_relevance_score: 45,
        competitor_candidate_big_box_penalty: 25,
        competitor_candidate_directory_penalty: 30,
        competitor_candidate_local_alignment_bonus: 15,
        updated_at: "2026-03-22T00:00:00Z",
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Minimum Relevance Score"), { target: { value: "45" } });
    fireEvent.change(screen.getByLabelText("Big-Box Mismatch Penalty"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("Directory/Aggregator Penalty"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Local Alignment Bonus"), { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Candidate Quality Settings" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        competitor_candidate_min_relevance_score: 45,
        competitor_candidate_big_box_penalty: 25,
        competitor_candidate_directory_penalty: 30,
        competitor_candidate_local_alignment_bonus: 15,
      }),
    );
    await screen.findByText("AI competitor candidate quality settings updated.");
  });

  it("rejects competitor quality values outside allowed bounds", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Minimum Relevance Score"), { target: { value: "101" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Candidate Quality Settings" }));

    expect(mockUpdateBusinessSettings).not.toHaveBeenCalled();
    expect(
      screen.getByText("Minimum relevance score must be an integer between 0 and 100."),
    ).toBeInTheDocument();
  });
});
