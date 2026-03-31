import type { ReactNode } from "react";

type SectionHeaderProps = {
  title: string;
  subtitle?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  headingLevel?: 1 | 2 | 3 | 4;
  compact?: boolean;
  variant?: "default" | "hero" | "support" | "focus";
  "data-testid"?: string;
};

export function SectionHeader({
  title,
  subtitle,
  meta,
  actions,
  headingLevel = 2,
  compact = false,
  variant = "default",
  "data-testid": dataTestId,
}: SectionHeaderProps) {
  const HeadingTag = `h${headingLevel}` as "h1" | "h2" | "h3" | "h4";
  const headerClassName = [
    "workspace-section-header",
    compact ? "workspace-section-header-compact" : "",
    variant === "default" ? "" : `workspace-section-header-${variant}`,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={headerClassName} data-testid={dataTestId}>
      <div
        className={`workspace-section-header-main${
          variant === "default" ? "" : ` workspace-section-header-main-${variant}`
        }`}
      >
        <HeadingTag className="workspace-section-title">{title}</HeadingTag>
        {subtitle ? <p className="hint muted workspace-section-subtitle">{subtitle}</p> : null}
        {meta ? <div className="workspace-section-meta">{meta}</div> : null}
      </div>
      {actions ? <div className="workspace-section-actions">{actions}</div> : null}
    </div>
  );
}
