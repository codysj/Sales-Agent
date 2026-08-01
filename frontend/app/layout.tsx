import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

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
