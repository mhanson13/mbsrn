"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "./AuthProvider";
import { logoutSession } from "../lib/api/client";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/sites", label: "Sites" },
  { href: "/audits", label: "Audit Runs" },
  { href: "/competitors", label: "Competitors" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/automation", label: "Automation" },
  { href: "/business-profile", label: "Business Profile" },
  { href: "/admin", label: "Admin", adminOnly: true },
];

type ShellWidthMode = "default" | "wide" | "full";

function resolveShellWidthMode(pathname: string): ShellWidthMode {
  if (pathname.startsWith("/sites/")) {
    return "full";
  }
  if (
    pathname.startsWith("/recommendations")
    || pathname.startsWith("/competitors")
    || pathname.startsWith("/audits")
    || pathname.startsWith("/automation")
  ) {
    return "wide";
  }
  return "default";
}

export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { token, refreshToken, principal, clearSession } = useAuth();
  const shellWidthMode = resolveShellWidthMode(pathname);
  const shellMainInnerClassName = [
    "operator-shell-main-inner",
    shellWidthMode === "default" ? "" : `operator-shell-main-inner-${shellWidthMode}`,
  ]
    .filter(Boolean)
    .join(" ");

  async function handleSignOut() {
    try {
      if (token) {
        await logoutSession(token, refreshToken || undefined);
      }
    } catch {
      // Clear local session state even when backend logout fails.
    } finally {
      clearSession();
    }
  }

  return (
    <>
      <header className="topnav">
        <div className="topnav-inner">
          <div className="topnav-brand">
            <strong>MBSRN Operator Workspace</strong>
          </div>
          <nav className="topnav-links">
            {links
              .filter((link) => !link.adminOnly || principal?.role === "admin")
              .map((link) => {
                const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={active ? "topnav-link is-active" : "topnav-link"}
                    aria-current={active ? "page" : undefined}
                  >
                    {link.label}
                  </Link>
                );
              })}
          </nav>
          <div className="topnav-session">
            {principal ? (
              <>
                <small className="topnav-principal">
                  {principal.display_name} ({principal.role})
                </small>
                <button type="button" onClick={() => void handleSignOut()}>
                  Sign out
                </button>
              </>
            ) : (
              <Link href="/" className="topnav-link">
                Sign in
              </Link>
            )}
          </div>
        </div>
      </header>
      <main className="operator-shell-main">
        <div className={shellMainInnerClassName}>{children}</div>
      </main>
    </>
  );
}
