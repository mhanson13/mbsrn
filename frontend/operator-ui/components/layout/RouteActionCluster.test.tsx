import { render, screen } from "@testing-library/react";

import { RouteActionCluster } from "./RouteActionCluster";

describe("RouteActionCluster", () => {
  it("renders primary, secondary, and shortcut action groups in deterministic order", () => {
    render(
      <RouteActionCluster
        data-testid="route-action-cluster"
        primaryActions={<button type="button">Primary action</button>}
        secondaryActions={<button type="button">Secondary action</button>}
        shortcutActions={<a href="/audit">Shortcut</a>}
        note="Action guidance"
      />,
    );

    const cluster = screen.getByTestId("route-action-cluster");
    expect(cluster).toHaveClass("route-action-cluster");
    expect(screen.getByRole("button", { name: "Primary action" }).closest(".route-action-cluster-primary")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Secondary action" }).closest(".route-action-cluster-secondary")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Shortcut" }).closest(".route-action-cluster-shortcuts")).toBeTruthy();
    expect(screen.getByText("Action guidance")).toHaveClass("route-action-cluster-note");
  });

  it("supports secondary-only usage for detail-route back-link clusters", () => {
    render(
      <RouteActionCluster
        data-testid="route-action-cluster-secondary-only"
        secondaryActions={(
          <>
            <a href="/one">Back one</a>
            <a href="/two">Back two</a>
          </>
        )}
      />,
    );

    const cluster = screen.getByTestId("route-action-cluster-secondary-only");
    expect(cluster.querySelector(".route-action-cluster-primary")).toBeNull();
    expect(cluster.querySelector(".route-action-cluster-shortcuts")).toBeNull();
    expect(screen.getByRole("link", { name: "Back one" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back two" })).toBeInTheDocument();
  });
});

