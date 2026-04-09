import type { HTMLAttributes, ReactNode } from "react";

type WorkspaceEmptyStateCardProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  compact?: boolean;
};

export function WorkspaceEmptyStateCard({
  children,
  className = "",
  compact = false,
  ...rest
}: WorkspaceEmptyStateCardProps): JSX.Element {
  const classes = [
    "workspace-empty-state",
    compact ? "workspace-empty-state-compact" : "",
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
