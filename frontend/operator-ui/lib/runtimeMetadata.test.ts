import { getPublicAppVersion, normalizePublicAppVersion } from "./runtimeMetadata";

describe("runtime metadata", () => {
  const originalPublicAppVersion = process.env.NEXT_PUBLIC_APP_VERSION;

  afterAll(() => {
    if (originalPublicAppVersion === undefined) {
      delete process.env.NEXT_PUBLIC_APP_VERSION;
      return;
    }
    process.env.NEXT_PUBLIC_APP_VERSION = originalPublicAppVersion;
  });

  it("returns unknown when NEXT_PUBLIC_APP_VERSION is missing", () => {
    delete process.env.NEXT_PUBLIC_APP_VERSION;
    expect(getPublicAppVersion()).toBe("unknown");
  });

  it("returns normalized version when value is safe", () => {
    process.env.NEXT_PUBLIC_APP_VERSION = "3f9f0c7";
    expect(getPublicAppVersion()).toBe("3f9f0c7");
  });

  it("rejects unsafe version strings", () => {
    expect(normalizePublicAppVersion("sha=abcd1234 token=secret")).toBe("unknown");
    expect(normalizePublicAppVersion("")).toBe("unknown");
  });
});
