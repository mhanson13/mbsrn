import type { HTMLAttributes, ReactNode } from "react";

type PageContainerProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  width?: "default" | "wide" | "full";
  density?: "default" | "compact";
};

export function PageContainer({
  children,
  className = "",
  width = "default",
  density = "default",
  ...rest
}: PageContainerProps) {
  const classes = [
    "page-container",
    `page-container-width-${width}`,
    `page-container-density-${density}`,
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
