import { render, screen, waitFor } from "@testing-library/react";
import { useRef } from "react";

import { AuthProvider, useAuth } from "./AuthProvider";

function AuthProbe() {
  const { token, principal } = useAuth();
  const firstTokenRef = useRef(token);
  const firstPrincipalRef = useRef(principal?.principal_id ?? null);

  return (
    <div
      data-testid="auth-probe"
      data-first-token={firstTokenRef.current ?? "null"}
      data-first-principal={firstPrincipalRef.current ?? "null"}
      data-current-token={token ?? "null"}
      data-current-principal={principal?.principal_id ?? "null"}
    />
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("hydrates session values after mount while keeping first render unauthenticated", async () => {
    window.sessionStorage.setItem("mbsrn.operator.access_token", "token-1");
    window.sessionStorage.setItem(
      "mbsrn.operator.principal",
      JSON.stringify({
        business_id: "biz-1",
        principal_id: "principal-1",
        display_name: "Operator One",
        role: "admin",
        is_active: true,
      }),
    );

    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );

    const probe = screen.getByTestId("auth-probe");
    expect(probe).toHaveAttribute("data-first-token", "null");
    expect(probe).toHaveAttribute("data-first-principal", "null");

    await waitFor(() => {
      expect(probe).toHaveAttribute("data-current-token", "token-1");
      expect(probe).toHaveAttribute("data-current-principal", "principal-1");
    });
  });
});
