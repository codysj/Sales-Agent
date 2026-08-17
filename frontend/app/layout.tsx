import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

// The one stylesheet, imported once (T-217; ADR-031). Every route renders inside this layout, so
// importing it here is what makes "no page falls back to browser defaults" a property of the
// application rather than a habit — `tests/stylesheet.test.ts` holds it to that.
import "./globals.css";

export const metadata: Metadata = {
  title: "Matrix Power — review dashboard",
  description: "Internal review and approval interface. Not public.",
  // Internal tool behind authentication (`T-061`); there is nothing here to index and no
  // reason to advertise it.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
