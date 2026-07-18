"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { tokens } from "../styles";

// ---------------------------------------------------------------------------
// Nav — left sidebar rendered once from ui/app/layout.tsx (inside the app
// panel). Client component (needs usePathname for active-link detection); the
// surrounding layout.tsx stays a server component.
//
// v1.1 "paper" redesign: was a sticky top bar, now the mockup's 236px sidebar
// with serif wordmark, icon+label nav items, a dark active pill, and a
// local-first status footer card. Nav order matches the mockup (Cashflow first).
// ---------------------------------------------------------------------------

const NAV_LINKS = [
  { href: "/cashflow", label: "Cashflow", icon: "cashflow" },
  { href: "/chat", label: "Chat", icon: "chat" },
  { href: "/investments", label: "Investments", icon: "investments" },
  { href: "/settings", label: "Settings", icon: "settings" },
] as const;

type IconName = (typeof NAV_LINKS)[number]["icon"];

// Inline stroke icons — geometry lifted from the mockup's icon() paths.
function Icon({ name }: { name: IconName }) {
  const common = {
    width: 20,
    height: 20,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  switch (name) {
    case "cashflow":
      return (
        <svg {...common}>
          <path d="M3 3v18h18" />
          <path d="M7 14l3-3 3 3 5-6" />
        </svg>
      );
    case "chat":
      return (
        <svg {...common}>
          <path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.3A8 8 0 1 1 21 12z" />
        </svg>
      );
    case "investments":
      return (
        <svg {...common}>
          <path d="M3 17l5-5 3 3 8-8" />
          <path d="M15 7h5v5" />
        </svg>
      );
    case "settings":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-2.7-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 4.6 15H4.5a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.1-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 11 4.6V4.5a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-1.1 2.7z" />
        </svg>
      );
  }
}

const sidebar: React.CSSProperties = {
  width: 236,
  flexShrink: 0,
  background: tokens.color.sidebar,
  borderRight: `1px solid ${tokens.color.border2}`,
  padding: "26px 18px",
  display: "flex",
  flexDirection: "column",
};

const brand: React.CSSProperties = {
  fontFamily: tokens.font.serif,
  fontSize: 30,
  letterSpacing: "-.5px",
  lineHeight: 1,
};

const menuLabel: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: ".12em",
  textTransform: "uppercase",
  color: tokens.color.muted2,
  padding: "0 10px 10px",
};

export default function Nav() {
  const pathname = usePathname();

  function isActive(href: string) {
    return pathname === href || pathname.startsWith(href + "/");
  }

  return (
    <aside className="app-sidebar" style={sidebar}>
      <div
        className="brand-word"
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          padding: "0 10px 26px",
        }}
      >
        <span style={brand}>monai</span>
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: tokens.color.green,
            marginBottom: 4,
          }}
        />
      </div>

      <div className="menu-label" style={menuLabel}>Menu</div>

      <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NAV_LINKS.map(({ href, label, icon }) => {
          const active = isActive(href);
          const itemStyle: React.CSSProperties = {
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "11px 12px",
            borderRadius: tokens.radius.md,
            fontSize: 14,
            fontWeight: active ? 600 : 500,
            textDecoration: "none",
            color: active ? tokens.color.inkText : tokens.color.muted3,
            background: active ? tokens.color.ink : "transparent",
            transition: "background .2s ease, color .2s ease",
          };
          return (
            <Link key={href} href={href} className="nav-item" style={itemStyle}>
              <span
                style={{ display: "inline-flex", width: 20, height: 20 }}
                aria-hidden
              >
                <Icon name={icon} />
              </span>
              <span className="nav-label">{label}</span>
            </Link>
          );
        })}
      </nav>

      <div
        className="footer-card"
        style={{
          marginTop: "auto",
          padding: 14,
          background: tokens.color.footerCard,
          border: `1px solid ${tokens.color.border2}`,
          borderRadius: tokens.radius.md,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3 }}>
          Local-first
        </div>
        <div
          style={{ fontSize: 12, color: tokens.color.muted, lineHeight: 1.45 }}
        >
          Your data stays on this machine.
        </div>
      </div>
    </aside>
  );
}
