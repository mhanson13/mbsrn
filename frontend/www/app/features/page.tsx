import type { Metadata } from "next";
import Link from "next/link";
import { appUrl, featureGroups } from "../../lib/siteContent";

export const metadata: Metadata = {
  title: "Features",
  description: "Core MBSRN capabilities for SEO operations and operator workflow execution.",
  alternates: {
    canonical: "/features",
  },
  openGraph: {
    title: "MBSRN Features",
    description:
      "Site visibility, competitor intelligence, recommendation actionability, and Google-connected measurement context.",
    url: "https://www.mbsrn.com/features",
    siteName: "MBSRN",
    type: "website",
  },
};

export default function FeaturesPage() {
  return (
    <div className="page-shell page-shell-narrow">
      <section className="section">
        <div className="section-header">
          <p className="eyebrow">Features</p>
          <h1>What MBSRN provides today</h1>
          <p>
            This page reflects shipped capabilities documented in the current repository. No inflated
            claims, no placeholder enterprise fluff.
          </p>
        </div>
      </section>

      <section className="section feature-groups">
        {featureGroups.map((group) => (
          <article key={group.title} className="feature-group-card">
            <h2>{group.title}</h2>
            <p className="feature-group-description">{group.description}</p>
            <ul>
              {group.bullets.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </article>
        ))}
      </section>

      <section className="section section-accent">
        <h2>Operator-first boundary</h2>
        <p>
          MBSRN supports analysis and action workflows. It does not promise guaranteed ranking gains
          and does not auto-publish website changes by default.
        </p>
        <a href={appUrl} target="_blank" rel="noreferrer" className="cta-button cta-button-primary">
          Open the operator app
        </a>
        <p className="section-support-link">
          Need legal/compliance context first? <Link href="/privacy">Privacy</Link> and <Link href="/terms">Terms</Link>.
        </p>
      </section>
    </div>
  );
}
