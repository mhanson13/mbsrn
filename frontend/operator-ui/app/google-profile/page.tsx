"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";

export default function GoogleProfilePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchParamsString = searchParams?.toString() || "";
  const sitesHref = searchParamsString ? `/sites?${searchParamsString}` : "/sites";

  useEffect(() => {
    router.replace(sitesHref);
  }, [router, sitesHref]);

  return (
    <PageContainer width="wide" density="compact">
      <SectionCard variant="support" className="role-surface-support" data-testid="google-profile-legacy-redirect">
        <SectionHeader
          title="Google setup moved"
          subtitle="Google Profile and GA4 settings now live under Sites in Selected Site Setup."
          headingLevel={1}
          variant="support"
        />
        <p className="hint muted">
          Redirecting to Sites setup now.
        </p>
        <Link href={sitesHref} className="button button-secondary button-inline">
          Open Sites setup
        </Link>
      </SectionCard>
    </PageContainer>
  );
}
