import { render, screen } from "@testing-library/react";

import GoogleProfilePage from "./page";

jest.mock("../business-profile/page", () => ({
  __esModule: true,
  default: () => <div data-testid="business-profile-surface">Google Profile Surface</div>,
}));

describe("google profile route", () => {
  it("renders the Google Profile surface from the business-profile compatibility page", () => {
    render(<GoogleProfilePage />);

    expect(screen.getByTestId("business-profile-surface")).toBeInTheDocument();
    expect(screen.getByText("Google Profile Surface")).toBeInTheDocument();
  });
});
