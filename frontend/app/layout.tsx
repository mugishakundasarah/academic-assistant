import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AppShell } from "./components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Today · Academic Assistant", template: "%s · Academic Assistant" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f6f3" },
    { media: "(prefers-color-scheme: dark)", color: "#151514" },
  ],
};

// Every page reads live data from the backend.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
