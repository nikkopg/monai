"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// ---------------------------------------------------------------------------
// Nav — shared, sticky top nav bar rendered once from ui/app/layout.tsx.
// Client component (needs usePathname for active-link detection); the
// surrounding layout.tsx stays a server component (RESEARCH.md Pitfall 5).
// ---------------------------------------------------------------------------

const NAV_LINKS = [
  { href: "/chat", label: "Chat" },
  { href: "/cashflow", label: "Cashflow" },
  { href: "/investments", label: "Investments" },
  { href: "/settings", label: "Settings" },
] as const;

const navBar: React.CSSProperties = {
  position: "sticky",
  top: 0,
  zIndex: 10,
  display: "flex",
  alignItems: "center",
  gap: 24,
  height: 56,
  padding: "0 24px",
  background: "#1a1d23",
  borderBottom: "1px solid #2a2e37",
};

const brand: React.CSSProperties = {
  fontSize: 20,
  fontWeight: 600,
  color: "#e6e8eb",
};

export default function Nav() {
  const pathname = usePathname();

  function isActive(href: string) {
    return pathname === href || pathname.startsWith(href + "/");
  }

  return (
    <nav style={navBar}>
      <span style={brand}>monai</span>
      {NAV_LINKS.map(({ href, label }) => {
        const active = isActive(href);
        const linkStyle: React.CSSProperties = {
          fontSize: 14,
          textDecoration: "none",
          color: active ? "#3b82f6" : "#9aa0a6",
          fontWeight: active ? 600 : 400,
          borderBottom: active
            ? "2px solid #3b82f6"
            : "2px solid transparent",
          paddingBottom: 4,
        };
        return (
          <Link key={href} href={href} style={linkStyle}>
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
