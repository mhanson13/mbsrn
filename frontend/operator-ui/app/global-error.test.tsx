import { fireEvent, render, screen } from "@testing-library/react";

import AppGlobalError from "./global-error";

describe("app global error boundary", () => {
  const originalPublicAppVersion = process.env.NEXT_PUBLIC_APP_VERSION;

  beforeEach(() => {
    process.env.NEXT_PUBLIC_APP_VERSION = "sha-test-build-1";
    window.history.replaceState({}, "", "/sites/site-1?state=abc123#callback");
  });

  afterAll(() => {
    if (originalPublicAppVersion === undefined) {
      delete process.env.NEXT_PUBLIC_APP_VERSION;
      return;
    }
    process.env.NEXT_PUBLIC_APP_VERSION = originalPublicAppVersion;
  });

  it("renders fallback and retries safely with null error payload", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);
    const reset = jest.fn();

    render(<AppGlobalError error={null} reset={reset} />);

    expect(screen.getByTestId("app-global-error-fallback")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(
      "[operator-ui] global_render_error",
      expect.objectContaining({
        classification: "missing_error_object",
        digest: "unavailable",
        pathname: "/sites/site-1",
        app_version: "sha-test-build-1",
      }),
    );
    expect(warnSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("classifies unexpected end of form as warning-level diagnostic", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);

    render(
      <AppGlobalError
        error={{ message: "Unexpected end of form", digest: "3200581505" }}
        reset={() => undefined}
      />,
    );

    expect(warnSpy).toHaveBeenCalledWith(
      "[operator-ui] global_render_warning",
      expect.objectContaining({
        classification: "unexpected_end_of_form",
        digest: "3200581505",
        pathname: "/sites/site-1",
        app_version: "sha-test-build-1",
      }),
    );
    expect(errorSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("renders fallback safely with undefined or non-Error payloads", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);

    render(<AppGlobalError error={undefined} reset={() => undefined} />);
    expect(screen.getByTestId("app-global-error-fallback")).toBeInTheDocument();

    render(<AppGlobalError error={{ code: "bad_state" }} reset={() => undefined} />);
    expect(errorSpy).toHaveBeenCalledWith(
      "[operator-ui] global_render_error",
      expect.objectContaining({
        digest: "unavailable",
        pathname: "/sites/site-1",
        app_version: "sha-test-build-1",
      }),
    );
    expect(warnSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("redacts token-like query params from global diagnostic message", () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <AppGlobalError
        error={{ message: "Callback failed /?code=abc123&state=xyz987", digest: null }}
        reset={() => undefined}
      />,
    );

    expect(errorSpy).toHaveBeenCalledWith(
      "[operator-ui] global_render_error",
      expect.objectContaining({
        message: "Callback failed /?code=[redacted]&state=[redacted]",
      }),
    );

    errorSpy.mockRestore();
  });
});
