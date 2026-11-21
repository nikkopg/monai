import { Instrument_Serif, Hanken_Grotesk } from "next/font/google";
import { cookies } from "next/headers";
import AppShell from "./components/AppShell";
import { tokens } from "./styles";
import "./globals.css";

// Fonts self-hosted by next/font (no runtime Google calls — privacy-aligned).
// Exposed as CSS variables consumed by tokens.font in styles.ts.
const serif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-serif",
  display: "swap",
});

const sans = Hanken_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata = {
  title: "monai",
  description: "Personal wealth intelligence",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable}`}>
      <body
        style={{
          margin: 0,
          fontFamily: tokens.font.sans,
          background: tokens.color.page,
          color: tokens.color.text,
          minHeight: "100vh",
        }}
      >
        {/* Same name as Nav.tsx SIDEBAR_COOKIE; a client module's const is not readable here. */}
        {/* Same name as SIDEBAR_COOKIE in Nav.tsx: a client module's constant can't be read here. */}
        <AppShell sidebarCollapsed={cookies().get("monai_sidebar")?.value === "1"}>{children}</AppShell>
      </body>
    </html>
  );
}
