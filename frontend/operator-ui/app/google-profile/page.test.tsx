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

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/sites"));
  });

  it("preserves query params when redirecting to Sites setup", async () => {
    mockUseSearchParams.mockReturnValue(new URLSearchParams("site_id=site-1&gbp_connect=success"));

    render(<GoogleProfilePage />);

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/sites?site_id=site-1&gbp_connect=success"));
    expect(screen.getByRole("link", { name: "Open Sites setup" })).toHaveAttribute(
      "href",
      "/sites?site_id=site-1&gbp_connect=success",
    );
  });
});
