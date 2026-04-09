import type { HTMLAttributes, ReactNode } from "react";

type WorkspaceActionBarVariant = "primary" | "secondary";

type WorkspaceActionBarProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  variant?: WorkspaceActionBarVariant;
};

export function WorkspaceActionBar({
  children,
  className = "",
  variant = "primary",
  ...rest
}: WorkspaceActionBarProps): JSX.Element {
  const classes = [
    "workspace-action-bar",
    `workspace-action-bar-${variant}`,
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
