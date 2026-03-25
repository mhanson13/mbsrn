import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import UsersCompatibilityPage from "./page";
import { ApiRequestError } from "../../lib/api/client";
import type {
  BusinessSettings,
  PrincipalIdentityListResponse,
  PrincipalListResponse,
  SEOSite,
} from "../../lib/api/types";
import {
  COMPETITOR_DIRECTORY_PENALTY_MIN,
  COMPETITOR_DIRECTORY_PENALTY_MAX,
  COMPETITOR_MIN_RELEVANCE_SCORE_MIN,
  COMPETITOR_MIN_RELEVANCE_SCORE_MAX,
  CRAWL_PAGE_LIMIT_MAX,
  CRAWL_PAGE_LIMIT_MIN,
} from "../../lib/validation/constants";

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
const mockUpdateAdminSite = jest.fn<Promise<SEOSite>, unknown[]>();
const mockDeleteAdminSite = jest.fn<Promise<void>, unknown[]>();
const INVALID_CRAWL_BELOW_MIN = CRAWL_PAGE_LIMIT_MIN - 1;
const INVALID_CRAWL_ABOVE_MAX = CRAWL_PAGE_LIMIT_MAX + 1;
const INVALID_PERSISTED_CRAWL_VALUE = CRAWL_PAGE_LIMIT_MAX + 50;
const INVALID_COMPETITOR_MIN_RELEVANCE = COMPETITOR_MIN_RELEVANCE_SCORE_MAX + 1;
const CRAWL_INPUT_RANGE_ERROR = `Crawl page limit must be an integer between ${CRAWL_PAGE_LIMIT_MIN} and ${CRAWL_PAGE_LIMIT_MAX}.`;
const CRAWL_BACKEND_RANGE_ERROR = `Crawl page limit must be between ${CRAWL_PAGE_LIMIT_MIN} and ${CRAWL_PAGE_LIMIT_MAX}.`;
const COMPETITOR_MIN_RELEVANCE_INPUT_RANGE_ERROR =
  `Minimum relevance score must be an integer between ${COMPETITOR_MIN_RELEVANCE_SCORE_MIN} and ${COMPETITOR_MIN_RELEVANCE_SCORE_MAX}.`;
const COMPETITOR_DIRECTORY_INPUT_RANGE_ERROR =
  `Directory/aggregator penalty must be an integer between ${COMPETITOR_DIRECTORY_PENALTY_MIN} and ${COMPETITOR_DIRECTORY_PENALTY_MAX}.`;

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
    updateAdminSite: (...args: unknown[]) => mockUpdateAdminSite(...args),
    deleteAdminSite: (...args: unknown[]) => mockDeleteAdminSite(...args),
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

function baseOperatorContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [buildSite()],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn<Promise<SEOSite[]>, []>().mockResolvedValue([buildSite()]),
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
    ai_prompt_text_competitor: null,
    ai_prompt_text_recommendations: null,
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

  it(`accepts crawl page limit at lower bound (${CRAWL_PAGE_LIMIT_MIN})`, async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: CRAWL_PAGE_LIMIT_MIN,
        updated_at: "2026-03-22T00:00:00Z",
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), {
      target: { value: String(CRAWL_PAGE_LIMIT_MIN) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        seo_audit_crawl_max_pages: CRAWL_PAGE_LIMIT_MIN,
      }),
    );
    await screen.findByText(`SEO crawl page limit updated to ${CRAWL_PAGE_LIMIT_MIN}.`);
  });

  it(`accepts crawl page limit at upper bound (${CRAWL_PAGE_LIMIT_MAX})`, async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: CRAWL_PAGE_LIMIT_MAX,
        updated_at: "2026-03-22T00:00:00Z",
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), {
      target: { value: String(CRAWL_PAGE_LIMIT_MAX) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        seo_audit_crawl_max_pages: CRAWL_PAGE_LIMIT_MAX,
      }),
    );
    await screen.findByText(`SEO crawl page limit updated to ${CRAWL_PAGE_LIMIT_MAX}.`);
  });

  it("saves crawl limit even when competitor quality inputs are currently invalid", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: CRAWL_PAGE_LIMIT_MAX,
        updated_at: "2026-03-22T00:00:00Z",
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Minimum Relevance Score"), {
      target: { value: String(INVALID_COMPETITOR_MIN_RELEVANCE) },
    });
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), {
      target: { value: String(CRAWL_PAGE_LIMIT_MAX) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        seo_audit_crawl_max_pages: CRAWL_PAGE_LIMIT_MAX,
      }),
    );
    await screen.findByText(`SEO crawl page limit updated to ${CRAWL_PAGE_LIMIT_MAX}.`);
  });

  it(`rejects crawl page limit below minimum (${INVALID_CRAWL_BELOW_MIN})`, async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), {
      target: { value: String(INVALID_CRAWL_BELOW_MIN) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    expect(mockUpdateBusinessSettings).not.toHaveBeenCalled();
    expect(
      screen.getByText(CRAWL_INPUT_RANGE_ERROR),
    ).toBeInTheDocument();
  });

  it(`rejects crawl page limit above maximum (${INVALID_CRAWL_ABOVE_MAX})`, async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), {
      target: { value: String(INVALID_CRAWL_ABOVE_MAX) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    expect(mockUpdateBusinessSettings).not.toHaveBeenCalled();
    expect(
      screen.getByText(CRAWL_INPUT_RANGE_ERROR),
    ).toBeInTheDocument();
  });

  it("shows crawl-specific backend validation errors in the crawl section", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockRejectedValueOnce(
      new ApiRequestError(`seo_audit_crawl_max_pages must be between ${CRAWL_PAGE_LIMIT_MIN} and ${CRAWL_PAGE_LIMIT_MAX}.`, {
        status: 422,
        detail: null,
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), {
      target: { value: String(CRAWL_PAGE_LIMIT_MAX) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await screen.findByText(CRAWL_BACKEND_RANGE_ERROR);
    expect(
      screen.queryByText("Unable to save this settings section. Please review the entered values."),
    ).not.toBeInTheDocument();
  });

  it("uses a safe fallback message for unexpected crawl validation failures", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockRejectedValueOnce(
      new ApiRequestError("validation failed", {
        status: 422,
        detail: null,
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), {
      target: { value: String(CRAWL_PAGE_LIMIT_MAX) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await screen.findByText("Unable to save SEO crawl settings. Please review the entered crawl limit.");
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

  it("shows a crawl settings health warning for invalid persisted crawl values", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockFetchBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: INVALID_PERSISTED_CRAWL_VALUE,
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    expect(screen.getByText("Settings health: Saved value is outside the allowed range.")).toBeInTheDocument();
  });

  it("shows no settings health warnings when persisted values are valid", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockFetchBusinessSettings.mockResolvedValueOnce(buildBusinessSettings());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    expect(screen.queryByText("Settings health: Saved value is outside the allowed range.")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Notification settings health: One or more saved values need review."),
    ).not.toBeInTheDocument();
  });

  it("shows notification settings health warning for invalid persisted notification values", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockFetchBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        sms_enabled: true,
        notification_phone: null,
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    expect(
      screen.getByText("Notification settings health: One or more saved values need review."),
    ).toBeInTheDocument();
  });

  it("renders plain-English helper guidance for competitor candidate quality settings", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockFetchBusinessSettings.mockResolvedValueOnce(buildBusinessSettings());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    expect(
      screen.getByText(
        "Controls how closely a competitor must match your business to be included. Higher values mean stricter, more relevant matches.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Reduces the chance that large national or big-box companies appear as competitors. Increase this to focus more on businesses like yours.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Reduces listings from directories or lead sites (like Yelp, Angi, etc.). Increase this to prioritize real business websites instead.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Boosts competitors that are located in or serve your area. Increase this to focus more on nearby businesses.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Raise this if competitors feel unrelated. Lower it if you are getting too few results.")).toBeInTheDocument();
    expect(screen.getByText("Raise this if large companies dominate your results.")).toBeInTheDocument();
    expect(screen.getByText("Raise this if you see too many directory or listing sites.")).toBeInTheDocument();
    expect(screen.getByText("Raise this if competitors are not local enough.")).toBeInTheDocument();
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

  it("does not block crawl saves when competitor quality persisted values are invalid", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockFetchBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        competitor_candidate_min_relevance_score: INVALID_COMPETITOR_MIN_RELEVANCE,
      }),
    );
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: 50,
        competitor_candidate_min_relevance_score: INVALID_COMPETITOR_MIN_RELEVANCE,
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    expect(screen.getByText("Settings health: One or more saved values need review.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        seo_audit_crawl_max_pages: 50,
      }),
    );
    await screen.findByText("SEO crawl page limit updated to 50.");
  });

  it("rejects competitor quality values outside allowed bounds", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Minimum Relevance Score"), {
      target: { value: String(INVALID_COMPETITOR_MIN_RELEVANCE) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Candidate Quality Settings" }));

    expect(mockUpdateBusinessSettings).not.toHaveBeenCalled();
    expect(
      screen.getByText(COMPETITOR_MIN_RELEVANCE_INPUT_RANGE_ERROR),
    ).toBeInTheDocument();
  });

  it("shows competitor-quality field-specific backend validation errors in the competitor section", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockRejectedValueOnce(
      new ApiRequestError(
        `competitor_candidate_directory_penalty must be between ${COMPETITOR_DIRECTORY_PENALTY_MIN} and ${COMPETITOR_DIRECTORY_PENALTY_MAX}.`,
        {
        status: 422,
        detail: null,
        },
      ),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Minimum Relevance Score"), { target: { value: "45" } });
    fireEvent.change(screen.getByLabelText("Big-Box Mismatch Penalty"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("Directory/Aggregator Penalty"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Local Alignment Bonus"), { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Candidate Quality Settings" }));

    await screen.findByText(COMPETITOR_DIRECTORY_INPUT_RANGE_ERROR);
    expect(screen.queryByText(CRAWL_BACKEND_RANGE_ERROR)).not.toBeInTheDocument();
  });

  it("clears crawl-section error after a subsequent valid crawl save", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings
      .mockRejectedValueOnce(
        new ApiRequestError("validation failed", {
          status: 422,
          detail: null,
        }),
      )
      .mockResolvedValueOnce(
        buildBusinessSettings({
          seo_audit_crawl_max_pages: CRAWL_PAGE_LIMIT_MAX,
          updated_at: "2026-03-22T00:00:00Z",
        }),
      );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), {
      target: { value: String(CRAWL_PAGE_LIMIT_MAX) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));
    await screen.findByText("Unable to save SEO crawl settings. Please review the entered crawl limit.");

    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));
    await screen.findByText(`SEO crawl page limit updated to ${CRAWL_PAGE_LIMIT_MAX}.`);
    await waitFor(() =>
      expect(
        screen.queryByText("Unable to save SEO crawl settings. Please review the entered crawl limit."),
      ).not.toBeInTheDocument(),
    );
  });

  it("clears crawl settings health warning after saving a valid crawl value", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockFetchBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: INVALID_PERSISTED_CRAWL_VALUE,
      }),
    );
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: 80,
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    expect(screen.getByText("Settings health: Saved value is outside the allowed range.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Crawl Limit" }));

    await screen.findByText("SEO crawl page limit updated to 80.");
    await waitFor(() =>
      expect(
        screen.queryByText("Settings health: Saved value is outside the allowed range."),
      ).not.toBeInTheDocument(),
    );
  });

  it("saves competitor quality settings even when crawl input is currently invalid", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        seo_audit_crawl_max_pages: 25,
        competitor_candidate_min_relevance_score: 45,
        competitor_candidate_big_box_penalty: 25,
        competitor_candidate_directory_penalty: 30,
        competitor_candidate_local_alignment_bonus: 15,
        updated_at: "2026-03-22T00:00:00Z",
      }),
    );

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.change(screen.getByLabelText("Crawl Page Limit"), {
      target: { value: String(INVALID_CRAWL_ABOVE_MAX) },
    });
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

  it("updates admin-managed AI prompt overrides", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        ai_prompt_text_competitor: "Prefer local and substitutable competitors.",
        ai_prompt_text_recommendations: "Prioritize specific next-step recommendations.",
      }),
    );

    const user = userEvent.setup();
    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    await user.clear(screen.getByLabelText("Competitor Prompt"));
    await user.type(
      screen.getByLabelText("Competitor Prompt"),
      "Prefer local and substitutable competitors.",
    );
    await user.clear(screen.getByLabelText("Recommendations Prompt"));
    await user.type(
      screen.getByLabelText("Recommendations Prompt"),
      "Prioritize specific next-step recommendations.",
    );
    await user.click(screen.getByRole("button", { name: "Save Prompt Overrides" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        ai_prompt_text_competitor: "Prefer local and substitutable competitors.",
        ai_prompt_text_recommendations: "Prioritize specific next-step recommendations.",
      }),
    );
    await screen.findByText("AI prompt overrides updated.");
  });

  it("clears AI prompt overrides back to deployment/default fallback", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    mockFetchBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        ai_prompt_text_competitor: "Existing competitor prompt override.",
        ai_prompt_text_recommendations: "Existing recommendation prompt override.",
      }),
    );
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        ai_prompt_text_competitor: null,
        ai_prompt_text_recommendations: null,
      }),
    );

    const user = userEvent.setup();
    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    expect(screen.getAllByText("Business admin override")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Use Deployment Fallbacks" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        ai_prompt_text_competitor: null,
        ai_prompt_text_recommendations: null,
      }),
    );
    await screen.findByText("AI prompt overrides cleared. Deployment fallback/default is now active.");
    expect(screen.getAllByText("Deployment/default fallback")).toHaveLength(2);
  });

  it("renders admin site edit and permanent delete controls", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    expect(screen.getByRole("heading", { name: "Site Management" })).toBeInTheDocument();
    const siteRow = screen.getByText("example.com").closest("tr");
    expect(siteRow).not.toBeNull();
    const scoped = within(siteRow as HTMLTableRowElement);
    expect(scoped.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(scoped.getByRole("button", { name: "Delete Permanently" })).toBeInTheDocument();
  });

  it("requires typed confirmation for permanent delete and removes the site from view", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    const contextValue = baseOperatorContext({ sites: [buildSite()] });
    contextValue.refreshSites.mockImplementation(async () => {
      contextValue.sites = [];
      return [];
    });
    mockUseOperatorContext.mockImplementation(() => contextValue);
    mockDeleteAdminSite.mockResolvedValueOnce();
    const promptSpy = jest.spyOn(window, "prompt").mockReturnValue("Main Site");

    render(<UsersCompatibilityPage />);

    await screen.findByText("operator-1");
    fireEvent.click(screen.getByRole("button", { name: "Delete Permanently" }));

    await waitFor(() => expect(mockDeleteAdminSite).toHaveBeenCalledWith("token-1", "biz-1", "site-1"));
    await waitFor(() => expect(screen.getByText("No sites found for this business.")).toBeInTheDocument());
    promptSpy.mockRestore();
  });
});
