import type { HTMLAttributes, ReactNode } from "react";

type SectionCardProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  as?: "section" | "div" | "article";
};

export function SectionCard({ children, className = "", as = "section", ...rest }: SectionCardProps) {
  const Component = as;
  const classes = className ? `panel stack section-card ${className}` : "panel stack section-card";
  return (
    <Component className={classes} {...rest}>
      {children}
    </Component>
  );
}
