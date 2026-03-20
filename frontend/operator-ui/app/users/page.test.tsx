import { render, screen } from "@testing-library/react";

import UsersPage from "./page";
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
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
    expect(screen.getByText("operator@example.com")).toBeInTheDocument();
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
});
