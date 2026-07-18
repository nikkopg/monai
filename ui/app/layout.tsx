import { Instrument_Serif, Hanken_Grotesk } from "next/font/google";
import Nav from "./components/Nav";
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
              overflow: "hidden",
              boxShadow: tokens.shadow.panel,
            }}
          >
            <Nav />
            <main style={{ flex: 1, minWidth: 0, overflowX: "hidden" }}>
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
