import type { HTMLAttributes, ReactNode } from "react";

import { WorkspaceActionBar } from "./WorkspaceActionBar";

type RouteActionClusterProps = HTMLAttributes<HTMLDivElement> & {
  primaryActions?: ReactNode;
  secondaryActions?: ReactNode;
  shortcutActions?: ReactNode;
  note?: ReactNode;
};

export function RouteActionCluster({
  primaryActions = null,
  secondaryActions = null,
  shortcutActions = null,
  note = null,
  className = "",
  ...rest
}: RouteActionClusterProps): JSX.Element {
  const classes = ["route-action-cluster", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes} {...rest}>
      {primaryActions ? (
        <WorkspaceActionBar variant="primary" className="route-action-cluster-primary">
          {primaryActions}
        </WorkspaceActionBar>
      ) : null}
      {secondaryActions ? (
        <WorkspaceActionBar variant="secondary" className="route-action-cluster-secondary">
          {secondaryActions}
        </WorkspaceActionBar>
      ) : null}
      {shortcutActions ? (
        <WorkspaceActionBar variant="secondary" className="route-action-cluster-shortcuts">
          {shortcutActions}
        </WorkspaceActionBar>
      ) : null}
      {note ? <p className="hint muted route-action-cluster-note">{note}</p> : null}
    </div>
  );
}

