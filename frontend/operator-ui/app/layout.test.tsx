import type { ReactNode } from "react";

jest.mock("../components/AuthProvider", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

jest.mock("../components/NavShell", () => ({
  NavShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

describe("root layout runtime marker", () => {
  const originalPublicAppVersion = process.env.NEXT_PUBLIC_APP_VERSION;

  afterAll(() => {
    if (originalPublicAppVersion === undefined) {
      delete process.env.NEXT_PUBLIC_APP_VERSION;
      return;
    }
    process.env.NEXT_PUBLIC_APP_VERSION = originalPublicAppVersion;
  });

  it("publishes bounded app version marker in metadata and body attribute", async () => {
    process.env.NEXT_PUBLIC_APP_VERSION = "sha-test-build-1";
    jest.resetModules();

    const layoutModule = await import("./layout");
    const metadataOther = (layoutModule.metadata.other || {}) as Record<string, string>;
    expect(metadataOther["mbsrn-ui-version"]).toBe("sha-test-build-1");

    const RootLayout = layoutModule.default;
    const layoutElement = RootLayout({
      children: <div>Child content</div>,
    }) as { props: { children: { props: Record<string, unknown> } } };
    const bodyElement = layoutElement.props.children;

    expect(bodyElement.props["data-mbsrn-ui-version"]).toBe("sha-test-build-1");
  });
});
