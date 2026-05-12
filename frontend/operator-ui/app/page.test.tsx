import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LoginPage from "./page";

const mockPush = jest.fn();
const mockSetSession = jest.fn();
const mockExchangeGoogleIdToken = jest.fn();
const mockStartGoogleAuth = jest.fn();
const mockUseAuth = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

jest.mock("../components/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("../lib/api/client", () => {
  const actual = jest.requireActual("../lib/api/client");
  return {
    ...actual,
    startGoogleAuth: (...args: unknown[]) => mockStartGoogleAuth(...args),
    exchangeGoogleIdToken: (...args: unknown[]) => mockExchangeGoogleIdToken(...args),
  };
});

jest.mock("../components/GoogleSignIn", () => ({
  GoogleSignIn: ({
    onCredential,
  }: {
    onCredential: (credential: string) => void;
    onInitializationError?: (error: { kind: string; message: string }) => void;
  }) => (
    <button onClick={() => onCredential("google-credential")}>Mock Google Sign-In</button>
  ),
}));

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  jest.spyOn(console, "warn").mockImplementation(() => undefined);
  mockUseAuth.mockReturnValue({
    setSession: mockSetSession,
    principal: null,
  });
  mockStartGoogleAuth.mockResolvedValue({
    state: "login-state-1",
    expires_at: "2026-03-23T00:00:00Z",
    flow: "google_login_exchange",
  });
  mockExchangeGoogleIdToken.mockResolvedValue({
    access_token: "access-1",
    refresh_token: "refresh-1",
    token_type: "bearer",
    expires_at: "2026-03-23T00:00:00Z",
    refresh_expires_at: "2026-04-22T00:00:00Z",
    auth_source: "google",
    principal: {
      business_id: "biz-1",
      principal_id: "admin-1",
      display_name: "Admin One",
      role: "admin",
      is_active: true,
    },
  });
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("login page", () => {
  it("renders production-ready operator sign-in copy", async () => {
    render(<LoginPage />);

    expect(screen.getByText("My Business Sucks Right Now")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sign in to My Business Sucks Right Now" })).toBeInTheDocument();
    expect(screen.queryByText("Manual Google ID token exchange (fallback)")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Mock Google Sign-In" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute(
      "href",
      "https://www.mbsrn.com/privacy",
    );
    expect(screen.getByRole("link", { name: "Terms of Service" })).toHaveAttribute(
      "href",
      "https://www.mbsrn.com/terms",
    );
  });

  it("exchanges Google sign-in credential and redirects to dashboard", async () => {
    render(<LoginPage />);

    await waitFor(() => expect(mockStartGoogleAuth).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Mock Google Sign-In" }));

    await waitFor(() =>
      expect(mockExchangeGoogleIdToken).toHaveBeenCalledWith("google-credential", "login-state-1"),
    );
    await waitFor(() => expect(mockSetSession).toHaveBeenCalled());
    expect(mockPush).toHaveBeenCalledWith("/dashboard");
  });

  it("shows redirecting state when an authenticated principal is already present", async () => {
    mockUseAuth.mockReturnValue({
      setSession: mockSetSession,
      principal: {
        business_id: "biz-1",
        principal_id: "admin-1",
        display_name: "Admin One",
        role: "admin",
        is_active: true,
      },
    });

    render(<LoginPage />);

    expect(await screen.findByText("Finalizing your Operator Workspace session...")).toBeInTheDocument();
    expect(mockPush).toHaveBeenCalledWith("/dashboard");
  });

  it("shows initialization failure and skips exchange until a state is available", async () => {
    mockStartGoogleAuth.mockRejectedValueOnce(new Error("init failed"));

    render(<LoginPage />);

    expect(await screen.findByText("Sign-in initialization failed. Retry in a moment.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry sign-in initialization" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mock Google Sign-In" })).not.toBeInTheDocument();
    expect(mockExchangeGoogleIdToken).not.toHaveBeenCalled();
  });

  it("handles malformed auth bootstrap payloads with bounded fallback and retry", async () => {
    mockStartGoogleAuth
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({
        state: "login-state-2",
        expires_at: "2026-03-23T00:00:00Z",
        flow: "google_login_exchange",
      });
    const user = userEvent.setup();

    render(<LoginPage />);

    expect(await screen.findByText("Sign-in initialization failed. Retry in a moment.")).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: "Retry sign-in initialization" });
    expect(retryButton).toBeInTheDocument();

    await user.click(retryButton);

    await screen.findByRole("button", { name: "Mock Google Sign-In" });
    expect(mockStartGoogleAuth).toHaveBeenCalledTimes(2);
    expect(console.error).toHaveBeenCalledWith(
      "[operator-ui] root_auth_error",
      expect.objectContaining({
        route: "/",
        classification: "auth_bootstrap_invalid_response",
      }),
    );
  });
});
