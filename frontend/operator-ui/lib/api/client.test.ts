import { ApiRequestError, ensureSiteTLSCertificate, fetchSites } from "./client";

describe("api client error normalization", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it("normalizes null fetch rejections to Error", async () => {
    const mockFetch = jest.fn().mockRejectedValueOnce(null);
    global.fetch = mockFetch as unknown as typeof fetch;

    await expect(fetchSites("token-1", "biz-1")).rejects.toEqual(
      expect.objectContaining({
        name: "Error",
        message: expect.stringContaining("Network request failed"),
      }),
    );
  });

  it("normalizes malformed success responses to Error", async () => {
    const mockFetch = jest.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: jest.fn().mockRejectedValueOnce(undefined),
    });
    global.fetch = mockFetch as unknown as typeof fetch;

    await expect(fetchSites("token-1", "biz-1")).rejects.toEqual(
      expect.objectContaining({
        name: "Error",
        message: expect.stringContaining("Invalid API response"),
      }),
    );
  });

  it("returns bounded ApiRequestError when non-ok payload is null", async () => {
    const mockFetch = jest.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: jest.fn().mockResolvedValueOnce(null),
    });
    global.fetch = mockFetch as unknown as typeof fetch;

    try {
      await fetchSites("token-1", "biz-1");
      throw new Error("Expected fetchSites to reject.");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiRequestError);
      expect(error).toEqual(
        expect.objectContaining({
          name: "ApiRequestError",
          status: 500,
          message: "Request failed.",
        }),
      );
    }
  });

  it("uses the idempotent ensure route for certificate provisioning", async () => {
    const responsePayload = { hostname: "platfire.site.mbsrn.com", published: true };
    const mockFetch = jest.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: jest.fn().mockResolvedValueOnce(responsePayload),
    });
    global.fetch = mockFetch as unknown as typeof fetch;

    await expect(
      ensureSiteTLSCertificate("token-1", "biz-1", "site-1", {
        validity_days: 90,
        key_algorithm: "rsa_2048",
      }),
    ).resolves.toEqual(responsePayload);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/businesses/biz-1/tls/sites/site-1/certificates/ensure"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ validity_days: 90, key_algorithm: "rsa_2048" }),
        headers: expect.objectContaining({ Authorization: "Bearer token-1" }),
      }),
    );
  });
});
