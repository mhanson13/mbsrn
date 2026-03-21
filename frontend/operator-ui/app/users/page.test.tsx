import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import UsersPage from "./page";
import { ApiRequestError } from "../../lib/api/client";
import type { PrincipalIdentityListResponse, PrincipalListResponse } from "../../lib/api/types";

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

describe("users page completeness", () => {
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

    render(<UsersPage />);

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

    render(<UsersPage />);

    await screen.findByText("admin-1");
    expect(screen.getByText("Sign-in identity details are temporarily unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Principals: 1")).toBeInTheDocument();
  });

  it("requires confirmation before deactivating a user", async () => {
    mockFetchPrincipals.mockResolvedValueOnce(principalsResponse(true));
    mockFetchPrincipalIdentities.mockResolvedValueOnce(identitiesResponse());
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);

    render(<UsersPage />);

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

    render(<UsersPage />);

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

    render(<UsersPage />);

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

    render(<UsersPage />);

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

    render(<UsersPage />);

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

    render(<UsersPage />);

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

    render(<UsersPage />);

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

    render(<UsersPage />);

    expect(screen.getByText("User administration is available to admin principals only.")).toBeInTheDocument();
    expect(screen.queryByText("Create User")).not.toBeInTheDocument();
    expect(screen.queryByText("Create and Link Identity")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deactivate Identity" })).not.toBeInTheDocument();
  });
});
