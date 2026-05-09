"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";

type SearchParamsLike = {
  get(name: string): string | null;
  toString(): string;
} | null;

function buildSitesSetupHref(searchParams: SearchParamsLike): string {
  const searchParamsString = searchParams?.toString() || "";
  const baseSitesHref = searchParamsString ? `/sites?${searchParamsString}` : "/sites";
  const siteId = (searchParams?.get("site_id") || "").trim();

  if (!siteId) {
    return baseSitesHref;
  }
  return `${baseSitesHref}#selected-site-setup`;
}

function CompatibilityNotice({ sitesHref }: { sitesHref: string }) {
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

function GoogleProfileRedirectClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sitesHref = useMemo(() => buildSitesSetupHref(searchParams), [searchParams]);

  useEffect(() => {
    router.replace(sitesHref);
  }, [router, sitesHref]);

  return <CompatibilityNotice sitesHref={sitesHref} />;
}

export default function GoogleProfilePage() {
  return (
    <Suspense fallback={<CompatibilityNotice sitesHref="/sites" />}>
      <GoogleProfileRedirectClient />
    </Suspense>
  );
}
