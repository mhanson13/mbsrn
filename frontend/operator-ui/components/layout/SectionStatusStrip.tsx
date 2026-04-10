import type { HTMLAttributes, ReactNode } from "react";

type SectionStatusTone = "neutral" | "success" | "warning" | "danger";

type SectionStatusStripProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  compact?: boolean;
};

type SectionStatusItemProps = HTMLAttributes<HTMLDivElement> & {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  tone?: SectionStatusTone;
  valueAsBadge?: boolean;
};

const SECTION_STATUS_BADGE_CLASS: Record<SectionStatusTone, string> = {
  neutral: "badge-muted",
  success: "badge-success",
  warning: "badge-warn",
  danger: "badge-error",
};

export function SectionStatusStrip({
  children,
  className = "",
  compact = false,
  ...rest
}: SectionStatusStripProps): JSX.Element {
  const classes = [
    "section-status-strip",
    compact ? "section-status-strip-compact" : "",
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

export function SectionStatusItem({
  label,
  value,
  detail = null,
  tone = "neutral",
  valueAsBadge = true,
  className = "",
  ...rest
}: SectionStatusItemProps): JSX.Element {
  const classes = [
    "section-status-item",
    `section-status-item-${tone}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  const badgeClassName = SECTION_STATUS_BADGE_CLASS[tone];
  return (
    <div className={classes} {...rest}>
      <span className="section-status-item-label">{label}</span>
      {valueAsBadge ? (
        <span className={`badge ${badgeClassName} section-status-item-value-badge`}>{value}</span>
      ) : (
        <span className="section-status-item-value">{value}</span>
      )}
      {detail ? <span className="section-status-item-detail">{detail}</span> : null}
    </div>
  );
}
