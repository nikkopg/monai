"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { tokens } from "../styles";
import { useVisiblePoll } from "../lib/useVisiblePoll";
import {
  badgeText,
  isPendingCount,
  navInboxLabel,
  parsePendingCount,
} from "../lib/inbox";

const SIDEBAR_COLLAPSED_KEY = "monai.sidebarCollapsed";

// ---------------------------------------------------------------------------
// Nav — left sidebar rendered once from ui/app/layout.tsx (inside the app
// panel). Client component (needs usePathname for active-link detection); the
// surrounding layout.tsx stays a server component.
//
// v1.1 "paper" redesign: was a sticky top bar, now the mockup's 236px sidebar
// with serif wordmark, icon+label nav items, a dark active pill, and a
// local-first status footer card. Nav order matches the mockup (Cashflow first).
//
// At 560px and below CSS hides the sidebar and shows the floating pill dock
// (261115-s37): 5 icon links plus a More menu that holds Settings.
// ---------------------------------------------------------------------------

const NAV_LINKS = [
  { href: "/cashflow", label: "Cashflow", icon: "cashflow" },
  { href: "/records", label: "Records", icon: "records" },
  { href: "/inbox", label: "Inbox", icon: "inbox" },
  { href: "/chat", label: "Chat", icon: "chat" },
  { href: "/investments", label: "Investments", icon: "investments" },
  { href: "/settings", label: "Settings", icon: "settings" },
] as const;

type IconName = (typeof NAV_LINKS)[number]["icon"] | "more";

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
    case "records":
      return (
        <svg {...common}>
          <path d="M4 6h16M4 12h10M4 18h13" />
        </svg>
      );
    case "inbox":
      return (
        <svg {...common}>
          <path d="M4 13l2-8h12l2 8" />
          <path d="M4 13v6h16v-6" />
          <path d="M4 13h5l1 2h4l1-2h5" />
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
    case "more":
      return (
        <svg {...common}>
          <circle cx="5" cy="12" r="1.4" />
          <circle cx="12" cy="12" r="1.4" />
          <circle cx="19" cy="12" r="1.4" />
        </svg>
      );
  }
}

function sidebarStyle(collapsed: boolean): React.CSSProperties {
  return {
    width: collapsed ? 68 : 236,
    flexShrink: 0,
    background: tokens.color.sidebar,
    borderRight: `1px solid ${tokens.color.border2}`,
    padding: collapsed ? "26px 10px" : "26px 18px",
    display: "flex",
    flexDirection: "column",
    alignItems: collapsed ? "center" : "stretch",
    transition: "width .2s ease, padding .2s ease",
  };
}

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

// Phone dock item: 48x48 round, light circle with an ink icon when active.
function dockItemStyle(active: boolean): React.CSSProperties {
  return {
    position: "relative",
    display: "grid",
    placeItems: "center",
    width: 48,
    height: 48,
    padding: 0,
    border: "none",
    borderRadius: tokens.radius.pill,
    textDecoration: "none",
    cursor: "pointer",
    color: active ? tokens.color.ink : tokens.color.inkTextMuted,
    background: active ? tokens.color.inkText : "transparent",
  };
}

