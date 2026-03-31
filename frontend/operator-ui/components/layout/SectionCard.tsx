import type { HTMLAttributes, ReactNode } from "react";

type SectionCardProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  as?: "section" | "div" | "article";
  variant?: "default" | "primary" | "summary" | "support" | "emphasis";
};

export function SectionCard({
  children,
  className = "",
  as = "section",
  variant = "default",
  ...rest
}: SectionCardProps) {
  const Component = as;
  const variantClassName = variant === "default" ? "" : `section-card-variant-${variant}`;
  const classes = [ "panel", "stack", "section-card", variantClassName, className ]
    .filter(Boolean)
    .join(" ");
  return (
    <Component className={classes} {...rest}>
      {children}
    </Component>
  );
}
