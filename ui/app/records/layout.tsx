// Server layout for the tab title only; the page itself is a client component.
export const metadata = { title: "Records · monai" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
