import { fireEvent, render, screen } from "@testing-library/react";

import RouteErrorBoundary from "./error";

const mockUsePathname = jest.fn(() => "/sites/site-1");
const ORIGINAL_PUBLIC_APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION;

jest.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

describe("app route error boundary", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    process.env.NEXT_PUBLIC_APP_VERSION = "sha-test-build-1";
    mockUsePathname.mockReturnValue("/sites/site-1");
  });

  afterAll(() => {
    if (ORIGINAL_PUBLIC_APP_VERSION === undefined) {
      delete process.env.NEXT_PUBLIC_APP_VERSION;
      return;
    }
    process.env.NEXT_PUBLIC_APP_VERSION = ORIGINAL_PUBLIC_APP_VERSION;
  });

  it("renders fallback safely and logs when error object is missing", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);
    const reset = jest.fn();

    render(<RouteErrorBoundary error={null} reset={reset} />);

    expect(screen.getByTestId("app-route-error-fallback")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(
      "[operator-ui] route_render_error",
      expect.objectContaining({
        pathname: "/sites/site-1",
        digest: "unavailable",
        classification: "missing_error_object",
        error_class: "UnknownError",
        app_version: "sha-test-build-1",
      }),
    );
    expect(warnSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("renders fallback safely when error payload is undefined", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);

    render(<RouteErrorBoundary error={undefined} reset={() => undefined} />);

    expect(screen.getByTestId("app-route-error-fallback")).toBeInTheDocument();
    expect(errorSpy).toHaveBeenCalledWith(
      "[operator-ui] route_render_error",
      expect.objectContaining({
        classification: "missing_error_object",
        digest: "unavailable",
        app_version: "sha-test-build-1",
      }),
    );
    expect(warnSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("logs malformed multipart parse failures as warnings", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);

    render(
      <RouteErrorBoundary
        error={{ message: "Unexpected end of form", digest: null }}
        reset={() => undefined}
      />,
    );

    expect(warnSpy).toHaveBeenCalledWith(
      "[operator-ui] route_render_warning",
      expect.objectContaining({
        classification: "unexpected_end_of_form",
        digest: "unavailable",
        app_version: "sha-test-build-1",
      }),
    );
    expect(errorSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("classifies stale server-action build mismatches as warning-level diagnostics", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);

    render(
      <RouteErrorBoundary
        error={{
          message:
            "Failed to find Server Action \"abc\". This request might be from an older or newer deployment. Original error: Cannot read properties of undefined (reading 'workers')",
          digest: null,
        }}
        reset={() => undefined}
      />,
    );

    expect(warnSpy).toHaveBeenCalledWith(
      "[operator-ui] route_render_warning",
      expect.objectContaining({
        classification: "stale_server_action_build_mismatch",
        digest: "unavailable",
        app_version: "sha-test-build-1",
      }),
    );
    expect(errorSpy).not.toHaveBeenCalled();
    expect(
      screen.getByText("A new version of MBSRN was deployed. Refresh this page before continuing."),
    ).toBeInTheDocument();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("logs normal route errors with digest when present", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);

    render(
      <RouteErrorBoundary
        error={{ message: "Boom route", digest: "abc123" }}
        reset={() => undefined}
      />,
    );

    expect(errorSpy).toHaveBeenCalledWith(
      "[operator-ui] route_render_error",
      expect.objectContaining({
        classification: "route_render_error",
        digest: "abc123",
        message: "Boom route",
        app_version: "sha-test-build-1",
      }),
    );
    expect(warnSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("sanitizes query/hash from route diagnostics", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);
    mockUsePathname.mockReturnValue("/google-profile?code=abc123&state=xyz#redirect");

    render(
      <RouteErrorBoundary
        error={{ message: "Callback failed", digest: null }}
        reset={() => undefined}
      />,
    );

    expect(errorSpy).toHaveBeenCalledWith(
      "[operator-ui] route_render_error",
      expect.objectContaining({
        pathname: "/google-profile",
        app_version: "sha-test-build-1",
      }),
    );
    expect(warnSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("redacts token-like query params from diagnostic message payload", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <RouteErrorBoundary
        error={{ message: "OAuth callback failed at /google-profile?code=abc123&state=xyz987", digest: null }}
        reset={() => undefined}
      />,
    );

    expect(errorSpy).toHaveBeenCalledWith(
      "[operator-ui] route_render_error",
      expect.objectContaining({
        message: "OAuth callback failed at /google-profile?code=[redacted]&state=[redacted]",
      }),
    );

    errorSpy.mockRestore();
  });
});
