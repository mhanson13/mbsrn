import Link from "next/link";
import Image from "next/image";
import { ThemeToggle } from "./ThemeToggle";

const navItems = [
  { href: "/", label: "Home" },
  { href: "/features", label: "Features" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
];

export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link href="/" className="brand-link" aria-label="MBSRN Home">
          <Image
            src="/brand/mbsrn-logo-horizontal-dark.svg"
            alt="MBSRN"
            className="brand-logo brand-logo-dark"
            width={172}
            height={36}
            priority
          />
          <Image
            src="/brand/mbsrn-logo-horizontal-light.svg"
            alt="MBSRN"
            className="brand-logo brand-logo-light"
            width={172}
            height={36}
            priority
          />
        </Link>
        <nav className="site-nav" aria-label="Primary">
          {navItems.map((item) => (
            <Link key={item.href} href={item.href} className="site-nav-link">
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="site-header-actions">
          <ThemeToggle />
          <a
            href="https://app.mbsrn.com"
            className="cta-button"
            target="_blank"
            rel="noreferrer"
          >
            Open Operator App
          </a>
        </div>
      </div>
    </header>
  );
}
