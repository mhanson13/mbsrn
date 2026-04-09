import type { HTMLAttributes, ReactNode } from "react";

type WorkspaceTableShellProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  compact?: boolean;
};

export function WorkspaceTableShell({
  children,
  className = "",
  compact = false,
  ...rest
}: WorkspaceTableShellProps): JSX.Element {
  const classes = [
    compact ? "table-container table-container-compact" : "table-container",
    "workspace-table-shell",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}
