import { render, screen } from "@testing-library/react";

import { NavShell } from "./NavShell";

const mockUsePathname = jest.fn<string, []>();
const mockUseAuth = jest.fn();

jest.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

jest.mock("./AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("../lib/api/client", () => ({
  logoutSession: jest.fn(),
}));

describe("NavShell", () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue("/dashboard");
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
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    expect(document.querySelectorAll(".topnav-links")).toHaveLength(1);
    expect(document.querySelector(".topnav-inner")).toBeTruthy();
    expect(document.querySelector(".operator-shell-main-inner")).toBeTruthy();
    expect(document.querySelector(".operator-shell-main-inner-wide")).toBeNull();
    expect(document.querySelector(".operator-shell-main-inner-full")).toBeNull();
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
  });
});
