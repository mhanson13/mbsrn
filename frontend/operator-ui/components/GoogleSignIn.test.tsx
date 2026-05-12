import { act, render } from "@testing-library/react";

import { GoogleSignIn } from "./GoogleSignIn";

jest.mock("next/script", () => {
  const React = require("react");
  return function MockNextScript({
    onLoad,
  }: {
    onLoad?: () => void;
  }) {
    React.useEffect(() => {
      onLoad?.();
    }, [onLoad]);
    return <div data-testid="google-script-mock" />;
  };
});

describe("GoogleSignIn", () => {
  afterEach(() => {
    jest.useRealTimers();
    delete (window as Window & { google?: unknown }).google;
    jest.restoreAllMocks();
  });

  it("initializes GIS and forwards credentials", () => {
    let capturedCredentialCallback: ((payload: { credential?: string }) => void) | null = null;
    const initialize = jest.fn((config: Record<string, unknown>) => {
      const callback = config.callback;
      capturedCredentialCallback = typeof callback === "function"
        ? (callback as (payload: { credential?: string }) => void)
        : null;
    });
    const renderButton = jest.fn();
    (window as Window & { google?: unknown }).google = {
      accounts: {
        id: {
          initialize,
          renderButton,
        },
      },
    };
    const onCredential = jest.fn();

    render(<GoogleSignIn clientId="client-id-1" onCredential={onCredential} />);

    expect(initialize).toHaveBeenCalledTimes(1);
    expect(renderButton).toHaveBeenCalledTimes(1);
    expect(capturedCredentialCallback).toBeTruthy();
    if (!capturedCredentialCallback) {
      throw new Error("Expected Google credential callback to be initialized.");
    }
    const credentialCallback = capturedCredentialCallback as (payload: { credential?: string }) => void;
    credentialCallback({ credential: "credential-token-1" });
    expect(onCredential).toHaveBeenCalledWith("credential-token-1");
  });

  it("handles null/unknown GIS initialization failures without throwing", () => {
    const initialize = jest.fn(() => {
      throw null;
    });
    const renderButton = jest.fn();
    (window as Window & { google?: unknown }).google = {
      accounts: {
        id: {
          initialize,
          renderButton,
        },
      },
    };
    const onInitializationError = jest.fn();

    expect(() => {
      render(
        <GoogleSignIn
          clientId="client-id-1"
          onCredential={() => undefined}
          onInitializationError={onInitializationError}
        />,
      );
    }).not.toThrow();

    expect(onInitializationError).toHaveBeenCalledWith({
      kind: "button_render_failed",
      message: "Google sign-in button render failed.",
    });
  });

  it("reports script-not-ready after bounded retry attempts", () => {
    jest.useFakeTimers();
    delete (window as Window & { google?: unknown }).google;
    const onInitializationError = jest.fn();

    render(
      <GoogleSignIn
        clientId="client-id-1"
        onCredential={() => undefined}
        onInitializationError={onInitializationError}
      />,
    );

    act(() => {
      jest.advanceTimersByTime(4000);
    });

    expect(onInitializationError).toHaveBeenCalledWith({
      kind: "script_not_ready",
      message: "Google sign-in script did not initialize in time.",
    });
  });
});
