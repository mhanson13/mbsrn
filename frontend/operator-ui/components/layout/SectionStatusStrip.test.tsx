import { render, screen } from "@testing-library/react";

import { SectionStatusItem, SectionStatusStrip } from "./SectionStatusStrip";

describe("SectionStatusStrip", () => {
  it("renders summary items with tone badges and detail text", () => {
    render(
      <SectionStatusStrip data-testid="section-status-strip">
        <SectionStatusItem label="Run status" value="completed" tone="success" detail="Terminal outcome is stable" />
        <SectionStatusItem label="Open recommendations" value={3} tone="warning" />
      </SectionStatusStrip>,
    );

    const strip = screen.getByTestId("section-status-strip");
    expect(strip).toHaveClass("section-status-strip");
    expect(screen.getByText("Run status")).toHaveClass("section-status-item-label");
    expect(screen.getByText("completed")).toHaveClass("badge-success");
    expect(screen.getByText("Terminal outcome is stable")).toHaveClass("section-status-item-detail");
    expect(screen.getByText("Open recommendations")).toHaveClass("section-status-item-label");
  });

  it("supports compact strips and non-badge value rendering", () => {
    render(
      <SectionStatusStrip data-testid="section-status-strip-compact" compact={true}>
        <SectionStatusItem
          label="Run ID"
          value={<code>run-123</code>}
          valueAsBadge={false}
          detail="Most recent execution record"
        />
      </SectionStatusStrip>,
    );

    const strip = screen.getByTestId("section-status-strip-compact");
    expect(strip).toHaveClass("section-status-strip-compact");
    expect(screen.getByText("run-123").closest(".section-status-item-value")).toBeTruthy();
    expect(screen.getByText("Most recent execution record")).toBeInTheDocument();
  });
});
