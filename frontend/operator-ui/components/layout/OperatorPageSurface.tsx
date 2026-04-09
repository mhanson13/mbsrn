import type { HTMLAttributes, ReactNode } from "react";

import { SectionCard } from "./SectionCard";
import { SectionHeader } from "./SectionHeader";

type OperatorPageSummaryStripProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  compact?: boolean;
};

type OperatorPageHeroProps = Omit<HTMLAttributes<HTMLDivElement>, "title"> & {
  title: string;
  subtitle?: ReactNode;
  summary?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
  headingLevel?: 1 | 2 | 3 | 4;
  children?: ReactNode;
  "data-testid"?: string;
};

type OperatorPageSectionStackProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export function OperatorPageSummaryStrip({
  children,
  className = "",
  compact = false,
  ...rest
}: OperatorPageSummaryStripProps): JSX.Element {
  const classes = [
    "workspace-summary-strip",
    "role-summary-strip",
    compact ? "workspace-summary-strip-compact" : "",
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

export function OperatorPageHero({
  title,
  subtitle,
  summary,
  actions,
  meta,
  headingLevel = 1,
  children = null,
  className = "",
  "data-testid": dataTestId,
  ...rest
}: OperatorPageHeroProps): JSX.Element {
  const classes = ["role-dashboard-landing", "operator-page-hero-surface", className]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} data-testid={dataTestId} {...rest}>
      <SectionCard variant="primary" className="role-dashboard-hero">
        <SectionHeader
          title={title}
          subtitle={subtitle}
          headingLevel={headingLevel}
          variant="hero"
          actions={actions}
          meta={meta}
        />
        {summary ? <OperatorPageSummaryStrip>{summary}</OperatorPageSummaryStrip> : null}
        {children}
      </SectionCard>
    </div>
  );
}

export function OperatorPageSectionStack({
  children,
  className = "",
  ...rest
}: OperatorPageSectionStackProps): JSX.Element {
  const classes = ["operator-page-section-stack", className]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}

