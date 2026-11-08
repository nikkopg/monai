"use client";

import { usePathname } from "next/navigation";
import Nav from "./Nav";
import { tokens } from "../styles";

// The centered app frame + panel + sidebar, moved out of layout.tsx so /login
// can render without it (and without Nav's /api polling). usePathname also
// covers client-side navigation, which a root layout cannot see.
export default function AppShell({ children }: { children: React.ReactNode }) {
  if (usePathname() === "/login") return <>{children}</>;
  return (
    <>
      {/* Centered app frame — mockup shell geometry */}
      <div
        className="app-frame"
        style={{
          minHeight: "100vh",
          display: "flex",
          justifyContent: "center",
          alignItems: "flex-start",
          padding: 28,
          boxSizing: "border-box",
        }}
      >
        <div
          className="app-panel"
          style={{
            width: 1240,
            maxWidth: "100%",
            minHeight: "calc(100vh - 56px)",
            display: "flex",
            background: tokens.color.panel,
            border: `1px solid ${tokens.color.border2}`,
            borderRadius: tokens.radius.xl,
            // clip, not hidden: hidden makes this a scroll container and stops the chat
            // composer's `position: sticky` from pinning to the window (D-22a).
            overflow: "clip",
            boxShadow: tokens.shadow.panel,
          }}
        >
          <Nav />
          <main style={{ flex: 1, minWidth: 0, overflowX: "clip" }}>
            {children}
          </main>
        </div>
      </div>
    </>
  );
}