// Floating pill dock for phones (261115-s37). The More menu copies RowMenu's
// behaviour (focus first item, outside mousedown, capture-phase Escape, Tab
// closes) but opens upward, has an icon trigger and holds a Link.
function PhoneDock({
  pathname,
  isActive,
  inboxLabel,
  badge,
}: {
  pathname: string;
  isActive: (href: string) => boolean;
  inboxLabel: string;
  badge: string | null;
}) {
  const uid = useId();
  const [moreOpen, setMoreOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const btnId = `${uid}-more`;
  const menuId = `${uid}-menu`;
  const settings = NAV_LINKS.find((l) => l.href === "/settings")!;

  useEffect(() => {
    if (!moreOpen) return;
    wrapRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setMoreOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      setMoreOpen(false);
      btnRef.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [moreOpen]);

  // Close the menu when the route changes.
  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  return (
    <nav
      className="app-dock"
      aria-label="Main"
      style={{
        position: "fixed",
        left: "50%",
        transform: "translateX(-50%)",
        bottom: "calc(20px + env(safe-area-inset-bottom))",
        // above page content, below RowMenu/scrim 10, drawer 20 and modals 100
        zIndex: 5,
        gap: 2,
        padding: 6,
        background: tokens.color.ink,
        borderRadius: tokens.radius.pill,
        boxShadow: "0 8px 24px rgba(35,32,27,.25)",
      }}
    >
      {NAV_LINKS.filter((l) => l.href !== "/settings").map(({ href, label, icon }) => {
        const active = isActive(href);
        return (
          <Link
            key={href}
            href={href}
            className="dock-item"
            style={dockItemStyle(active)}
            aria-label={icon === "inbox" ? inboxLabel : label}
            aria-current={active ? "page" : undefined}
          >
            <span aria-hidden style={{ display: "inline-flex", width: 20, height: 20 }}>
              <Icon name={icon} />
            </span>
            {icon === "inbox" && badge !== null && (
              <span
                aria-hidden
                className="dock-badge"
                style={{
                  position: "absolute",
                  top: 3,
                  right: 3,
                  minWidth: 18,
                  height: 18,
                  padding: "0 5px",
                  borderRadius: tokens.radius.pill,
                  fontSize: 11,
                  fontWeight: 700,
                  lineHeight: "16px",
                  textAlign: "center",
                  fontVariantNumeric: "tabular-nums",
                  boxSizing: "border-box",
                  background: tokens.color.tintWarm,
                  color: tokens.color.ink,
                  border: `1px solid ${tokens.color.border2}`,
                }}
              >
                {badge}
              </span>
            )}
          </Link>
        );
      })}
      <span ref={wrapRef} style={{ position: "relative", display: "flex" }}>
        <button
          ref={btnRef}
          type="button"
          id={btnId}
          className="dock-item"
          style={dockItemStyle(moreOpen || isActive("/settings"))}
          aria-label="More"
          aria-haspopup="menu"
          aria-expanded={moreOpen}
          aria-controls={moreOpen ? menuId : undefined}
          onClick={() => setMoreOpen((o) => !o)}
        >
          <span aria-hidden style={{ display: "inline-flex", width: 20, height: 20 }}>
            <Icon name="more" />
          </span>
        </button>
        {moreOpen && (
          <div
            role="menu"
            id={menuId}
            aria-labelledby={btnId}
            style={{
              position: "absolute",
              right: 0,
              bottom: "calc(100% + 10px)",
              minWidth: 168,
              padding: 6,
              background: tokens.color.card,
              border: `1px solid ${tokens.color.border}`,
              borderRadius: tokens.radius.md,
              boxShadow: "0 8px 24px rgba(35,32,27,.15)",
            }}
            onKeyDown={(e) => {
              if (e.key === "Tab") setMoreOpen(false);
            }}
          >
            <Link
              href={settings.href}
              role="menuitem"
              tabIndex={-1}
              className="dock-menu-item"
              aria-current={isActive(settings.href) ? "page" : undefined}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                minHeight: 44,
                padding: "10px 12px",
                borderRadius: tokens.radius.sm,
                color: tokens.color.ink,
                fontSize: 14,
                textDecoration: "none",
              }}
            >
              <span aria-hidden style={{ display: "inline-flex", width: 20, height: 20 }}>
                <Icon name={settings.icon} />
              </span>
              {settings.label}
            </Link>
          </div>
        )}
      </span>
    </nav>
  );
}

