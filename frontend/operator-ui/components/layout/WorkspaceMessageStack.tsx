import type { HTMLAttributes, ReactNode } from "react";

type WorkspaceMessageStackProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export function WorkspaceMessageStack({
  children,
  className = "",
  ...rest
}: WorkspaceMessageStackProps): JSX.Element {
  const classes = ["workspace-message-stack", className]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}
