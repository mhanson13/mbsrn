import { render, screen } from "@testing-library/react";

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

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../components/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

describe("admin route", () => {
  beforeEach(() => {
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

  it("renders the admin page shell at /admin", () => {
    render(<AdminPage />);

    expect(screen.getByRole("heading", { name: "Admin" })).toBeInTheDocument();
    expect(screen.getByText("Business administration is available to admin principals only.")).toBeInTheDocument();
    expect(document.querySelector(".page-container-width-wide")).toBeTruthy();
  });

  it("keeps /users as a compatibility alias", () => {
    expect(UsersCompatibilityPage).toBe(AdminPage);
  });
});
