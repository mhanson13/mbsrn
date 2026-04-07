import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import {
  appUrl,
  coreFeatureHighlights,
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
      <section className="hero hero-upgraded">
        <div className="hero-copy">
          <p className="eyebrow">My Business Sucks Right Now (MBSRN)</p>
          <h1>My Business Sucks Right Now.</h1>
          <p className="hero-subheadline">But it doesn&apos;t have to stay that way.</p>
          <p className="lead">Turn scattered SEO chaos into clear next actions.</p>
          <div className="hero-actions">
            <a href={appUrl} target="_blank" rel="noreferrer" className="cta-button cta-button-primary">
              Open the app
            </a>
            <Link href="/features" className="cta-button cta-button-secondary">
              Learn what MBSRN does
            </Link>
          </div>
          <p className="hero-legal-links">
            <Link href="/privacy">Privacy Policy</Link>
            <span aria-hidden="true">·</span>
            <Link href="/terms">Terms of Service</Link>
          </p>
        </div>
        <div className="hero-panel hero-brand-panel">
          <div className="hero-brand-anchor">
            <Image
              src="/images/mbsrn-logo-small.jpg"
              alt="My Business Sucks Right Now logo"
              width={128}
              height={128}
              className="hero-logo-image"
              priority
            />
          </div>
          <h2>My Business Starts Right Now.</h2>
          <p className="hint muted">
            Built for overloaded operators who need one clear next step, not another noisy dashboard.
          </p>
        </div>
      </section>

      <section className="section section-story">
        <div className="section-header">
          <h2>You&apos;re not bad at your business. You&apos;re overloaded.</h2>
          <p>You&apos;re on-site, on calls, fixing real problems.</p>
          <p>Your website? It&apos;s just another thing breaking.</p>
          <p>SEO tools don&apos;t help - they add noise.</p>
        </div>
        <div className="story-support-card">
          <p>Most operators are already maxed out. SEO should reduce confusion, not add another fire.</p>
        </div>
        <div className="story-image-grid" aria-label="Examples of overloaded operators">
          <article className="story-image-card">
            <Image
              src="/images/frust-cleaning-person.png"
              alt="Cleaning operator overwhelmed by schedule changes"
              width={1024}
              height={1536}
              className="story-image"
              sizes="(max-width: 980px) 100vw, 280px"
            />
          </article>
          <article className="story-image-card">
            <Image
              src="/images/frust-plumber-person.png"
              alt="Plumber operator dealing with a broken laptop in the field"
              width={1024}
              height={1536}
              className="story-image"
              sizes="(max-width: 980px) 100vw, 280px"
            />
          </article>
          <article className="story-image-card">
            <Image
              src="/images/frust-foodservice-person.png"
              alt="Food service operator overwhelmed during kitchen operations"
              width={1024}
              height={1536}
              className="story-image"
              sizes="(max-width: 980px) 100vw, 280px"
            />
          </article>
          <article className="story-image-card">
            <Image
              src="/images/frust-general-contractor-person.png"
              alt="General contractor struggling with field laptop issues"
              width={1024}
              height={1536}
              className="story-image"
              sizes="(max-width: 980px) 100vw, 280px"
            />
          </article>
          <article className="story-image-card">
            <Image
              src="/images/frust-yard-service-person.png"
              alt="Yard service operator handling equipment failure and communication issues"
              width={1024}
              height={1536}
              className="story-image"
              sizes="(max-width: 980px) 100vw, 280px"
            />
          </article>
        </div>
      </section>

      <section className="section section-transition">
        <div className="section-header">
          <h2>From &apos;Sucks Right Now&apos; -&gt; &apos;Starts Right Now&apos;</h2>
          <p>You don&apos;t need another dashboard.</p>
          <p>You need to know what to do next.</p>
          <p>MBSRN gives you that - clearly.</p>
        </div>
      </section>

      <section className="section section-before-after">
        <div className="section-header">
          <h2>What changes</h2>
          <p>Same business. Better operational focus.</p>
        </div>
        <div className="before-after-grid">
          <article className="before-after-card before-card">
            <h3>Before</h3>
            <ul>
              <li>No priorities</li>
              <li>Confusing tools</li>
              <li>Guessing what matters</li>
            </ul>
          </article>
          <article className="before-after-card after-card">
            <h3>After</h3>
            <ul>
              <li>Clear next actions</li>
              <li>Ranked priorities</li>
              <li>Work you can actually execute</li>
            </ul>
          </article>
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
