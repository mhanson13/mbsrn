import { render, screen, waitFor } from "@testing-library/react";

import GoogleProfilePage from "./page";

const mockReplace = jest.fn();
const mockUseSearchParams = jest.fn<URLSearchParams, []>(() => new URLSearchParams());

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => mockUseSearchParams(),
}));

describe("google profile legacy compatibility route", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSearchParams.mockReturnValue(new URLSearchParams());
  });

  it("redirects to Sites setup while rendering compatibility guidance", async () => {
    render(<GoogleProfilePage />);

    expect(screen.getByTestId("google-profile-legacy-redirect")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Google setup moved" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Sites setup" })).toHaveAttribute("href", "/sites");
    expect(screen.queryByRole("button", { name: "Save GA4 Property" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("google-profile-ga4-health")).not.toBeInTheDocument();

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/sites"));
  });

  it("preserves query params and appends selected-site setup hash when site_id is present", async () => {
    mockUseSearchParams.mockReturnValue(new URLSearchParams("site_id=site-1&gbp_connect=success"));

    render(<GoogleProfilePage />);

    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/sites?site_id=site-1&gbp_connect=success#selected-site-setup"),
    );
    expect(screen.getByRole("link", { name: "Open Sites setup" })).toHaveAttribute(
      "href",
      "/sites?site_id=site-1&gbp_connect=success#selected-site-setup",
    );
  });
});