export default function Nav() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  // Pending Inbox count: null until the first valid count arrives.
  const [pending, setPending] = useState<number | null>(null);
  const [inboxOffline, setInboxOffline] = useState(false);

  const poll = useVisiblePoll<number>({
    url: "/api/proposals/counts",
    intervalMs: 30_000,
    parse: parsePendingCount,
    onData: (n) => setPending(n),
  });
  const offline = poll.offline || inboxOffline;

  // The Inbox page pushes fresher state through window events; anything that
  // is not a valid count is ignored (T-33-08).
  useEffect(() => {
    const onCount = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (isPendingCount(detail)) setPending(detail as number);
    };
    const onOff = () => setInboxOffline(true);
    const onOn = () => setInboxOffline(false);
    window.addEventListener("monai:inbox-count", onCount);
    window.addEventListener("monai:inbox-offline", onOff);
    window.addEventListener("monai:inbox-online", onOn);
    return () => {
      window.removeEventListener("monai:inbox-count", onCount);
      window.removeEventListener("monai:inbox-offline", onOff);
      window.removeEventListener("monai:inbox-online", onOn);
    };
  }, []);

  // Hydrate persisted collapsed state after mount (init-then-hydrate avoids
  // an SSR/hydration mismatch since localStorage isn't available server-side).
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true");
    } catch {
      // ignore (e.g. storage disabled)
    }
  }, []);

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
    } catch {
      // ignore (e.g. storage disabled)
    }
  }

  function isActive(href: string) {
    return pathname === href || pathname.startsWith(href + "/");
  }

  return (
    <>
    <aside className="app-sidebar" style={sidebarStyle(collapsed)}>
      <div
        className="brand-word"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "space-between",
          gap: 8,
          padding: collapsed ? "0 0 26px" : "0 10px 26px",
        }}
      >
        {!collapsed && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
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
        )}
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 24,
            height: 24,
            padding: 0,
            border: "none",
            background: "transparent",
            color: tokens.color.muted3,
            cursor: "pointer",
          }}
        >
          <svg
            width={16}
            height={16}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.7}
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{
              transform: collapsed ? "rotate(180deg)" : undefined,
              transition: "transform .2s ease",
            }}
          >
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
      </div>

      {!collapsed && (
        <div className="menu-label" style={menuLabel}>Menu</div>
      )}

      <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NAV_LINKS.map(({ href, label, icon }) => {
          const active = isActive(href);
          const itemStyle: React.CSSProperties = {
            display: "flex",
            alignItems: "center",
            justifyContent: collapsed ? "center" : "flex-start",
            gap: collapsed ? 0 : 12,
            padding: collapsed ? "11px" : "11px 12px",
            borderRadius: tokens.radius.md,
            fontSize: 14,
            fontWeight: active ? 600 : 500,
            textDecoration: "none",
            color: active ? tokens.color.inkText : tokens.color.muted3,
            background: active ? tokens.color.ink : "transparent",
            transition: "background .2s ease, color .2s ease",
            ...(icon === "inbox" ? { position: "relative" as const } : {}),
          };
          const badge = icon === "inbox" ? badgeText(pending, offline) : null;
          return (
            <Link
              key={href}
              href={href}
              className="nav-item"
              style={itemStyle}
              aria-label={
                icon === "inbox" ? navInboxLabel(pending, offline) : label
              }
              title={collapsed ? label : undefined}
            >
              <span
                style={{ display: "inline-flex", width: 20, height: 20 }}
                aria-hidden
              >
                <Icon name={icon} />
              </span>
              {!collapsed && <span className="nav-label">{label}</span>}
              {badge !== null && (
                <span
                  aria-hidden
                  className="nav-badge"
                  style={{
                    borderRadius: tokens.radius.pill,
                    minWidth: 20,
                    height: 20,
                    padding: "0 8px",
                    fontSize: 12,
                    fontWeight: 600,
                    lineHeight: "20px",
                    textAlign: "center",
                    fontVariantNumeric: "tabular-nums",
                    boxSizing: "border-box",
                    background: tokens.color.tintWarm,
                    color: tokens.color.ink,
                    border: `1px solid ${tokens.color.border2}`,
                    ...(collapsed
                      ? { position: "absolute", top: 4, right: 4 }
                      : { marginLeft: "auto" }),
                  }}
                >
                  {badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {!collapsed && (
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
            style={{
              fontSize: 12,
              color: tokens.color.muted,
              lineHeight: 1.45,
            }}
          >
            Your data stays on this machine.
          </div>
        </div>
      )}
    </aside>
    <PhoneDock
      pathname={pathname}
      isActive={isActive}
      inboxLabel={navInboxLabel(pending, offline)}
      badge={badgeText(pending, offline)}
    />
    </>
  );
}
