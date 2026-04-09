import { render, screen } from "@testing-library/react";

import {
  OperatorPageHero,
  OperatorPageSectionStack,
  OperatorPageSummaryStrip,
} from "./OperatorPageSurface";
import { SummaryStatCard } from "./SummaryStatCard";

describe("operator page surface primitives", () => {
  it("renders standardized hero composition", () => {
    render(
      <OperatorPageHero
        title="Route Title"
        subtitle="Route subtitle"
        data-testid="operator-page-hero"
        actions={<button type="button">Primary action</button>}
        summary={(
          <>
            <SummaryStatCard label="One" value={1} detail="detail" />
            <SummaryStatCard label="Two" value={2} detail="detail" />
          </>
        )}
      >
        <p className="hint muted">Hero body</p>
      </OperatorPageHero>,
    );

    expect(screen.getByTestId("operator-page-hero")).toHaveClass("operator-page-hero-surface");
    expect(screen.getByText("Route Title")).toBeInTheDocument();
    expect(screen.getByText("Route subtitle")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Primary action" })).toBeInTheDocument();
    expect(screen.getByText("Hero body")).toBeInTheDocument();
    expect(document.querySelector(".workspace-summary-strip.role-summary-strip")).toBeTruthy();
  });

  it("renders summary strip and section stack wrappers", () => {
    render(
      <>
        <OperatorPageSummaryStrip data-testid="operator-summary-strip" compact={true}>
          <span className="hint">summary</span>
        </OperatorPageSummaryStrip>
        <OperatorPageSectionStack data-testid="operator-section-stack">
          <div>Section A</div>
          <div>Section B</div>
        </OperatorPageSectionStack>
      </>,
    );

    expect(screen.getByTestId("operator-summary-strip")).toHaveClass("workspace-summary-strip-compact");
    expect(screen.getByTestId("operator-section-stack")).toHaveClass("operator-page-section-stack");
  });
});

