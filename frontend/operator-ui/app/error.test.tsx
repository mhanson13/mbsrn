import { fireEvent, render, screen } from "@testing-library/react";

import RouteErrorBoundary from "./error";

const mockUsePathname = jest.fn(() => "/sites/site-1");

jest.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

describe("app route error boundary", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUsePathname.mockReturnValue("/sites/site-1");
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
      }),
    );
    expect(errorSpy).not.toHaveBeenCalled();

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
      }),
    );
    expect(warnSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });
});
