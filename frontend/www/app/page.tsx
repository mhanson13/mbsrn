import type { Metadata } from "next";
import Link from "next/link";
import {
  appUrl,
  coreFeatureHighlights,
  homeContent,
  howItWorksSteps,
  outcomes,
  trustSignals,
} from "../lib/siteContent";

export const metadata: Metadata = {
  title: "SEO Operations For Small Businesses",
  description:
    "MBSRN helps small business operators move from weak website visibility to prioritized SEO action with audits, competitor context, and actionable recommendations.",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "My Business Sucks Right Now (MBSRN) | SEO Operations For Small Businesses",
    description:
      "Audit visibility, competitor intelligence, recommendation workflows, and operator-first SEO execution.",
    url: "https://www.mbsrn.com/",
    siteName: "MBSRN",
    type: "website",
  },
};

export default function HomePage() {
  return (
    <div className="page-shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">{homeContent.hero.eyebrow}</p>
          <h1>{homeContent.hero.heading}</h1>
          <p className="lead">{homeContent.hero.subheading}</p>
          <div className="hero-actions">
            <a href={appUrl} target="_blank" rel="noreferrer" className="cta-button cta-button-primary">
              Open the app
            </a>
            <Link href="/features" className="cta-button cta-button-secondary">
              Learn what MBSRN does
            </Link>
            <Link href="/privacy" className="cta-button cta-button-secondary">
              Review privacy
            </Link>
            <Link href="/terms" className="cta-button cta-button-secondary">
              Review terms
            </Link>
          </div>
        </div>
        <div className="hero-panel">
          <h2>{homeContent.audience.title}</h2>
          <ul>
            {homeContent.audience.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="hero-panel-note">{homeContent.problem.body}</p>
        </div>
      </section>

      <section className="section">
        <div className="section-header">
          <h2>What the product does</h2>
          <p>
            MBSRN helps operators understand why visibility is underperforming, prioritize work, and
            execute clear next actions without guessing.
          </p>
        </div>
      </section>

      <section className="section">
        <div className="section-header">
          <h2>Core features</h2>
          <p>Built for operator workflows: actionable, bounded, and review-safe.</p>
        </div>
        <div className="feature-grid">
          {coreFeatureHighlights.map((feature) => (
            <article className="feature-card" key={feature.title}>
              <h3>{feature.title}</h3>
              <p>{feature.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section section-accent">
        <div className="section-header">
          <h2>Key outcomes</h2>
          <p>The platform is built to make SEO operations easier to run, not noisier to interpret.</p>
        </div>
        <div className="stats-grid">
          {outcomes.map((outcome) => (
            <article className="stat-card" key={outcome.title}>
              <p className="stat-value">{outcome.title}</p>
              <p className="stat-label">{outcome.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-header">
          <h2>How it works</h2>
          <p>Simple operator loop: baseline, detect, prioritize, execute, re-check.</p>
        </div>
        <ol className="workflow-list">
          {howItWorksSteps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      <section className="section">
        <div className="section-header">
          <h2>Why operators trust it</h2>
          <p>Signals stay grounded, actions are explicit, and boundaries are clear.</p>
        </div>
        <ul className="trust-list">
          {trustSignals.map((signal) => (
            <li key={signal}>{signal}</li>
          ))}
        </ul>
      </section>

      <section className="section final-cta">
        <h2>Ready to run your SEO workflow?</h2>
        <p>
          Open the operator workspace to connect your site, review recommendations, and track what
          to do next.
        </p>
        <div className="hero-actions">
          <a href={appUrl} target="_blank" rel="noreferrer" className="cta-button cta-button-primary">
            Open app.mbsrn.com
          </a>
          <Link href="/terms" className="cta-button cta-button-secondary">
            Terms of service
          </Link>
        </div>
      </section>
    </div>
  );
}
