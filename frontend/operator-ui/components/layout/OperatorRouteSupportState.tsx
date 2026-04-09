import Link from "next/link";
import type { HTMLAttributes } from "react";

import { PageContainer } from "./PageContainer";
import { SectionHeader } from "./SectionHeader";
import { WorkspaceEmptyStateCard } from "./WorkspaceEmptyStateCard";

type OperatorRouteSupportStateProps = HTMLAttributes<HTMLDivElement> & {
  title: string;
  subtitle: string;
  backHref?: string;
  backLabel?: string;
};

export function OperatorRouteSupportState({
  title,
  subtitle,
  backHref,
  backLabel = "Back",
  className = "",
  ...rest
}: OperatorRouteSupportStateProps): JSX.Element {
  return (
    <PageContainer>
      <WorkspaceEmptyStateCard className={className} {...rest}>
        <SectionHeader
          title={title}
          subtitle={subtitle}
          headingLevel={1}
          variant="support"
        />
        {backHref ? (
          <p>
            <Link href={backHref}>{backLabel}</Link>
          </p>
        ) : null}
      </WorkspaceEmptyStateCard>
    </PageContainer>
  );
}
