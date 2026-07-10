import { __resetMiddlewareTestState, middleware } from "./middleware";
jest.mock("next/server", () => {
  class MockNextResponse {
    status: number;
    headers: Headers;
    private readonly bodyText: string;

    constructor(body?: string | null, init?: { status?: number; headers?: HeadersInit }) {
      this.status = init?.status ?? 200;
      this.headers = new Headers(init?.headers);
      this.bodyText = typeof body === "string" ? body : "";
    }

    static next() {
      return new MockNextResponse(null, {
        status: 200,
        headers: { "x-middleware-next": "1" },
      });
    }

    async text() {
      return this.bodyText;
    }
  }

  return {
    NextResponse: MockNextResponse,
  };
});

function createRequest(overrides?: {
  url?: string;
  method?: string;
  contentType?: string;
}): Parameters<typeof middleware>[0] {
  const url = overrides?.url ?? "https://operator.example/sites";
  const method = overrides?.method ?? "GET";
  const headers = new Headers();
  if (overrides?.contentType) {
    headers.set("content-type", overrides.contentType);
  }
  const requestLike = {
    method,
    headers,
    nextUrl: new URL(url),
  };
  return requestLike as Parameters<typeof middleware>[0];
}

describe("operator-ui middleware multipart guard", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_APP_VERSION = "sha-test-build-1";
    __resetMiddlewareTestState();
  });

  it("blocks unsupported multipart POST requests outside /api", async () => {
    const logSpy = jest.spyOn(console, "log").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);
    const request = createRequest({
      url: "https://operator.example/sites",
      method: "POST",
      contentType: "multipart/form-data; boundary=----abc",
    });

    const response = middleware(request);

    expect(response.status).toBe(400);
    expect(response.headers.get("x-middleware-next")).toBeNull();
    await expect(response.text()).resolves.toBe("Unsupported multipart request.");
    expect(logSpy).toHaveBeenCalledTimes(1);
    const logged = JSON.parse(String(logSpy.mock.calls[0]?.[0]));
    expect(logged).toEqual(expect.objectContaining({
      severity: "INFO",
      component: "operator-ui",
      event: "blocked_unsupported_multipart_request",
      method: "POST",
      pathname: "/sites",
      classification: "unsupported_non_api_multipart_request",
      app_version: "sha-test-build-1",
      has_boundary: true,
    }));
    expect(warnSpy).not.toHaveBeenCalled();

    logSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("allows multipart POST requests for /api paths", () => {
    const request = createRequest({
      url: "https://operator.example/api/upload",
      method: "POST",
      contentType: "multipart/form-data; boundary=----abc",
    });

    const response = middleware(request);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows multipart POST requests for the /api root path", () => {
    const request = createRequest({
      url: "https://operator.example/api",
      method: "POST",
      contentType: "multipart/form-data; boundary=----abc",
    });

    const response = middleware(request);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("blocks stale server-action requests outside /api with bounded diagnostics", async () => {
    const logSpy = jest.spyOn(console, "log").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);
    const request = createRequest({
      url: "https://operator.example/sites",
      method: "POST",
      contentType: "multipart/form-data; boundary=----abc",
    });
    (request as { headers: Headers }).headers.set("next-action", "1");

    const response = middleware(request);
    expect(response.status).toBe(409);
    expect(response.headers.get("x-middleware-next")).toBeNull();
    await expect(response.text()).resolves.toContain("A new version of MBSRN was deployed");
    expect(response.headers.get("X-Operator-UI-Error-Classification")).toBe(
      "stale_server_action_build_mismatch",
    );
    expect(response.headers.get("X-Operator-UI-Refresh-Required")).toBe("true");
    expect(logSpy).toHaveBeenCalledTimes(1);
    const logged = JSON.parse(String(logSpy.mock.calls[0]?.[0]));
    expect(logged).toEqual(expect.objectContaining({
      severity: "INFO",
      component: "operator-ui",
      event: "blocked_stale_server_action_request",
      method: "POST",
      pathname: "/sites",
      classification: "stale_server_action_build_mismatch",
      app_version: "sha-test-build-1",
      refresh_required: true,
    }));
    expect(warnSpy).not.toHaveBeenCalled();

    logSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("allows next-action requests to /api paths", () => {
    const request = createRequest({
      url: "https://operator.example/api/forms",
      method: "POST",
      contentType: "multipart/form-data; boundary=----abc",
    });
    (request as { headers: Headers }).headers.set("next-action", "1");

    const response = middleware(request);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("throttles repeated stale server-action warnings while continuing to block requests", async () => {
    const logSpy = jest.spyOn(console, "log").mockImplementation(() => undefined);
    const nowSpy = jest.spyOn(Date, "now").mockReturnValue(1_700_000_000_000);
    try {
      const firstRequest = createRequest({
        url: "https://operator.example/sites",
        method: "POST",
      });
      (firstRequest as { headers: Headers }).headers.set("next-action", "1");
      const firstResponse = middleware(firstRequest);
      expect(firstResponse.status).toBe(409);

      const secondRequest = createRequest({
        url: "https://operator.example/sites",
        method: "POST",
      });
      (secondRequest as { headers: Headers }).headers.set("next-action", "1");
      const secondResponse = middleware(secondRequest);
      expect(secondResponse.status).toBe(409);

      expect(logSpy).toHaveBeenCalledTimes(1);
    } finally {
      nowSpy.mockRestore();
      logSpy.mockRestore();
    }
  });

  it("allows non-multipart traffic", () => {
    const request = createRequest({
      url: "https://operator.example/sites",
      method: "GET",
    });

    const response = middleware(request);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
