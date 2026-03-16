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
];

export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { token, refreshToken, principal, clearSession } = useAuth();

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
          <div>
            <strong>Work Boots Operator</strong>
          </div>
          <nav className="topnav-links">
            {links.map((link) => (
              <Link key={link.href} href={link.href} style={{ opacity: pathname === link.href ? 1 : 0.75 }}>
                {link.label}
              </Link>
            ))}
          </nav>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            {principal ? (
              <>
                <small>
                  {principal.display_name} ({principal.role})
                </small>
                <button onClick={() => void handleSignOut()}>Sign out</button>
              </>
            ) : (
              <Link href="/">Sign in</Link>
            )}
          </div>
        </div>
      </header>
      <main>{children}</main>
    </>
  );
}
