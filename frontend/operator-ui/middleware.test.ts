import { middleware } from "./middleware";
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
  it("blocks unsupported multipart POST requests outside /api", async () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => undefined);
    const request = createRequest({
      url: "https://operator.example/sites",
      method: "POST",
      contentType: "multipart/form-data; boundary=----abc",
    });

    const response = middleware(request);

    expect(response.status).toBe(400);
    await expect(response.text()).resolves.toBe("Unsupported multipart request.");
    expect(warnSpy).toHaveBeenCalledWith(
      "[operator-ui] blocked_unsupported_multipart_request",
      expect.objectContaining({
        method: "POST",
        pathname: "/sites",
        has_boundary: true,
      }),
    );

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

  it("allows multipart POST requests with next-action header", () => {
    const request = createRequest({
      url: "https://operator.example/sites",
      method: "POST",
      contentType: "multipart/form-data; boundary=----abc",
    });
    (request as { headers: Headers }).headers.set("next-action", "1");

    const response = middleware(request);
    expect(response.headers.get("x-middleware-next")).toBe("1");
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
