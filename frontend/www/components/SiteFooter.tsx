import Link from "next/link";
import Image from "next/image";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="site-footer-brand">
          <Image
            src="/brand/mbsrn-logo-mark.svg"
            alt="MBSRN mark"
            className="footer-mark"
            width={32}
            height={32}
          />
          <div>
            <p className="site-footer-brand-title">My Business Sucks Right Now</p>
            <p className="site-footer-brand-copy">
              MBSRN helps small businesses turn weak website visibility into actionable
              SEO operations.
            </p>
          </div>
        </div>
        <div className="site-footer-links" aria-label="Footer links">
          <Link href="/features">Features</Link>
          <Link href="/privacy">Privacy Policy</Link>
          <Link href="/terms">Terms of Service</Link>
          <a href="https://app.mbsrn.com" target="_blank" rel="noreferrer">
            Operator App
          </a>
        </div>
        <p className="site-footer-meta">
          Public website for My Business Sucks Right Now (MBSRN).
        </p>
      </div>
    </footer>
  );
}
