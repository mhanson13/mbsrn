import { render, screen } from "@testing-library/react";

import { WorkspaceActionBar } from "./WorkspaceActionBar";
import { WorkspaceEmptyStateCard } from "./WorkspaceEmptyStateCard";
import { WorkspaceMessageStack } from "./WorkspaceMessageStack";
import { WorkspaceMetadataGrid, WorkspaceMetadataItem } from "./WorkspaceMetadataGrid";
import { WorkspaceTableShell } from "./WorkspaceTableShell";

describe("workspace surface primitives", () => {
  it("renders action bar variants", () => {
    const { rerender } = render(
      <WorkspaceActionBar data-testid="action-bar-primary" variant="primary">
        <button type="button">Primary action</button>
      </WorkspaceActionBar>,
    );
    expect(screen.getByTestId("action-bar-primary")).toHaveClass("workspace-action-bar");
    expect(screen.getByTestId("action-bar-primary")).toHaveClass("workspace-action-bar-primary");

    rerender(
      <WorkspaceActionBar data-testid="action-bar-secondary" variant="secondary">
        <a href="/next">Secondary link</a>
      </WorkspaceActionBar>,
    );
    expect(screen.getByTestId("action-bar-secondary")).toHaveClass("workspace-action-bar-secondary");
  });

  it("renders message stack and empty state card variants", () => {
    render(
      <>
        <WorkspaceMessageStack data-testid="message-stack">
          <p className="hint warning">Warning</p>
        </WorkspaceMessageStack>
        <WorkspaceEmptyStateCard data-testid="empty-state-default">
          <p className="hint muted">No records</p>
        </WorkspaceEmptyStateCard>
        <WorkspaceEmptyStateCard data-testid="empty-state-compact" compact={true}>
          <p className="hint muted">No compact records</p>
        </WorkspaceEmptyStateCard>
      </>,
    );

    expect(screen.getByTestId("message-stack")).toHaveClass("workspace-message-stack");
    expect(screen.getByTestId("empty-state-default")).toHaveClass("workspace-empty-state");
    expect(screen.getByTestId("empty-state-compact")).toHaveClass("workspace-empty-state-compact");
  });

  it("renders metadata grid and table shell wrappers", () => {
    render(
      <>
        <WorkspaceMetadataGrid data-testid="metadata-grid">
          <WorkspaceMetadataItem label="Model" data-testid="metadata-item">
            <span className="hint">gpt-5.1</span>
          </WorkspaceMetadataItem>
        </WorkspaceMetadataGrid>
        <WorkspaceTableShell data-testid="table-shell">
          <table className="table">
            <tbody>
              <tr>
                <td>Row</td>
              </tr>
            </tbody>
          </table>
        </WorkspaceTableShell>
      </>,
    );

    expect(screen.getByTestId("metadata-grid")).toHaveClass("workspace-metadata-grid");
    expect(screen.getByTestId("metadata-item")).toHaveClass("workspace-metadata-item");
    expect(screen.getByText("Model")).toHaveClass("workspace-metadata-label");
    expect(screen.getByTestId("table-shell")).toHaveClass("table-container");
    expect(screen.getByTestId("table-shell")).toHaveClass("workspace-table-shell");
  });
});
