import { render, screen, waitFor } from "@testing-library/react";

import BusinessProfilePage from "./page";
import type { GoogleBusinessProfileConnectionStatusResponse } from "../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: Array<{ id: string; display_name: string }>;
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchGoogleBusinessProfileConnection = jest.fn<
  Promise<GoogleBusinessProfileConnectionStatusResponse>,
  unknown[]
>();
const mockFetchGoogleBusinessProfileLocations = jest.fn<
  Promise<{ locations: Array<unknown> }>,
  unknown[]
>();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    fetchGoogleBusinessProfileConnection: (...args: unknown[]) => mockFetchGoogleBusinessProfileConnection(...args),
    fetchGoogleBusinessProfileLocations: (...args: unknown[]) => mockFetchGoogleBusinessProfileLocations(...args),
  };
});

function buildDisconnectedConnection(
  overrides: Partial<GoogleBusinessProfileConnectionStatusResponse> = {},
): GoogleBusinessProfileConnectionStatusResponse {
  return {
    provider: "google_business_profile",
    connected: false,
    business_id: "biz-1",
    granted_scopes: [],
    refresh_token_present: false,
    expires_at: null,
    connected_at: null,
    last_refreshed_at: null,
    reconnect_required: false,
    required_scopes_satisfied: false,
    token_status: "reconnect_required",
    ...overrides,
  };
}

describe("business profile callback notice UX", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.history.pushState({}, "", "/business-profile");

    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [],
      selectedSiteId: null,
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });
    mockFetchGoogleBusinessProfileConnection.mockResolvedValue(buildDisconnectedConnection());
    mockFetchGoogleBusinessProfileLocations.mockResolvedValue({ locations: [] });
  });

  it("renders success callback notice when gbp_connect=success", async () => {
    window.history.pushState({}, "", "/business-profile?gbp_connect=success");

    render(<BusinessProfilePage />);

    await waitFor(() =>
      expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1"),
    );
    expect(document.querySelector(".page-container-width-wide")).toBeTruthy();
    expect(screen.queryByLabelText("Site")).not.toBeInTheDocument();
    expect(
      await screen.findByText("Google Business Profile connected successfully."),
    ).toBeInTheDocument();
  });

  it("renders reconnect-required error callback notice safely", async () => {
    window.history.pushState(
      {},
      "",
      "/business-profile?gbp_connect=error&gbp_reconnect_required=true&gbp_connect_error=token_exchange_failed&gbp_raw=provider_detail",
    );

    render(<BusinessProfilePage />);

    await waitFor(() =>
      expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1"),
    );
    expect(
      await screen.findByText("Google Business Profile connection requires reauthorization. Please reconnect."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/token_exchange_failed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/provider_detail/i)).not.toBeInTheDocument();
  });

  it("renders generic error callback notice when reconnect flag is absent", async () => {
    window.history.pushState(
      {},
      "",
      "/business-profile?gbp_connect=error&gbp_connect_error=access_denied&gbp_error_description=raw_oauth_error",
    );

    render(<BusinessProfilePage />);

    await waitFor(() =>
      expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1"),
    );
    expect(
      await screen.findByText("Google Business Profile connection did not complete. Please try connecting again."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/raw_oauth_error/i)).not.toBeInTheDocument();
  });

  it("does not render callback notice when no callback query params are present", async () => {
    window.history.pushState({}, "", "/business-profile");

    render(<BusinessProfilePage />);

    await waitFor(() =>
      expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1"),
    );
    await screen.findByRole("heading", { name: "Google Business Profile" });
    expect(screen.queryByText("Google Business Profile connected successfully.")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Google Business Profile connection did not complete. Please try connecting again."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Google Business Profile connection requires reauthorization. Please reconnect."),
    ).not.toBeInTheDocument();
  });
});
