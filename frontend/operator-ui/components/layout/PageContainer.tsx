import type { HTMLAttributes, ReactNode } from "react";

type PageContainerProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export function PageContainer({ children, className = "", ...rest }: PageContainerProps) {
  const classes = className ? `page-container ${className}` : "page-container";
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}
