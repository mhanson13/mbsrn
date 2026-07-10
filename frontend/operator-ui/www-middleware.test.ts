type WwwMiddleware = typeof import("../www/middleware")["middleware"];
let middleware: WwwMiddleware;

function createNextServerMock() {
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
}

jest.mock("next/server", () => createNextServerMock(), { virtual: true });
jest.mock("../www/node_modules/next/server.js", () => createNextServerMock(), { virtual: true });
({ middleware } = require("../www/middleware") as { middleware: WwwMiddleware });

function createRequest(overrides?: {
  url?: string;
  method?: string;
  contentType?: string;
  nextAction?: string;
}): Parameters<typeof middleware>[0] {
  const url = overrides?.url ?? "https://www.example/";
  const method = overrides?.method ?? "GET";
  const headers = new Headers();
  if (overrides?.contentType) {
    headers.set("content-type", overrides.contentType);
  }
  if (overrides?.nextAction) {
    headers.set("next-action", overrides.nextAction);
  }
  return {
    method,
    headers,
    nextUrl: new URL(url),
  } as Parameters<typeof middleware>[0];
}

describe("mbsrn-www middleware POST guard", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_APP_VERSION = "sha-www-build-1";
  });

  it("blocks unsupported multipart POST / with 415 and structured info log", async () => {
    const logSpy = jest.spyOn(console, "log").mockImplementation(() => undefined);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);
    const request = createRequest({
      url: "https://www.example/",
      method: "POST",
      contentType: "multipart/form-data; boundary=----abc",
    });

    const response = middleware(request);

    expect(response.status).toBe(415);
    await expect(response.text()).resolves.toBe("Unsupported multipart request.");
    expect(response.headers.get("x-middleware-next")).toBeNull();
    expect(logSpy).toHaveBeenCalledTimes(1);
    const logged = JSON.parse(String(logSpy.mock.calls[0]?.[0]));
    expect(logged).toEqual(expect.objectContaining({
      severity: "INFO",
      component: "mbsrn-www",
      event: "blocked_unsupported_multipart_request",
      method: "POST",
      pathname: "/",
      classification: "unsupported_non_api_multipart_request",
      app_version: "sha-www-build-1",
      has_boundary: true,
    }));
    expect(warnSpy).not.toHaveBeenCalled();

    logSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("blocks unsupported POST / before Next server-action resolution", async () => {
    const logSpy = jest.spyOn(console, "log").mockImplementation(() => undefined);
    const request = createRequest({
      url: "https://www.example/",
      method: "POST",
      nextAction: "1",
    });

    const response = middleware(request);

    expect(response.status).toBe(405);
    await expect(response.text()).resolves.toBe("Method not allowed.");
    expect(response.headers.get("Allow")).toBe("GET, HEAD");
    expect(response.headers.get("x-middleware-next")).toBeNull();
    expect(logSpy).toHaveBeenCalledTimes(1);
    const logged = JSON.parse(String(logSpy.mock.calls[0]?.[0]));
    expect(logged).toEqual(expect.objectContaining({
      severity: "INFO",
      component: "mbsrn-www",
      event: "blocked_unsupported_public_post_request",
      method: "POST",
      pathname: "/",
      classification: "unsupported_non_api_post_request",
      app_version: "sha-www-build-1",
    }));

    logSpy.mockRestore();
  });

  it("allows GET and HEAD requests to pass through", () => {
    const getRequest = createRequest({
      url: "https://www.example/",
      method: "GET",
    });
    const headRequest = createRequest({
      url: "https://www.example/",
      method: "HEAD",
    });

    const getResponse = middleware(getRequest);
    const headResponse = middleware(headRequest);

    expect(getResponse.headers.get("x-middleware-next")).toBe("1");
    expect(headResponse.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows /api POST traffic to pass through", () => {
    const request = createRequest({
      url: "https://www.example/api/upload",
      method: "POST",
      contentType: "multipart/form-data; boundary=----abc",
    });

    const response = middleware(request);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
