import type { HTMLAttributes, ReactNode } from "react";

type WorkspaceMetadataGridProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

type WorkspaceMetadataItemProps = HTMLAttributes<HTMLDivElement> & {
  label: string;
  children: ReactNode;
};

export function WorkspaceMetadataGrid({
  children,
  className = "",
  ...rest
}: WorkspaceMetadataGridProps): JSX.Element {
  const classes = ["workspace-metadata-grid", className]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}

export function WorkspaceMetadataItem({
  label,
  children,
  className = "",
  ...rest
}: WorkspaceMetadataItemProps): JSX.Element {
  const classes = ["workspace-metadata-item", className]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} {...rest}>
      <span className="workspace-metadata-label">{label}</span>
      {children}
    </div>
  );
}
