import Nav from "./components/Nav";

export const metadata = {
  title: "monai",
  description: "Personal wealth intelligence",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily:
            "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
          background: "#0f1115",
          color: "#e6e8eb",
        }}
      >
        <Nav />
        {children}
      </body>
    </html>
  );
}
